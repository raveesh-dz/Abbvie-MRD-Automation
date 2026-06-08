// apex_deck.js — APEX-template deck generator (config-driven)
// Used by the pipeline: build a deck from a config object describing slides.
// See README.md for the config schema and CLI usage.

const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

// real brand assets extracted from the APEX template
const ASSETS = path.join(__dirname, "..", "assets");
const A = {
  logo: path.join(ASSETS, "apex_logo.png"),
  logoWhite: path.join(ASSETS, "apex_logo_white.png"),
  footer: path.join(ASSETS, "footer_bar.png"),
  titleArt: path.join(ASSETS, "title_art.png"),
  dividerArt: path.join(ASSETS, "divider_art.png"),
};

// ----------------------------------------------------------------------------
// APEX brand tokens (extracted from the reference APEX business-review deck)
// ----------------------------------------------------------------------------
const C = {
  navy: "071D49",     // dominant brand color: titles, table headers, dividers
  teal: "07B2AC",
  green: "00B050",    // "Updated" tag
  red: "C00000",
  amber: "FFC000",
  blue: "00B0F0",
  magenta: "E40D62",  // the "X" in APEX
  purple: "7030A0",
  gray: "50535A",
  rule: "D9DEE8",
  white: "FFFFFF",
};
// line-series palette, in priority order
const SERIES = [C.teal, C.navy, C.amber, C.red, C.blue, C.magenta, C.green, C.purple];
// watercolor gradient stops (recreated programmatically; no image dependency)
const GRAD = ["7030A0", "E40D62", "C00000", "FFC000", "07B2AC", "00B0F0"];

const FONT_H = "Georgia";  // stand-in for brand header font (F37 Lineca)
const FONT_B = "Calibri";  // stand-in for brand body font (Roboto)
const W = 13.333, H = 7.5;

// ----------------------------------------------------------------------------
// shared chrome
// ----------------------------------------------------------------------------
// footer: real watercolor bar image + real APEX logo
function footer(slide, pptx, dark) {
  // gradient bar spans full width, sits flush at the very bottom
  slide.addImage({ path: A.footer, x: 0, y: 7.24, w: W, h: 0.26 });
  // logo (full lockup includes the tagline); placed bottom-left above the bar
  slide.addImage({ path: dark ? A.logoWhite : A.logo, x: 0.4, y: 6.84, w: 1.6, h: 0.44 });
}

function updatedTag(slide, pptx) {
  slide.addShape(pptx.ShapeType.roundRect, { x: 11.95, y: 0.28, w: 1.0, h: 0.4, rectRadius: 0.06, fill: { color: C.green }, line: { type: "none" } });
  slide.addText("Updated", { x: 11.95, y: 0.28, w: 1.0, h: 0.4, color: C.white, fontFace: FONT_B, fontSize: 11, bold: true, align: "center", valign: "middle" });
}

function sparseLabels(labels, keepEvery) {
  const k = keepEvery || Math.max(1, Math.round(labels.length / 20));
  return labels.map((l, i) => (i % k === 0 ? l : ""));
}

// ----------------------------------------------------------------------------
// slide builders
// ----------------------------------------------------------------------------
function buildDivider(pptx, slide) {
  const s = pptx.addSlide();
  s.background = { color: C.navy };
  // real diagonal watercolor art, full-bleed right (white made transparent so navy shows)
  s.addImage({ path: A.dividerArt, x: 4.0, y: 0, w: 9.333, h: 7.5, sizing: { type: "cover", w: 9.333, h: 7.5 } });
  s.addText(slide.title || "", { x: 0.6, y: 2.5, w: 4.6, h: 2.2, color: C.white, fontFace: FONT_H, fontSize: 40, bold: true, valign: "middle" });
  if (slide.subtitle) s.addText(slide.subtitle, { x: 0.62, y: 4.5, w: 4.4, h: 0.6, color: "CADCFC", fontFace: FONT_B, fontSize: 16 });
  footer(s, pptx, true);
}

function buildTitle(pptx, slide) {
  const s = pptx.addSlide();
  s.background = { color: C.white };
  // real watercolor splash, upper area, full width
  s.addImage({ path: A.titleArt, x: 0, y: 0, w: W, h: 4.3, sizing: { type: "cover", w: W, h: 4.3 } });
  s.addText(slide.title || "", { x: 0.7, y: 4.55, w: 9.5, h: 1.2, color: C.navy, fontFace: FONT_H, fontSize: 40, bold: true });
  if (slide.subtitle) s.addText(slide.subtitle, { x: 0.72, y: 5.75, w: 9.0, h: 0.6, color: C.gray, fontFace: FONT_B, fontSize: 16 });
  footer(s, pptx, false);
}

// chart slide: 1 or 2 line charts + optional summary table
function buildChart(pptx, slide) {
  const s = pptx.addSlide();
  s.background = { color: C.white };
  s.addText(slide.title || "", { x: 0.5, y: 0.3, w: 11.2, h: 0.85, color: C.navy, fontFace: FONT_H, fontSize: 22, bold: true, valign: "middle" });
  if (slide.updated) updatedTag(s, pptx);

  const charts = slide.charts || [];
  const two = charts.length === 2;
  const chartOpts = (extra) => Object.assign({
    showLegend: true, legendPos: "b", legendFontFace: FONT_B, legendFontSize: 9,
    lineSize: 1.75, lineSmooth: true, lineDataSymbol: "none",
    catAxisLabelFontFace: FONT_B, catAxisLabelFontSize: 7, catAxisLabelRotate: 45,
    valAxisLabelFontFace: FONT_B, valAxisLabelFontSize: 8, valGridLine: { style: "none" },
    showTitle: false,
  }, extra);

  charts.forEach((ch, idx) => {
    const data = ch.series.map(se => ({ name: se.name, labels: sparseLabels(ch.labels), values: se.values }));
    const colors = ch.series.map((se, i) => se.color || SERIES[i % SERIES.length]);
    const geo = two
      ? { x: idx === 0 ? 0.5 : 6.85, y: 1.3, w: 6.0, h: slide.table ? 3.4 : 5.2 }
      : { x: 0.5, y: 1.3, w: 12.3, h: slide.table ? 3.6 : 5.4 };
    if (ch.subtitle) s.addText(ch.subtitle, { x: geo.x, y: 1.1, w: geo.w, h: 0.3, color: C.gray, fontFace: FONT_B, fontSize: 11, bold: true });
    s.addChart(pptx.ChartType.line, data, chartOpts(Object.assign(geo, { chartColors: colors })));
  });

  if (slide.table) {
    const t = slide.table;
    const hdr = t.columns.map(c => ({ text: c, options: { bold: true, fill: { color: C.navy }, color: C.white } }));
    const body = t.rows.map(r => r.map(cell => ({ text: String(cell) })));
    s.addTable([hdr, ...body], {
      x: 0.5, y: 5.15, w: 12.3, h: 1.55, fontFace: FONT_B, fontSize: 9,
      border: { type: "solid", pt: 0.5, color: C.rule }, align: "center", valign: "middle", fill: { color: C.white },
    });
  }
  footer(s, pptx, false);
}

const BUILDERS = { divider: buildDivider, title: buildTitle, chart: buildChart };

// ----------------------------------------------------------------------------
// entry point
// ----------------------------------------------------------------------------
function generate(config, outPath) {
  const pptx = new pptxgen();
  pptx.defineLayout({ name: "W", width: W, height: H });
  pptx.layout = "W";
  (config.slides || []).forEach(slide => {
    const fn = BUILDERS[slide.type];
    if (!fn) throw new Error("Unknown slide type: " + slide.type);
    fn(pptx, slide);
  });
  return pptx.writeFile({ fileName: outPath }).then(() => outPath);
}

module.exports = { generate, tokens: { C, SERIES, GRAD } };

// CLI: node apex_deck.js config.json output.pptx
if (require.main === module) {
  const [, , cfgPath, outPath] = process.argv;
  if (!cfgPath || !outPath) { console.error("usage: node apex_deck.js <config.json> <output.pptx>"); process.exit(1); }
  const config = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
  generate(config, outPath).then(p => console.log("wrote " + p)).catch(e => { console.error(e); process.exit(1); });
}
