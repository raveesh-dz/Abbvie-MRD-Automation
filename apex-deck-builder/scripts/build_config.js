// build_config.js — turn a weekly time-series CSV into an APEX deck config.
//
// This is the bridge between the pipeline's table output and apex_deck.js.
// It groups numeric columns into charts and computes a latest-vs-prior summary.
//
// Usage:
//   node build_config.js <data.csv> <spec.json> <config.out.json>
//
// spec.json (all optional — sensible defaults applied):
// {
//   "title": "Tremfya SQ Performance",
//   "dateColumn": "Date",
//   "priorWeeks": 4,                       // lookback for the change column
//   "charts": [                            // if omitted, auto-grouped (see below)
//     { "title": "...", "subtitle": "...", "columns": ["UC 100mg SQ TRx", ...] }
//   ]
// }
//
// AUTO-GROUPING: when "charts" is omitted, columns sharing a trailing token
// pattern are grouped (e.g. all "...100mg SQ TRx" columns become one chart).
// This lets the pipeline pass nothing but a CSV and still get a sensible deck.

const fs = require("fs");

function parseCSV(path) {
  const lines = fs.readFileSync(path, "utf8").trim().split(/\r?\n/);
  const header = lines[0].split(",").map(s => s.trim());
  const rows = lines.slice(1).map(l => l.split(",").map(s => s.trim()));
  return { header, rows };
}

function num(v) { const n = parseFloat(v); return isNaN(n) ? 0 : n; }

// group columns by the part of the name after the indication token
function autoGroup(measureCols) {
  const groups = {};
  measureCols.forEach(col => {
    // strip a leading indication token (UC / CD / IBD) to find the group key
    const key = col.replace(/^(UC|CD|IBD)\s+/i, "").trim() || col;
    (groups[key] = groups[key] || []).push(col);
  });
  return Object.entries(groups).map(([key, cols]) => ({
    title: key,
    columns: cols,
  }));
}

function shortLabel(col) {
  const m = col.match(/^(UC|CD|IBD)/i);
  if (m) return m[1].toUpperCase() === "IBD" ? "IBD (total)" : m[1].toUpperCase();
  return col;
}

function build(dataPath, spec) {
  const { header, rows } = parseCSV(dataPath);
  const dateCol = spec.dateColumn || header[0];
  const di = header.indexOf(dateCol);
  const measureCols = header.filter((h, i) => i !== di);
  const idx = Object.fromEntries(header.map((h, i) => [h, i]));

  const labels = rows.map(r => {
    const d = r[di] || "";
    return d.length >= 10 ? d.slice(5) : d; // MM/DD from YYYY/MM/DD
  });
  const colValues = col => rows.map(r => num(r[idx[col]]));

  const priorN = spec.priorWeeks || 4;
  const chartSpecs = spec.charts && spec.charts.length ? spec.charts : autoGroup(measureCols);

  const slides = [];
  slides.push({ type: "divider", title: spec.title || "Performance", subtitle: spec.subtitle || "" });

  chartSpecs.forEach(cs => {
    const series = cs.columns.map(col => ({ name: cs.labelMap ? (cs.labelMap[col] || shortLabel(col)) : shortLabel(col), values: colValues(col) }));
    // summary table: latest week, prior week, % change
    const tableRows = cs.columns.map(col => {
      const v = colValues(col);
      const last = v[v.length - 1];
      const prev = v[v.length - 1 - priorN] != null ? v[v.length - 1 - priorN] : v[0];
      const chg = prev ? ((last - prev) / prev) * 100 : 0;
      return [shortLabel(col), last.toFixed(1), prev.toFixed(1), (chg >= 0 ? "+" : "") + chg.toFixed(1) + "%"];
    });
    slides.push({
      type: "chart",
      title: cs.title.match(/trend|weekly/i) ? cs.title : `Tremfya ${cs.title} \u2014 weekly trend by indication`,
      updated: spec.updated !== false,
      charts: [{ labels, subtitle: cs.subtitle || "", series }],
      table: { columns: ["Indication", "Latest Wk", `${priorN} Wks Prior`, "Change"], rows: tableRows },
    });
  });

  return { slides };
}

module.exports = { build };

if (require.main === module) {
  const [, , dataPath, specPath, outPath] = process.argv;
  if (!dataPath || !outPath) { console.error("usage: node build_config.js <data.csv> [spec.json] <config.out.json>"); process.exit(1); }
  const spec = specPath && fs.existsSync(specPath) ? JSON.parse(fs.readFileSync(specPath, "utf8")) : {};
  const cfg = build(dataPath, spec);
  fs.writeFileSync(outPath, JSON.stringify(cfg, null, 2));
  console.log("wrote " + outPath + " (" + cfg.slides.length + " slides)");
}
