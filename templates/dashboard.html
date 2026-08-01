<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RCA — incident ledger</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#1A1A1A; --bg2:#212121; --card:#2B2B2B; --line:#3A3A3A;
  --fg:#F2F2F2; --muted:#9B9B9B; --dim:#6E6E6E;
  --red:#EF4444; --red-bg:#3B1416; --red-fg:#FF8A8A;
  --grn:#22C55E; --grn-bg:#14401F; --grn-fg:#5FE87C;
  --amb:#F59E0B; --amb-bg:#3A2A0B; --amb-fg:#FFC04D;
  --sans:'Inter',system-ui,sans-serif; --mono:'IBM Plex Mono',monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);
  -webkit-font-smoothing:antialiased}
a{color:var(--amb-fg)}

header{display:flex;align-items:center;gap:22px;padding:14px 28px;flex-wrap:wrap;
  border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30;
  background:rgba(26,26,26,.96);backdrop-filter:blur(8px)}
.brand{font-weight:600;font-size:15px}
.brand i{width:7px;height:7px;border-radius:50%;background:var(--grn);
  display:inline-block;margin-right:8px;animation:ping 2.4s ease-out infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}
  70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.seg{display:flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.seg button{background:none;border:0;color:var(--muted);font-family:var(--sans);
  font-size:12px;padding:6px 13px;cursor:pointer}
.seg button.on{background:var(--card);color:var(--fg)}
.meta{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:auto;
  display:flex;gap:16px;flex-wrap:wrap}
.meta b{color:var(--fg);font-weight:500}

main{padding:22px 28px 70px}
.count{font-family:var(--mono);font-size:11px;color:var(--dim);margin-bottom:14px;
  letter-spacing:.08em;text-transform:uppercase}

/* ---------- the horizontal record ---------- */
.rec{background:var(--bg2);border:1px solid var(--line);border-left:3px solid var(--line);
  border-radius:8px;margin-bottom:12px;overflow:hidden;animation:rise .3s ease both}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.rec.anomaly{border-left-color:var(--red)}
.rec.normal{border-left-color:var(--grn)}
.rec.insufficient_volume{border-left-color:var(--amb)}
.rec.fresh{animation:landed 2.6s ease-out}
@keyframes landed{0%{background:rgba(245,158,11,.2)}100%{background:var(--bg2)}}

.row{display:flex;align-items:center;gap:26px;padding:15px 20px;cursor:pointer;
  flex-wrap:wrap}
.row:hover{background:var(--card)}
.cell{min-width:0}
.cell .k{font-family:var(--mono);font-size:9px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--dim);margin-bottom:4px;white-space:nowrap}
.cell .v{font-family:var(--mono);font-size:14px;white-space:nowrap}
.cell.wide{flex:1 1 260px;min-width:200px}
.cell.wide .v{font-family:var(--sans);font-size:13.5px;white-space:normal;
  line-height:1.45;color:var(--fg)}
.cell.wide .v.pending{color:var(--dim);font-family:var(--mono);font-size:11.5px}

.badge{font-family:var(--mono);font-size:10px;padding:3px 9px;border-radius:4px;
  text-transform:uppercase;letter-spacing:.07em;white-space:nowrap}
.badge.anomaly{background:var(--red-bg);color:var(--red-fg);border:1px solid var(--red)}
.badge.normal{background:var(--grn-bg);color:var(--grn-fg);border:1px solid var(--grn)}
.badge.insufficient_volume{background:var(--amb-bg);color:var(--amb-fg);border:1px solid var(--amb)}
.badge.ruled_out{background:var(--grn-bg);color:var(--grn-fg);border:1px solid var(--grn)}
.down{color:var(--red-fg)} .up{color:var(--grn-fg)} .flat{color:var(--muted)}
.caret{color:var(--dim);font-family:var(--mono);font-size:14px;margin-left:auto;
  transition:transform .2s}
.rec.open .caret{transform:rotate(180deg)}

/* ---------- drawer ---------- */
.drawer{display:none;border-top:1px solid var(--line);padding:18px 20px 20px;
  background:var(--bg)}
.rec.open .drawer{display:block}
.drawer h4{font-family:var(--mono);font-size:9.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--dim);font-weight:500;margin:0 0 10px}
.chain{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11.5px;
  margin-bottom:18px}
.chain th{text-align:left;color:var(--dim);font-weight:500;padding:6px 12px 6px 0;
  border-bottom:1px solid var(--line);font-size:9px;letter-spacing:.1em;
  text-transform:uppercase;white-space:nowrap}
.chain td{padding:8px 12px 8px 0;border-bottom:1px solid rgba(58,58,58,.5);
  color:var(--muted);vertical-align:top}
.chain td.step{color:var(--fg)}
.chain td.why{font-family:var(--sans);font-size:12px;line-height:1.45;min-width:220px}
.chain tr.anomaly td.step{color:var(--red-fg)}
.bar{width:70px;height:3px;background:var(--line);border-radius:2px;
  overflow:hidden;display:inline-block;vertical-align:middle;margin-right:8px}
.bar i{display:block;height:100%;background:var(--red)}
.foot{display:flex;gap:22px;flex-wrap:wrap;font-family:var(--mono);font-size:11px;
  color:var(--muted);padding-top:4px}
.foot .verified{color:var(--grn-fg)} .foot .unverified{color:var(--amb-fg)}

/* ---------- health ---------- */
.health{margin-top:34px;border-top:1px solid var(--line);padding-top:22px}
.health h3{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim);font-weight:500;margin:0 0 14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(115px,1fr));gap:12px;
  margin-bottom:18px}
.kpi{background:var(--bg2);border:1px solid var(--line);border-radius:7px;padding:11px 14px}
.kpi .k{font-family:var(--mono);font-size:9px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--dim)}
.kpi .v{font-family:var(--mono);font-size:19px;font-weight:600;margin-top:5px}
.kpi .v small{font-size:11px;color:var(--muted);font-weight:400}
.ok{color:var(--grn-fg)} .bad{color:var(--red-fg)} .warn{color:var(--amb-fg)}
#hbox table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:10.5px}
#hbox th{text-align:left;color:var(--dim);font-weight:500;padding:5px 10px 5px 0;
  border-bottom:1px solid var(--line);font-size:9px;letter-spacing:.08em;text-transform:uppercase}
#hbox td{padding:5px 10px 5px 0;border-bottom:1px solid rgba(58,58,58,.5);color:var(--muted)}
#hbox td.s-success{color:var(--grn-fg)} #hbox td.s-failure{color:var(--red-fg)}

#toast{position:fixed;bottom:24px;right:24px;background:var(--card);
  border-left:3px solid var(--amb);padding:13px 18px;border-radius:6px;
  font-family:var(--mono);font-size:12px;transform:translateY(80px);opacity:0;
  transition:.35s cubic-bezier(.2,.8,.2,1);z-index:60;max-width:300px}
#toast.show{transform:none;opacity:1}
#toast b{color:var(--amb)}
.empty{color:var(--dim);font-family:var(--mono);font-size:12px;padding:60px 0;
  text-align:center;line-height:1.9}
.err{border:1px solid var(--red);background:rgba(239,68,68,.08);color:var(--red-fg);
  padding:14px 16px;border-radius:6px;font-family:var(--mono);font-size:12px;line-height:1.6}
@media(max-width:820px){.row{gap:16px}.cell.wide{flex-basis:100%}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>

<header>
  <div class="brand"><i></i>RCA &middot; incident ledger</div>
  <div class="seg">
    <button id="bAnom" class="on" onclick="setFilter(true)">Anomalies</button>
    <button id="bAll" onclick="setFilter(false)">All runs</button>
  </div>
  <div class="meta" id="pulse">connecting&hellip;</div>
</header>

<main>
  <div class="count" id="count"></div>
  <div id="list"><div class="empty">loading&hellip;</div></div>
  <div class="health"><h3>Pipeline health &middot; last 24h</h3>
    <div class="kpis" id="kpis"></div><div id="hbox"></div></div>
</main>

<div id="toast"></div>

<script>
let ONLY_ANOM = true, FP = null, LOADED = {}, OPEN = new Set();
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nf = (n, d) => n === null || n === undefined || isNaN(n) ? '—'
  : Number(n).toLocaleString('en-US', {minimumFractionDigits:d ?? 0, maximumFractionDigits:d ?? 0});
const isMoney = m => /revenue|ecpm|cpm|spend|cost|price/i.test(m || '');
const fmt = (n, m) => n === null || n === undefined ? '—'
  : isMoney(m) ? '₹' + nf(n, Math.abs(n) >= 1000 ? 0 : 2)
  : Math.abs(n) >= 1000 ? nf(n, 0)
  : nf(n, 4).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
const day = s => String(s).slice(0, 10);

function toast(m){ const t=$('#toast'); t.innerHTML=m; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 5000); }

async function pulse(){
  try{
    const p = await (await fetch('/api/pulse')).json();
    if(p.error) throw new Error(p.error);
    $('#pulse').innerHTML = `ledger rows <b>${p.total_rows}</b>`
      + `<span>runs <b>${p.runs}</b></span>`
      + `<span>traces <b>${p.traces}</b></span>`
      + `<span>last write <b>${p.latest}</b></span>`;
    if(FP && p.fingerprint !== FP){
      toast('<b>New investigation written.</b><br>refreshing the ledger');
      await load(true); health();
    }
    FP = p.fingerprint;
  }catch(e){ $('#pulse').innerHTML = `<span class="bad">clickhouse unreachable — ${esc(e.message)}</span>`; }
}

function setFilter(only){
  ONLY_ANOM = only;
  $('#bAnom').classList.toggle('on', only);
  $('#bAll').classList.toggle('on', !only);
  load(false);
}

async function load(highlight){
  const r = await (await fetch(`/api/incidents?only_anomalies=${ONLY_ANOM}`)).json();
  if(r.error){ $('#list').innerHTML = `<div class="err">${esc(r.error)}</div>`; return; }
  const seen = new Set([...document.querySelectorAll('.rec')].map(e=>e.dataset.id));

  $('#count').textContent = ONLY_ANOM
    ? `${r.incidents.length} confirmed anomal${r.incidents.length===1?'y':'ies'}`
    : `${r.incidents.length} investigation${r.incidents.length===1?'':'s'}`;

  $('#list').innerHTML = r.incidents.map(x =>
    record(x, highlight && !seen.has(x.run_id))).join('')
    || `<div class="empty">${ONLY_ANOM
        ? 'No confirmed anomalies.<br>Every investigation was cleared or inconclusive.'
        : 'Ledger is empty.'}</div>`;

  r.incidents.forEach(x => { if(OPEN.has(x.run_id)) expand(x.run_id, true); });
  r.incidents.forEach(x => fetchDiagnosis(x.run_id));
}

function record(x, fresh){
  const dir = x.change_pct < 0 ? 'down' : x.change_pct > 0 ? 'up' : 'flat';
  const where = x.driver_segment && x.driver_segment !== 'all'
    ? `${x.driver_dimension}=${x.driver_segment}`
    : (x.segment && x.segment !== 'all' ? `${x.dimension}=${x.segment}` : 'global');
  return `
  <div class="rec ${x.verdict}${fresh?' fresh':''}" data-id="${x.run_id}">
    <div class="row" onclick="toggle('${x.run_id}')">
      <div class="cell"><div class="k">window</div>
        <div class="v">${day(x.incident_start)}</div></div>
      <div class="cell"><div class="k">metric</div>
        <div class="v">${esc(x.metric)}</div></div>
      <div class="cell"><div class="k">observed</div>
        <div class="v">${fmt(x.observed, x.metric)}</div></div>
      <div class="cell"><div class="k">expected</div>
        <div class="v">${fmt(x.expected, x.metric)}</div></div>
      <div class="cell"><div class="k">change</div>
        <div class="v ${dir}">${x.change_pct===null?'—':x.change_pct.toFixed(1)+'%'}</div></div>
      <div class="cell"><div class="k">localised to</div>
        <div class="v">${esc(where)}</div></div>
      <div class="cell"><div class="k">verdict</div>
        <div class="v"><span class="badge ${x.verdict}">${esc(x.verdict.replace('_',' '))}</span></div></div>
      <div class="cell wide"><div class="k">diagnosis</div>
        <div class="v pending" id="dx-${x.run_id}">narrating&hellip;</div></div>
      <div class="caret">&#8964;</div>
    </div>
    <div class="drawer" id="dw-${x.run_id}">
      <div class="empty">opening&hellip;</div>
    </div>
  </div>`;
}

async function fetchDiagnosis(id){
  if(LOADED[id]) { paint(id, LOADED[id]); return; }
  try{
    const d = await (await fetch(`/api/run/${id}`)).json();
    if(d.error) throw new Error(d.error);
    LOADED[id] = d; paint(id, d);
  }catch(e){
    const el = document.getElementById('dx-' + id);
    if(el){ el.className = 'v pending'; el.textContent = 'narration unavailable'; }
  }
}

function paint(id, d){
  const el = document.getElementById('dx-' + id);
  if(el){
    const t = (d.diagnosis && d.diagnosis.text) || d.steps.find(s=>s.step_type==='final')?.rationale;
    el.className = 'v'; el.textContent = t || '—';
  }
  const dw = document.getElementById('dw-' + id);
  if(dw) dw.innerHTML = drawer(d);
}

function drawer(d){
  const g = d.diagnosis && d.diagnosis.grounding;
  const rows = d.steps.map(s => `
    <tr class="${s.verdict}">
      <td>${s.step_order}</td>
      <td class="step">${esc(s.step_name)}</td>
      <td>${esc(s.step_type)}</td>
      <td>${esc(s.metric)}</td>
      <td>${esc(s.dimension)}=${esc(s.segment)}</td>
      <td>${fmt(s.expected, s.metric)} &rarr; ${fmt(s.observed, s.metric)}</td>
      <td><span class="bar"><i style="width:${Math.min(100,Math.abs(s.contribution_pct||0))}%"></i></span>${nf(s.contribution_pct,0)}%</td>
      <td><span class="badge ${s.verdict}">${esc(String(s.verdict).replace('_',' '))}</span></td>
      <td class="why">${esc(s.rationale)}</td>
    </tr>`).join('');

  return `<h4>Investigation chain &middot; ${d.steps.length} steps</h4>
    <table class="chain">
      <tr><th>#</th><th>step</th><th>type</th><th>metric</th><th>scope</th>
          <th>expected &rarr; observed</th><th>contribution</th><th>verdict</th><th>rationale</th></tr>
      ${rows}
    </table>
    <div class="foot">
      <span>&#9201; ${(d.latency_ms/1000).toFixed(1)}s</span>
      <span>&#9889; ${d.diagnosis.cached ? 'cached narration' : esc(d.model)}</span>
      ${g ? `<span class="${g.unverified.length?'unverified':'verified'}">
        ${g.unverified.length ? '&#9888; '+g.unverified.length+' of '+g.total+' numbers unverified'
                              : '&#10003; '+g.total+' numbers, all verified'}</span>` : ''}
      ${d.ledger_trace_url ? `<a href="${d.ledger_trace_url}" target="_blank" rel="noopener">
        &#8599; langfuse trace ${d.ledger_trace_id.slice(0,8)}</a>` : ''}
      <span>run ${d.run_id.slice(0,8)}</span>
    </div>`;
}

function toggle(id){
  const rec = document.querySelector(`.rec[data-id="${id}"]`);
  const open = rec.classList.toggle('open');
  open ? OPEN.add(id) : OPEN.delete(id);
  if(open && !LOADED[id]) fetchDiagnosis(id);
}
function expand(id, silent){
  const rec = document.querySelector(`.rec[data-id="${id}"]`);
  if(rec) rec.classList.add('open');
}

async function health(){
  const h = await (await fetch('/api/health')).json();
  if(h.error) return;
  const k = h.kpi;
  $('#kpis').innerHTML = [
    ['calls 24h', k.calls, ''],
    ['success', k.ok, 'ok'],
    ['failure', k.failed, k.failed>0?'bad':''],
    ['success rate', k.success_rate+'<small>%</small>', k.success_rate>=95?'ok':'warn'],
    ['p95', k.p95_ms+'<small>ms</small>', ''],
    ['llm calls', k.llm_calls, ''],
    ['cache hits', k.cache_hits, 'ok'],
  ].map(([a,b,c])=>`<div class="kpi"><div class="k">${a}</div><div class="v ${c}">${b}</div></div>`).join('');

  $('#hbox').innerHTML = `<table><tr><th>time</th><th>endpoint</th><th>status</th>
    <th>stage</th><th>ms</th><th>error</th></tr>` +
    h.recent.map(r=>`<tr><td>${r.ts.slice(11,19)}</td><td>${esc(r.endpoint)}</td>
      <td class="s-${r.status}">${esc(r.status)}</td><td>${esc(r.stage)}</td>
      <td>${r.latency_ms}</td><td>${esc(r.error)||'—'}</td></tr>`).join('') + `</table>`;
}

pulse(); load(false); health();
setInterval(pulse, 4000);
setInterval(health, 20000);
</script>
</body>
</html>
