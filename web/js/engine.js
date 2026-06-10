import { $, api } from './api.js';
import { chip, esc, toast } from './ui.js';
import { showResult } from './results.js';
import { loadViews } from './views.js';

let pollTimer = null;
let pollMisses = 0;
let lastItemsJson = '';

function schedulePoll() {
  // the rescheduled call must not die silently on a transient failure —
  // tolerate 5 misses (like pollJob), then give up loudly
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => {
    loadEngineItems().catch((e) => {
      if (++pollMisses >= 5) toast(`Inbox poll lost: ${e.message}`, 'fail');
      else schedulePoll();
    });
  }, 3000);
}

export async function loadEngineItems() {
  const items = await api('GET', '/api/engine');
  pollMisses = 0;
  const box = $('#engine-items');
  const next = JSON.stringify(items);
  const active = items.some((i) => i.status === 'queued' || i.status === 'running');
  clearTimeout(pollTimer);
  if (active) schedulePoll();
  if (next === lastItemsJson) return;            // skip identical 3s repaints
  lastItemsJson = next;
  box.innerHTML = items.map((i) => {
    const st = i.status === 'done' ? chip('ok', 'done')
      : i.status === 'failed' ? chip('fail', 'failed')
      : i.status === 'running' ? chip('run', 'running…')
      : chip('warn', 'queued');
    // view_id = id the engine registered in views.yaml (placeholder id for
    // promoted items, item id for plain asks) — see ENGINE_INBOX.md step 4
    const open = i.status === 'done'
      ? `<button class="btn open-result" data-vid="${esc(i.view_id || i.id)}">Open result</button>` : '';
    return `<div class="card">
      <h3>${esc(i.question)}</h3>
      <div class="meta">${esc(i.created_at)}${i.answer ? ` · ${esc(i.answer)}` : ''}${i.error ? ` · ${esc(i.error)}` : ''}</div>
      <div class="chips">${st} ${i.build_deck ? chip('ok', 'deck requested') : ''} ${open}</div>
    </div>`;
  }).join('') || '<div class="card"><div class="meta">No questions yet.</div></div>';

  document.querySelectorAll('.open-result').forEach((el) => {
    el.onclick = async () => {
      try {
        await loadViews();               // engine session registered it in views.yaml
        await showResult(el.dataset.vid);
      } catch (e) {
        toast(e.message || 'View not registered yet — check views.yaml', 'fail');
      }
    };
  });
}

export function wireEngine() {
  $('#btn-ask').onclick = async () => {
    const q = $('#ask-q').value.trim();
    if (!q) { toast('Type a question first', 'fail'); return; }
    try {
      await api('POST', '/api/engine/ask', { question: q, build_deck: $('#ask-deck').checked });
      $('#ask-q').value = '';
      toast('Queued — the live Claude Code session will pick it up');
      await loadEngineItems();
    } catch (e) { toast(e.message, 'fail'); }
  };
}
