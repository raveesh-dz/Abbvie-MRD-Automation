import { $, $$, api } from './api.js';
import { chip, esc, skeleton, toast } from './ui.js';
import { pollJob } from './pipeline.js';
import { showResult } from './results.js';
import { loadEngineItems } from './engine.js';

const SELECTED = new Set();

export async function loadViews() {
  const box = $('#views');
  if (!box.children.length) skeleton(box, 3);   // first paint only — no flash on refresh
  const views = await api('GET', '/api/views');
  box.innerHTML = views.map((v) => {
    if (v.status !== 'built') {
      const action = v.tag === 'capability-ready'
        ? `<button class="btn promote" data-id="${v.id}">Ask engine to build</button>`
        : '';
      return `<div class="card view-card placeholder">
        <h3>${esc(v.title)}</h3>
        <div class="meta">${esc(v.description) || ''}</div>
        <div class="tag ${v.tag}">${v.tag === 'data-gap' ? 'Data gap' : 'Capability ready'}</div>
        ${v.note ? `<div class="status">${esc(v.note)}</div>` : ''}
        <div class="chips">${action}</div></div>`;
    }
    const chips = [
      v.stale ? chip('warn', 'stale') : chip('ok', 'fresh'),
      v.validation ? chip(v.validation === 'pass' ? 'ok' : 'fail', `validation ${v.validation}`) : '',
      v.deck_available ? chip('ok', 'deck') : '',
    ].join(' ');
    const last = v.never_run ? 'never run'
      : `last run ${v.last_run_at} · ${v.row_count} rows`;
    return `<div class="card view-card${SELECTED.has(v.id) ? ' selected' : ''}" data-id="${v.id}" tabindex="0" role="checkbox" aria-checked="${SELECTED.has(v.id)}">
      <h3>${esc(v.title)}</h3>
      <div class="meta">${esc(v.description) || ''}</div>
      <div class="status">${last}</div>
      <div class="chips">${chips}</div></div>`;
  }).join('');

  $$('.view-card:not(.placeholder)').forEach((el) => {
    const toggle = () => {
      const id = el.dataset.id;
      if (SELECTED.has(id)) SELECTED.delete(id); else SELECTED.add(id);
      el.classList.toggle('selected', SELECTED.has(id));
      el.setAttribute('aria-checked', SELECTED.has(id));
    };
    el.onclick = toggle;
    el.onkeydown = (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); } };
  });
  $$('.promote').forEach((el) => {
    el.onclick = async (e) => {
      e.stopPropagation();
      try {
        await api('POST', `/api/views/${el.dataset.id}/promote`);
        toast('Queued for the engine — see Ask the engine below');
        await loadEngineItems();
      } catch (err) { toast(err.message, 'fail'); }
    };
  });
}

export function wireRunSelected(refreshAll) {
  $('#select-all').onclick = (e) => {
    $$('.view-card:not(.placeholder)').forEach((el) => {
      if (e.target.checked) SELECTED.add(el.dataset.id); else SELECTED.delete(el.dataset.id);
      el.classList.toggle('selected', e.target.checked);
      el.setAttribute('aria-checked', e.target.checked);   // keep SR state in sync
    });
  };
  $('#btn-run').onclick = async () => {
    if (!SELECTED.size) { toast('Select at least one view', 'fail'); return; }
    try {
      const ids = [...SELECTED];
      const { job_id } = await api('POST', '/api/views/run', { views: ids });
      pollJob(job_id, async (job) => {
        await refreshAll();
        for (const r of (job.summary?.results || [])) {
          if (r.ok) await showResult(r.id);
        }
      });
    } catch (e) { toast(e.message, 'fail'); }   // launch failure: loud, not silent
  };
}
