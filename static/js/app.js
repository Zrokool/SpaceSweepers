// SpaceSweepers dashboard: hash router, shared state (habitat, Habitat view switch, pillar), and the detail drawer.
import { el, api, failed, loading, hideTip, PILLAR_LABEL } from "./ui.js";
import { openDetail } from "./views/detail.js";

const VIEWS = {
  overview: () => import("./views/overview.js"),
  insights: () => import("./views/insights.js"),
  rank: () => import("./views/rank.js"),
  compare: () => import("./views/compare.js"),
  envelope: () => import("./views/envelope.js"),
  sweeper: () => import("./views/sweeper.js"),
  earth: () => import("./views/earth.js"),
  sources: () => import("./views/sources.js"),
};

export const state = { meta: null, habitat: "moon", habitatView: true, pillar: null, view: "overview", params: new URLSearchParams() };
const $ = (id) => document.getElementById(id);

// The Habitat view switch. On (the default) shows every habitat part; Off hides them.
// It is kept in the page address (hv=off) and remembered in this browser.
const HV_KEY = "spacesweepers.habitatView";
function storedHabitatView() {
  try { return localStorage.getItem(HV_KEY) !== "off"; } catch { return true; }
}
function storeHabitatView(on) {
  try { localStorage.setItem(HV_KEY, on ? "on" : "off"); } catch { /* storage unavailable: the address still carries it */ }
}
function viewParams() { return state.habitatView ? {} : { hv: "off" }; }

export function habitatQuery() {
  const q = new URLSearchParams({ habitat: state.habitat });
  if (state.pillar) q.set("pillar", state.pillar);
  return q.toString();
}
// The address part every link carries: habitat, pillar and the Habitat view switch.
function linkQuery() {
  const q = new URLSearchParams(habitatQuery());
  for (const [k, v] of Object.entries(viewParams())) q.set(k, v);
  return q.toString();
}
export function currentHabitat() { return state.meta.habitats.find((h) => h.key === state.habitat); }
export function navigate(view, params = {}) {
  const q = new URLSearchParams({ habitat: state.habitat, ...(state.pillar ? { pillar: state.pillar } : {}), ...viewParams(), ...params });
  location.hash = `#/${view}?${q}`;
}
export { openDetail };

function readHash() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query);
  state.view = VIEWS[path] ? path : "overview";
  state.params = params;
  const habitat = params.get("habitat");
  if (habitat && state.meta.habitats.some((h) => h.key === habitat)) state.habitat = habitat;
  const pillar = params.get("pillar");
  state.pillar = state.meta.pillars.includes(pillar) ? pillar : null;
  const hv = params.get("hv");
  state.habitatView = hv === "off" ? false : hv === "on" ? true : storedHabitatView();
  if (hv === "off" || hv === "on") storeHabitatView(state.habitatView);   // a link that sets it is remembered too
}

// Which of the habitat and pillar controls change a view's numbers. Compare and References use neither.
const CONTROLS_USED = {
  overview: { habitat: true, pillar: true },
  rank: { habitat: true, pillar: true },
  envelope: { habitat: true },
  sweeper: { habitat: true },
  earth: { pillar: true },
};

function syncControls() {
  $("habitat").value = state.habitat;
  for (const b of $("pillar").children) b.setAttribute("aria-checked", String((b.dataset.pillar || null) === state.pillar));
  const h = currentHabitat();
  $("habitat-basis").textContent = `${h.basis} The range around these numbers was chosen by the team, not taken from NASA.`;
  $("habitat-disclaimer").textContent = "Atmosphere values are given by the NASA Space Apps challenge text and are used here as a reference; they are not PSI data.";
  const sw = $("habitat-view");
  sw.setAttribute("aria-checked", String(state.habitatView));
  sw.querySelector(".switch-label").textContent = state.habitatView ? "On" : "Off";
  // Each view shows only the controls it actually uses (the snapshot line is in the page footer).
  const uses = CONTROLS_USED[state.view] || {};
  $("context").hidden = !uses.habitat && !uses.pillar;
  $("habitat-view-field").hidden = !uses.habitat;
  $("habitat-field").hidden = !uses.habitat || !state.habitatView;
  $("habitat-basis").hidden = !uses.habitat || !state.habitatView;
  $("habitat-disclaimer").hidden = !uses.habitat || !state.habitatView;
  $("habitat-key").hidden = !uses.habitat || !state.habitatView;
  $("pillar-field").hidden = !uses.pillar;
  for (const a of $("nav").children) {
    if (a.dataset.view === state.view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    a.href = `#/${a.dataset.view}?${linkQuery()}`;
  }
}

let renderToken = 0;
async function render() {
  readHash();
  syncControls();
  hideTip();
  const root = $("view"), token = ++renderToken;
  loading(root);
  try {
    const module = await VIEWS[state.view]();
    const fragment = el("div");
    // Views write `condition && element`; drop the false/null ones instead of printing them.
    fragment.append = (...kids) => Element.prototype.append.apply(fragment, kids.flat().filter((k) => k != null && k !== false));
    await module.render(fragment, state);
    if (token !== renderToken) return;  // a newer navigation won
    root.replaceChildren(...fragment.childNodes);
    // A link can open an investigation's detail directly: #/rank?detail=PSI-159
    const detail = state.params.get("detail");
    if (/^PSI-\d{1,5}$/.test(detail || "")) openDetail(detail); else closeDrawer();
    document.title = `${state.view[0].toUpperCase()}${state.view.slice(1)} · SpaceSweepers`;
  } catch (error) {
    if (token === renderToken) failed(root, error);
  }
}

function buildControls() {
  $("habitat").append(...state.meta.habitats.map((h) => el("option", { value: h.key, text: `${h.label} — ${h.summary}` })));
  $("habitat").addEventListener("change", (e) => { state.habitat = e.target.value; navigate(state.view, keepParams()); });
  $("habitat-view").addEventListener("click", () => {
    state.habitatView = !state.habitatView;
    storeHabitatView(state.habitatView);
    navigate(state.view, { ...keepParams(), hv: state.habitatView ? "on" : "off" });
  });
  const options = [[null, "All"], ...state.meta.pillars.map((p) => [p, PILLAR_LABEL[p]])];
  $("pillar").append(...options.map(([key, label]) => el("button", {
    type: "button", role: "radio", text: label, dataset: key ? { pillar: key } : {},
    onclick: () => { state.pillar = key; navigate(state.view, keepParams()); },
  })));
  const s = state.meta.snapshot, c = state.meta.counts;
  const stale = state.meta.tables.stale, note = $("refresh-note");
  note.replaceChildren(...(stale.length ? [el("strong", { text: "Data refresh needed. " }),
    `${stale.length} test table${stale.length === 1 ? " has" : "s have"} changed since ${stale.length === 1 ? "it was" : "they were"} mapped, so ${stale.length === 1 ? "its" : "their"} data is hidden until re-mapped: ${stale.map((s) => `${s.name} (${s.file})`).join(", ")}. Run python -m app.nimbus.tables.`] : []));
  note.hidden = stale.length === 0;
  // The habitat bands in the method note are read from the same table the calculations use, so the note cannot drift from the code.
  const pc = (x) => String(Math.round(x * 1000) / 10);
  $("method-habitats").replaceChildren(...state.meta.habitats.map((h) =>
    el("li", { text: `${h.label}: oxygen ${pc(h.o2[0])} to ${pc(h.o2[1])}%, pressure ${h.pressure_psi[0]} to ${h.pressure_psi[1]} psi` })));
  $("snapshot").textContent = `PSI snapshot ${s.fetched_at.slice(0, 10)} · ${c.investigations} investigations · ${c.tests} tests`;
  $("drawer-close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

function keepParams() {
  const extra = {};
  for (const [k, v] of state.params) if (!["habitat", "pillar", "hv"].includes(k)) extra[k] = v;
  return extra;
}
export function closeDrawer() { $("drawer").hidden = true; }

async function boot() {
  try {
    state.meta = await api("/api/meta");
    state.habitat = state.meta.default_habitat;
    buildControls();
    window.addEventListener("hashchange", render);
    await render();
  } catch (error) {
    failed($("view"), error);
  }
}
boot();
