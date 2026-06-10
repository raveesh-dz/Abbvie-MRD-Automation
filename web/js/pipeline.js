import { $, $$, api } from './api.js';
import { esc, icon, setPipelineChip, toast } from './ui.js';
import { showResult } from './results.js';

const HINTS = {
  check: 'Compare live data against the last acknowledged snapshot. Read-only.',
  data: 'Acknowledge new data and update the dataset cards. No analyses run.',
  full: 'Run every stale view end-to-end (analysis → validate → deck), then acknowledge.',
};
let mode = 'check';

function renderReport(r) {
  const b = $('#banner');
  b.classList.remove('hidden');
  if (r.schema === 'drift') {
    b.className = 'banner warn';
    b.textContent = 'Schema drift detected — check the data dictionaries before running anything.';
    return;
  }
  if (r.changed_tables.length) {
    b.className = 'banner warn';
    b.textContent = `Data has updated (${r.changed_tables.join(', ')}). ` +
      `${r.stale_views.length} view(s) stale: ${r.stale_views.join(', ') || '—'}.` +
      (r.acknowledged ? ' Snapshot acknowledged.' : '');
  } else if (r.stale_views.length) {
    // possible state: Data refresh acknowledged the snapshot without running
    // analyses — tables match but views still lag. Never claim "up to date".
    b.className = 'banner warn';
    b.textContent = `No new table data, but ${r.stale_views.length} view(s) are ` +
      `still stale: ${r.stale_views.join(', ')}.`;
  } else {
    b.className = 'banner';
    b.textContent = `No new data. Schema: ${r.schema}. All views up to date.`;
  }
}

// Jobs queue server-side (item 12), so two poll loops can be live at once
// (e.g. Run selected while Full pipeline runs). The OLDEST active job owns
// the stepper; later jobs show as a queued-count row. The chip goes idle
// only when NO tracked job remains.
const ACTIVE = new Map();              // jobId -> latest job object (insertion = start order)
let lastStepperJson = '';

function renderStepper() {
  const ol = $('#stepper');
  if (!ACTIVE.size) return;
  ol.classList.remove('hidden');
  const jobs = [...ACTIVE.values()];
  const job = jobs[0];                 // oldest active job owns the panel
  const queued = jobs.length - 1;
  const next = JSON.stringify([job.steps, queued]);
  if (next === lastStepperJson) return;          // skip identical 1s repaints
  lastStepperJson = next;
  ol.innerHTML = job.steps.map((s) => {
    const cls = s.status === 'ok' ? 'ok' : s.status === 'fail' ? 'fail'
      : s.status === 'running' ? 'running' : 'pending';
    const ic = s.status === 'ok' ? icon('ok') : s.status === 'fail' ? icon('fail')
      : s.status === 'running' ? '<span class="spin"></span>' : '·';
    return `<li class="${cls}"><span class="ic">${ic}</span>${esc(s.name)}` +
      `<span class="detail">${esc(s.detail) || ''}</span></li>`;
  }).join('') + (queued
    ? `<li class="pending"><span class="ic">·</span>queued: ${queued} more job(s)</li>` : '');
}

export async function pollJob(jobId, onDone) {
  ACTIVE.set(jobId, { id: jobId, steps: [] });
  setPipelineChip('run', 'pipeline running');
  let misses = 0;
  const tick = async () => {
    let job;
    try {
      job = await api('GET', `/api/jobs/${jobId}`);
      misses = 0;
    } catch (e) {
      if (++misses >= 5) {                       // ~5s of failures: give up loudly
        ACTIVE.delete(jobId);
        if (!ACTIVE.size) setPipelineChip('fail', 'poll lost');
        toast(`Lost contact with job ${jobId}: ${e.message}`, 'fail');
        return;
      }
      setTimeout(tick, 1000);
      return;
    }
    ACTIVE.set(jobId, job);
    renderStepper();
    if (job.status === 'done' || job.status === 'failed') {
      ACTIVE.delete(jobId);
      if (!ACTIVE.size) setPipelineChip('idle', 'idle');   // last active job only
      if (job.status === 'done') {
        const s = job.summary || {};
        toast(`Pipeline done — ${s.views_ok ?? 0}/${s.views_run ?? 0} views refreshed`);
      } else {
        toast('Pipeline failed — see stepper', 'fail');
      }
      try { await onDone(job); }                 // post-job render failure: loud
      catch (e) { toast(e.message, 'fail'); }
      renderStepper();                           // hand the panel to the next job
      return;
    }
    setTimeout(tick, 1000);
  };
  tick();
}

export function wirePipeline(refreshAll) {
  $('#mode-hint').textContent = HINTS[mode];
  $$('.seg').forEach((el) => {
    el.onclick = () => {
      mode = el.dataset.mode;
      $$('.seg').forEach((s) => {
        s.classList.toggle('active', s === el);
        s.setAttribute('aria-pressed', s === el);
      });
      $('#mode-hint').textContent = HINTS[mode];
    };
  });

  $('#btn-go').onclick = async () => {
    try {
      $('#confirm').classList.add('hidden');
      if (mode === 'check' || mode === 'data') {
        const r = await api('POST', '/api/pipeline/run', { mode });
        renderReport(r);
        if (mode === 'data') await refreshAll();
        return;
      }
      // full: pre-flight confirm
      const pre = await api('POST', '/api/pipeline/run', { mode: 'check' });
      renderReport(pre);
      if (pre.schema === 'drift') return;
      if (!pre.stale_views.length) {
        toast('Nothing stale — full pipeline not needed');
        return;
      }
      const c = $('#confirm');
      c.classList.remove('hidden');
      c.innerHTML = `<span>${pre.stale_views.length} stale view(s) will run: ` +
        `<b>${pre.stale_views.map(esc).join(', ')}</b>. This takes a few minutes.</span>` +
        `<button class="btn primary" id="btn-confirm">Run pipeline</button>` +
        `<button class="btn ghost" id="btn-cancel">Cancel</button>`;
      $('#btn-cancel').onclick = () => c.classList.add('hidden');
      $('#btn-confirm').onclick = async () => {
        try {
          c.classList.add('hidden');
          // pass the stale list we just confirmed — the backend skips its
          // own pre-check (one validate_schema subprocess instead of two)
          const { job_id } = await api('POST', '/api/pipeline/run',
            { mode: 'full', views: pre.stale_views });
          pollJob(job_id, async (job) => {
            await refreshAll();
            for (const r of (job.summary?.results || [])) {
              if (r.ok) await showResult(r.id);   // populate result tabs, like Run selected
            }
          });
        } catch (e) { toast(e.message, 'fail'); }
      };
    } catch (e) { toast(e.message, 'fail'); }   // 409/500/network: loud, not silent
  };
}
