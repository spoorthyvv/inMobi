import os
import re
import time
import json
import hashlib
import traceback
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import clickhouse_connect
from langfuse import get_client, propagate_attributes
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
DB = os.environ.get("CH_DB", "rca")
LEDGER = os.environ.get("AUDIT_TABLE", f"{DB}.ledger")
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b:free")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

CACHE_TABLE = f"{DB}.rationale_cache"
EVENTS_TABLE = f"{DB}.app_events"

app = FastAPI(title="RCA Ledger")
templates = Jinja2Templates(directory="templates")

client = clickhouse_connect.get_client(
    host=os.environ["CH_HOST"],
    port=int(os.environ.get("CH_PORT", 8443)),
    username=os.environ.get("CH_USER", "default"),
    password=os.environ["CH_PASSWORD"],
    secure=True,
)

langfuse = get_client()

llm = OpenAI(base_url="https://openrouter.ai/api/v1",
             api_key=os.environ["OPENROUTER_API_KEY"])

# Ledger Diagnosis Narration skill.
NARRATE_PROMPT = """You are a diagnostics narrator for a ClickHouse investigation system.
You are given structured ledger rows that capture the outcome of each analysis step.
Produce a factual incident diagnosis from these rows.

Rules:
- Only use values provided in the rows. Do not invent or infer new numbers or causes.
- Use the row rationale text when possible.
- Respect the final row's verdict. If it is 'normal', say the investigation cleared it.
  If it is 'insufficient_volume', say the signal was too weak to confirm.
- Sentence 1: the root cause diagnosis, or the reason it was cleared.
- Sentence 2 (optional): what was checked or ruled out.
- Write for a business stakeholder. No jargon, no metric names in snake_case.
- Maximum 45 words total.
- If the evidence is not enough, say exactly: Insufficient evidence to produce a diagnosis from the provided ledger rows.

Return plain prose only. No markdown, no bullets, no preamble, no JSON."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def rows_to_dicts(result) -> List[Dict[str, Any]]:
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def text_hash(text: str) -> int:
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


def log_event(endpoint: str, run_id: str, status: str, stage: str,
              latency_ms: int, rows: int = 0, error: str = "", trace_id: str = ""):
    try:
        client.insert(
            EVENTS_TABLE,
            [[endpoint, str(run_id or ""), status, stage, int(latency_ms),
              int(rows), error[:500], str(trace_id or "")]],
            column_names=["endpoint", "run_id", "status", "stage",
                          "latency_ms", "rows_returned", "error", "trace_id"])
    except Exception:
        pass


def cache_get(keys: List[int]) -> Dict[int, str]:
    res = client.query(
        f"SELECT rationale_hash, plain_text FROM {CACHE_TABLE} "
        f"WHERE rationale_hash IN {{h:Array(UInt64)}}", parameters={"h": keys})
    return {h: t for h, t in res.result_rows}


def cache_put(key: int, source: str, text: str):
    try:
        client.insert(CACHE_TABLE, [[key, source[:4000], text, MODEL]],
                      column_names=["rationale_hash", "rationale", "plain_text", "model"])
    except Exception:
        pass


NUM_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def numbers_in(text: str) -> List[float]:
    out = []
    for m in NUM_RE.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def groundedness(narration: str, rows: List[Dict[str, Any]]):
    """Every number in the narration must trace back to a ledger value.

    This is what turns the LLM output from a nice sentence into evidence:
    if the model invents a figure, the badge says so instead of hiding it.
    """
    allowed = set()
    for r in rows:
        for k in ("observed_value", "expected_value", "delta_value", "contribution_pct"):
            v = r.get(k)
            if v is None:
                continue
            allowed.update({round(float(v), 4), round(abs(float(v)), 4),
                            round(float(v) / 1000, 4), round(float(v) * 100, 4)})
        obs, exp = r.get("observed_value"), r.get("expected_value")
        if obs is not None and exp not in (None, 0):
            change = (float(obs) - float(exp)) / abs(float(exp)) * 100
            allowed.update({round(change, 1), round(abs(change), 1),
                            round(change, 0), round(abs(change), 0)})
        allowed.update(round(n, 4) for n in numbers_in(r.get("rationale", "")))

    found = numbers_in(narration)
    unverified = []
    for n in found:
        if not any(abs(n - a) < 0.51 or (a and abs(n - a) / max(abs(a), 1e-9) < 0.01)
                   for a in allowed):
            unverified.append(n)

    total = len(found)
    ok = total - len(unverified)
    return {"total": total, "verified": ok, "unverified": unverified,
            "score": 1.0 if total == 0 else round(ok / total, 3)}


def lf_score(name: str, value: float, comment: str = ""):
    try:
        langfuse.create_score(name=name, value=value, comment=comment[:400])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# narration
# ---------------------------------------------------------------------------

def select_evidence(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Final row plus the strongest supporting rows. 2-4 rows, per the skill."""
    final = [s for s in steps if s["step_type"] == "final"]
    support = sorted(
        [s for s in steps if s["step_type"] in ("localization", "ruleout", "decomposition")],
        key=lambda s: abs(s["contribution_pct"] or 0), reverse=True)[:3]
    chosen = final + support or steps[-3:]

    keep = ("run_id", "step_order", "step_type", "metric", "dimension", "segment",
            "observed_value", "expected_value", "delta_value", "contribution_pct",
            "verdict", "rationale")
    return [{k: (str(s[k]) if k == "run_id" else s[k]) for k in keep} for s in chosen]


def call_llm(payload: str, strict: bool = False) -> str:
    sys_prompt = NARRATE_PROMPT
    if strict:
        sys_prompt += "\n\nYour previous reply was not usable. Reply with one or two plain sentences and nothing else."
    resp = llm.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": f"Input rows:\n{payload}"}],
        max_tokens=250, temperature=0)
    return resp, (resp.choices[0].message.content or "").strip()


def clean_narration(text: str) -> str:
    """Free models like to wrap prose in fences, JSON, or a preamble. Strip it."""
    t = text.strip()
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t).strip()
    if t.startswith("{") or t.startswith("["):
        try:
            parsed = json.loads(t)
            if isinstance(parsed, list):
                t = " ".join(str(x) for x in parsed)
            elif isinstance(parsed, dict):
                t = " ".join(str(v) for v in parsed.values())
        except Exception:
            pass
    t = re.sub(r"^\s*(diagnosis|answer|output|summary)\s*[:\-]\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*[-*•]\s*", "", t, flags=re.M)
    return " ".join(t.split()).strip('"').strip()


def narrate(steps: List[Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
    out = {"text": None, "cached": False, "ok": None, "error": None,
           "tokens": 0, "grounding": None, "attempts": 0}

    evidence = select_evidence(steps)
    if not evidence:
        return out
    payload = json.dumps(evidence, sort_keys=True, default=str)
    key = text_hash("narrate-v2::" + payload)

    if not force:
        try:
            hit = cache_get([key])
            if key in hit and hit[key].strip():
                out.update(text=hit[key], cached=True, ok=True)
                out["grounding"] = groundedness(hit[key], evidence)
                return out
        except Exception:
            pass

    with langfuse.start_as_current_observation(
            as_type="generation", name="llm-diagnosis-narration") as gen:
        gen.update(input={"system": NARRATE_PROMPT, "rows": evidence}, model=MODEL)
        text = ""
        try:
            for attempt in (False, True):          # one plain try, one strict retry
                out["attempts"] += 1
                resp, raw = call_llm(payload, strict=attempt)
                text = clean_narration(raw)
                out["tokens"] += ((resp.usage.prompt_tokens or 0)
                                  + (resp.usage.completion_tokens or 0))
                if len(text.split()) >= 4:
                    break

            if len(text.split()) < 4:
                raise ValueError(f"unusable narration: {text!r}")

            out["text"] = text
            out["ok"] = True
            out["grounding"] = groundedness(text, evidence)
            gen.update(output=text, usage_details={"input_tokens": resp.usage.prompt_tokens or 0,
                                                   "output_tokens": resp.usage.completion_tokens or 0},
                       metadata={"attempts": out["attempts"],
                                 "grounding": out["grounding"]})
            lf_score("narration-groundedness", out["grounding"]["score"],
                     f"{out['grounding']['verified']}/{out['grounding']['total']} numbers verified")
            cache_put(key, payload, text)

        except Exception as e:
            out["ok"] = False
            out["error"] = str(e)
            gen.update(output={"error": str(e)}, level="ERROR", status_message=str(e))
            lf_score("narration-groundedness", 0.0, "narration failed")

    return out


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})


@app.get("/api/pulse")
def pulse():
    """Polled every 4s. Fingerprint changes the moment a new ledger row lands."""
    t0 = time.time()
    try:
        res = client.query(f"""
            SELECT count()                AS total_rows,
                   uniqExact(run_id)      AS runs,
                   uniqExact(trace_id)    AS traces,
                   max(created_at)        AS latest
            FROM {LEDGER}""")
        total, runs, traces, latest = res.result_rows[0]
        log_event("/api/pulse", "", "success", "clickhouse",
                  int((time.time() - t0) * 1000), rows=1)
        return {"total_rows": total, "runs": runs, "traces": traces,
                "latest": str(latest), "fingerprint": f"{total}:{runs}:{latest}"}
    except Exception as e:
        log_event("/api/pulse", "", "failure", "clickhouse",
                  int((time.time() - t0) * 1000), error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/incidents")
def incidents(only_anomalies: bool = True, limit: int = 100):
    """One horizontal record per run_id. The FINAL row decides the verdict."""
    t0 = time.time()
    sql = f"""
        SELECT
            toString(run_id)                                                AS run_id,
            toString(any(trace_id))                                         AS trace_id,
            min(incident_start)                                             AS incident_start,
            max(incident_end)                                               AS incident_end,
            count()                                                         AS steps,

            argMaxIf(verdict,          step_order, step_type='final')       AS verdict,
            argMaxIf(metric,           step_order, step_type='final')       AS metric,
            argMaxIf(dimension,        step_order, step_type='final')       AS dimension,
            argMaxIf(segment,          step_order, step_type='final')       AS segment,
            argMaxIf(observed_value,   step_order, step_type='final')       AS observed,
            argMaxIf(expected_value,   step_order, step_type='final')       AS expected,
            argMaxIf(delta_value,      step_order, step_type='final')       AS delta,
            argMaxIf(contribution_pct, step_order, step_type='final')       AS confidence,
            argMaxIf(rationale,        step_order, step_type='final')       AS final_rationale,

            argMaxIf(metric,           contribution_pct,
                     verdict='anomaly' AND step_type IN ('localization','decomposition'))  AS driver_metric,
            argMaxIf(dimension,        contribution_pct,
                     verdict='anomaly' AND step_type IN ('localization','decomposition'))  AS driver_dimension,
            argMaxIf(segment,          contribution_pct,
                     verdict='anomaly' AND step_type IN ('localization','decomposition'))  AS driver_segment,
            maxIf(contribution_pct,
                     verdict='anomaly' AND step_type IN ('localization','decomposition'))  AS driver_contribution,

            arrayDistinct(groupArrayIf(metric, step_type='ruleout'))         AS ruled_out,
            countIf(verdict='anomaly')                                       AS anomaly_steps,
            max(created_at)                                                  AS written_at
        FROM {LEDGER}
        GROUP BY run_id
        {"HAVING verdict = 'anomaly'" if only_anomalies else ""}
        ORDER BY written_at DESC
        LIMIT {{limit:UInt32}}"""
    try:
        res = client.query(sql, parameters={"limit": limit})
        data = rows_to_dicts(res)
        for d in data:
            for k in ("incident_start", "incident_end", "written_at"):
                d[k] = str(d[k])
            d["change_pct"] = (round((d["observed"] - d["expected"])
                                     / abs(d["expected"]) * 100, 1)
                               if d["expected"] else None)
            d["trace_url"] = f"{LANGFUSE_HOST}/trace/{d['trace_id']}" if d["trace_id"] else ""
        log_event("/api/incidents", "", "success", "clickhouse",
                  int((time.time() - t0) * 1000), rows=len(data))
        return {"incidents": data, "only_anomalies": only_anomalies}
    except Exception as e:
        log_event("/api/incidents", "", "failure", "clickhouse",
                  int((time.time() - t0) * 1000), error=str(e))
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[-800:]},
                            status_code=500)


@app.get("/api/run/{run_id}")
def run_detail(run_id: str, force: bool = False):
    """Step chain + narrated diagnosis for one run. Fully traced in Langfuse."""
    t0 = time.time()
    app_trace_id = ""

    with propagate_attributes(session_id=run_id, tags=["rca-ledger"]):
        with langfuse.start_as_current_observation(
                as_type="span", name="rca-run-detail") as root:
            root.update(input={"run_id": run_id, "force": force})
            try:
                app_trace_id = langfuse.get_current_trace_id() or ""
            except Exception:
                pass

            with langfuse.start_as_current_observation(
                    as_type="span", name="clickhouse-fetch-ledger") as fetch:
                q = (f"SELECT * FROM {LEDGER} WHERE run_id = toUUID({{run_id:String}}) "
                     f"ORDER BY step_order")
                fetch.update(input={"sql": q, "table": LEDGER})
                try:
                    res = client.query(q, parameters={"run_id": run_id})
                    steps = rows_to_dicts(res)
                    fetch.update(output={"rows": len(steps),
                                         "columns": res.column_names})
                except Exception as e:
                    fetch.update(output={"error": str(e)}, level="ERROR",
                                 status_message=str(e))
                    log_event("/api/run", run_id, "failure", "clickhouse",
                              int((time.time() - t0) * 1000), error=str(e),
                              trace_id=app_trace_id)
                    return JSONResponse({"error": str(e)}, status_code=500)

            if not steps:
                log_event("/api/run", run_id, "failure", "clickhouse",
                          int((time.time() - t0) * 1000), error="not found",
                          trace_id=app_trace_id)
                return JSONResponse({"error": f"No ledger rows for {run_id}"},
                                    status_code=404)

            for s in steps:
                for k, v in list(s.items()):
                    if k in ("run_id", "trace_id"):
                        s[k] = str(v)
                    elif k in ("incident_start", "incident_end", "created_at"):
                        s[k] = str(v)

            final = next((s for s in steps if s["step_type"] == "final"), steps[-1])
            diag = narrate(steps, force=force)

            latency = int((time.time() - t0) * 1000)
            ok = diag["ok"] is not False

            # trace-level context: what judges actually read in Langfuse
            try:
                langfuse.update_current_trace(
                    name=f"rca:{final['metric']}:{final['verdict']}",
                    session_id=str(final.get("trace_id") or run_id),
                    tags=["rca-ledger", f"verdict:{final['verdict']}",
                          f"metric:{final['metric']}",
                          f"dimension:{final['dimension']}"],
                    metadata={"run_id": run_id,
                              "ledger_trace_id": str(final.get("trace_id") or ""),
                              "steps": len(steps),
                              "incident_start": steps[0]["incident_start"],
                              "incident_end": steps[0]["incident_end"],
                              "cached": diag["cached"],
                              "llm_attempts": diag["attempts"]},
                    input={"run_id": run_id, "steps": len(steps)},
                    output={"verdict": final["verdict"], "diagnosis": diag["text"]})
            except Exception:
                pass

            lf_score("run-latency-ms", float(latency))
            lf_score("narration-cache-hit", 1.0 if diag["cached"] else 0.0)

            root.update(output={"verdict": final["verdict"],
                                "diagnosis": diag["text"],
                                "grounding": diag["grounding"]})

    log_event("/api/run", run_id, "success" if ok else "failure",
              "cache_hit" if diag["cached"] else "llm", latency,
              rows=len(steps), error=diag["error"] or "", trace_id=app_trace_id)

    ledger_trace = str(final.get("trace_id") or "")
    return {
        "run_id": run_id,
        "verdict": final["verdict"],
        "steps": steps,
        "diagnosis": diag,
        "ledger_trace_id": ledger_trace,
        "ledger_trace_url": f"{LANGFUSE_HOST}/trace/{ledger_trace}" if ledger_trace else "",
        "app_trace_id": app_trace_id,
        "model": MODEL,
        "latency_ms": latency,
    }


@app.get("/api/health")
def health(hours: int = 24):
    try:
        res = client.query(f"""
            SELECT count()                                                       AS calls,
                   countIf(status='success')                                     AS ok,
                   countIf(status='failure')                                     AS failed,
                   round(100*countIf(status='success')/greatest(count(),1), 1)    AS success_rate,
                   round(quantile(0.95)(latency_ms))                             AS p95_ms,
                   countIf(stage='llm')                                          AS llm_calls,
                   countIf(stage='cache_hit')                                    AS cache_hits
            FROM {EVENTS_TABLE}
            WHERE ts > now() - INTERVAL {{h:UInt32}} HOUR""", parameters={"h": hours})
        kpi = dict(zip(res.column_names, res.result_rows[0]))

        recent = client.query(f"""
            SELECT toString(ts) AS ts, endpoint, status, stage, latency_ms, error
            FROM {EVENTS_TABLE}
            WHERE ts > now() - INTERVAL {{h:UInt32}} HOUR
            ORDER BY ts DESC LIMIT 20""", parameters={"h": hours})

        return {"kpi": kpi, "recent": rows_to_dicts(recent)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/verdicts")
def verdicts():
    """Outcome split across the ledger, judged by the final row of each run."""
    try:
        res = client.query(f"""
            SELECT verdict, count() AS runs FROM (
                SELECT run_id, argMaxIf(verdict, step_order, step_type='final') AS verdict
                FROM {LEDGER} GROUP BY run_id
            ) GROUP BY verdict ORDER BY runs DESC""")
        return {"breakdown": rows_to_dicts(res)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
