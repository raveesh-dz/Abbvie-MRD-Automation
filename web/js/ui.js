import { $ } from './api.js';

const ICONS = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6 9 17l-5-5"/></svg>',
  fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
};
export const icon = (k) => ICONS[k] || '';

export function toast(msg, kind = 'ok') {
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// Escape untrusted text before interpolating into innerHTML templates
// (engine questions are user-typed; answers/errors/takeaways come from files).
export const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

export function chip(kind, label) {
  const ic = kind === 'ok' ? icon('ok') : kind === 'fail' ? icon('fail')
           : kind === 'warn' ? icon('warn') : '';
  return `<span class="chip ${kind}">${ic}${label}</span>`;
}

export function skeleton(el, n = 3) {
  el.innerHTML = Array.from({ length: n }, () => '<div class="skel"></div>').join('');
}

export function setPipelineChip(state, label) {
  const c = $('#pipeline-chip');
  c.className = `chip ${state}`;
  c.innerHTML = state === 'run' ? `<span class="spin"></span>${label}` : label;
}
