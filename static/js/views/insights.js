// SI Insights: ask questions about all the PSI data. SI writes, Nimbus checks every sentence, sources are shown.
// All text is set with textContent (through el()), so PSI text and model text can never become HTML.
import { el, api, fmt, safeHref, METHOD_LABEL } from "../ui.js";
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

// The conversation outlives tab switches (module state) and page reloads (sessionStorage).
const chat = { turns: [], active: null, selected: null, running: null, status: null, warm: "idle", nextId: 1 };

function save() {
  try {
    const done = chat.turns.filter((t) => t.report).map((t) => ({ id: t.id, q: t.q, chips: t.chips, report: t.report }));
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
async function askStream(question, history, onEvent, signal) {
  const resp = await fetch("/api/insights/ask", { method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }) });
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

const PROVENANCE = { computed: "Computed by code from PSI data", si: "SI reading, verified against its sources" };

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
  if (r.table) kids.push(tableBlock(r.table));
  else if (r.facts) kids.push(tableBlock(r.facts));
  if (r.list) kids.push(listBlock(r.list));
  const links = linkRow(r);
  if (links) kids.push(links);
  kids.push(el("button", { class: "btn-ghost show-sources", type: "button", text: `Sources and verification (${r.sources.length}) →`,
    onclick: () => { chat.active = turn.id; chat.selected = null; renderSources(); renderAll(false); document.querySelector(".chat-sources")?.scrollIntoView({ block: "start", behavior: "smooth" }); } }));
  if (r.followups.length) {
    kids.push(el("div", { class: "chips followups" }, el("span", { class: "muted", text: "Try next:" }),
      ...r.followups.map((f) => el("button", { class: "chip", type: "button", text: f.label, onclick: () => send(f.question) }))));
  }
  return kids;
}

function turnView(turn) {
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
  ui.send.disabled = !!chat.running;
  ui.stop.hidden = !chat.running;
  ui.exportBtn.disabled = !chat.turns.some((t) => t.report);
}

const EXAMPLES = [
  ["Find research by topic", "Which investigations study smoke detection?"],
  ["Compare two investigations", "Compare BASS and BASS-II"],
  ["Where does extinction happen?", "What did FLEX find about extinction?"],
];
function introView() {
  return el("div", { class: "intro" }, el("h2", { text: "Ask the PSI combustion research" }),
    el("p", { class: "muted", text: "Short answers with PSI's own words and sources. Every sentence is checked by code against the data." }),
    el("div", { class: "examples" }, ...EXAMPLES.map(([title, q]) => el("button", { class: "example", type: "button", onclick: () => send(q) },
      el("strong", { text: title }), el("span", { class: "muted", text: q })))));
}

function renderStatus() {
  if (!ui.status) return;
  const s = chat.status;
  const text = !s ? "checking SI…" : !s.available ? "SI unavailable" : chat.warm === "loading" ? `${s.model} · loading model…` : `${s.model} · ready`;
  ui.status.className = `pill ${!s ? "" : !s.available ? "off" : chat.warm === "loading" ? "wait" : "ok"}`;
  ui.status.textContent = `${!s ? "…" : !s.available ? "○" : chat.warm === "loading" ? "◔" : "●"} ${text}`;
  ui.status.title = s && !s.available ? s.message : "";
}

// ---------- sources panel ----------
function sourceCard(s, turn) {
  const card = el("div", { class: `src${chat.selected === s.n && chat.active === turn?.id ? " selected" : ""}`, id: `src-${s.n}` });
  const detail = el("div", { class: "src-detail", hidden: true });
  const more = el("button", { class: "btn-ghost", type: "button", text: "Show surrounding text", hidden: s.computed,
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
async function send(question) {
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
    await askStream(question, history, (ev) => {
      if (ev.type === "frame") turn.chips = ev.chips;
      else if (ev.type === "stage") turn.stages[ev.stage] = { status: ev.status, detail: ev.detail };
      else if (ev.type === "evidence") { turn.evidence = ev.sources; renderSources(); }
      else if (ev.type === "draft") turn.draft = ev.sentences;
      else if (ev.type === "report") turn.report = ev.report;
      renderAll();
      if (ev.type === "report") renderSources();
    }, controller.signal);
    if (!turn.report && !turn.error) turn.error = "The answer ended before it was finished.";
  } catch (e) {
    turn.error = e.name === "AbortError" ? "Stopped." : e.message;
  } finally {
    chat.running = null;
    save(); renderAll(); renderSources();
    ui.input.focus();
  }
}

// The exported file is opened in other programs: neutralise anything that would become a link, image or markup there.
const md = (t) => String(t ?? "").replace(/[\\`*_{}\[\]<>()#+!|~]/g, (c) => `\\${c}`).replace(/\s+/g, " ").trim();

function toMarkdown() {
  const lines = ["# SI Insights chat", "", `Exported from SpaceSweepers on ${new Date().toISOString().slice(0, 10)}. Answers were written by SI and checked by Nimbus against PSI data. NASA does not endorse SpaceSweepers.`, ""];
  for (const t of chat.turns.filter((x) => x.report)) {
    const r = t.report;
    lines.push(`## ${md(t.q)}`, "");
    for (const s of r.answer) lines.push(s.note ? `_${md(s.text)}_` : `${md(s.text)} ${s.cites.map((n) => `[${n}]`).join("")}`, "");
    if (r.sources.length) { lines.push("**Sources**", ""); for (const s of r.sources) lines.push(`${s.n}. ${md(s.label)} (${md(s.kind)})${s.doi ? ` DOI ${md(s.doi)}` : ""}${s.url && safeHref(s.url) ? ` <${safeHref(s.url)}>` : ""}`); lines.push(""); }
    if (r.removed.length) { lines.push("**Removed by Nimbus**", ""); for (const x of r.removed) lines.push(`- ~~${md(x.text)}~~ (${x.rules[0]}: ${md(x.reason)})`); lines.push(""); }
    if (r.not_covered.length) { lines.push("**What the data doesn't cover**", ""); for (const g of r.not_covered) lines.push(`- ${md(g)}`); lines.push(""); }
  }
  return lines.join("\n");
}

function download() {
  const url = URL.createObjectURL(new Blob([toMarkdown()], { type: "text/markdown" }));
  const a = el("a", { href: url, download: "si-insights-chat.md" });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function render(root, state) {
  restore();
  ui = {};
  ui.log = el("div", { class: "chat-log", role: "log", "aria-live": "polite" });
  ui.sources = el("aside", { class: "chat-sources", "aria-label": "Sources" });
  ui.status = el("span", { class: "pill" });
  ui.input = el("textarea", { class: "chat-input", rows: 2, maxlength: MAX_QUESTION, "aria-label": "Your question",
    placeholder: "Ask about the PSI data, e.g. “What did FLEX find about extinction?”" });
  ui.count = el("span", { class: "muted count", text: `0 / ${MAX_QUESTION}` });
  ui.send = el("button", { class: "btn-primary", type: "button", text: "Ask", onclick: () => send() });
  ui.stop = el("button", { class: "btn", type: "button", text: "Stop", hidden: true, onclick: () => chat.running?.controller.abort() });
  ui.exportBtn = el("button", { class: "btn-ghost", type: "button", text: "Export chat", onclick: download });
  ui.starters = el("div", { class: "chips starters" });
  ui.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  ui.input.addEventListener("input", () => { ui.count.textContent = `${ui.input.value.length} / ${MAX_QUESTION}`; });

  root.append(
    el("div", { class: "insights-head" }, el("div", {}, el("p", { class: "eyebrow", text: "SI Insights" }),
      el("h1", { text: "Ask the PSI combustion data" })), el("div", { class: "head-actions" }, ui.status,
      el("button", { class: "btn-ghost", type: "button", text: "New chat", onclick: () => { if (!chat.running) { chat.turns = []; chat.active = chat.selected = null; save(); renderAll(); renderSources(); } } }), ui.exportBtn)),
    el("div", { class: "notice", text: "Research context only. SI Insights never declares a fire or an emergency and does not replace spacecraft fire-detection and emergency procedures." }),
    el("div", { class: "insights" }, el("div", { class: "chat" }, ui.log,
      el("div", { class: "composer" }, ui.starters, ui.input, el("div", { class: "composer-row" }, ui.count, el("span", { class: "grow" }), ui.stop, ui.send))), ui.sources));
  renderAll(); renderSources(); renderStatus();

  // A link like #/insights?q=What did FLEX find about extinction? asks that question when the page opens.
  const linked = (state.params.get("q") || "").slice(0, MAX_QUESTION).trim();
  if (linked && !chat.turns.some((x) => x.q === linked) && !chat.running) send(linked);

  // Starter questions, the SI status, and a warm-up so the first question isn't slow (a cold model can take minutes).
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
