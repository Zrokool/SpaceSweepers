// Figure data from PSI's Analyzed Data files, drawn as the investigators published it. Nothing here is counted, modelled or pooled.
// Measured series are dots, computed series are dashed lines, series the file does not label are solid lines, and tests from another
// investigation (CFI) are squares. Shape and line style carry the meaning, so colour is never the only cue.
import { el, svg, api, showTip, hideTip, fmt } from "../ui.js";

const W = 680, H = 330, M = { l: 60, r: 18, t: 14, b: 46 };
const KIND_TEXT = { experiment: "measured", simulation: "computed", published: "as published", "experiment-cfi": "measured, CFI (PSI-39)" };
const MARK_MAX = 40;                                  // above this many points a series is drawn without a marker on every point

function niceScale(lo, hi, wantZero) {
  if (wantZero && lo > 0 && lo <= 0.35 * hi) lo = 0;
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.05;
  lo = wantZero && lo === 0 ? 0 : lo - pad; hi += pad;
  const raw = (hi - lo) / 5, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const start = Math.floor(lo / step) * step, ticks = [];
  for (let v = start; v <= hi + step * 0.999; v += step) { ticks.push(Math.round(v / step * 1e6) / 1e6 * step); if (ticks.length > 12) break; }
  return { min: start, max: ticks[ticks.length - 1], ticks };
}
const tickText = (v) => (Math.abs(v) >= 1000 ? fmt(v, 0) : Math.abs(v) >= 10 ? fmt(v, 1) : Math.abs(v) >= 1 ? fmt(v, 2) : String(Math.round(v * 1e4) / 1e4));

function groupClass(c) {
  const groups = [...new Set(c.series.map((s) => s.group))];
  return (s) => `fig-g${groups.indexOf(s.group) % 4}`;
}

function sample(kind, cls, style) {   // the legend's miniature of a series, drawn with the same shapes as the chart
  const g = svg("svg", { class: "fig-key", viewBox: "0 0 26 14", width: 26, height: 14 });
  if (kind === "simulation") g.append(svg("line", { class: `fig-sim ${cls}`, x1: 0, x2: 26, y1: 7, y2: 7 }));
  else if (kind === "published" && style !== "points") g.append(svg("line", { class: `fig-line ${cls}`, x1: 0, x2: 26, y1: 7, y2: 7 }));
  else if (kind === "experiment-cfi") g.append(svg("rect", { class: `fig-sq ${cls}`, x: 8.5, y: 3.5, width: 9, height: 9 }));
  else g.append(svg("circle", { class: `fig-dot ${cls}`, cx: 13, cy: 7, r: 4.5 }));
  return g;
}

function draw(c, series) {
  const pts = series.flatMap((s) => s.points);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const X = niceScale(Math.min(...xs), Math.max(...xs), true), Y = niceScale(Math.min(...ys), Math.max(...ys), true);
  const x = (v) => M.l + ((v - X.min) / (X.max - X.min)) * (W - M.l - M.r), y = (v) => H - M.b - ((v - Y.min) / (Y.max - Y.min)) * (H - M.t - M.b);
  const cls = groupClass(c);
  const root = svg("svg", { class: "fig-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${c.title}` });
  for (const t of Y.ticks) root.append(svg("line", { class: "gridline", x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }), svg("text", { x: M.l - 8, y: y(t) + 4, "text-anchor": "end", text: tickText(t) }));
  for (const t of X.ticks) root.append(svg("text", { x: x(t), y: H - M.b + 18, "text-anchor": "middle", text: tickText(t) }));
  root.append(svg("text", { x: (W + M.l - M.r) / 2, y: H - 6, "text-anchor": "middle", text: c.x.label }),
    svg("text", { x: 14, y: H / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${H / 2})`, text: c.y.label }));
  const tip = (s, p) => (e) => showTip(e, s.name, [`${c.x.label}: ${p[0]}`, `${c.y.label}: ${p[1]}`, p[2] || null, `${KIND_TEXT[s.kind] || s.kind} · ${c.figure}`]);
  const upper = series.find((s) => s.bound === "upper"), lower = series.find((s) => s.bound === "lower");
  if (upper && lower) {
    for (const hi of upper.points) {
      const lo = lower.points.find((p) => p[0] === hi[0]);
      if (lo) root.append(svg("line", { class: `fig-bar ${cls(upper)}`, x1: x(hi[0]), x2: x(hi[0]), y1: y(hi[1]), y2: y(lo[1]) }));
    }
  }
  for (const s of series.filter((s) => !s.bound)) {
    const poly = [...s.points].sort((a, b) => a[0] - b[0]).map((p) => `${x(p[0])},${y(p[1])}`).join(" ");
    const dense = s.points.length > MARK_MAX;
    const line = s.kind === "simulation" || (s.kind === "published" && s.style !== "points");
    if (line) root.append(svg("polyline", { class: `${s.kind === "simulation" ? "fig-sim" : "fig-line"} ${cls(s)}`, points: poly }));
    if (s.kind === "simulation" && !dense) for (const p of s.points) {
      const m = svg("rect", { class: `fig-diamond ${cls(s)}`, x: x(p[0]) - 4.5, y: y(p[1]) - 4.5, width: 9, height: 9, transform: `rotate(45 ${x(p[0])} ${y(p[1])})`, tabindex: 0 });
      m.addEventListener("mousemove", tip(s, p)); m.addEventListener("mouseleave", hideTip); root.append(m);
    } else if (s.kind === "published" && s.style !== "points" && dense) {
      continue;
    } else if (s.kind !== "simulation") for (const p of s.points) {
      const common = { class: `${s.kind === "experiment-cfi" ? "fig-sq" : "fig-dot"} ${cls(s)}`, tabindex: dense ? null : 0 };
      const m = s.kind === "experiment-cfi" ? svg("rect", { ...common, x: x(p[0]) - 4, y: y(p[1]) - 4, width: 8, height: 8 }) : svg("circle", { ...common, cx: x(p[0]), cy: y(p[1]), r: dense && s.style !== "points" ? 2.2 : 4.5 });
      m.addEventListener("mousemove", tip(s, p)); m.addEventListener("mouseleave", hideTip); root.append(m);
    }
  }
  return root;
}

export function figure(c) {
  let overlayOn = false;
  const holder = el("div");
  const cls = groupClass(c);
  const render = () => {
    const series = [...c.series, ...(overlayOn && c.overlay ? c.overlay.series.filter((s) => s.points.length) : [])];
    const used = overlayOn && c.overlay ? [...c.series, ...c.overlay.series] : c.series;
    holder.replaceChildren(
      el("div", { class: "legend" }, ...used.filter((s) => !s.bound).map((s) => el("span", { class: "key" }, sample(s.kind, groupClass({ series: used })(s), s.style), `${s.name}`)),
        used.some((s) => s.bound) && el("span", { class: "key", text: "vertical bar = the file's upper and lower values" })),
      el("div", { class: "chart" }, draw({ ...c, series: used }, series)));
  };
  render();
  return el("figure", { class: "fig" },
    el("p", { class: "fig-title", text: c.title }),
    Object.keys(c.conditions || {}).length > 0 && el("p", { class: "tiny", text: Object.entries(c.conditions).map(([k, v]) => `${k}: ${v}`).join(" · ") }),
    c.overlay && el("div", { class: "legend" }, el("button", { class: "chip", type: "button", "aria-pressed": "false",
      text: "Show CFI (PSI-39) measured tests for the same conditions",
      onclick: (e) => { overlayOn = !overlayOn; e.currentTarget.setAttribute("aria-pressed", String(overlayOn)); render(); } }),
      el("span", { class: "tiny", text: `${c.overlay.tests} tests: ${c.overlay.conditions}. Different investigation and apparatus; shown only on request, never combined.` })),
    holder,
    (c.y.unit_note || c.note) && el("p", { class: "tiny", text: [c.y.unit_note, c.note].filter(Boolean).join(" ") }),
    el("p", { class: "tiny" }, `File: ${c.file}. `, c.reference && el("a", { href: c.reference, target: "_blank", rel: "noopener", text: "Paper (DOI)" })));
}

export function figureSection(psiId) {
  const body = el("div", { class: "fig-body" }, el("p", { class: "muted", text: "Loading the investigators' figure data…" }));
  api(`/api/figure-data/${encodeURIComponent(psiId)}`).then((d) => {
    if (!d.charts.length) { body.replaceChildren(el("p", { class: "muted", text: "The figure data files are not in this snapshot." })); return; }
    const byFile = new Map();
    for (const c of d.charts) { if (!byFile.has(c.file)) byFile.set(c.file, []); byFile.get(c.file).push(c); }
    body.replaceChildren(...[
      d.intro && el("p", { class: "note", text: d.intro }),
      ...[...byFile.entries()].map(([file, list], i) => el("details", { class: "fig-group", open: i === 0 },
        el("summary", {}, el("strong", { text: list[0].figure }), ` · ${list.length} chart${list.length === 1 ? "" : "s"} · ${file.replace(/^PSI-\d+_Analyzed Data_/, "").replace(/\.(csv|xlsx)$/, "")}`),
        ...list.map(figure))),
      d.dropped?.length > 0 && el("details", { class: "fig-group" }, el("summary", { text: `Not drawn (${d.dropped.length})` }),
        el("ul", { class: "facts" }, ...d.dropped.map((x) => el("li", { text: x })))),
      el("p", { class: "tiny" }, d.doi && ["Dataset ", el("a", { href: `https://doi.org/${d.doi}`, target: "_blank", rel: "noopener", text: `DOI ${d.doi}` }), ` · licence ${d.license || "not recorded"} · ${d.files.length} file${d.files.length === 1 ? "" : "s"} stored unchanged, SHA-256 in the manifest.`])].filter(Boolean));
  }).catch((e) => body.replaceChildren(el("p", { class: "note", text: e.message })));
  return el("section", {}, el("p", { class: "eyebrow", text: "Figure data (as published)" }), body);
}
