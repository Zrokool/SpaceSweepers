// Flame Sweeper: sweep the oxygen x pressure field. Tested cells are revealed (how many tests, how many flames kept burning);
// untested cells stay hidden. A model estimate appears in an untested cell only where the model beat guessing in cross-validation.
import { el, svg, api, showTip, hideTip, fmt, hab, isStatic, README_RUN_URL } from "../ui.js";
import { habitatQuery, openDetail } from "../app.js";

const W = 700, M = { l: 62, r: 16, t: 12, b: 50 };
const OUTCOME_LABEL = { extinguished: "Extinction", completed: "Completion", disrupted: "Disruption",
  ignited: "Hot ignition: yes", no_ignition: "Hot ignition: no", flash: "Flash only" };
const DOC_LABEL = { burned: "Notes: burned", no_ignition: "Notes: did not ignite" };   // outcomes read from lab notes, not a table column
const outcomeText = (k, data) => (data.layer === "document" ? DOC_LABEL[k] : OUTCOME_LABEL[k]) || k;
const BUCKET_LABEL = ["0–20% kept burning", "20–40%", "40–60%", "60–80%", "80–100% kept burning"];
const pct = (x) => `${fmt(x * 100, 0)}%`;
const bucket = (share) => Math.min(4, Math.floor(share * 5));

let sel = { family: "droplet_end_state", fuel: "", diluent: "", cell: null };
let layers = { simulations: false };      // optional layers: never part of any count or statistic
let explained = {};        // Micro-Flame's answer for the current selection: { status: "idle" | "running" | "done" | "error", data }

function explainKey() { return `${sel.family}|${sel.fuel}|${sel.diluent}`; }

async function runExplain(habitatKey) {
  const key = explainKey();
  explained[key] = { status: "running" };
  rerender();
  try {
    const data = await api("/api/sweeper/explain", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ family: sel.family, fuel: sel.fuel || null, diluent: sel.diluent || null, habitat: habitatKey }) });
    explained[key] = { status: "done", data };
  } catch (e) {
    explained[key] = { status: "error", error: e.message };
  }
  rerender();
}

function explainBlock(habitatKey) {
  // The static demo has no model. The patterns above are computed by code and are the same there.
  if (isStatic) return el("p", { class: "muted" }, "The SI explanation of these patterns needs the local SI model, so it isn't on this demo. To install and run the SI, follow the ",
    el("a", { href: README_RUN_URL, target: "_blank", rel: "noopener noreferrer", text: "README (Run it)" }), ", then use \"Explain these patterns (SI)\" in the full app.");
  const s = explained[explainKey()] || { status: "idle" };
  const button = el("button", { class: "btn", type: "button", disabled: s.status === "running", onclick: () => runExplain(habitatKey),
    text: s.status === "running" ? "Micro-Flame is reading PSI passages…" : "Explain these patterns (SI)" });
  const kids = [button];
  if (s.status === "running") kids.push(el("p", { class: "muted", text: "Granite runs on this computer's CPU, so this takes up to a minute." }));
  if (s.status === "error") kids.push(el("div", { class: "note", text: s.error }));
  if (s.status === "done") {
    const d = s.data;
    kids.push(...d.notes.map((n) => el("div", { class: "note", text: n })));
    kids.push(...d.answer.map((a) => el("p", { class: "sentence" }, a.text, " ", ...a.cites.map((n) => el("span", { class: "cite-n", text: `[${n}]` })))));
    if (d.sources.length) kids.push(el("details", { class: "gaps", open: true }, el("summary", { text: "Sources for this explanation" }),
      el("ol", { class: "facts" }, ...d.sources.map((x) => el("li", {}, el("strong", { text: x.computed ? "Computed by code. " : `${x.label}. ` }), x.text.length > 360 ? `${x.text.slice(0, 360)}…` : x.text)))));
    if (d.removed.length) kids.push(el("details", { class: "removed" }, el("summary", { text: `Removed by Nimbus (${d.removed.length}): not supported by their sources` }),
      el("ul", { class: "facts" }, ...d.removed.map((x) => el("li", {}, el("span", { class: "strike", text: x.text }), el("span", { class: "muted", text: ` — ${x.rules[0]}: ${x.reason}` }))))));
    kids.push(el("p", { class: "muted", text: "Written by the local SI model from the patterns and PSI passages above; Nimbus removes any sentence its sources don't back, including any physical mechanism no PSI passage names." }));
  }
  return el("div", { class: "sw-explain" }, ...kids);
}

function legend(data, habitatOn) {
  const key = (cls, text) => el("span", { class: "key" }, svg("svg", { class: "sw-key", viewBox: "0 0 14 14", width: 14, height: 14 }, svg("rect", { class: cls, x: 0, y: 0, width: 14, height: 14, rx: 2 })), text);
  return el("div", { class: "legend" },
    ...BUCKET_LABEL.map((t, n) => key(`sw-b${n}`, t)),
    key("sw-fog", "not tested"),
    data.layer === "document" && el("span", { class: "key" }, svg("svg", { class: "sw-key", viewBox: "0 0 14 14", width: 14, height: 14 }, svg("rect", { class: "sw-b3 sw-doc", x: 1, y: 1, width: 12, height: 12 })), "outlined = outcome read from the lab's notes, observed counts only (no model)"),
    habitatOn && el("span", { class: "key" }, svg("svg", { class: "sw-key", viewBox: "0 0 14 14", width: 14, height: 14 }, svg("rect", { class: "sw-box-key", x: 1, y: 1, width: 12, height: 12 })), hab(`dashed box = ${data.habitat.label || "habitat"} atmosphere`)),
    el("span", { class: "key", text: "number = tests in the cell" }),
    el("span", { class: "key", text: "⚑ = flame kept burning in every test (3 or more)" }),
    data.skill.passes && el("span", { class: "key", text: "~ hatched = model estimate, not a test" }),
    layers.simulations && data.simulations.length > 0 && el("span", { class: "key" }, svg("svg", { class: "sw-key", viewBox: "0 0 14 14", width: 14, height: 14 },
      svg("rect", { class: "sw-sim-key", x: 4, y: 1, width: 6, height: 12 })), "dashed bar = where PSI-117 simulated this fuel (list only; no simulated result is shown)"));
}

function grid(data, habitatOn) {
  const { o2, p_atm: pa } = data.axes;
  const right = layers.simulations && data.simulations.length ? 130 : M.r;
  const cell = Math.min(46, Math.floor((W - M.l - right) / o2.n));
  const gw = cell * o2.n, gh = cell * pa.n, H = M.t + gh + M.b;
  const x0 = M.l, y0 = M.t;
  const px = (v) => x0 + ((v - o2.min) / (o2.max - o2.min)) * gw;
  const py = (v) => y0 + gh - ((v - pa.min) / (pa.max - pa.min)) * gh;
  const root = svg("svg", { class: "sweeper-grid", viewBox: `0 0 ${W} ${H}`, role: "group", "aria-label": "Oxygen by pressure field of tests" },
    svg("defs", {}, svg("pattern", { id: "sw-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
      svg("rect", { width: 6, height: 6, class: "sw-est-bg" }), svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "sw-est-line" }))));
  for (const c of data.cells) {
    const x = x0 + c.i * cell, y = y0 + gh - (c.j + 1) * cell;
    const g = svg("g", { class: `sw-cell ${c.state}${sel.cell && sel.cell.i === c.i && sel.cell.j === c.j ? " picked" : ""}`, tabindex: 0, role: "button",
      "aria-label": cellLabel(c, data) });
    const fill = c.state === "revealed" ? (c.share == null ? "sw-b2" : `sw-b${bucket(c.share)}`) : c.estimate ? "sw-est" : "sw-fog";
    g.append(svg("rect", { class: data.layer === "document" && c.state === "revealed" ? `${fill} sw-doc` : fill, x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 3 }));
    if (c.state === "revealed") {
      g.append(svg("text", { class: "sw-n", x: x + cell / 2, y: y + cell / 2 + 5, "text-anchor": "middle", text: c.n }));
      if (c.share != null) g.append(svg("text", { class: "sw-s", x: x + cell / 2, y: y + cell - 6, "text-anchor": "middle", text: pct(c.share) }));
      if (c.flag) g.append(svg("text", { class: "sw-flag", x: x + 5, y: y + 14, text: "⚑" }));
    } else if (c.estimate) {
      g.append(svg("text", { class: "sw-e", x: x + cell / 2, y: y + cell / 2 + 4, "text-anchor": "middle", text: `~${pct(c.estimate.share)}` }));
    }
    g.addEventListener("mousemove", (e) => showTip(e, tipTitle(c), tipLines(c, data)));
    g.addEventListener("mouseleave", hideTip);
    g.addEventListener("click", () => pick(c));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(c); } });
    root.append(g);
  }
  for (let n = 0; n <= o2.n; n += Math.max(1, Math.round(o2.n / 8))) {
    root.append(svg("text", { class: "ax", x: x0 + n * cell, y: y0 + gh + 18, "text-anchor": "middle", text: (o2.min + n * o2.step).toFixed(2) }));
  }
  for (let n = 0; n <= pa.n; n += Math.max(1, Math.round(pa.n / 8))) {
    root.append(svg("text", { class: "ax", x: x0 - 8, y: y0 + gh - n * cell + 4, "text-anchor": "end", text: (pa.min + n * pa.step).toFixed(2) }));
  }
  root.append(svg("text", { class: "ax", x: x0 + gw / 2, y: H - 8, "text-anchor": "middle", text: "Oxygen in the chamber (mole fraction)" }),
    svg("text", { class: "ax", x: 14, y: y0 + gh / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${y0 + gh / 2})`, text: "Pressure (atm)" }));
  if (layers.simulations) {
    const clamp = (v) => Math.max(pa.min, Math.min(pa.max, v));
    data.simulations.forEach((s, i) => {
      const x = x0 + gw + 16 + i * 14;
      const lines = [`${s.fuel}${s.droplet_mm ? ` · droplet ${s.droplet_mm} mm` : ""}`, s.figure ? `Published as ${s.figure}${s.reference ? ` (${s.reference})` : ""}` : null,
        "A simulation by the PSI-117 investigators. The figure data is stored in this snapshot (see the PSI-117 detail panel)."];
      const marks = s.kind === "range"
        ? [svg("rect", { class: "sw-sim", x, y: py(clamp(s.p_atm[1])), width: 8, height: Math.max(3, py(clamp(s.p_atm[0])) - py(clamp(s.p_atm[1]))) })]
        : s.p_atm.map((v) => svg("rect", { class: "sw-sim", x, y: py(clamp(v)) - 4, width: 8, height: 8, transform: `rotate(45 ${x + 4} ${py(clamp(v))})` }));
      for (const m of marks) {
        m.addEventListener("mousemove", (e) => showTip(e, `${s.label} · ${s.p_atm.join(s.kind === "range" ? "–" : " and ")} atm (simulated)`, lines));
        m.addEventListener("mouseleave", hideTip);
        root.append(m);
      }
    });
    root.append(svg("text", { class: "ax", x: x0 + gw + 16, y: y0 + 8, text: "PSI-117 simulations" }));
  }
  const h = data.habitat;
  if (habitatOn && h.o2 && h.p_atm[1] >= pa.min && h.o2[1] >= o2.min && h.o2[0] <= o2.max && h.p_atm[0] <= pa.max) {
    const hx0 = Math.max(x0, px(h.o2[0])), hx1 = Math.min(x0 + gw, px(h.o2[1])), hy1 = Math.max(y0, py(h.p_atm[1])), hy0 = Math.min(y0 + gh, py(h.p_atm[0]));
    root.append(svg("rect", { class: "sw-box", x: hx0, y: hy1, width: Math.max(0, hx1 - hx0), height: Math.max(0, hy0 - hy1), "aria-hidden": "true" }));
  }
  return root;
}

function tipTitle(c) {
  return c.state === "revealed" ? `${c.n} test${c.n === 1 ? "" : "s"} · oxygen ${c.o2[0].toFixed(2)}–${c.o2[1].toFixed(2)}, ${c.p_atm[0].toFixed(2)}–${c.p_atm[1].toFixed(2)} atm`
    : `Not tested · oxygen ${c.o2[0].toFixed(2)}–${c.o2[1].toFixed(2)}, ${c.p_atm[0].toFixed(2)}–${c.p_atm[1].toFixed(2)} atm`;
}
function tipLines(c, data) {
  if (c.state === "revealed") {
    return [Object.entries(c.counts).map(([k, n]) => `${outcomeText(k, data)} ${n}`).join(" · "),
      c.share != null ? `${pct(c.share)} "${data.sustained_label}" (95% range ${pct(c.share_ci[0])}–${pct(c.share_ci[1])}, ${c.modelled} tests)` : null,
      c.flag ? "Flag: the flame kept going in every one of these tests" : null,
      data.layer === "document" ? "Outcome read from the lab's test notes (document text), not a table value" : null, "Click to list the tests"];
  }
  return c.estimate ? [`Model estimate, not a test: ${pct(c.estimate.share)} "${data.sustained_label}" (90% range ${pct(c.estimate.low)}–${pct(c.estimate.high)})`,
    `Shown because the model beat guessing in cross-validation and this cell lies beside tested cells.`] : ["No test here.", "Nothing is estimated: the model either didn't beat guessing or this cell is outside the tested range."];
}
function cellLabel(c, data) {
  return `${tipTitle(c)}. ${tipLines(c, data).filter(Boolean).join(". ")}`;
}

let rerender = () => {};
function pick(c) { sel.cell = sel.cell && sel.cell.i === c.i && sel.cell.j === c.j ? null : c; rerender(); }

function detail(data) {
  const c = sel.cell && data.cells.find((x) => x.i === sel.cell.i && x.j === sel.cell.j);
  if (!c) return el("p", { class: "muted", text: "Click a cell to list its tests with their file and row." });
  if (c.state !== "revealed") return el("div", { class: "card" }, el("h3", { text: tipTitle(c) }), ...tipLines(c, data).filter(Boolean).map((t) => el("p", { class: "muted", text: t })));
  return el("div", { class: "card" }, el("h3", { text: tipTitle(c) }),
    el("p", { class: "muted", text: tipLines(c, data).filter(Boolean).join(" · ") }),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["Investigation", "Test", "Oxygen", "Pressure (atm)", "Gas / fuel", "Outcome", "Source"].map((t) => el("th", { text: t })))),
      el("tbody", {}, ...c.tests.map((t) => el("tr", { class: "clickable", onclick: () => openDetail(t.psi) },
        el("td", { text: t.psi }), el("td", { text: t.test_id }), el("td", { text: t.o2.toFixed(3) }), el("td", { text: t.p_atm.toFixed(2) }),
        el("td", { text: `${t.fuel}${t.diluent && t.diluent !== "nitrogen only" ? ` + ${t.diluent}` : ""}` }),
        el("td", { text: outcomeText(t.outcome, data) }), el("td", { class: "mono", text: `${t.file.replace(/^PSI-\d+_/, "")}, row ${t.row}${t.source === "document" && t.quote ? ` · lab note: "${t.quote}"` : ""}` })))))),
    c.n > c.tests.length && el("p", { class: "muted", text: `Showing the first ${c.tests.length} of ${c.n}.` }));
}

function skillCard(data) {
  const s = data.skill;
  const bar = (label, v) => {
    const fill = el("span", { class: "sw-fill" });
    fill.style.width = `${fmt(v * 100, 0)}%`;                 // set through the DOM: the page's CSP forbids inline style attributes
    return el("div", { class: "sw-bar" }, el("span", { text: label }), el("span", { class: "sw-track" }, fill), el("span", { text: pct(v) }));
  };
  return el("div", { class: "card" }, el("h3", { text: "Skill check" }),
    s.accuracy != null && el("div", {}, bar("Model, cross-validated", s.accuracy), bar("Always guess the commoner outcome", s.baseline),
      el("p", { class: "muted", text: `AUC ${s.auc.toFixed(2)} · ${s.folds}-fold cross-validation on ${s.tests} tests · features: ${s.features.join(", ")}` })),
    el("p", { text: s.reason }), s.gate && el("p", { class: "muted", text: s.gate }));
}

export async function render(root, state) {
  const want = state.params.get("family");
  if (["droplet_end_state", "gas_ignition", "droplet_reignition", "solid_burn"].includes(want)) sel = { family: want, fuel: state.params.get("fuel") || "", diluent: state.params.get("diluent") || "", cell: null };
  const habitatOn = state.habitatView;
  sel.cell = null;
  const holder = el("div");
  rerender = () => draw();
  async function draw() {
    const q = new URLSearchParams(habitatQuery());
    q.set("family", sel.family);
    if (!habitatOn) q.set("habitat_view", "off");
    if (sel.fuel) q.set("fuel", sel.fuel);
    if (sel.diluent) q.set("diluent", sel.diluent);
    const data = await api(`/api/sweeper?${q}`);
    const dropped = Object.entries(data.dropped);
    const filters = sel.family === "droplet_end_state" && el("div", { class: "sw-filters" },
      el("label", { class: "field" }, el("span", { class: "eyebrow", text: "Fuel" }),
        el("select", { "aria-label": "Fuel", onchange: (e) => { sel.fuel = e.target.value; sel.cell = null; draw(); } },
          ...[["", "All fuels"], ["heptane", "Heptane"], ["methanol", "Methanol"]].map(([v, t]) => el("option", { value: v, text: t, selected: v === sel.fuel })))),
      el("label", { class: "field" }, el("span", { class: "eyebrow", text: "Gas mixed with oxygen" }),
        el("select", { "aria-label": "Gas mixed with oxygen", onchange: (e) => { sel.diluent = e.target.value; sel.cell = null; draw(); } },
          ...[["", "All"], ["nitrogen only", "Nitrogen only"], ["helium", "With helium"], ["carbon dioxide", "With carbon dioxide"]].map(([v, t]) => el("option", { value: v, text: t, selected: v === sel.diluent })))));
    holder.replaceChildren(...[
      el("div", { class: "segmented", role: "radiogroup", "aria-label": "Experiment family" },
        ...data.families.map((f) => el("button", { type: "button", role: "radio", "aria-checked": String(f.key === sel.family), text: `${f.short} (${f.tests})`,
          onclick: () => { sel = { family: f.key, fuel: "", diluent: "", cell: null }; draw(); } }))),
      el("p", { class: "muted", text: data.definition }), filters || null,
      data.simulations.length > 0 && el("div", { class: "legend" }, el("button", { class: "chip", type: "button", "aria-pressed": String(layers.simulations),
        text: layers.simulations ? "Hide PSI-117 simulation coverage" : "Show PSI-117 simulation coverage (list only)", onclick: () => { layers.simulations = !layers.simulations; draw(); } })),
      data.axes ? el("div", { class: "split" },
        el("div", {}, legend(data, habitatOn), el("div", { class: "chart sw-chart" }, grid(data, habitatOn)), detail(data)),
        el("div", { class: "grid" },
          el("div", { class: "card" }, el("h3", { text: "What the data says" }),
            el("ul", { class: "facts" }, ...data.patterns.map((p) => el("li", p.kind === "habitat" ? {} : { text: p.text }, p.kind === "habitat" ? hab(p.text) : null))),
            el("p", { class: "muted", text: "Every sentence is computed by code from the tests shown. These are patterns in what NASA tested; they do not say what will happen in a real fire." }),
            explainBlock(habitatOn ? state.habitat : null)),
          skillCard(data),
          el("div", { class: "card" }, el("h3", { text: "What to test next" }),
            el("p", { class: "muted", text: `Untested cells beside tested ones, where neighbours disagree${habitatOn ? " or that lie inside the habitat's atmosphere" : ""}. A suggestion for experiment designers, not safety guidance.` }),
            data.next.length ? el("ul", { class: "plain" }, ...data.next.map((n) => el("li", {}, el("button", { class: "btn-ghost", type: "button",
              text: `Oxygen ${n.o2[0].toFixed(2)}–${n.o2[1].toFixed(2)}, ${n.p_atm[0].toFixed(2)}–${n.p_atm[1].toFixed(2)} atm`,
              onclick: () => { sel.cell = data.cells.find((c) => c.i === n.i && c.j === n.j); draw(); } }), ` ${n.why}`))) : el("p", { text: "None found." })),
          el("div", { class: "card" }, el("h3", { text: "Data used" }),
            el("p", { text: `${fmt(data.tests)} tests from ${data.investigations.join(", ") || "–"}.` }),
            dropped.length > 0 && el("p", { class: "muted", text: `Left out: ${dropped.map(([k, n]) => `${n} (${k})`).join("; ")}.` }),
            el("p", { class: "muted", text: "Families are never pooled: different experiments have different physics." }))))
        : el("div", { class: "note", text: data.skill.reason })].filter(Boolean));
  }
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "Flame Sweeper" }), el("h1", { text: "Sweep the field: where did flames keep burning, and where has nothing been tested?" }),
      el("p", { class: "lede", text: "Each square is a range of oxygen and pressure. A revealed square shows how many tests NASA ran there and how many flames kept burning. Hidden squares have no test. A summary of two experiment families from PSI, not a safety rating." })),
    holder);
  await draw();
}
