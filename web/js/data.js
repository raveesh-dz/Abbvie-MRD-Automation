import { $, api, fmt } from './api.js';
import { chip, esc, skeleton, toast } from './ui.js';

export async function loadTables() {
  const box = $('#tables');
  if (!box.children.length) skeleton(box, 2);   // first paint only — no flash on refresh
  const tables = await api('GET', '/api/tables');
  let maxStamp = '';
  box.innerHTML = tables.map((t) => {
    if (t.max_date > maxStamp) maxStamp = t.max_date;
    const quality = t.metric_nulls === 0
      ? chip('ok', 'no nulls') : chip('warn', `${t.metric_nulls} nulls`);
    return `<div class="card">
      <h3>${esc(t.name)}</h3>
      <div class="meta">
        <div>${esc(t.description) || ''}</div>
        <div><b>Grain:</b> ${esc(t.grain)}</div>
        <div><b>Range:</b> ${esc(t.min_date)} → ${esc(t.max_date)} (${t.periods} periods)</div>
        <div><b>Rows:</b> ${fmt(t.row_count, 0)} · <b>Refresh:</b> ${esc(t.refresh)}</div>
      </div>
      <div class="chips">${t.updated ? chip('warn', 'data updated') : chip('ok', 'in sync')} ${quality}</div>
    </div>`;
  }).join('');
  $('#freshness').textContent = `Latest data: ${maxStamp}`;
}

export async function refreshDemoChip() {
  const { demo_active } = await api('GET', '/api/data/demo-status');
  $('#demo-chip').classList.toggle('hidden', !demo_active);
}

export function wireSimulate(refreshAll) {
  $('#btn-simulate').onclick = async () => {
    const weeks = +$('#sim-weeks').value;
    try {
      const r = await api('POST', '/api/data/simulate', { weeks });
      toast(`Added weeks ${r.weekly_added.join(', ')} + month ${r.monthly_added[0]}`);
      await refreshAll();
    } catch (e) { toast(e.message, 'fail'); }
  };
  $('#btn-reset').onclick = async () => {
    try {
      await api('POST', '/api/data/reset');
      toast('Demo data reset to originals');
      await refreshAll();
    } catch (e) { toast(e.message, 'fail'); }
  };
}
