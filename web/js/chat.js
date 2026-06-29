import { $, api } from './api.js';
import { esc, toast } from './ui.js';
import { showResult } from './results.js';
import { loadViews } from './views.js';

let pollTimer = null;
let pollMisses = 0;
let lastThreadJson = '';
let lastKey = '';           // composite render key (thread JSON + stalled flag)
let lastChangeAt = 0;       // when the thread JSON last changed (stall detection)
let stalled = false;

const box = () => $('#chat-transcript');

function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => {
    loadChat().catch((e) => {
      if (++pollMisses >= 5) toast(`Chat poll lost: ${e.message}`, 'fail');
      else schedulePoll();
    });
  }, 3000);
}

function bubble(m) {
  if (m.role === 'user') return `<div class="msg user">${esc(m.text)}</div>`;
  if (m.kind === 'question' || m.kind === 'deck_offer') {
    const chips = (m.options || []).map((o) =>
      `<button class="chip-btn" data-seq="${m.seq}" data-opt="${esc(o)}">${esc(o)}</button>`).join(' ');
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">${chips}</div></div>`;
  }
  if (m.kind === 'result') {
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">` +
      `<button class="chip-btn open-result" data-vid="${esc(m.view_id)}">Open result</button></div></div>`;
  }
  if (m.kind === 'deck_ready') {
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">` +
      `<a class="chip-btn" href="${esc(m.deck_url)}">Download deck</a></div></div>`;
  }
  if (m.kind === 'error') return `<div class="msg eng err">${esc(m.text)}</div>`;
  return `<div class="msg eng">${esc(m.text)}</div>`;
}

function render(thread) {
  const engineTurn = !!(thread.thread_id && thread.turn === 'engine');
  let html = (thread.messages || []).map(bubble).join('');
  if (engineTurn) {
    html += `<div class="msg eng status"><span class="spin"></span>${esc(thread.engine_status || 'engine working…')}</div>`;
    if (stalled) {
      html += `<div class="msg eng err">waiting for the engine — is the /loop session running?` +
        `<div class="chip-row"><button class="chip-btn" id="chat-reset">Reset turn</button></div></div>`;
    }
  }
  box().innerHTML = html || '<div class="meta">Start a brainstorm — type a question below.</div>';
  $('#chat-input').disabled = engineTurn;
  $('#chat-send').disabled = engineTurn;
  box().scrollTop = box().scrollHeight;
  wireDynamic();
}

function wireDynamic() {
  document.querySelectorAll('.chip-btn[data-opt]').forEach((el) => {
    el.onclick = () => sendMessage(el.dataset.opt,
      { in_reply_to: +el.dataset.seq, chosen: el.dataset.opt });
  });
  document.querySelectorAll('.open-result').forEach((el) => {
    el.onclick = async () => {
      try { await loadViews(); await showResult(el.dataset.vid); }
      catch (e) { toast(e.message || 'view not registered yet', 'fail'); }
    };
  });
  const reset = $('#chat-reset');
  if (reset) reset.onclick = async () => {
    await api('POST', '/api/chat/reset-turn'); stalled = false; lastThreadJson = ''; lastKey = ''; await loadChat();
  };
}

export async function loadChat() {
  const thread = await api('GET', '/api/chat');
  pollMisses = 0;
  const next = JSON.stringify(thread);
  const active = !!(thread.thread_id && thread.turn === 'engine');
  if (next !== lastThreadJson) { lastChangeAt = Date.now(); stalled = false; }
  else if (active && Date.now() - lastChangeAt > 30000) { stalled = true; }
  clearTimeout(pollTimer);
  if (active) schedulePoll();                    // restart polling for the next engine turn
  lastThreadJson = next;
  // gate on a composite key so an unchanged stalled state is not repainted every tick
  const key = next + (stalled ? '|stalled' : '');
  if (key === lastKey) return;
  lastKey = key;
  render(thread);
}

async function sendMessage(text, extra = {}) {
  const t = (text ?? $('#chat-input').value).trim();
  if (!t) { toast('Type a question first', 'fail'); return; }
  try {
    await api('POST', '/api/chat/message', { text: t, ...extra });
    $('#chat-input').value = '';
    lastThreadJson = ''; lastKey = '';   // force a repaint of the new turn
    await loadChat();
  } catch (e) {
    if (e.status === 409) toast('Engine is working — wait for its reply', 'fail');
    else toast(e.message, 'fail');
  }
}

export function wireChat() {
  const send = $('#chat-send');
  if (!send) return;
  send.onclick = () => sendMessage();
  $('#chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $('#chat-new').onclick = async () => {
    try {
      await api('POST', '/api/chat/new');
    } catch (e) {
      if (e.status === 409) {
        if (!confirm('Discard the running chat?')) return;
        await api('POST', '/api/chat/new', { force: true });
      } else { toast(e.message, 'fail'); return; }
    }
    lastThreadJson = ''; lastKey = ''; stalled = false; await loadChat();
  };
  document.querySelectorAll('input[name="engine-mode"]').forEach((r) => {
    r.onchange = () => {
      const chatMode = document.querySelector('input[name="engine-mode"]:checked').value === 'chat';
      $('#engine-quick').style.display = chatMode ? 'none' : '';
      $('#engine-chat').style.display = chatMode ? '' : 'none';
      $('#chat-new').style.display = chatMode ? '' : 'none';
      if (chatMode) { lastThreadJson = ''; lastKey = ''; loadChat().catch((e) => toast(e.message, 'fail')); }
      else { clearTimeout(pollTimer); }            // stop polling while the chat panel is hidden
    };
  });
  $('#chat-new').style.display = 'none';        // hidden until chat mode is selected
}
