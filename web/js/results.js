import { $, api, fmt } from './api.js';
import { esc } from './ui.js';
import { renderDeckPreview } from './deckpreview.js';

const PANELS = new Map();   // id -> {el, chart}
// Skill palette: blue + amber is the lead pair (colorblind-safe).
const PALETTE = { UC: '#1E40AF', CD: '#D97706' };
const FALLBACK = ['#1E40AF', '#D97706', '#0E7490', '#DC2626', '#64748B'];

function seriesColor(name, i) { return PALETTE[name] || FALLBACK[i % FALLBACK.length]; }

function activate(id) {
  for (const [pid, p] of PANELS) {
    p.el.classList.toggle('hidden', pid !== id);
    document.querySelector(`.tab[data-id="${pid}"]`)?.classList.toggle('active', pid === id);
  }
}

function kpis(rows, spec) {
  const s = spec.series_columns || [];
  const tot = (r) => spec.total_column ? +r[spec.total_column]
    : s.reduce((a, c) => a + (+r[c] || 0), 0);
  const last = rows[rows.length - 1], prev = rows[rows.length - 2];
  const t = tot(last), tp = prev ? tot(prev) : null;
  const wow = tp ? ((t - tp) / tp) * 100 : null;
  const cells = [
    { k: `Latest total (${last[spec.date_column]})`, n: t,
      // glyph is decorative — "% WoW" + color class carry the meaning
      d: wow == null ? '' : `<span aria-hidden="true">${wow >= 0 ? '▲' : '▼'}</span> ${fmt(Math.abs(wow))}% WoW`,
      dir: wow >= 0 ? 'up' : 'down' },
    ...s.map((c) => ({ k: c, n: +last[c],
      d: t ? `${fmt((100 * +last[c]) / t)}% of total` : '', dir: 'up' })),
  ];
  return `<div class="kpis">${cells.map((c) =>
    `<div class="kpi"><div class="k">${esc(c.k)}</div>` +
    `<div class="v" data-n="${c.n}">${fmt(c.n, 0)}</div>` +
    `<div class="d ${c.dir}">${c.d}</div></div>`).join('')}</div>`;
}

function animateKpis(root) {  // Executive Dashboard count-up (skill effect)
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  root.querySelectorAll('.kpi .v[data-n]').forEach((el) => {
    const target = +el.dataset.n, dur = 300, t0 = performance.now();  // ≤300ms motion band
    const step = (now) => {
      const k = Math.min((now - t0) / dur, 1);
      el.textContent = fmt(target * (0.25 + 0.75 * k), 0);
      if (k < 1) requestAnimationFrame(step); else el.textContent = fmt(target, 0);
    };
    requestAnimationFrame(step);
  });
}

function drawChart(canvas, rows, spec, old) {
  if (old) old.destroy();
  const labels = rows.map((r) => r[spec.date_column]);
  const datasets = (spec.series_columns || []).map((s, i) => ({
    label: s, data: rows.map((r) => +r[s]),
    borderColor: seriesColor(s, i), backgroundColor: seriesColor(s, i),
    borderWidth: 2.25, pointRadius: 0, tension: 0.15,
    borderDash: i >= 3 ? [6, 4] : [],          // 4th+ series: dash (a11y)
  }));
  return new Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options: {
      animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 250 },
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', labels: { usePointStyle: true, font: { size: 11 } } } },
      scales: {
        x: { ticks: { autoSkip: true, maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: '#E2E8F0' } },
      },
    },
  });
}

function validationPanel(meta) {
  const d = meta?.validation_detail;
  if (!d) return '';
  const items = d.checks.length
    ? d.checks.map((c) => `<li><span class="lvl ${c.level}">${c.level.toUpperCase()}</span>${esc(c.message)}</li>`).join('')
    : d.ran.map((r) => `<li><span class="lvl ok">OK</span>${esc(r)}</li>`).join('');
  return `<div class="panel"><h4>Validation — ${d.verdict} (${d.rows ?? '?'} rows)</h4>
    <ul class="checks">${items}</ul></div>`;
}

function diffPanel(diff) {
  if (!diff?.available) return '';
  const rows = Object.entries(diff.latest_deltas || {}).map(([c, d]) =>
    `<li><span class="lvl ${d.delta >= 0 ? 'ok' : 'warn'}">${d.delta >= 0 ? '+' : ''}${fmt(d.delta)}</span>` +
    `${esc(c)}: ${fmt(d.prev)} → ${fmt(d.curr)} (at ${esc(diff.compared_at)})</li>`).join('');
  return `<div class="panel"><h4>What changed vs previous run</h4>
    <ul class="checks">
      <li><span class="lvl ok">NEW</span>${diff.new_rows.length} new period(s): ${esc(diff.new_rows.join(', ')) || '—'}</li>
      ${rows || '<li><span class="lvl ok">OK</span>no value changes on shared periods</li>'}
    </ul></div>`;
}

function historyPanel(hist) {
  if (!hist.length) return '';
  const rows = hist.slice(-5).reverse().map((h) =>
    `<li><span class="lvl ${h.ok ? 'ok' : 'error'}">${h.ok ? 'OK' : 'FAIL'}</span>` +
    `${esc(h.last_run_at)} · validation ${esc(h.validation_status ?? '—')} · ${esc(h.row_count ?? '—')} rows</li>`).join('');
  return `<details><summary>Run history (last ${Math.min(hist.length, 5)})</summary>
    <div class="panel"><ul class="checks">${rows}</ul></div></details>`;
}

function tableHtml(rows, spec) {
  const cols = [spec.date_column, ...(spec.series_columns || []),
                ...(spec.total_column ? [spec.total_column] : [])];
  const head = cols.map((c) => `<th>${esc(c)}</th>`).join('');
  const body = rows.map((r) => `<tr>${cols.map((c) =>
    `<td>${isNaN(+r[c]) ? esc(r[c]) : fmt(+r[c])}</td>`).join('')}</tr>`).join('');
  return `<div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

export async function showResult(id, log = '') {
  const [data, diff, hist] = await Promise.all([
    api('GET', `/api/views/${id}/result`),
    api('GET', `/api/views/${id}/diff`),
    api('GET', `/api/views/${id}/history`),
  ]);
  $('#sec-results').classList.remove('hidden');

  if (!PANELS.has(id)) {
    const tab = document.createElement('button');
    tab.className = 'tab'; tab.dataset.id = id;
    tab.onclick = () => activate(id);
    $('#result-tabs').appendChild(tab);
    const el = document.createElement('div');
    $('#result-panels').appendChild(el);
    PANELS.set(id, { el, chart: null });
  }
  const p = PANELS.get(id);
  document.querySelector(`.tab[data-id="${id}"]`).textContent =
    (data.spec.title || id).replace(/\n/g, ' ');

  const maxAt = data.data_max_at_run
    ? (typeof data.data_max_at_run === 'string'
        ? data.data_max_at_run
        : Object.values(data.data_max_at_run).sort().pop())
    : null;

  p.el.innerHTML = `
    ${kpis(data.rows, data.spec)}
    <div class="deck-link">
      ${maxAt ? `<span class="run-against">Run against data through <b>${esc(maxAt)}</b></span>` : ''}
      ${data.meta?.deck_available ? `<a class="btn" href="/api/views/${id}/deck">Download deck (.pptx)</a>` : ''}
    </div>
    <div class="result-wrap">
      <div class="chart-box"><canvas height="130"></canvas></div>
      <div class="takeaways">${esc(data.takeaways) || 'No takeaways file.'}</div>
    </div>
    ${diffPanel(diff)}
    ${validationPanel(data.meta)}
    <div class="deckprev-slot"></div>
    ${historyPanel(hist)}
    ${log ? `<details><summary>Run log</summary><pre>${esc(log)}</pre></details>` : ''}
    ${tableHtml(data.rows, data.spec)}`;

  p.chart = drawChart(p.el.querySelector('canvas'), data.rows, data.spec, p.chart);
  renderDeckPreview(p.el.querySelector('.deckprev-slot'), data.rows, data.spec);
  animateKpis(p.el);
  activate(id);
  $('#sec-results').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
