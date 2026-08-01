# inMobi — RCA Audit Trail

Automated root-cause analysis, made readable. Every investigation the analyst runs
writes a step-by-step audit trail into ClickHouse; this app turns that trail into a
live dashboard that anyone can read, with full LLM observability behind it.

Built for Click-a-thon 2026, Data Warehousing track — team **Flux4**.

```
      loader / RCA agent
             │
             ▼
   ClickHouse Cloud  ──────────────┐  rca.audit_log      (the reasoning chain)
   (primary database)              │  rca.rationale_cache (plain-English cache)
             │                     │  rca.app_events      (this app's own telemetry)
             ▼                     │
   FastAPI  /api/pulse  ───────────┘
            /api/runs                     ┌──────────────┐
            /api/run/{id} ──▶ OpenRouter ─┤ plain English │
            /api/health                   └──────────────┘
             │                                   │
             ▼                                   ▼
        Dashboard UI                        Langfuse Cloud
   (live, auto-refreshing)            session_id = run_id, every
                                      step and LLM call traced
```

## What it does

**1. Reads the reasoning chain.** Each run in `rca.audit_log` is a numbered sequence
of steps — detect, decompose, localize, rule out, conclude. The dashboard renders it
as a ladder so you can follow the analyst's logic top to bottom, with the actual vs
baseline numbers and a contribution bar on every rung.

**2. Translates the jargon.** The `rationale` column is written for analysts. One LLM
call per run rewrites all of it for a business stakeholder, and the toggle flips
between the two. Results are cached in ClickHouse by content hash, so the second load
costs nothing. If the LLM is down, the original text shows and the header says so.

**3. Picks up new batches by itself.** `/api/pulse` fingerprints the table every four
seconds. When the loader inserts a new run, a toast fires and the run appears at the
top of the rail — no refresh. `/api/run` selects every column and maps known ones
through an alias table, so **a column added upstream renders automatically** instead
of breaking the page.

**4. Watches itself.** Every request writes success or failure, stage, latency and
error into `rca.app_events`. The KPI strip and health table read straight back out of
it. The dashboard is observed by the same warehouse it serves from.

**5. Traces end to end.** Langfuse `session_id` is the `run_id`, so one investigation
is one session. Child spans cover the ClickHouse fetch, the cache lookup, and the LLM
generation with prompt, output and token counts. The Langfuse `trace_id` is stored on
each `app_events` row, so you can go from a slow query in ClickHouse straight to the
trace that caused it.

## Setup

```bash
git clone <your-repo-url> && cd inMobi
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in the real values
```

Then paste `sql/01_setup.sql` into the ClickHouse Cloud SQL console. It creates the
cache and telemetry tables, and the audit table if you do not already have one.

```bash
uvicorn app:app --reload --port 8000   # http://localhost:8000
```

### Environment

| Variable | What it is |
|---|---|
| `CH_HOST` `CH_PORT` `CH_USER` `CH_PASSWORD` | ClickHouse Cloud, port 8443, TLS on |
| `CH_DB` `AUDIT_TABLE` | database and fully-qualified audit table name |
| `OPENROUTER_API_KEY` | from openrouter.ai → Keys, starts `sk-or-` |
| `LLM_MODEL` | `openai/gpt-oss-20b:free` — free tier, reliable at structured output |
| `LANGFUSE_PUBLIC_KEY` `LANGFUSE_SECRET_KEY` `LANGFUSE_HOST` | cloud.langfuse.com |

`.env` is gitignored. On Render, set the same keys under Environment.

### If your column names differ

Everything reads through the `COLS` dict at the top of `app.py`. Add your name to the
right list and the whole app follows — no other file changes.

## Demo

Leave the dashboard on the projector. In a second terminal:

```bash
python scripts/load_batch.py
python scripts/load_batch.py --metric ctr --segment "iOS 18" --drop 0.31
```

The toast fires, the run lands at the top of the rail, the ladder renders, and the
health strip counts it. Open Langfuse alongside and the matching session is already
there.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | dashboard |
| `GET /api/pulse` | row/run/batch counts and latest load time — the poll target |
| `GET /api/runs` | one summary card per investigation, newest first |
| `GET /api/run/{run_id}` | full chain, plain English, Langfuse trace id |
| `GET /api/health` | success/failure KPIs and the last 25 calls |
| `GET /api/verdicts` | anomaly vs normal split across the audit table |

Add `?plain=false` to see raw rationale, `?force=true` to bypass the cache.

## Stack

ClickHouse Cloud · FastAPI · Jinja2 · Langfuse v4 · OpenRouter · Render
