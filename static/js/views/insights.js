// SI Insights: ask questions about all the PSI data. SI writes, Nimbus checks every sentence, sources are shown.
// All text is set with textContent (through el()), so PSI text and model text can never become HTML.
import { el, api, fmt, METHOD_LABEL, isStatic, README_RUN_URL } from "../ui.js";
import { normQuestion } from "../staticmap.js";
import { openDetail, navigate } from "../app.js";

const STAGES = [
  ["read", "Read the question"],
  ["investigator", "Investigator (SI) picks tools"],
  ["tools", "Tools look up PSI data"],
  ["analyst", "Analyst (SI) writes"],
  ["nimbus", "Nimbus checks every sentence"],
];
const STORE = "spacesweepers.insights";
const MAX_QUESTION = 500;
const EXPERT_NOTICE = "Research context only. SI Insights never declares a fire or an emergency and does not replace spacecraft fire-detection and emergency procedures.";

// The conversation outlives tab switches (module state) and page reloads (sessionStorage).
const MODE_KEY = "spacesweepers.chatMode";
function storedMode() { try { return localStorage.getItem(MODE_KEY) === "expert" ? "expert" : "guided"; } catch { return "guided"; } }
const chat = { mode: storedMode(), turns: [], active: null, selected: null, running: null, status: null, warm: "idle", nextId: 1 };

function save() {
  try {
    const done = chat.turns.filter((t) => t.report).map((t) => ({ id: t.id, q: t.q, parentQ: t.parentQ || null, chips: t.chips, report: t.report }));
    sessionStorage.setItem(STORE, JSON.stringify(done.slice(-20)));
  } catch { /* storage unavailable: the chat just isn't kept across reloads */ }
}
function restore() {
  if (chat.turns.length) return;
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE) || "[]");
    chat.turns = saved.map((t) => ({ ...t, stages: {}, evidence: null }));
    chat.nextId = Math.max(0, ...chat.turns.map((t) => t.id)) + 1;
    chat.active = chat.turns.at(-1)?.id ?? null;
  } catch { /* ignore a damaged store */ }
}

// ---------- talking to the server ----------
async function askStream(question, history, scenario, onEvent, signal, extra = {}) {
  const resp = await fetch("/api/insights/ask", { method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history, ...(scenario ? { scenario } : {}), ...extra }) });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { const j = await resp.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not JSON */ }
    throw new Error(resp.status === 429 ? "Too many questions in a minute. Wait a moment and try again." : detail);
  }
  const reader = resp.body.getReader(), decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of block.split("\n")) if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

// Guided only: the conditions of the previous answer, so "what about heptane?" can build on it.
function lastSlots() {
  const prev = [...chat.turns].reverse().find((t) => t.report);
  return prev?.report?.scenario || null;
}

function aboutIds(turn) { return (turn.chips || []).filter((c) => c.kind === "about").map((c) => c.psi); }

// ---------- rendering ----------
let ui = {};      // elements of the current page render

const STATUS_TEXT = { read: "Reading the question…", investigator: "Looking up PSI data…", tools: "Looking up PSI data…",
  analyst: "Writing a short answer…", nimbus: "Checking every sentence against its sources…" };
function stageLine(turn) {
  const running = STAGES.map(([k]) => k).filter((k) => turn.stages[k]?.status === "running").pop();
  const last = STAGES.map(([k]) => k).filter((k) => turn.stages[k]).pop();
  return el("p", { class: "status-line", role: "status", text: STATUS_TEXT[running || last] || "Reading the question…" });
}

const CHIP_LABEL = { about: "About", topic: "Topic", fuel: "Fuel", method: "Method", type: "Type", number: "Condition" };
function chipRow(chips) {
  return el("div", { class: "chips" }, ...(chips || []).map((c) => el("span", { class: `chip static ${c.kind}`,
    text: CHIP_LABEL[c.kind] ? `${CHIP_LABEL[c.kind]}: ${c.label}` : c.label })));
}

function citeButtons(turn, cites) {
  return cites.map((n) => el("button", { class: "cite", type: "button", "aria-label": `Source ${n}`, text: String(n),
    onclick: () => { chat.active = turn.id; chat.selected = n; renderSources(); renderAll(false); } }));
}

function tableBlock(t) {
  const label = (cell) => (cell.length ? cell.map((v) => METHOD_LABEL[v] || v).join(", ") : "–");
  return el("div", { class: "table-wrap computed" }, el("p", { class: "eyebrow", text: t.title }),
    el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "Attribute" }), ...t.columns.map((c) => el("th", { text: c.name })))),
      el("tbody", {}, ...t.rows.map((r) => el("tr", {}, el("td", { text: r.attribute }),
        ...t.columns.map((c) => el("td", { class: t.columns.length < 2 ? null : r.all_same ? "shared" : "differs", text: label(r.cells[c.psi] || []) })))))));
}

function listBlock(l) {
  return el("div", { class: "computed" }, el("p", { class: "eyebrow", text: l.title }), l.note && el("p", { class: "muted", text: l.note }),
    el("ul", { class: "plain" }, ...l.rows.map((r) => el("li", {}, el("a", { href: "#", text: r.name === r.psi ? r.psi : `${r.name} · ${r.psi}`,
      onclick: (e) => { e.preventDefault(); openDetail(r.psi); } }), el("span", { class: "muted", text: ` — ${r.title}` })))));
}

const excerpt = (t) => (t.length > 240 ? t.slice(0, 240).replace(/\s+\S*$/, "") + "…" : t);

function linkRow(r) {
  if (!r.links?.length) return null;
  const go = { detail: (l) => openDetail(l.psi), compare: (l) => navigate("compare", { ids: l.ids.join(",") }), sweeper: () => navigate("sweeper") };
  return el("div", { class: "chips next-links" }, ...r.links.map((l) => el("button", { class: "btn-ghost", type: "button", text: `${l.label} →`, onclick: () => go[l.kind](l) })));
}

// Nimbus's verdict and the audit trail live with the sources, so the answer itself stays short and nothing is shown twice.
function verification(r) {
  const s = r.stats, open = r.mode === "no_answer" || r.mode === "sources_only";
  const summary = r.mode === "si" ? `Nimbus verification: ${s.kept} sentence${s.kept === 1 ? "" : "s"} verified${s.removed ? `, ${s.removed} withheld` : ""}`
    : r.mode === "computed" ? "Computed by code from PSI data, no SI involved"
    : r.mode === "no_answer" ? `Nothing could be verified (${s.removed} withheld)` : "Evidence only";
  return el("details", { class: "verify", open }, el("summary", { text: summary }),
    r.removed.length > 0 && el("div", {}, el("p", { class: "eyebrow", text: "Withheld: PSI does not back these sentences" }),
      el("ul", { class: "facts" }, ...r.removed.map((x) => el("li", {}, el("span", { class: "strike", text: x.text }), el("span", { class: "muted", text: ` — ${x.reason}` }))))),
    r.not_covered.length > 0 && el("div", {}, el("p", { class: "eyebrow", text: "What the data does not cover" }), el("ul", { class: "facts" }, ...r.not_covered.map((g) => el("li", { text: g })))),
    el("div", {}, el("p", { class: "eyebrow", text: "How this answer was made" }),
      el("ul", { class: "facts" }, ...r.tools.map((t) => el("li", {}, el("span", { class: "badge plain", text: t.source === "investigator" ? "SI chose" : "code" }), ` ${t.label}`))),
      el("p", { class: "muted", text: r.model ? `Sentences written by ${r.model} on this computer; every one checked by fixed rules. Run ${r.run_id}.` : "No SI was used." })));
}

// A scenario answer: the key numbers, the tests behind them (each with its file and row), and what the answer does not tell you.
function analysisCard(a) {
  const go = (l) => navigate("sweeper", { ...(l.family ? { family: l.family } : {}), ...(l.fuel ? { fuel: l.fuel } : {}), ...(l.diluent ? { diluent: l.diluent } : {}) });
  const t = a.table, q = a.quote;
  return el("div", { class: "analysis" },
    q && el("blockquote", { class: "quote" }, el("p", { text: q.text }), el("footer", { text: q.where })),
    a.quote2 && el("blockquote", { class: "quote" }, el("p", { class: "eyebrow", text: a.quote2.label }), el("p", { text: a.quote2.text }), el("footer", { text: a.quote2.where })),
    a.metrics.length > 0 && el("div", { class: "metrics" }, ...a.metrics.map((m) => el("div", { class: "metric" }, el("div", { class: "value", text: m.value }), el("div", { class: "label", text: m.label })))),
    t && el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...t.columns.map((c) => el("th", { text: c })))),
      el("tbody", {}, ...t.rows.map((row, i) => el("tr", { class: t.psi[i] ? "clickable" : null, onclick: t.psi[i] ? () => openDetail(t.psi[i]) : null }, ...row.map((cell, j) => el("td", { class: j === row.length - 1 && t.psi.length ? "mono" : null, text: cell}))))))),
    t && t.total > t.shown && el("p", { class: "tiny", text: `Showing ${t.shown} of ${t.total} tests.` }),
    a.links.length > 0 && el("div", { class: "chips next-links" }, ...a.links.map((l) => el("button", { class: "btn-ghost", type: "button", text: `${l.label} →`, onclick: () => go(l) }))),
    a.caveats.length > 0 && el("details", { class: "verify" }, el("summary", { text: "What this does not tell you" }), el("ul", { class: "facts" }, ...a.caveats.map((c) => el("li", { text: c })))));
}

const PROVENANCE = { computed: "Computed by code from the PSI tests listed below", si: "SI reading, verified against its sources" };

function reportBlock(turn) {
  const r = turn.report;
  const kids = r.notes.filter((n) => !/^Answered (directly|earlier)/.test(n)).map((n) => el("div", { class: "note", text: n }));
  if (r.mode === "sources_only") kids.push(el("p", { class: "muted", text: "SI isn't available, so the PSI evidence found for your question is in the sources panel." }));
  const computed = r.mode === "computed";
  if (["si", "no_answer", "computed"].includes(r.mode)) {
    kids.push(...r.answer.map((x) => (x.note
      ? el("div", { class: "note", text: x.text })
      : el("p", { class: `sentence${computed ? " headline" : ""}` }, x.text, " ", ...citeButtons(turn, x.cites)))));
    if (r.mode !== "no_answer") kids.push(el("p", { class: "tiny provenance", text: PROVENANCE[computed ? "computed" : "si"] }));
  }
  if (r.analysis) kids.push(analysisCard(r.analysis));
  if (r.table) kids.push(tableBlock(r.table));
  else if (r.facts) kids.push(tableBlock(r.facts));
  if (r.list) kids.push(listBlock(r.list));
  const links = linkRow(r);
  if (links) kids.push(links);
  kids.push(el("button", { class: "btn-ghost show-sources", type: "button", text: `Sources and verification (${r.sources.length}) →`,
    onclick: () => { chat.active = turn.id; chat.selected = null; renderSources(); renderAll(false); document.querySelector(".chat-sources")?.scrollIntoView({ block: "start", behavior: "smooth" }); } }));
  const next = isStatic ? r.followups.filter((f) => demoFor(f.question, turn.q)) : r.followups;
  if (next.length) {
    kids.push(el("div", { class: "chips followups" }, el("span", { class: "muted", text: "Try next:" }),
      ...next.map((f) => el("button", { class: "chip", type: "button", text: f.label, onclick: () => send(f.question, null, turn) }))));
  }
  return kids;
}

function turnView(turn) {
  if (chat.mode === "guided") return guidedTurn(turn);
  const running = chat.running && chat.running.turn === turn;
  const ai = el("div", { class: `msg ai${chat.active === turn.id ? " active" : ""}` },
    el("div", { class: "who", text: "SI Insights" }), turn.chips && turn.chips.length > 0 && chipRow(turn.chips),
    (running || !turn.report) && !turn.error && stageLine(turn),
    running && !turn.report && turn.draft && turn.draft.length > 0 && el("div", { class: "draft" },
      el("p", { class: "eyebrow", text: "Draft, still being checked" }),
      ...turn.draft.map((x) => el("p", { class: "sentence", text: x }))),
    turn.error && el("div", { class: "note", text: turn.error }),
    turn.report && reportBlock(turn),
    !turn.report && turn.evidence && el("button", { class: "btn-ghost show-sources", type: "button", text: "Show evidence found so far",
      onclick: () => { chat.active = turn.id; chat.selected = null; renderSources(); renderAll(false); } }));
  return [el("div", { class: "msg user" }, el("div", { class: "who", text: "You" }), el("p", { text: turn.q })), ai];
}

function renderAll(scroll = true) {
  if (!ui.log) return;
  ui.log.replaceChildren(...(chat.turns.length ? chat.turns.flatMap(turnView) : [introView()]));
  if (scroll) ui.log.scrollTop = ui.log.scrollHeight;
  ui.send.disabled = isStatic || !!chat.running;
  if (ui.cases && !chat.turns.length) ui.cases.open = true;
  ui.stop.hidden = !chat.running;
}

const EXAMPLES = [
  ["Closest tested conditions to your design", "We are designing a cabin at 34% oxygen and 8.2 psi. Which tested conditions are closest and what happened?"],
  ["A limit you need", "What is the lowest oxygen concentration at which methanol droplets burned in FLEX?"],
  ["Compare two suppressants", "How does carbon dioxide compare with helium as a suppressant in FLEX?"],
];
// The Scenario builder: choose conditions instead of phrasing a question. It runs the same analysis as a typed question.
const WANTS = [
  { key: "nearest", label: "Which tested conditions are closest to mine?", goal: "nearest", needs: ["o2", "p"] },
  { key: "outcomes", label: "What happened in these tests?", goal: "outcomes" },
  { key: "lowO2", label: "What is the lowest oxygen where it burned?", goal: "threshold", target: "burn", variable: "o2" },
  { key: "reig", label: "At what pressure did the flame reignite?", goal: "threshold", target: "reignite", variable: "p" },
  { key: "effect", label: "How does oxygen change whether it burned?", goal: "profile", target: "burn", variable: "o2" },
  { key: "gases", label: "Compare helium, carbon dioxide and nitrogen", goal: "compare", target: "extinguish" },
];
function scenarioForm() {
  const f = {};
  const field = (label, node) => el("label", { class: "field" }, el("span", { class: "eyebrow", text: label }), node);
  f.fuel = el("select", { "aria-label": "Fuel or material" }, el("option", { value: "", text: "Any fuel or material" }));
  f.gas = el("select", { "aria-label": "Gas mixed with oxygen" }, el("option", { value: "", text: "Any gas" }));
  f.o2 = el("input", { type: "number", min: "1", max: "100", step: "0.1", placeholder: "e.g. 34", "aria-label": "Oxygen percent" });
  f.p = el("input", { type: "number", min: "0.01", step: "0.1", placeholder: "e.g. 8.2", "aria-label": "Pressure" });
  f.unit = el("select", { "aria-label": "Pressure unit" }, ...["psi", "atm", "kpa"].map((u) => el("option", { value: u, text: u })));
  f.want = el("select", { "aria-label": "What do you want to know" }, ...WANTS.map((w) => el("option", { value: w.key, text: w.label })));
  f.note = el("p", { class: "tiny", role: "status" });
  if (!isStatic) api("/api/insights/scenario-options").then((o) => {          // the demo has no scenario form, so nothing to fill
    f.fuel.append(...o.fuels.map((x) => el("option", { value: x.name, text: `${x.name} (${x.tests} tests)` })));
    f.gas.append(...o.diluents.map((x) => el("option", { value: x.name, text: `${x.name} (${x.tests} tests)` })));
    f.o2.placeholder = `${o.o2_percent[0]} to ${o.o2_percent[1]}`; f.p.placeholder = `${o.pressure_psi[0]} to ${o.pressure_psi[1]} psi`;
  }).catch(() => {});
  const submit = () => {
    const want = WANTS.find((w) => w.key === f.want.value), o2 = f.o2.value ? Number(f.o2.value) : null, p = f.p.value ? Number(f.p.value) : null;
    if ((want.needs || []).includes("o2") && o2 == null || (want.needs || []).includes("p") && p == null) { f.note.textContent = "That question needs both an oxygen % and a pressure."; return; }
    f.note.textContent = "";
    const scenario = { goal: want.goal, ...(want.target ? { target: want.target } : {}), ...(want.variable ? { variable: want.variable } : {}), ...(f.fuel.value ? { fuel: f.fuel.value } : {}),
      ...(f.gas.value ? { diluent: f.gas.value } : {}), ...(o2 != null ? { o2_percent: o2 } : {}), ...(p != null ? { pressure: p, pressure_unit: f.unit.value } : {}) };
    const bits = [f.fuel.value, f.gas.value, o2 != null ? `${o2}% oxygen` : "", p != null ? `${p} ${f.unit.value}` : ""].filter(Boolean).join(", ");
    send(`Scenario${bits ? ` (${bits})` : ""}: ${want.label}`, scenario);
  };
  return el("details", { class: "scenario", open: chat.turns.length === 0 }, el("summary", { text: "Describe a scenario: fuel, gas, oxygen, pressure" }),
    el("div", { class: "scenario-grid" }, field("Fuel or material", f.fuel), field("Gas mixed with oxygen", f.gas), field("Oxygen (%)", f.o2),
      field("Pressure", el("span", { class: "pair" }, f.p, f.unit)), field("What do you want to know", f.want)),
    el("div", { class: "composer-row" }, f.note, el("span", { class: "grow" }), el("button", { class: "btn", type: "button", text: "Analyse this scenario", onclick: submit })));
}

function introView() {
  if (isStatic) return demoIntro();
  if (chat.mode === "guided") return guidedIntro();
  return el("div", { class: "intro" }, el("h2", { text: "Ask the PSI combustion research" }),
    el("p", { class: "muted", text: "Short answers with PSI's own words and sources. Every sentence is checked by code against the data." }),
    el("div", { class: "examples" }, ...EXAMPLES.map(([title, q]) => el("button", { class: "example", type: "button", onclick: () => send(q) },
      el("strong", { text: title }), el("span", { class: "muted", text: q })))));
}

function renderStatus() {
  if (!ui.status) return;
  const s = chat.status;
  const text = chat.mode === "guided" ? (!s ? "checking SI…" : !s.available ? "SI unavailable" : "SI ready") : !s ? "checking SI…" : !s.available ? "SI unavailable" : chat.warm === "loading" ? `${s.model} · loading model…` : `${s.model} · ready`;
  ui.status.className = `pill ${!s ? "" : !s.available ? "off" : chat.warm === "loading" ? "wait" : "ok"}`;
  ui.status.textContent = `${!s ? "…" : !s.available ? "○" : chat.warm === "loading" ? "◔" : "●"} ${text}`;
  ui.status.title = s && !s.available ? s.message : "";
}

// ---------- sources panel ----------
function sourceCard(s, turn) {
  const card = el("div", { class: `src${chat.selected === s.n && chat.active === turn?.id ? " selected" : ""}`, id: `src-${s.n}` });
  const detail = el("div", { class: "src-detail", hidden: true });
  const more = el("button", { class: "btn-ghost", type: "button", text: "Show surrounding text", hidden: s.computed || isStatic,
    onclick: async () => {
      if (!detail.hidden) { detail.hidden = true; more.textContent = "Show surrounding text"; return; }
      more.textContent = "Loading…";
      try {
        const p = await api(`/api/insights/passage/${encodeURIComponent(s.id)}`);
        detail.replaceChildren(...p.neighbours.filter((n) => n.position === "before").map((n) => el("blockquote", { class: "muted", text: n.text.slice(0, 700) })),
          el("blockquote", { text: p.text.slice(0, 1500) }), ...p.neighbours.filter((n) => n.position === "after").map((n) => el("blockquote", { class: "muted", text: n.text.slice(0, 700) })));
        detail.hidden = false; more.textContent = "Hide surrounding text";
      } catch (e) { detail.replaceChildren(el("p", { class: "muted", text: e.message })); detail.hidden = false; more.textContent = "Show surrounding text"; }
    } });
  card.append(...[el("div", { class: "src-head" }, el("span", { class: "src-n", text: String(s.n) }), el("strong", { text: s.label }), el("span", { class: "badge plain", text: s.kind })),
    s.shown_not_cited && el("p", { class: "muted", text: "Found for your question; not cited by an answer." }),
    s.computed ? el("p", { class: "src-text", text: s.text.length > 320 ? s.text.slice(0, 320).replace(/\s+\S*$/, "") + "…" : s.text })
      : el("blockquote", { class: "quote" }, el("p", { text: s.text.length > 320 ? s.text.slice(0, 320).replace(/\s+\S*$/, "") + "…" : s.text })),
    s.cited_by?.length > 0 && el("p", { class: "tiny", text: `Cited by sentence${s.cited_by.length === 1 ? "" : "s"} ${s.cited_by.join(", ")}` }),
    s.checks?.length > 0 && el("ul", { class: "checks" }, ...s.checks.map((c) => el("li", { text: c }))),
    el("div", { class: "src-links" }, s.psi && el("a", { href: "#", text: "Open investigation", onclick: (e) => { e.preventDefault(); openDetail(s.psi); } }),
      s.doi && el("a", { href: `https://doi.org/${s.doi}`, target: "_blank", rel: "noopener", text: `DOI ${s.doi}` }),
      s.url && el("a", { href: s.url, target: "_blank", rel: "noopener", text: "PSI page" }), more), detail].filter(Boolean));
  return card;
}

function renderSources() {
  if (!ui.sources) return;
  if (chat.mode === "guided") return renderGuidedDetails();
  const turn = chat.turns.find((t) => t.id === chat.active);
  const sources = turn?.report?.sources || turn?.evidence || [];
  ui.sources.replaceChildren(...[
    el("h3", { text: turn?.report ? "Sources and verification for this answer" : turn ? "Evidence found" : "Sources" }),
    !turn && el("p", { class: "muted", text: "Every answer lists the PSI passages, test rows and documents it relies on, with DOIs and links." }),
    turn && !turn.report && el("p", { class: "muted", text: "Found so far (not yet checked)." }),
    ...sources.map((s) => sourceCard(s, turn)),
    turn?.report && verification(turn.report),
  ].filter(Boolean));
  const picked = chat.selected && ui.sources.querySelector(`#src-${chat.selected}`);
  if (picked) picked.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------- asking ----------
async function send(question, scenario = null, parent = null) {
  if (isStatic) return sendDemo(question, parent);
  question = (question || ui.input.value).trim();
  if (!question || chat.running) return;
  const turn = { id: chat.nextId++, q: question, chips: null, stages: {}, evidence: null, report: null, error: null };
  chat.turns.push(turn);
  chat.active = turn.id; chat.selected = null;
  const controller = new AbortController();
  chat.running = { turn, controller };
  ui.input.value = ""; ui.count.textContent = `0 / ${MAX_QUESTION}`;
  renderAll(); renderSources();
  const history = chat.turns.filter((t) => t.report).slice(-3).map((t) => ({ psi_ids: aboutIds(t) }));
  try {
    await askStream(question, history, scenario, (ev) => {
      if (ev.type === "frame") turn.chips = ev.chips;
      else if (ev.type === "stage") turn.stages[ev.stage] = { status: ev.status, detail: ev.detail };
      else if (ev.type === "evidence") { turn.evidence = ev.sources; renderSources(); }
      else if (ev.type === "draft") turn.draft = ev.sentences;
      else if (ev.type === "report") turn.report = ev.report;
      renderAll();
      if (ev.type === "report") renderSources();
    }, controller.signal, chat.mode === "guided" ? { audience: "guided", ...(lastSlots() ? { context: lastSlots() } : {}) } : {});
    if (!turn.report && !turn.error) turn.error = "The answer ended before it was finished.";
  } catch (e) {
    turn.error = e.name === "AbortError" ? "Stopped." : e.message;
  } finally {
    chat.running = null;
    save(); renderAll(); renderSources();
    ui.input.focus();
  }
}

// ---------- the static demo (GitHub Pages) ----------
// There is no server and no SI model there, so the answers were generated once by the full app's own pipeline, with the model switched off,
// for both modes (see app/static_export.py). This page shows them with the same code that shows a live answer.
let demo = null;      // { cases: [{label, question}], answers: { guided: {key: {chips, report}}, expert: {...} } }

// A stored answer for the current mode. A follow-up is stored under "<parent question>||<question>".
function demoFor(question, parentQ) {
  const bucket = demo?.answers?.[chat.mode];
  if (!bucket) return null;
  return (parentQ && bucket[`${normQuestion(parentQ)}||${normQuestion(question)}`]) || bucket[normQuestion(question)] || null;
}

// Switching mode swaps each answer for the stored one in the other mode, as a live chat shows the same question in either mode.
function rehydrate() {
  for (const t of chat.turns) { const a = demoFor(t.q, t.parentQ); if (a) { t.report = a.report; t.chips = a.chips; } }
}

async function sendDemo(question, parent) {
  question = (question || "").trim();
  if (!question || chat.running) return;
  const before = parent || [...chat.turns].reverse().find((t) => t.report) || null;
  const turn = { id: chat.nextId++, q: question, parentQ: before?.q || null, chips: null, stages: {}, evidence: null, report: null, error: null };
  chat.turns.push(turn);
  chat.active = turn.id; chat.selected = null;
  chat.running = { turn, controller: new AbortController() };
  renderAll(); renderSources();
  await new Promise((done) => setTimeout(done, 350));              // a short pause, so the answer arrives the way a live one does
  const found = demoFor(question, turn.parentQ);
  if (found) { turn.chips = found.chips; turn.report = found.report; }
  else turn.error = "This is the demo, so only the use cases above have answers. To ask your own question, run the full app: the steps are at the bottom of this page.";
  chat.running = null;
  save(); renderAll(); renderSources();
}

const demoBanner = () => el("div", { class: "demo-banner", role: "note" }, el("strong", { text: "Demo Mode: SI Not Enabled" }),
  el("span", { class: "muted", text: "Answers are pre-generated by the full app, in Guided and in Expert. Steps to run it yourself are at the bottom." }));

function demoIntro() {
  return el("div", { class: "intro" }, el("h2", { text: "Ask the PSI combustion research" }),
    el("p", { class: "muted", text: "Choose a use case below to see the answer, then switch between Guided and Expert to see how the same answer is shown." }));
}

function casesPanel() {
  const cases = demo?.cases || [];
  return el("details", { class: "demo-cases", open: true }, el("summary", { text: `Use cases (${cases.length})` }),
    cases.length ? el("div", { class: "chips" }, ...cases.map((c) => el("button", { class: "chip", type: "button", title: c.question, text: c.label, onclick: () => send(c.question) })))
      : el("p", { class: "muted", text: "The demo answers could not be loaded." }));
}

// The steps to run the full app, at the foot of the page.
function runItYourself() {
  const cmd = (text) => el("pre", { class: "code" }, text);
  const readme = el("a", { class: "btn", href: README_RUN_URL, target: "_blank", rel: "noopener noreferrer", text: "Follow the README: Deploy with Docker" });
  return el("section", { class: "card static-note run-it", id: "run-it" },
    el("p", { class: "eyebrow", text: "Run it yourself" }),
    el("h2", { text: "Install and run the SI on your computer" }),
    el("p", { text: "SI Insights needs a Python server and a local SI model (IBM Granite 3.3 2B, run through Ollama), and a static web page can run neither. With the model on, you can ask your own questions, and the SI writes short answers that Nimbus checks." }),
    el("p", { text: "To use the SI, follow the README in the repository (it is the source of truth for the steps). In short:" }),
    el("ol", { class: "steps" },
      el("li", {}, "Install Docker and Ollama (ollama.com), then pull the SI model:", cmd("ollama pull granite3.3:2b")),
      el("li", {}, "Get the code:", cmd("git clone https://github.com/Zrokool/SpaceSweepers\ncd SpaceSweepers")),
      el("li", {}, "Build and run it with Docker:", cmd("docker build -t spacesweepers .\ndocker run --rm -p 8000:8000 -e 'SS_ALLOWED_HOSTS=[\"localhost\",\"127.0.0.1\",\"your.domain\"]' -e SS_OLLAMA_URL=http://host.docker.internal:11434 spacesweepers")),
      el("li", { text: "Open http://localhost:8000 and choose SI Insights. The Flame Sweeper's \"Explain these patterns (SI)\" button works there too." })),
    el("p", { class: "muted", text: "SS_OLLAMA_URL lets the container reach the Ollama on your computer; without it the dashboard works and the SI shows as offline. On Linux, also add --add-host=host.docker.internal:host-gateway and start Ollama with OLLAMA_HOST=0.0.0.0." }),
    el("p", {}, readme));
}

export async function render(root, state) {
  if (isStatic && !demo) { try { demo = await api("/api/insights/demo"); } catch { demo = null; } }
  restore();
  if (isStatic) rehydrate();
  ui = {};
  ui.log = el("div", { class: "chat-log", role: "log", "aria-live": "polite" });
  ui.sources = el("aside", { class: "chat-sources", "aria-label": "Sources" });
  ui.status = el("span", { class: "pill" });
  ui.input = el("textarea", { class: "chat-input", rows: 2, maxlength: MAX_QUESTION, "aria-label": "Your question", disabled: isStatic,
    placeholder: isStatic ? "Demo mode: pick a use case above. To ask your own question, run the full app (steps at the bottom)."
      : "Ask about the PSI data, e.g. “What did FLEX find about extinction?”" });
  ui.count = el("span", { class: "muted count", text: `0 / ${MAX_QUESTION}` });
  ui.send = el("button", { class: "btn-primary", type: "button", text: "Ask", onclick: () => send() });
  ui.stop = el("button", { class: "btn", type: "button", text: "Stop", hidden: true, onclick: () => chat.running?.controller.abort() });
  ui.starters = el("div", { class: "chips starters" });
  ui.scenario = scenarioForm();
  if (isStatic) ui.cases = casesPanel();
  ui.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  ui.input.addEventListener("input", () => { ui.count.textContent = `${ui.input.value.length} / ${MAX_QUESTION}`; });

  root.append(...[
    el("div", { class: "insights-head" }, el("div", {}, el("p", { class: "eyebrow", text: "SI Insights" }),
      el("h1", { text: "Ask the PSI combustion data" })), el("div", { class: "head-actions" }, modeSwitch(), !isStatic && ui.status,
      el("button", { class: "btn-ghost", type: "button", text: "New chat", onclick: () => { if (!chat.running) { chat.turns = []; chat.active = chat.selected = null; save(); renderAll(); renderSources(); } } }))),
    isStatic && demoBanner(),
    (ui.notice = el("div", { class: "notice", text: EXPERT_NOTICE })),
    (ui.modeHint = el("p", { class: "tiny mode-hint" }, "You are in Guided mode: a plain chat with the PSI evidence beside it. ", el("button", { class: "btn-ghost", type: "button", text: isStatic ? "Switch to Expert for tables and checks" : "Switch to Expert for tables, checks and the Scenario form", onclick: () => setMode("expert") }))),
    (ui.insights = el("div", { class: "insights" }, el("div", { class: "chat" }, ui.log,
      el("div", { class: "composer" }, ui.cases, ui.scenario, ui.starters, ui.input, el("div", { class: "composer-row" }, ui.count, el("span", { class: "grow" }), ui.stop, ui.send))), ui.sources)),
    isStatic && runItYourself()].filter(Boolean));
  applyMode();
  renderAll(); renderSources(); renderStatus();

  // A link like #/insights?q=What did FLEX find about extinction? asks that question when the page opens.
  const linked = (state.params.get("q") || "").slice(0, MAX_QUESTION).trim();
  if (linked && !chat.turns.some((x) => x.q === linked) && !chat.running) send(linked);

  // Starter questions, the SI status, and a warm-up so the first question isn't slow (a cold model can take minutes). The demo has none of these.
  if (isStatic) return;
  api("/api/insights/suggestions").then((s) => ui.starters.replaceChildren(...s.starters.slice(0, 3).map((q) =>
    el("button", { class: "chip", type: "button", text: q, onclick: () => send(q) })))).catch(() => {});
  api("/api/si/status").then((s) => { chat.status = s; renderStatus(); if (s.available && chat.warm === "idle") warm(); }).catch(() => { chat.status = { available: false, message: "Couldn't reach the server." }; renderStatus(); });
}

async function warm() {
  chat.warm = "loading"; renderStatus();
  try { const r = await api("/api/insights/warm", { method: "POST" }); chat.warm = r.ready ? "ready" : "failed"; if (!r.ready) chat.status = { ...chat.status, available: false, message: r.message }; }
  catch { chat.warm = "failed"; }
  renderStatus();
}

// ---------- Guided mode: a plain chat on the left, the PSI details behind each answer on the right ----------
// Expert mode (everything above) is untouched. Guided shows the same report data, composed more simply.
const GUIDED_STARTERS = [
  "What is the lowest oxygen concentration at which methanol droplets burned in FLEX?",
  "How does carbon dioxide compare with helium as a suppressant in FLEX?",
  "What is a cool flame and why does it matter for spacecraft fire safety?",
];

function guidedIntro() {
  if (isStatic) return demoIntro();
  return el("div", { class: "intro" }, el("h2", { text: "Ask the PSI combustion research" }),
    el("p", { class: "muted", text: "Answers come only from NASA's PSI data. The evidence behind each answer appears on the right." }),
    el("div", { class: "examples" }, ...GUIDED_STARTERS.map((q) => el("button", { class: "example", type: "button", onclick: () => send(q) }, el("span", { text: q })))));
}

function guidedTurn(turn) {
  const running = chat.running && chat.running.turn === turn;
  const ai = el("div", { class: `msg ai${chat.active === turn.id ? " active" : ""}` },
    (running || !turn.report) && !turn.error && el("p", { class: "status-line", role: "status", text: "Thinking…" }),
    turn.error && el("div", { class: "note", text: turn.error }),
    turn.report && guidedAnswer(turn),
    turn.report && el("button", { class: "btn-ghost show-sources", type: "button", text: "Show the PSI details",
      onclick: () => { chat.active = turn.id; chat.selected = null; renderSources(); renderAll(false); } }));
  return [el("div", { class: "msg user" }, el("p", { text: turn.q })), ai];
}

function guidedAnswer(turn) {
  const r = turn.report;
  const kids = r.notes.filter((n) => !/^Answered (directly|earlier)/.test(n)).map((n) => el("div", { class: "note", text: n }));
  if (r.analysis?.context_note) kids.push(el("p", { class: "tiny", text: r.analysis.context_note }));
  if (["si", "no_answer", "computed"].includes(r.mode)) {
    kids.push(...r.answer.map((x) => (x.note
      ? el("p", { class: "sentence", text: x.text })
      : el("p", { class: "sentence" }, x.text, " ", ...citeButtons(turn, x.cites)))));
  }
  if (r.mode === "sources_only") kids.push(el("p", { class: "muted", text: "SI is not available right now. The PSI details on the right show what was found for your question." }));
  const next = isStatic ? r.followups.filter((f) => demoFor(f.question, turn.q)) : r.followups;
  if (next.length) {
    kids.push(el("div", { class: "chips followups" }, el("span", { class: "muted", text: "You could ask:" }),
      ...next.slice(0, 3).map((f) => el("button", { class: "chip", type: "button", text: f.label, onclick: () => send(f.question, null, turn) }))));
  }
  return kids;
}

function guidedTests(a) {
  const t = a.table;
  return t && el("div", {}, el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...t.columns.map((c) => el("th", { text: c })))),
    el("tbody", {}, ...t.rows.map((row, i) => el("tr", { class: t.psi[i] ? "clickable" : null, onclick: t.psi[i] ? () => openDetail(t.psi[i]) : null }, ...row.map((cell) => el("td", { text: cell }))))))),
    t.total > t.shown && el("p", { class: "tiny", text: `Showing ${t.shown} of ${t.total} tests.` }),
    a.links?.[0] && el("button", { class: "btn-ghost", type: "button", text: `${a.links[0].label} →`,
      onclick: () => navigate("sweeper", { ...(a.links[0].family ? { family: a.links[0].family } : {}), ...(a.links[0].fuel ? { fuel: a.links[0].fuel } : {}), ...(a.links[0].diluent ? { diluent: a.links[0].diluent } : {}) }) }));
}

function guidedSource(s) {
  const detail = el("div", { class: "src-detail", hidden: true });
  const more = el("button", { class: "btn-ghost", type: "button", text: "Show surrounding text", hidden: s.computed || isStatic, onclick: async () => {
    if (!detail.hidden) { detail.hidden = true; more.textContent = "Show surrounding text"; return; }
    more.textContent = "Loading…";
    try {
      const p = await api(`/api/insights/passage/${encodeURIComponent(s.id)}`);
      detail.replaceChildren(el("blockquote", { text: p.text.slice(0, 1500) }));
      detail.hidden = false; more.textContent = "Hide surrounding text";
    } catch (e) { detail.replaceChildren(el("p", { class: "muted", text: e.message })); detail.hidden = false; more.textContent = "Show surrounding text"; }
  } });
  return el("div", { class: `src${chat.selected === s.n ? " selected" : ""}`, id: `src-${s.n}` },
    el("div", { class: "src-head" }, el("span", { class: "src-n", text: String(s.n) }), el("strong", { text: s.computed ? "PSI test data" : s.label })),
    el("div", { class: "src-links" }, s.psi && el("a", { href: "#", text: "Open investigation", onclick: (e) => { e.preventDefault(); openDetail(s.psi); } }),
      s.doi && el("a", { href: `https://doi.org/${s.doi}`, target: "_blank", rel: "noopener", text: `DOI ${s.doi}` }),
      s.url && el("a", { href: s.url, target: "_blank", rel: "noopener", text: "PSI page" }), more), detail);
}

function renderGuidedDetails() {
  const turn = chat.turns.find((t) => t.id === chat.active);
  const r = turn?.report, a = r?.analysis;
  const words = a?.quote ? [a.quote, ...(a.quote2 ? [{ text: a.quote2.text, where: a.quote2.where, label: a.quote2.label }] : [])]
    : (r?.sources || []).filter((s) => !s.computed).slice(0, 3).map((s) => ({ text: excerpt(s.text), where: s.label, n: s.n }));
  const keep = a?.caveats?.length ? a.caveats : (r?.not_covered || []);
  const section = (title, ...kids) => { const k = kids.filter(Boolean); return k.length ? el("section", { class: "gd-section" }, el("p", { class: "eyebrow", text: title }), ...k) : null; };
  ui.sources.replaceChildren(...[
    el("h3", { text: "PSI details" }),
    !r && el("p", { class: "muted", text: turn ? "Looking up PSI data…" : "Ask a question. The PSI evidence behind the answer appears here: PSI's own words, the tests, and the sources." }),
    r && section("In PSI's words", ...words.map((q) => el("blockquote", { class: "quote" }, q.label && el("p", { class: "eyebrow", text: q.label }), el("p", { text: q.text }), el("footer", { text: q.where })))),
    r && a && section("The tests", guidedTests(a)),
    r && section("Keep in mind", el("ul", { class: "facts" }, ...keep.map((c) => el("li", { text: c })))),
    r && section("Sources", ...r.sources.map(guidedSource)),
  ].filter(Boolean));
  const picked = chat.selected && ui.sources.querySelector(`#src-${chat.selected}`);
  if (picked) picked.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// The mode switch: Guided (plain chat, details on the right) or Expert (the full screen).
function setMode(mode) {
  chat.mode = mode;
  try { localStorage.setItem(MODE_KEY, mode); } catch { /* the choice just is not remembered */ }
  if (isStatic) rehydrate();
  applyMode();
  renderAll(false); renderSources(); renderStatus();
}

function applyMode() {
  const guided = chat.mode === "guided";
  if (ui.scenario) ui.scenario.hidden = guided || isStatic;           // the demo has no scenario form: its answers are the use cases
  if (ui.starters) ui.starters.hidden = guided;
  if (ui.modeHint) ui.modeHint.hidden = !guided;
  if (ui.notice) ui.notice.textContent = guided ? "Answers come only from NASA PSI data. Research context only: this does not replace spacecraft emergency procedures." : EXPERT_NOTICE;
  for (const b of ui.modeButtons || []) b.setAttribute("aria-checked", String(b.dataset.mode === chat.mode));
  if (ui.insights) ui.insights.dataset.mode = chat.mode;
}

function modeSwitch() {
  ui.modeButtons = [["guided", "Guided"], ["expert", "Expert"]].map(([key, label]) => el("button", { type: "button", role: "radio", "aria-checked": String(chat.mode === key),
    dataset: { mode: key }, text: label, onclick: () => setMode(key) }));
  return el("div", { class: "segmented mode-switch", role: "radiogroup", "aria-label": "Chat mode" }, ...ui.modeButtons);
}
