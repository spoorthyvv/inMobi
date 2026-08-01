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
# CONFIG  -- only these three lines are schema-specific. Change if yours differ.
# ---------------------------------------------------------------------------
DB = os.environ.get("CH_DB", "rca")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", f"{DB}.audit_log")
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b:free")

DB = os.environ.get("CH_DB", "rca")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", f"{DB}.ledger")   # was audit_log
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b:free")
# Column aliases. The dashboard looks for the first name that exists in your
# table, so renaming a column upstream does not break the UI.
COLS = {
    "run_id":      ["run_id", "investigation_id", "trace_id"],
    "batch_id":    ["batch_id", "load_id", "ingest_id"],
    "win_start":   ["window_start", "period_start", "start_ts"],
    "win_end":     ["window_end", "period_end", "end_ts"],
    "step_no":     ["step_number", "step_no", "seq"],
    "step_name":   ["step_name", "step", "action"],
    "step_type":   ["step_type", "phase", "stage"],
    "metric":      ["metric", "kpi", "measure"],
    "dimension":   ["dimension", "dim", "grain"],
    "dim_value":   ["dimension_value", "dim_value", "segment"],
    "actual":      ["actual_value", "actual", "observed", "current_value"],
    "baseline":    ["baseline_value", "baseline", "expected", "expected_value"],
    "delta":       ["delta", "diff", "change"],
    "contrib":     ["contribution_pct", "contribution", "confidence", "score"],
    "verdict":     ["verdict", "status", "result", "outcome"],
    "rationale":   ["rationale", "explanation", "reason", "narrative"],
    "created_at":  ["created_at", "inserted_at", "ingested_at", "event_time"],
}

app = FastAPI(title="RCA Audit Trail")
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

SYSTEM_PROMPT = """You rewrite technical analytics findings for a business stakeholder.

Rules:
- One sentence per finding. Maximum 22 words.
- No jargon: no "baseline", "delta", "trailing", "decomposition", "contribution", "variance", "fill rate" -> say "how many ad slots actually got filled".
- Say what happened and why it matters in money or user terms.
- Never invent numbers that are not given to you.
- Return ONLY a JSON array of strings, same length and same order as the input. No markdown, no backticks, no preamble.
"""

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def pick(row: Dict[str, Any], key: str):
    """Return the value for a logical field, whatever it is physically called."""
    for candidate in COLS[key]:
        if candidate in row:
            return row[candidate]
    return None


def rows_to_dicts(result) -> List[Dict[str, Any]]:
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def rationale_hash(text: str) -> int:
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


def log_event(endpoint: str, run_id: str, status: str, stage: str,
              latency_ms: int, rows: int = 0, error: str = "", trace_id: str = ""):
    """Write app telemetry back into ClickHouse. Never allowed to break a request."""
    try:
        client.insert(
            EVENTS_TABLE,
            [[endpoint, str(run_id or ""), status, stage, int(latency_ms),
              int(rows), error[:500], trace_id]],
            column_names=["endpoint", "run_id", "status", "stage",
                          "latency_ms", "rows_returned", "error", "trace_id"],
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM rationale simplifier (cached in ClickHouse)
# ---------------------------------------------------------------------------


def simplify_rationales(rationales: List[str], force: bool = False) -> Dict[str, Any]:
    """Technical rationale -> plain English. Cache-first, one LLM call per run."""
    out = {"plain": {}, "cache_hits": 0, "llm_called": False, "llm_ok": None,
           "error": None, "tokens": 0}

    uniq = list(dict.fromkeys([r for r in rationales if r]))
    if not uniq:
        return out

    hashes = {r: rationale_hash(r) for r in uniq}
    missing = list(uniq)

    if not force:
        with langfuse.start_as_current_observation(as_type="span", name="cache-lookup") as sp:
            try:
                res = client.query(
                    f"SELECT rationale_hash, plain_text FROM {CACHE_TABLE} "
                    f"WHERE rationale_hash IN {{h:Array(UInt64)}}",
                    parameters={"h": list(hashes.values())},
                )
                found = {h: t for h, t in res.result_rows}
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
        gen.update(input={"system": SYSTEM_PROMPT, "user": missing}, model=MODEL)
        try:
            resp = llm.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(missing)},
                ],
                max_tokens=800,
                temperature=0,
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
            gen.update(
                output=plain,
                usage_details={
                    "input_tokens": resp.usage.prompt_tokens or 0,
                    "output_tokens": resp.usage.completion_tokens or 0,
                },
            )

            rows = [[hashes[o], o, out["plain"][o], MODEL] for o in missing]
            client.insert(CACHE_TABLE, rows,
                          column_names=["rationale_hash", "rationale", "plain_text", "model"])

        except Exception as e:
            out["llm_ok"] = False
            out["error"] = str(e)
            gen.update(output={"error": str(e)}, level="ERROR", status_message=str(e))
            for r in missing:          # graceful degradation: show the original
                out["plain"][r] = r

    return out


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})


@app.get("/api/pulse")
def pulse():
    """Cheap poll. Frontend compares this every 4s to detect a fresh batch load."""
    t0 = time.time()
    rid, bid, cts = COLS["run_id"][0], COLS["batch_id"][0], COLS["created_at"][0]
    try:
        res = client.query(
            f"SELECT count() AS total_rows, uniqExact({rid}) AS runs, "
            f"uniqExact({bid}) AS batches, max({cts}) AS latest FROM {AUDIT_TABLE}"
        )
        total, runs, batches, latest = res.result_rows[0]
        log_event("/api/pulse", "", "success", "clickhouse",
                  int((time.time() - t0) * 1000), rows=1)
        return {"total_rows": total, "runs": runs, "batches": batches,
                "latest": str(latest),
                "fingerprint": f"{total}:{runs}:{latest}"}
    except Exception as e:
        log_event("/api/pulse", "", "failure", "clickhouse",
                  int((time.time() - t0) * 1000), error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/runs")
def runs(limit: int = 50):
    """One card per investigation run, newest first."""
    t0 = time.time()
    c = {k: v[0] for k, v in COLS.items()}
    sql = f"""
        SELECT
            {c['run_id']}                                        AS run_id,
            any({c['batch_id']})                                 AS batch_id,
            min({c['win_start']})                                AS window_start,
            max({c['win_end']})                                  AS window_end,
            count()                                              AS steps,
            countIf({c['verdict']} = 'anomaly')                   AS anomaly_steps,
            argMaxIf({c['metric']}, {c['step_no']}, {c['step_type']} = 'final')     AS headline_metric,
            argMaxIf({c['dim_value']}, {c['step_no']}, {c['step_type']} = 'final')  AS headline_segment,
            argMaxIf({c['delta']}, {c['step_no']}, {c['step_type']} = 'final')      AS headline_delta,
            argMaxIf({c['rationale']}, {c['step_no']}, {c['step_type']} = 'final')  AS headline_rationale,
            max({c['created_at']})                               AS loaded_at
        FROM {AUDIT_TABLE}
        GROUP BY run_id
        ORDER BY loaded_at DESC
        LIMIT {{limit:UInt32}}
    """
    try:
        res = client.query(sql, parameters={"limit": limit})
        data = rows_to_dicts(res)
        for d in data:
            for k in ("window_start", "window_end", "loaded_at"):
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
    trace_id = ""

    # session_id = run_id  ->  every step of one investigation groups into one
    # Langfuse session. This is the traceability story for the judges.
    with propagate_attributes(session_id=run_id, tags=["rca-audit", "clickhouse"]):
        with langfuse.start_as_current_observation(as_type="span", name="rca-run-detail") as root:
            root.update(input={"run_id": run_id, "plain": plain, "force": force})
            try:
                trace_id = langfuse.get_current_trace_id() or ""
            except Exception:
                pass

            # --- 1. fetch: SELECT * so newly added columns show up automatically
            with langfuse.start_as_current_observation(as_type="span", name="clickhouse-fetch-run") as fetch:
                q = (f"SELECT * FROM {AUDIT_TABLE} "
                     f"WHERE {COLS['run_id'][0]} = {{run_id:String}} "
                     f"ORDER BY {COLS['step_no'][0]}")
                fetch.update(input={"sql": q})
                try:
                    res = client.query(q, parameters={"run_id": run_id})
                    raw = rows_to_dicts(res)
                    fetch.update(output={"rows": len(raw)})
                except Exception as e:
                    fetch.update(output={"error": str(e)}, level="ERROR")
                    log_event("/api/run", run_id, "failure", "clickhouse",
                              int((time.time() - t0) * 1000), error=str(e), trace_id=trace_id)
                    return JSONResponse({"error": str(e)}, status_code=500)

            if not raw:
                log_event("/api/run", run_id, "failure", "clickhouse",
                          int((time.time() - t0) * 1000), error="run not found", trace_id=trace_id)
                return JSONResponse({"error": f"No rows for run_id {run_id}"}, status_code=404)

            known = {name for names in COLS.values() for name in names}
            steps = []
            for r in raw:
                steps.append({
                    "step_no":    pick(r, "step_no"),
                    "step_name":  pick(r, "step_name"),
                    "step_type":  pick(r, "step_type"),
                    "metric":     pick(r, "metric"),
                    "dimension":  pick(r, "dimension"),
                    "dim_value":  pick(r, "dim_value"),
                    "actual":     pick(r, "actual"),
                    "baseline":   pick(r, "baseline"),
                    "delta":      pick(r, "delta"),
                    "contrib":    pick(r, "contrib"),
                    "verdict":    pick(r, "verdict"),
                    "rationale":  pick(r, "rationale"),
                    # any column the schema gains later lands here and renders
                    "extra": {k: str(v) for k, v in r.items() if k not in known},
                })

            # --- 2. simplify
            simplification = {"plain": {}, "cache_hits": 0, "llm_called": False,
                              "llm_ok": None, "error": None, "tokens": 0}
            if plain:
                simplification = simplify_rationales(
                    [s["rationale"] for s in steps], force=force)
                for s in steps:
                    s["plain"] = simplification["plain"].get(s["rationale"], s["rationale"])

            latency = int((time.time() - t0) * 1000)
            ok = simplification["llm_ok"] is not False
            root.update(output={"steps": len(steps), "llm_ok": simplification["llm_ok"],
                                "cache_hits": simplification["cache_hits"]})

    log_event("/api/run", run_id, "success" if ok else "failure",
              "llm" if simplification["llm_called"] else "cache_hit",
              latency, rows=len(steps), error=simplification["error"] or "",
              trace_id=trace_id)

    header = {
        "run_id": run_id,
        "batch_id": str(pick(raw[0], "batch_id")),
        "window_start": str(pick(raw[0], "win_start")),
        "window_end": str(pick(raw[0], "win_end")),
        "loaded_at": str(pick(raw[-1], "created_at")),
        "columns": res.column_names,
    }
    return {"header": header, "steps": steps, "trace_id": trace_id,
            "llm": {"model": MODEL, "called": simplification["llm_called"],
                    "ok": simplification["llm_ok"], "cache_hits": simplification["cache_hits"],
                    "tokens": simplification["tokens"], "error": simplification["error"]},
            "latency_ms": latency}


@app.get("/api/health")
def health(hours: int = 24):
    """Success / failure panel. Reads the app's own telemetry out of ClickHouse."""
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
        cols = res.column_names
        kpi = dict(zip(cols, res.result_rows[0]))

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
def verdicts(hours: int = 168):
    """Anomaly vs normal split across the audit table itself."""
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
