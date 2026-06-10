# Dashboard Page Overrides

> **PROJECT:** Query-to-Slide Dashboard
> **Generated:** 2026-06-10 01:45:06
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** 1. Hero (product + live preview or status), 2. Key metrics/indicators, 3. How it works, 4. CTA (Start trial / Contact)

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Dark or neutral. Status colors (green/amber/red). Data-dense but scannable.

### Component Overrides

- Avoid: Leave UI frozen with no feedback

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Deal movement animations, metric updates, leaderboard ranking changes, gauge needle movements, status change highlights
- Animation: Use skeleton screens or spinners
- CTA Placement: Primary CTA in nav + After metrics

## Component Overrides (dashboard v2 — 2026-06-10)
- Primary buttons: background --color-primary #1E40AF; accent #D97706 is reserved
  for the brand mark, warm highlights, and chart series 2 (colorblind-safe
  blue/orange pair).
- Cards: white surface (Master's #F8FAFC equals the page background and would
  render invisible), 16px padding, shadow-only hover (no translateY — data-dense
  tables should not move); base shadow reduced to 0 1px 2px (shadow-sm) for the
  data-dense grid, hover uses the custom --lift instead of shadow-lg.
- Ghost buttons darken to #475569 on hover (--gray on the --muted hover tint
  is only 4.08:1).
- Buttons: compact 9x16px padding (data-dense layout; Master's 12x24 is for
  marketing CTAs).
- Spacing: data-dense scale — 12px grid gap, 36px section margins (Master token
  scale relaxed for maximum data visibility, per the Data-Dense Dashboard style).
- On-tint chip text: fail #B91C1C, idle #475569 (AA on their tinted backgrounds).
- Placeholder cards: meta/status text #475569 and data-gap tag #B91C1C (AA on the
  #F1F5F9 muted surface, where --gray/--fail fall to ~4.3:1).
- Inputs: compact 8x10px padding and 14px font for the data-dense layout; focus
  uses the global :focus-visible ring instead of the Master box-shadow ring.
- .deck-prev keeps DataZymes deck colors — it previews the branded .pptx.
