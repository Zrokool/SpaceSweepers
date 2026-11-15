// Envelope: where NASA has tested, in oxygen and pressure. With the Habitat view on, the habitat's atmosphere is drawn as a box.
import { el, svg, api, showTip, hideTip, fmt, hab, habName, ROLE_LABEL } from "../ui.js";
import { habitatQuery, openDetail } from "../app.js";

const FUEL_COLOR = { gas: "#3987e5", liquid: "#d95926", solid: "#199e70" };
const W = 760, H = 440, M = { l: 56, r: 20, t: 16, b: 46 };

function chart(data, habitatOn) {
  const pts = data.points;
  const maxP = Math.max(20, ...pts.map((p) => p.pressure_psi), ...(habitatOn ? data.habitats.map((h) => h.pressure_psi[1]) : [])) * 1.06;
  const x = (o2) => M.l + o2 * (W - M.l - M.r);
  const y = (p) => H - M.b - (p / maxP) * (H - M.t - M.b);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": habitatOn
    ? "Tests plotted by oxygen fraction and pressure, with the habitat atmosphere as a shaded box"
    : "Tests plotted by oxygen fraction and pressure" });
  for (let i = 0; i <= 10; i += 2) {
    root.append(svg("line", { class: "gridline", x1: x(i / 10), x2: x(i / 10), y1: M.t, y2: H - M.b }),
      svg("text", { x: x(i / 10), y: H - M.b + 18, "text-anchor": "middle", text: `${i * 10}%` }));
  }
  const step = maxP > 60 ? 20 : 10;
  for (let p = 0; p <= maxP; p += step) {
    root.append(svg("line", { class: "gridline", x1: M.l, x2: W - M.r, y1: y(p), y2: y(p) }),
      svg("text", { x: M.l - 8, y: y(p) + 4, "text-anchor": "end", text: p }));
  }
  root.append(svg("text", { x: (M.l + W - M.r) / 2, y: H - 8, "text-anchor": "middle", text: "Oxygen (mole fraction)" }),
    svg("text", { x: 14, y: (M.t + H - M.b) / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${(M.t + H - M.b) / 2})`, text: "Pressure (psi)" }));
  const h = data.habitat;
  if (habitatOn) {
    root.append(svg("rect", { class: "box", x: x(h.o2[0]), y: y(h.pressure_psi[1]), width: x(h.o2[1]) - x(h.o2[0]), height: y(h.pressure_psi[0]) - y(h.pressure_psi[1]) }),
      svg("text", { class: "box-label", x: x(h.o2[1]) - 6, y: y(h.pressure_psi[1]) - 7, "text-anchor": "end", text: h.label }));
  }
  // Reference: Earth's air at sea level.
  root.append(svg("path", { class: "ref", d: `M${x(0.21) - 6},${y(14.7)} h12 M${x(0.21)},${y(14.7) - 6} v12` }),
    svg("text", { x: x(0.21) + 9, y: y(14.7) - 7, text: "Earth air" }));
  // Many tests share the same oxygen and pressure. Draw one mark per place, sized by how many tests sit there.
  const groups = new Map();
  for (const p of pts) {
    const key = [p.investigation, p.o2, p.pressure_psi, p.o2_role, p.fuel_class].join("|");
    if (!groups.has(key)) groups.set(key, { ...p, tests: [] });
    groups.get(key).tests.push(p);
  }
  const tally = (items, field) => {
    const counts = {};
    for (const i of items) counts[i[field] || "unknown"] = (counts[i[field] || "unknown"] || 0) + 1;
    return Object.entries(counts).map(([k, n]) => `${k.replace("_", " ")} ${n}`).join(", ");
  };
  for (const g of [...groups.values()].sort((a, b) => b.tests.length - a.tests.length)) {
    const ambient = g.o2_role === "ambient", n = g.tests.length;
    const dot = svg("circle", { class: `pt ${ambient ? "filled" : "hollow"} ${g.fuel_class || ""}`, cx: x(g.o2), cy: y(g.pressure_psi),
      r: 4 + 1.6 * Math.sqrt(n - 1), tabindex: 0 });
    dot.addEventListener("mousemove", (e) => showTip(e, `${g.name} · ${n} test${n === 1 ? "" : "s"}`, [
      `${fmt(g.o2 * 100, 1)}% oxygen (${ROLE_LABEL[g.o2_role] || g.o2_role || "role unknown"}) · ${fmt(g.pressure_psi, 1)} psi`,
      `Fuel: ${tally(g.tests, "fuel")}`, `Outcome: ${tally(g.tests, "outcome")}`,
      ambient ? (habitatOn && g.in_box ? "Inside the habitat box" : null)
              : (habitatOn ? "Not counted: this oxygen value isn't room air" : "This oxygen value is the burner stream, not room air"),
      `${g.file}, rows ${Math.min(...g.tests.map((t) => t.row))}–${Math.max(...g.tests.map((t) => t.row))}`]));
    dot.addEventListener("mouseleave", hideTip);
    dot.addEventListener("click", () => openDetail(g.investigation));
    root.append(dot);
  }
  return root;
}

export async function render(root, state) {
  const habitatOn = state.habitatView;
  let measuredOnly = false;
  const holder = el("div");
  async function draw() {
    const data = await api(`/api/envelope?${habitatQuery()}&measured_only=${measuredOnly}`);
    const g = data.gaps, h = data.habitat;
    const byInv = {};
    for (const p of data.points) (byInv[p.investigation] ||= { name: p.name, n: 0, roles: new Set() }).n++, byInv[p.investigation].roles.add(p.o2_role);
    // With the Habitat view off, this summary replaces the "inside the box" panel. It uses no habitat.
    const count = (field, label) => {
      const n = {};
      for (const p of data.points) n[p[field] || "unknown"] = (n[p[field] || "unknown"] || 0) + 1;
      return Object.entries(n).map(([k, v]) => `${label[k] || k} ${v}`).join(" · ");
    };
    const stream = data.points.filter((p) => p.o2_role !== "ambient").length;
    const withoutTables = g.investigations_without_tables.length;
    const plotted = el("div", { class: "card" }, el("h3", { text: "What's plotted" }),
      el("div", { class: "tile" }, el("div", { class: "value", text: fmt(data.points.length) }), el("div", { class: "label", text: "tests with oxygen and pressure values" })),
      data.points.length > 0 && el("p", { text: `Where the oxygen value comes from: ${count("o2_role", { ambient: "room air", oxidizer_stream: "burner stream" })}` }),
      data.points.length > 0 && el("p", { text: `Fuel: ${count("fuel_class", {})}` }),
      stream > 0 && el("div", { class: "note", text: `${stream} of these tests give the oxygen of the gas leaving the burner, not of the air around the flame. They are drawn hollow and must not be read as room-air oxygen.` }),
      withoutTables > 0 && el("div", { class: "note", text: `${withoutTables} of the combustion investigations have no plotted tests on this chart yet (their tables aren't mapped yet, or PSI lists none). An empty part of the chart means "not in the data we hold", not "never tested".` }));
    holder.replaceChildren(
      el("div", { class: "split" },
        el("div", {},
          el("div", { class: "legend" },
            ...Object.entries(FUEL_COLOR).map(([k, c]) => { const s = el("span", { class: "swatch" }); s.style.background = c; return el("span", { class: "key" }, s, `${k} fuel`); }),
            el("span", { class: "key", text: "bigger mark: more tests at that point" }),
            el("span", { class: "key" }, el("span", { class: "dot" }), "filled: oxygen of the room air"),
            el("span", { class: "key" }, el("span", { class: "ring" }), "hollow: oxygen of the burner stream (not room air)")),
          el("div", { class: "chart" }, chart(data, habitatOn)),
          el("p", { class: "muted", text: `${data.points.length} tests plotted. Hover a mark for its tests and source rows; click it for the investigation.` })),
        el("div", { class: "grid" },
          !habitatOn && plotted,
          habitatOn && el("div", { class: "card" }, el("h3", {}, "Inside the ", hab(habName(h.label)), " box"),
            el("div", { class: "tile" }, el("div", { class: "value" }, hab(fmt(g.in_box))), el("div", { class: "label" }, hab(`tests at ${h.summary}`))),
            Object.keys(g.in_box_by_fuel_class).length > 0 && el("p", {}, hab(Object.entries(g.in_box_by_fuel_class).map(([k, n]) => `${k}: ${n}`).join(" · "))),
            g.look_alike_note && el("div", { class: "note", text: g.look_alike_note }),
            g.caveat && el("div", { class: "note", text: g.caveat })),
          el("div", { class: "card" }, el("h3", { text: "Partial gravity" }),
            el("p", { class: "muted", text: "PSI has no Moon- or Mars-gravity combustion data yet. Microgravity and normal-gravity results can only bound what happens in between. ACME E-FIELD Flames mimicked partial gravity with an electric field." })),
          el("div", { class: "card" }, el("h3", { text: "Data behind this chart" }),
            el("ul", { class: "plain" }, ...Object.entries(byInv).map(([id, v]) => el("li", {},
              el("a", { href: "#", text: `${v.name} (${id})`, onclick: (e) => { e.preventDefault(); openDetail(id); } }),
              ` — ${v.n} tests · `, el("a", { href: `/api/investigations/${id}/tests.csv`, text: "CSV with sources" })))),
            Object.keys(data.skipped).length > 0 && el("p", { class: "muted", text: `Left out: ${Object.entries(data.skipped).map(([k, n]) => `${n} ${k}`).join("; ")}.${(data.left_out_by || []).length ? " Mostly from " + data.left_out_by.slice(0, 4).map((x) => `${x.investigation} (${x.tests}${x.plotted ? "" : ", none plotted"})`).join(", ") + "." : ""}` })))));
  }
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "Flammability envelope" }), el("h1", { text: "Where has NASA tested, and where does the data stop?" }),
      el("p", { class: "lede", text: habitatOn
        ? "Every harmonised test is a point. The shaded box is the habitat's atmosphere. Only tests whose oxygen value describes the surrounding air can count as inside it."
        : "Every harmonised test is a point, placed by its oxygen fraction and pressure." })),
    el("label", { class: "legend" }, el("span", { class: "key" }, el("input", { type: "checkbox", onchange: async (e) => { measuredOnly = e.target.checked; await draw(); } }), "Measured tests only (hide simulation results)")),
    holder);
  await draw();
}
