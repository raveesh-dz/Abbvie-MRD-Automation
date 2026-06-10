import { fmt } from './api.js';
import { esc } from './ui.js';

// Builder defaults — VERBATIM from scripts/build_deck_pptx.py content_slide()
// (DEFAULT_DEK/DEFAULT_BLOCKS/DEFAULT_TLDR + the statement_title fallback),
// with {key:spec} placeholders intact: fill() consumes the :spec suffix and
// deckCtx pre-formats every value, so preview text == slide text.
const DEFAULT_STATEMENT_TITLE =
  "Crohn's Has Overtaken Ulcerative Colitis in Tremfya's IBD Mix";
const DEFAULT_DEK =
  "Tremfya's weekly IBD volume has scaled from ~{first_total:,.0f} to " +
  "~{latest_total:,.0f} TRx since {first_month}. Within IBD, Crohn's pulled " +
  'level in {cross_month} and now leads ulcerative colitis.';
const DEFAULT_BLOCKS = [
  { num: '01', head: "Crohn's now leads",
    body_template: 'CD ~{latest_cd:,.0f} vs UC ~{latest_uc:,.0f} TRx in the latest week ({latest_label}).' },
  { num: '02', head: 'Crossover · {cross_month}',
    body_template: 'UC led decisively in early 2025; the two drew level by autumn before CD pulled ahead.' },
  { num: '03', head: '~{ramp:,.0f}x ramp',
    body_template: "Tremfya's IBD volume rose from ~{first_total:,.0f} to ~{latest_total:,.0f} weekly TRx." },
];
const DEFAULT_TLDR =
  "Within Tremfya's IBD business, Crohn's has overtaken ulcerative colitis " +
  'and is the faster-growing of the two indications.';
const DEFAULT_SECTION_STRIP = 'TREMFYA IBD  ·  WEEKLY TRX BY INDICATION';

const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const prettyMonth = (d) => {
  const [y, m] = String(d).split('-');
  return `${MONTHS[+m] || ''} ${y}`.trim();
};

function deckCtx(rows, spec) {
  const d = spec.date_column, s = spec.series_columns || [];
  const tot = (r) => spec.total_column ? +r[spec.total_column]
    : s.reduce((a, c) => a + (+r[c] || 0), 0);
  // builder: first meaningful week = first row with total > 0
  let firstIdx = rows.findIndex((r) => tot(r) > 0);
  if (firstIdx < 0) firstIdx = 0;
  const first = rows[firstIdx], last = rows[rows.length - 1];
  const [a, b] = s;                              // series-1 (UC), series-2 (CD)
  // builder: durable crossover = week AFTER the last week series-1 led (total > 1)
  let lastLead = -1;
  rows.forEach((r, i) => { if (tot(r) > 1 && (+r[a] || 0) > (+r[b] || 0)) lastLead = i; });
  const cross = (lastLead >= 0 && lastLead + 1 < rows.length)
    ? prettyMonth(rows[lastLead + 1][d]) : '2025';
  const pct = (x, t) => (t ? Math.round((100 * x) / t) : 0);
  return {
    first_total: fmt(tot(first), 0), latest_total: fmt(tot(last), 0),
    ramp: fmt(Math.round(tot(last) / Math.max(tot(first), 1)), 0),
    first_month: prettyMonth(rows[0][d]),         // builder uses row 0, not firstIdx
    cross_month: cross,
    latest_label: String(last[d]).slice(5),       // MM-DD, matching the builder
    latest_uc: fmt(+last[a] || 0, 0), latest_cd: fmt(+last[b] || 0, 0),
    first_uc_pct: pct(+first[a] || 0, tot(first)),
    latest_uc_pct: pct(+last[a] || 0, tot(last)),
    latest_cd_pct: pct(+last[b] || 0, tot(last)),
  };
}

// Consume an optional Python format spec ({ramp:,.0f}) — values are pre-formatted.
const fill = (t, ctx) => (t || '').replace(/\{(\w+)(?::[^{}]*)?\}/g, (m, k) => ctx[k] ?? m);

export function renderDeckPreview(slot, rows, spec) {
  // inferred spec = no deck_spec.json = this view has no deck to preview
  if (spec.inferred || (!spec.statement_title && !spec.title) || !rows.length) {
    slot.innerHTML = '';
    return;
  }
  const ctx = deckCtx(rows, spec);
  // builder falls back to its Tremfya-tuned defaults for sparse specs —
  // only meaningful for the 2-series indication-split shape
  const isSplit = (spec.series_columns || []).length === 2;
  const title = spec.statement_title
    ?? (isSplit ? DEFAULT_STATEMENT_TITLE : spec.title);   // builder's fallback
  const dek = spec.dek_template ?? (isSplit ? DEFAULT_DEK : '');
  // esc() the TEMPLATE before fill(): deck_spec.json text is engine-authored
  // from user-typed questions; ctx values are generated numbers/months and
  // esc leaves {key} placeholders untouched.
  const F = (t) => fill(esc(t), ctx);
  const blocks = (spec.blocks ?? (isSplit ? DEFAULT_BLOCKS : [])).map((b) =>
    `<div class="blk"><div class="n">${esc(b.num ?? '')}</div>` +
    `<div class="h">${F(b.head)}</div>` +
    `<div class="b">${F(b.body_template)}</div></div>`).join('');
  const tldr = spec.tldr ?? (isSplit ? DEFAULT_TLDR : '');
  // builder renders spec.section_strip (it never reads an "eyebrow" key)
  const strip = spec.section_strip ?? (isSplit ? DEFAULT_SECTION_STRIP : '');
  slot.innerHTML = `<div class="panel"><h4>Slide preview (from deck_spec.json)</h4>
    <div class="deck-prev">
      <div class="strip"></div>
      ${strip ? `<div class="eyebrow">${F(strip)}</div>` : ''}
      <div class="st">${F(title).replace(/\n/g, ' ')}</div>
      ${dek ? `<div class="dek">${F(dek)}</div>` : ''}
      ${blocks ? `<div class="blocks">${blocks}</div>` : ''}
      ${tldr ? `<div class="tldr">TL;DR — ${F(tldr)}</div>` : ''}
    </div></div>`;
}
