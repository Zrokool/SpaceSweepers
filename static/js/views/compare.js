// Compare: 2–4 investigations side by side, and how all of them relate.
import { el, svg, api, showTip, hideTip, title, METHOD_LABEL, isStatic } from "../ui.js";
import { compareFromProfiles } from "../staticmap.js";
import { navigate, openDetail } from "../app.js";

const DEFAULT_IDS = ["PSI-69", "PSI-117", "PSI-142"];  // FLEX and the two ground studies built on its data

function cellText(attribute, values) {
  if (attribute === "Method") return values.map((v) => METHOD_LABEL[v] || v).join(", ");
  return values.join(", ");
}

function table(result) {
  const ids = result.investigations.map((i) => i.id);
  return el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { text: "Attribute" }),
      ...result.investigations.map((i) => el("th", {}, el("a", { href: "#", text: title(i),
        onclick: (e) => { e.preventDefault(); openDetail(i.id); } }))))),
    el("tbody", {}, ...result.attributes.map((row) => el("tr", {}, el("td", { text: row.attribute }),
      ...ids.map((id) => {
        const values = row.cells[id];
        if (!values.length) return el("td", { class: "empty", text: "–" });
        return el("td", { class: row.all_same ? "shared" : "differs" }, cellText(row.attribute, values));
      }))))));
}

function graph(data, selected) {
  // Three columns: ground studies, flight investigations, shared hardware.
  const inv = data.nodes.filter((n) => n.kind === "investigation");
  const cols = [inv.filter((n) => n.type !== "Microgravity"), inv.filter((n) => n.type === "Microgravity"),
    data.nodes.filter((n) => n.kind === "hardware")];
  const X = [150, 470, 800], ROW = 27, TOP = 44;
  const height = TOP + Math.max(...cols.map((c) => c.length)) * ROW + 16;
  const pos = {};
  cols.forEach((col, c) => {
    const offset = (height - TOP - col.length * ROW) / 2;
    col.forEach((n, r) => { pos[n.id] = { x: X[c], y: TOP + offset + r * ROW + ROW / 2, col: c }; });
  });
  const root = svg("svg", { viewBox: `0 0 960 ${height}`, role: "img",
    "aria-label": "How the investigations relate: ground studies, the flight investigations whose data they use, and shared hardware" });
  ["Ground studies", "Flight investigations", "Shared hardware"].forEach((t, c) =>
    root.append(svg("text", { x: X[c], y: 20, "text-anchor": "middle", text: t })));
  const edgeEls = [], nodeEls = {};
  for (const e of data.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    let d;
    if (a.col === b.col) {  // same column: bow out to the left
      const bow = 40 + Math.abs(a.y - b.y) * 0.25;
      d = `M${a.x - 58},${a.y} C${a.x - 58 - bow},${a.y} ${b.x - 58 - bow},${b.y} ${b.x - 58},${b.y}`;
    } else {
      const dir = b.x > a.x ? 1 : -1, ax = a.x + dir * 62, bx = b.x - dir * (b.col === 2 ? 96 : 62), mid = (ax + bx) / 2;
      d = `M${ax},${a.y} C${mid},${a.y} ${mid},${b.y} ${bx},${b.y}`;
    }
    const cls = e.relation === "uses flight data from" ? "edge flight" : e.relation === "ran on" ? "edge hw" : "edge";
    const path = svg("path", { d, class: cls });
    edgeEls.push({ path, e });
    root.append(path);
  }
  const focus = (id) => {
    const linked = new Set([id]);
    for (const { e } of edgeEls) if (e.from === id || e.to === id) { linked.add(e.from); linked.add(e.to); }
    for (const { path, e } of edgeEls) path.classList.toggle("dim", id != null && e.from !== id && e.to !== id);
    for (const [nid, g] of Object.entries(nodeEls)) g.classList.toggle("dim", id != null && !linked.has(nid));
  };
  for (const n of data.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const hw = n.kind === "hardware", w = hw ? 190 : 122;
    const g = svg("g", { class: "node", transform: `translate(${p.x - w / 2},${p.y - 10})`, tabindex: hw ? null : 0 });
    const stroke = hw ? "#3a3e45" : selected.includes(n.id) ? "#f2f2f0" : n.type === "Microgravity" ? "#3987e5" : "#c98500";
    g.append(svg("rect", { width: w, height: 20, rx: 4, fill: "#1d2024", stroke, "stroke-width": selected.includes(n.id) ? 2 : 1 }),
      svg("text", { x: w / 2, y: 14, "text-anchor": "middle", text: n.label.length > (hw ? 28 : 17) ? n.label.slice(0, hw ? 27 : 16) + "…" : n.label }));
    const links = data.edges.filter((e) => e.from === n.id || e.to === n.id);
    g.addEventListener("mousemove", (ev) => showTip(ev, hw ? n.label : title({ name: n.label, id: n.id }),
      hw ? [`${links.length} flight investigations ran on it`]
         : [`${n.type} · ${METHOD_LABEL[n.method] || n.method}`, ...links.filter((e) => e.relation !== "ran on")
             .map((e) => e.from === n.id ? `${e.relation} ${e.to}` : `${e.from}: ${e.relation} this`)]));
    g.addEventListener("mouseenter", () => focus(n.id));
    g.addEventListener("mouseleave", () => { focus(null); hideTip(); });
    if (!hw) g.addEventListener("click", () => openDetail(n.id));
    nodeEls[n.id] = g;
    root.append(g);
  }
  return root;
}

export async function render(root, state) {
  const [list, graphData] = await Promise.all([api("/api/investigations"), api("/api/graph")]);
  const all = list.investigations.slice().sort((a, b) => a.id.localeCompare(b.id, "en", { numeric: true }));
  const known = new Set(all.map((i) => i.id));
  let ids = (state.params.get("ids") || "").split(",").filter((i) => known.has(i)).slice(0, 4);
  if (ids.length < 2) ids = DEFAULT_IDS.filter((i) => known.has(i));
  const result = isStatic ? compareFromProfiles(await api("/api/compare-profiles"), ids)
    : await api("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) });

  const toggle = (id) => {
    const next = ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id];
    if (next.length >= 2 && next.length <= 4) navigate("compare", { ids: next.join(",") });
  };
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "Compare" }), el("h1", { text: "How are these investigations alike, and how do they differ?" }),
      el("p", { class: "lede", text: "Pick two to four investigations. A green edge marks an attribute they all share; orange marks one where they differ." })),
    el("div", { class: "chips", role: "group", "aria-label": "Investigations to compare" }, ...all.map((i) =>
      el("button", { class: "chip", type: "button", "aria-pressed": String(ids.includes(i.id)), text: i.name === i.id ? i.id : `${i.name}`,
        title: i.title, onclick: () => toggle(i.id) }))),
    table(result),
    result.links.length > 0 && el("div", { class: "card" }, el("h3", { text: "Links between them" }),
      el("ul", { class: "facts" }, ...result.links.map((l) => el("li", { text: `${l.from} ${l.relation} ${l.to} (listed by ${l.listed_by}).` })))),
    el("div", {}, el("h2", { text: "How all the investigations relate" }),
      el("p", { class: "muted", text: "Hover a box to trace its links; click one for detail. PSI's links are one-way, so each line shows who listed it." })),
    el("div", { class: "chart" }, graph(graphData, ids)),
    el("div", { class: "legend" },
      el("span", { class: "key", text: "Orange line: a ground study uses that flight investigation's data" }),
      el("span", { class: "key", text: "Grey line: listed as related, or ran on that hardware" }),
      el("span", { class: "key", text: "Blue outline: microgravity · yellow outline: ground" })),
  );
}
