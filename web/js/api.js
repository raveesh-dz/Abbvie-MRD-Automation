export const $ = (s) => document.querySelector(s);
export const $$ = (s) => [...document.querySelectorAll(s)];

export async function api(method, path, body) {
  const r = await fetch(path, body
    ? { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : { method });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
}

export const fmt = (n, d = 1) =>
  (+n).toLocaleString(undefined, { maximumFractionDigits: d });
