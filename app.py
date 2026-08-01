import os
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
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", f"{DB}.ledger")
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b:free")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

CACHE_TABLE = f"{DB}.rationale_cache"
EVENTS_TABLE = f"{DB}.app_events"

# Physical column names in rca.ledger, first entry wins. Extra entries are
# fallbacks so an upstream rename does not break the dashboard.
COLS = {
    "run_id":      ["run_id"],
    "trace_id":    ["trace_id"],
    "win_start":   ["incident_start", "window_start", "period_start"],
    "win_end":     ["incident_end", "window_end", "period_end"],
    "step_no":     ["step_order", "step_number", "step_no"],
    "step_name":   ["step_name", "step", "action"],
    "step_type":   ["step_type", "phase"],
    "metric":      ["metric", "kpi", "measure"],
    "dimension":   ["dimension", "dim", "grain"],
    "segment":     ["segment", "dimension_value", "dim_value"],
    "observed":    ["observed_value", "actual_value", "actual"],
    "expected":    ["expected_value", "baseline_value", "baseline"],
    "delta":       ["delta_value", "delta", "diff"],
    "contrib":     ["contribution_pct", "contribution"],
    "verdict":     ["verdict", "status", "result"],
    "rationale":   ["rationale", "explanation", "reason"],
    "created_at":  ["created_at", "inserted_at", "event_time"],
}

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

llm = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Per-row plain-English rewrite, for the "Plain English" toggle.
SIMPLIFY_PROMPT = """You rewrite technical analytics findings for a business stakeholder.

Rules:
- One sentence per finding. Maximum 22 words.
- No jargon. Say "how many ad slots actually got filled" rather than "fill rate".
- Never invent numbers that are not given to you.
- Return ONLY a JSON array of strings, same length and same order as the input.
  No markdown, no backticks, no preamble.
"""

# Ledger Diagnosis Narration skill, applied to the final + top evidence rows.
NARRATE_PROMPT = """You are a diagnostics narrator for a ClickHouse investigation system.
You are given structured ledger rows that capture the outcome of each analysis step.
Produce a factual incident diagnosis from these rows.

Rules:
- Only use values provided in the rows.
- Do not invent or infer new numbers or causes.
- Use the row rationale text when possible.
- Summarize the root cause and what was checked or ruled out.
- Keep the output factual and concise.
- Sentence 1: root cause diagnosis. Sentence 2 (optional): rule-out or supporting detail.
- If the evidence is not enough, say exactly: Insufficient evidence to produce a diagnosis from the provided ledger rows.

Return plain text only. No markdown, no preamble, no bullet points.
"""

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def col(key: str) -> str:
    """Physical column name for a logical field."""
    return COLS[key][0]


def pick(row: Dict[str, Any], key: str):
    for candidate in COLS[key]:
        if candidate in row:
            return row[candidate]
    return None


def rows_to_dicts(result) -> List[Dict[str, Any]]:
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def text_hash(text: str) -> int:
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


def log_event(endpoint: str, run_id: str, status: str, stage: str,
              latency_ms: int, rows: int = 0, error: str = "", trace_id: str = ""):
    """Write app telemetry into ClickHouse. Never allowed to break a request."""
    try:
        client.insert(
            EVENTS_TABLE,
            [[endpoint, str(run_id or ""), status, stage, int(latency_ms),
              int(rows), error[:500], str(trace_id or "")]],
            column_names=["endpoint", "run_id", "status", "stage",
                          "latency_ms", "rows_returned", "error", "trace_id"],
        )
    except Exception:
        pass


def cache_get(keys: List[int]) -> Dict[int, str]:
    res = client.query(
        f"SELECT rationale_hash, plain_text FROM {CACHE_TABLE} "
        f"WHERE rationale_hash IN {{h:Array(UInt64)}}",
        parameters={"h": keys},
    )
    return {h: t for h, t in res.result_rows}


def cache_put(rows: List[List[Any]]):
    client.insert(CACHE_TABLE, rows,
                  column_names=["rationale_hash", "rationale", "plain_text", "model"])


# ---------------------------------------------------------------------------
# LLM: per-row simplify + skill-based narration
# ---------------------------------------------------------------------------


def simplify_rationales(rationales: List[str], force: bool = False) -> Dict[str, Any]:
    out = {"plain": {}, "cache_hits": 0, "llm_called": False, "llm_ok": None,
           "error": None, "tokens": 0}

    uniq = list(dict.fromkeys([r for r in rationales if r]))
    if not uniq:
        return out

    hashes = {r: text_hash(r) for r in uniq}
    missing = list(uniq)

    if not force:
        with langfuse.start_as_current_observation(as_type="span", name="cache-lookup") as sp:
            try:
                found = cache_get(list(hashes.values()))
                for r in uniq:
                    if hashes[r] in found:
                        out["plain"][r] = found[hashes[r]]
                missing = [r for r in uniq if r not in out["plain"]]
                out["cache_hits"] = len(out["plain"])
                sp.update(output={"hits": out["cache_hits"], "misses": len(missing)})
            except Exception as e:
                sp.update(output={"cache_error": str(e)})

    if not missing:
        return out

    out["llm_called"] = True
    with langfuse.start_as_current_observation(
        as_type="generation", name="llm-rationale-simplify"
    ) as gen:
        gen.update(input={"system": SIMPLIFY_PROMPT, "user": missing}, model=MODEL)
        try:
            resp = llm.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SIMPLIFY_PROMPT},
                          {"role": "user", "content": json.dumps(missing)}],
                max_tokens=800, temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            plain = json.loads(raw)
            if not isinstance(plain, list) or len(plain) != len(missing):
                raise ValueError(f"expected {len(missing)} items, got {len(plain)}")

            for original, simple in zip(missing, plain):
                out["plain"][original] = str(simple).strip()

            out["tokens"] = (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
            out["llm_ok"] = True
            gen.update(output=plain, usage_details={
                "input_tokens": resp.usage.prompt_tokens or 0,
                "output_tokens": resp.usage.completion_tokens or 0})

            cache_put([[hashes[o], o, out["plain"][o], MODEL] for o in missing])

        except Exception as e:
            out["llm_ok"] = False
            out["error"] = str(e)
            gen.update(output={"error": str(e)}, level="ERROR", status_message=str(e))
            for r in missing:
                out["plain"][r] = r          # degrade to the original text

    return out


def select_evidence(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Final row plus the top localization/ruleout rows. 2-4 rows, per the skill."""
    final = [s for s in steps if s["step_type"] == "final"]
    support = sorted(
        [s for s in steps if s["step_type"] in ("localization", "ruleout")],
        key=lambda s: abs(s["contrib"] or 0), reverse=True,
    )[:3]
    chosen = final + support
    if not chosen:
        chosen = steps[-3:]

    fields = ("run_id", "step_order", "step_type", "metric", "dimension", "segment",
              "observed_value", "expected_value", "delta_value", "contribution_pct",
              "verdict", "rationale")
    payload = []
    for s in chosen:
        payload.append({
            "run_id": s["run_id"], "step_order": s["step_no"],
            "step_type": s["step_type"], "metric": s["metric"],
            "dimension": s["dimension"], "segment": s["segment"],
            "observed_value": s["observed"], "expected_value": s["expected"],
            "delta_value": s["delta"], "contribution_pct": s["contrib"],
            "verdict": s["verdict"], "rationale": s["rationale"],
        })
    return payload


def narrate_diagnosis(steps: List[Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
    """Ledger Diagnosis Narration skill. Cached by evidence payload hash."""
    out = {"text": None, "cached": False, "llm_ok": None, "error": None, "tokens": 0}

    evidence = select_evidence(steps)
    if not evidence:
        return out
    payload = json.dumps(evidence, sort_keys=True, default=str)
    key = text_hash("narrate::" + payload)

    if not force:
        try:
            hit = cache_get([key])
            if key in hit:
                out["text"] = hit[key]
                out["cached"] = True
                return out
        except Exception:
            pass

    with langfuse.start_as_current_observation(
        as_type="generation", name="llm-diagnosis-narration"
    ) as gen:
        gen.update(input={"system": NARRATE_PROMPT, "rows": evidence}, model=MODEL)
        try:
            resp = llm.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": NARRATE_PROMPT},
                          {"role": "user", "content": f"Input rows:\n{payload}"}],
                max_tokens=300, temperature=0,
            )
            text = resp.choices[0].message.content.strip().strip("`").strip()
            if not text:
                raise ValueError("empty narration")
            out["text"] = text
            out["llm_ok"] = True
            out["tokens"] = (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
            gen.update(output=text, usage_details={
                "input_tokens": resp.usage.prompt_tokens or 0,
                "output_tokens": resp.usage.completion_tokens or 0})
            cache_put([[key, payload[:2000], text, MODEL]])
        except Exception as e:
            out["llm_ok"] = False
            out["error"] = str(e)
            gen.update(output={"error": str(e)}, level="ERROR", status_message=str(e))

    return out


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})


@app.get("/api/pulse")
def pulse():
    """Cheap poll, every 4s, to detect a freshly written investigation."""
    t0 = time.time()
    try:
        res = client.query(
            f"SELECT count() AS total_rows, "
            f"uniqExact({col('run_id')}) AS runs, "
            f"uniqExact({col('trace_id')}) AS traces, "
            f"max({col('created_at')}) AS latest "
            f"FROM {AUDIT_TABLE}"
        )
        total, runs, traces, latest = res.result_rows[0]
        log_event("/api/pulse", "", "success", "clickhouse",
                  int((time.time() - t0) * 1000), rows=1)
        return {"total_rows": total, "runs": runs, "traces": traces,
                "latest": str(latest), "fingerprint": f"{total}:{runs}:{latest}"}
    except Exception as e:
        log_event("/api/pulse", "", "failure", "clickhouse",
                  int((time.time() - t0) * 1000), error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/runs")
def runs(limit: int = 50):
    """One card per investigation, newest first."""
    t0 = time.time()
    c = {k: v[0] for k, v in COLS.items()}
    sql = f"""
        SELECT
            toString({c['run_id']})                                       AS run_id,
            toString(any({c['trace_id']}))                                AS trace_id,
            min({c['win_start']})                                         AS incident_start,
            max({c['win_end']})                                           AS incident_end,
            count()                                                       AS steps,
            countIf({c['verdict']} = 'anomaly')                           AS anomaly_steps,
            argMaxIf({c['metric']}, {c['step_no']}, {c['step_type']} = 'final')    AS headline_metric,
            argMaxIf({c['segment']}, {c['step_no']}, {c['step_type']} = 'final')   AS headline_segment,
            argMaxIf({c['delta']}, {c['step_no']}, {c['step_type']} = 'final')     AS headline_delta,
            max({c['created_at']})                                        AS loaded_at
        FROM {AUDIT_TABLE}
        GROUP BY {c['run_id']}
        ORDER BY loaded_at DESC
        LIMIT {{limit:UInt32}}
    """
    try:
        res = client.query(sql, parameters={"limit": limit})
        data = rows_to_dicts(res)
        for d in data:
            for k in ("incident_start", "incident_end", "loaded_at"):
                d[k] = str(d[k])
        log_event("/api/runs", "", "success", "clickhouse",
                  int((time.time() - t0) * 1000), rows=len(data))
        return {"runs": data}
    except Exception as e:
        log_event("/api/runs", "", "failure", "clickhouse",
                  int((time.time() - t0) * 1000), error=str(e))
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[-800:]},
                            status_code=500)


@app.get("/api/run/{run_id}")
def run_detail(run_id: str, plain: bool = True, force: bool = False):
    """Full reasoning chain for one run, Langfuse-traced end to end."""
    t0 = time.time()
    app_trace_id = ""

    with propagate_attributes(session_id=run_id, tags=["rca-ledger", "clickhouse"]):
        with langfuse.start_as_current_observation(as_type="span", name="rca-run-detail") as root:
            root.update(input={"run_id": run_id, "plain": plain, "force": force})
            try:
                app_trace_id = langfuse.get_current_trace_id() or ""
            except Exception:
                pass

            # --- fetch. SELECT * so a new ledger column appears automatically.
            with langfuse.start_as_current_observation(
                as_type="span", name="clickhouse-fetch-run"
            ) as fetch:
                q = (f"SELECT * FROM {AUDIT_TABLE} "
                     f"WHERE {col('run_id')} = toUUID({{run_id:String}}) "
                     f"ORDER BY {col('step_no')}")
                fetch.update(input={"sql": q})
                try:
                    res = client.query(q, parameters={"run_id": run_id})
                    raw = rows_to_dicts(res)
                    fetch.update(output={"rows": len(raw)})
                except Exception as e:
                    fetch.update(output={"error": str(e)}, level="ERROR")
                    log_event("/api/run", run_id, "failure", "clickhouse",
                              int((time.time() - t0) * 1000), error=str(e),
                              trace_id=app_trace_id)
                    return JSONResponse({"error": str(e)}, status_code=500)

            if not raw:
                log_event("/api/run", run_id, "failure", "clickhouse",
                          int((time.time() - t0) * 1000), error="run not found",
                          trace_id=app_trace_id)
                return JSONResponse({"error": f"No ledger rows for run_id {run_id}"},
                                    status_code=404)

            known = {n for names in COLS.values() for n in names}
            steps = []
            for r in raw:
                steps.append({
                    "run_id":    str(pick(r, "run_id")),
                    "step_no":   pick(r, "step_no"),
                    "step_name": pick(r, "step_name"),
                    "step_type": pick(r, "step_type"),
                    "metric":    pick(r, "metric"),
                    "dimension": pick(r, "dimension"),
                    "segment":   pick(r, "segment"),
                    "observed":  pick(r, "observed"),
                    "expected":  pick(r, "expected"),
                    "delta":     pick(r, "delta"),
                    "contrib":   pick(r, "contrib"),
                    "verdict":   pick(r, "verdict"),
                    "rationale": pick(r, "rationale"),
                    # any column the ledger gains later lands here and renders
                    "extra": {k: str(v) for k, v in r.items() if k not in known},
                })

            # --- narration (the skill) + per-row simplify (the toggle)
            diag = narrate_diagnosis(steps, force=force)

            simp = {"plain": {}, "cache_hits": 0, "llm_called": False,
                    "llm_ok": None, "error": None, "tokens": 0}
            if plain:
                simp = simplify_rationales([s["rationale"] for s in steps], force=force)
                for s in steps:
                    s["plain"] = simp["plain"].get(s["rationale"], s["rationale"])

            latency = int((time.time() - t0) * 1000)
            ok = simp["llm_ok"] is not False and diag["llm_ok"] is not False
            root.update(output={"steps": len(steps), "llm_ok": ok,
                                "cache_hits": simp["cache_hits"]})

    log_event("/api/run", run_id, "success" if ok else "failure",
              "llm" if (simp["llm_called"] or diag["llm_ok"]) else "cache_hit",
              latency, rows=len(steps),
              error=simp["error"] or diag["error"] or "", trace_id=app_trace_id)

    # the ledger's own trace_id points at the pipeline's Langfuse session
    ledger_trace = str(pick(raw[0], "trace_id") or "")

    header = {
        "run_id": run_id,
        "ledger_trace_id": ledger_trace,
        "ledger_trace_url": f"{LANGFUSE_HOST}/trace/{ledger_trace}" if ledger_trace else "",
        "incident_start": str(pick(raw[0], "win_start")),
        "incident_end": str(pick(raw[0], "win_end")),
        "loaded_at": str(pick(raw[-1], "created_at")),
        "columns": res.column_names,
    }
    return {
        "header": header,
        "steps": steps,
        "diagnosis": diag,
        "app_trace_id": app_trace_id,
        "llm": {"model": MODEL, "called": simp["llm_called"], "ok": simp["llm_ok"],
                "cache_hits": simp["cache_hits"],
                "tokens": simp["tokens"] + diag["tokens"], "error": simp["error"]},
        "latency_ms": latency,
    }


@app.get("/api/health")
def health(hours: int = 24):
    """Success / failure panel, read from the app's own telemetry."""
    try:
        res = client.query(f"""
            SELECT
                count()                                              AS calls,
                countIf(status = 'success')                          AS ok,
                countIf(status = 'failure')                          AS failed,
                round(100 * countIf(status='success') / greatest(count(), 1), 1) AS success_rate,
                round(avg(latency_ms))                               AS avg_ms,
                round(quantile(0.95)(latency_ms))                    AS p95_ms,
                countIf(stage = 'llm')                               AS llm_calls,
                countIf(stage = 'cache_hit')                         AS cache_hits
            FROM {EVENTS_TABLE}
            WHERE ts > now() - INTERVAL {{h:UInt32}} HOUR
        """, parameters={"h": hours})
        kpi = dict(zip(res.column_names, res.result_rows[0]))

        recent = client.query(f"""
            SELECT toString(ts) AS ts, endpoint, status, stage, latency_ms, error
            FROM {EVENTS_TABLE}
            WHERE ts > now() - INTERVAL {{h:UInt32}} HOUR
            ORDER BY ts DESC LIMIT 25
        """, parameters={"h": hours})

        return {"kpi": kpi, "recent": rows_to_dicts(recent)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/verdicts")
def verdicts():
    """Verdict split across the whole ledger."""
    c = {k: v[0] for k, v in COLS.items()}
    try:
        res = client.query(f"""
            SELECT {c['step_type']} AS step_type,
                   {c['verdict']}   AS verdict,
                   count()          AS n
            FROM {AUDIT_TABLE}
            GROUP BY step_type, verdict
            ORDER BY n DESC
        """)
        return {"breakdown": rows_to_dicts(res)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
