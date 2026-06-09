const $ = (s) => document.querySelector(s);
const api = async (m, p, b) => {
  const r = await fetch(p, b ? {method:m, headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)} : {method:m});
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.status);
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
};

let SELECTED = new Set();

async function loadTables(){
  const tables = await api('GET','/api/tables');
  let maxStamp = '';
  $('#tables').innerHTML = tables.map(t=>{
    if (t.max_date > maxStamp) maxStamp = t.max_date;
    return `<div class="card">
      <h3>${t.name} ${t.updated?'<span class="badge updated">data updated</span>':''}</h3>
      <div class="meta">
        <div>${t.description||''}</div>
        <div><b>Grain:</b> ${t.grain}</div>
        <div><b>Date range:</b> ${t.min_date} → ${t.max_date}</div>
        <div><b>Rows:</b> ${t.row_count.toLocaleString()} · <b>Refresh:</b> ${t.refresh}</div>
      </div></div>`;
  }).join('');
  $('#freshness').textContent = `Latest data: ${maxStamp}`;
}

async function loadViews(){
  const views = await api('GET','/api/views');
  $('#views').innerHTML = views.map(v=>{
    if (v.status !== 'built'){
      return `<div class="card view-card placeholder">
        <h3>${v.title}</h3>
        <div class="meta">${v.description||''}</div>
        <div class="tag ${v.tag}">${v.tag==='data-gap'?'Data gap':'Capability ready'}</div>
        ${v.note?`<div class="status">${v.note}</div>`:''}</div>`;
    }
    const stale = v.stale?'<span class="badge stale">stale</span>':'';
    const last = v.never_run?'never run':`last run ${v.last_run_at} · ${v.row_count} rows`;
    return `<div class="card view-card${SELECTED.has(v.id)?' selected':''}" data-id="${v.id}">
      <h3>${v.title} ${stale}</h3>
      <div class="meta">${v.description||''}</div>
      <div class="status">${last}</div>
      <div class="runstate" id="rs-${v.id}"></div></div>`;
  }).join('');
  document.querySelectorAll('.view-card:not(.placeholder)').forEach(el=>{
    el.onclick = ()=>{
      const id = el.dataset.id;
      if (SELECTED.has(id)){SELECTED.delete(id); el.classList.remove('selected');}
      else {SELECTED.add(id); el.classList.add('selected');}
    };
  });
}

async function dataRefresh(){
  const r = await api('POST','/api/data/refresh-check');
  const b = $('#banner'); b.classList.remove('hidden');
  if (r.changed_tables.length){
    b.className = 'banner warn';
    b.innerHTML = `Data has updated (${r.changed_tables.join(', ')}). `+
      `${r.stale_views.length} view(s) can be refreshed. `+
      `<button class="btn" id="btn-ack">Acknowledge</button>`;
    $('#btn-ack').onclick = async()=>{ await api('POST','/api/data/acknowledge'); await refreshAll(); $('#banner').classList.add('hidden'); };
  } else {
    b.className = 'banner';
    b.textContent = `No new data. Schema: ${r.schema}. All views up to date.`;
  }
  if (r.schema === 'drift') b.innerHTML += `<div>⚠ schema drift — check dictionaries.</div>`;
}

async function runSelected(){
  if (!SELECTED.size){ alert('Select at least one view.'); return; }
  $('#btn-run').disabled = true;
  for (const id of SELECTED){
    const rs = $('#rs-'+id); if (rs){rs.className='runstate running'; rs.textContent='running…';}
    try{
      const res = await api('POST',`/api/views/${id}/run`);
      if (rs){ rs.className='runstate '+(res.ok?'ok':'fail');
        rs.textContent = res.ok?`✓ ${res.row_count} rows · validation ${res.validation}`:'✗ failed'; }
      if (res.ok) await showResult(id, res.log, res.deck_available);
    }catch(e){ if (rs){rs.className='runstate fail'; rs.textContent='✗ '+e.message;} }
  }
  $('#btn-run').disabled = false;
  await loadViews();
}

async function showResult(id, log, deckAvailable){
  const data = await api('GET',`/api/views/${id}/result`);
  $('#result-section').classList.remove('hidden');
  $('#result-title').textContent = data.spec.title?.replace(/\n/g,' ') || id;
  $('#deck-link').innerHTML =
    (data.data_max_at_run ? `<span class="run-against">Run against data through <b>${data.data_max_at_run}</b></span>` : '') +
    (deckAvailable ? `<a class="btn" href="/api/views/${id}/deck">⬇ Download deck (.pptx)</a>` : '');
  $('#takeaways').textContent = data.takeaways || '';
  $('#runlog').textContent = log || '';
  drawChart(data.rows, data.spec);
  drawTable(data.rows, data.spec);
}

function drawChart(rows, spec){
  const W=620,H=320,P=40;
  const date=spec.date_column, series=spec.series_columns;
  const colors={UC:'#07B2AC',CD:'#E40D62'};
  const xs=rows.map((_,i)=>i);
  const all=series.flatMap(s=>rows.map(r=>+r[s]));
  const ymax=Math.max(...all,1);
  const px=i=>P+i*(W-2*P)/Math.max(rows.length-1,1);
  const py=v=>H-P-(v/ymax)*(H-2*P);
  const line=s=>rows.map((r,i)=>`${i?'L':'M'}${px(i).toFixed(1)},${py(+r[s]).toFixed(1)}`).join(' ');
  const legend=series.map((s,i)=>`<text x="${P+i*130}" y="18" fill="${colors[s]||'#071D49'}" font-size="12" font-weight="700">● ${s}</text>`).join('');
  const paths=series.map(s=>`<path d="${line(s)}" fill="none" stroke="${colors[s]||'#071D49'}" stroke-width="2.25"/>`).join('');
  $('#chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%">
    ${legend}
    <line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" stroke="#D9DEE8"/>
    <line x1="${P}" y1="${P}" x2="${P}" y2="${H-P}" stroke="#D9DEE8"/>
    <text x="${P}" y="${H-P+16}" font-size="10" fill="#50535A">${rows[0][date]}</text>
    <text x="${W-P}" y="${H-P+16}" font-size="10" fill="#50535A" text-anchor="end">${rows[rows.length-1][date]}</text>
    ${paths}</svg>`;
}

function drawTable(rows, spec){
  const cols=[spec.date_column,...spec.series_columns,spec.total_column];
  const head=cols.map(c=>`<th>${c}</th>`).join('');
  const body=rows.map(r=>`<tr>${cols.map(c=>`<td>${isNaN(+r[c])?r[c]:(+r[c]).toLocaleString(undefined,{maximumFractionDigits:1})}</td>`).join('')}</tr>`).join('');
  $('#result-table').innerHTML=`<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function refreshAll(){ await loadTables(); await loadViews(); }

$('#btn-refresh').onclick = dataRefresh;
$('#btn-run').onclick = runSelected;
$('#btn-simulate').onclick = async()=>{ await api('POST','/api/data/simulate'); await refreshAll(); await dataRefresh(); };
$('#btn-reset').onclick = async()=>{ try{ await api('POST','/api/data/reset'); await refreshAll(); $('#banner').classList.add('hidden'); }catch(e){ alert(e.message);} };
$('#select-all').onclick = (e)=>{
  document.querySelectorAll('.view-card:not(.placeholder)').forEach(el=>{
    if (e.target.checked){SELECTED.add(el.dataset.id); el.classList.add('selected');}
    else {SELECTED.delete(el.dataset.id); el.classList.remove('selected');}
  });
};
refreshAll();
