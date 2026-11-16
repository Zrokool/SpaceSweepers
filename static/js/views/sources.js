// PSI Source: where the data comes from, how far it goes, and how the numbers are kept honest.
// Told in five steps (source, what PSI holds, what could be charted, how it is kept honest, how to cite it). The table-by-table detail
// is kept, in a collapsible audit at the end. Every number comes from the snapshot, so this page can never go out of date.
import { el, api, title, fmt } from "../ui.js";
import { openDetail } from "../app.js";

const yesNo = (v) => (v ? "yes" : "no");
const plural = (n, w) => `${n.toLocaleString("en-US")} ${w}${n === 1 ? "" : "s"}`;
const who = (r) => (r.name === r.psi ? r.psi : `${r.name} · ${r.psi}`);
const sizeText = (mb) => (mb >= 1e6 ? `${(mb / 1e6).toFixed(1)} TB` : mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`);
const head = (cols) => el("thead", {}, el("tr", {}, ...cols.map((t) => el("th", { text: t }))));
const step = (n, heading, ...children) => el("div", { class: "card" }, el("h2", { text: `${n}. ${heading}` }), ...children);
const tile = (value, label, sub) => el("div", { class: "tile" }, el("div", { class: "value", text: value }), el("div", { class: "label", text: label }), el("p", { class: "tiny", text: sub }));

// 2. What PSI holds
function levels() {
  return el("ol", { class: "facts" },
    el("li", {}, el("strong", { text: "Summary table. " }), "A few lines listing what was varied, often as ranges or lists (for example \"0.17; 0.21; 0.25; 0.3\")."),
    el("li", {}, el("strong", { text: "Per-test table. " }), "One row per test. Only these can be placed on the charts, and only when oxygen and pressure are both recorded."),
    el("li", {}, el("strong", { text: "Analyzed Data. " }), "Processed results (spreadsheets, text, PDFs). Often small enough to read."),
    el("li", {}, el("strong", { text: "Raw Data. " }), "Instrument and camera output. Terabytes for some investigations, so it is listed here but never downloaded."));
}

// 3. What could be charted
function funnel(meta, tbl, withTables) {
  const c = meta.counts, other = c.investigations - c.combustion;
  const notUsed = (tbl.by_status["not mappable"] || 0) + (tbl.by_status.superseded || 0);
  return [
    el("ol", { class: "facts funnel" },
      el("li", { text: `${c.investigations} investigations are in the snapshot. ${c.combustion} are combustion science${other ? `; the other ${other} are kept and labelled as not combustion research` : ""}.` }),
      el("li", { text: `${withTables} of them have at least one test table downloaded (${tbl.total} tables in all).` }),
      el("li", { text: `${tbl.by_status.parsed || 0} of those tables, from ${c.investigations_with_tests} investigations, could be turned into comparable tests: ${fmt(c.tests)} tests. These feed Rank, Envelope and the Flame Sweeper.` }),
      el("li", { text: `The other ${notUsed} tables cannot be placed on the oxygen and pressure charts. The reasons:` },
        el("ul", {}, ...Object.entries(tbl.by_reason).map(([code, n]) => el("li", { text: `${n}: ${tbl.reason_text[code] || code}` }))))),
    el("p", { class: "muted", text: "An investigation without charted tests still appears in Rank, Correlation, Fire Safety and SI Insights through its record, documents and publications. A gap on a chart means \"not in the data we hold\", not \"never tested\"." }),
    el("h3", { text: "Why the numbers are hard to use" }),
    el("ul", { class: "facts" },
      el("li", { text: "A value can be a range or an estimate: \"21.5 - 21.7\" and \"~ 21.5\" (SAFFIRE-I). We keep the text and flag it as approximate or a range." }),
      el("li", { text: "A number can be missing or a word: burn time \"Insignificant\" (SAFFIRE-II) means the flame did not sustain, but it is not a number." }),
      el("li", { text: "The same quantity is written in different units and formats: oxygen as a mole fraction in one table and as a percent in another, pressure in atm, psi or mmHg." }),
      el("li", { text: "A header can disagree with its values: the BASS as-run header says \"% by volume\" while the values are mole fractions, so that mapping is reviewed by hand with a document quote." }),
      el("li", { text: "A missing column cannot be guessed: BASS-II records oxygen but no pressure, so its tests are counted but cannot be placed. We never assume a pressure." })),
  ];
}

// The audit: the table-by-table detail behind steps 2 and 3.
function audit(tbl, cx) {
  return el("details", { class: "card audit" },
    el("summary", {}, el("strong", { text: "Table-by-table audit" }), " (for checking the numbers above)"),
    el("h3", { text: "Test-table coverage" }),
    el("p", { class: "muted", text: `${tbl.total} downloaded test tables: ${Object.entries(tbl.by_status).map(([k, n]) => `${n} ${k}`).join(", ")}. A mapping only applies to the exact table it was made for.` }),
    el("h3", { text: "What each test table can support" }),
    el("p", { class: "muted", text: "Every downloaded test table is placed in an experiment family from its own column headers, and in a readiness tier from what could be mapped. Different families are never pooled." }),
    el("ul", { class: "facts" }, ...Object.entries(tbl.tiers).map(([k, v]) => el("li", { text: `Tier ${k} (${tbl.by_tier[k] || 0}): ${v}` }))),
    el("div", { class: "table-wrap" }, el("table", {},
      head(["Investigation", "Table", "Family", "Tier", "Why", "Tests"]),
      el("tbody", {}, ...tbl.readiness.map((r) => el("tr", { class: "clickable", onclick: () => openDetail(r.psi) },
        el("td", { text: `${r.name} · ${r.psi}` }), el("td", { class: "mono", text: r.file.replace(/^PSI-\d+_(Experimental table_)?/, "").replace(/\.csv$/, "") }),
        el("td", { text: r.family }), el("td", { text: r.tier }), el("td", { text: r.why }), el("td", { text: String(r.tests) })))))),
    el("h3", { text: "Tier B tables: results recorded, but can they be charted?" }),
    el("p", { class: "muted", text: "Tier B tables record measured results such as burn time or weight loss. The columns show why most still cannot sit on the oxygen and pressure charts." }),
    el("div", { class: "table-wrap" }, el("table", {}, head(["Investigation", "Table", "Rows", "Columns it has", "Oxygen", "Pressure", "On the charts"]),
      el("tbody", {}, ...cx.tier_b.map((r) => el("tr", { class: "clickable", onclick: () => openDetail(r.psi) },
        el("td", { text: who(r) }), el("td", { class: "mono", text: r.file.replace(/^PSI-\d+_(Experimental table_|Workbook table_)?/, "").replace(/\.csv$/, "") }),
        el("td", { class: "num", text: String(r.rows) }), el("td", { text: r.columns.slice(0, 5).join(", ") }),
        el("td", { text: yesNo(r.has_oxygen) }), el("td", { text: yesNo(r.has_pressure) }),
        el("td", { text: r.on_charts ? `${r.on_charts} tests` : r.why_not })))))),
    el("p", { class: "tiny", text: "Rows counts every non-blank line in PSI's file, including notes and flow-visualisation entries, so it can exceed the number of tests." }),
    el("h3", { text: "What PSI lists behind each investigation" }),
    el("p", { class: "muted", text: `Analyzed Data up to ${cx.limits.analyzed_mb} MB is small enough to download and review. Raw Data is never downloaded.` }),
    el("div", { class: "table-wrap" }, el("table", {}, head(["Investigation", "Table rows", "Analyzed Data", "Raw Data"]),
      el("tbody", {}, ...cx.layers.map((r) => el("tr", { class: "clickable", onclick: () => openDetail(r.psi) },
        el("td", { text: who(r) }), el("td", { class: "num", text: String(r.table_rows) }),
        el("td", { text: r.analyzed ? `${plural(r.analyzed.files, "file")}, ${sizeText(r.analyzed.mb)} (${r.analyzed.types.join(", ") || "n/a"}) · ${r.analyzed.feasible ? "small enough to read" : "too large for now"}${r.stored ? ` · ${r.stored} stored in this snapshot` : ""}` : "none listed" }),
        el("td", { text: r.raw ? `${plural(r.raw.files, "file")}, ${sizeText(r.raw.mb)} · ${r.raw.feasible ? "small" : "not feasible"}` : "none listed" })))))));
}

export async function render(root, state) {
  const [sources, quality, si, cx, list] = await Promise.all([api("/api/sources"), api("/api/quality"), api("/api/si/status"), api("/api/data-complexity"), api("/api/investigations")]);
  const s = state.meta.snapshot, tbl = state.meta.tables, c = state.meta.counts;
  const publications = list.investigations.reduce((n, i) => n + i.publications, 0);
  const withTables = list.investigations.filter((i) => i.table_rows > 0).length;
  const row = (i) => el("tr", { class: "clickable", onclick: () => openDetail(i.id) },
    el("td", { text: title(i) }),
    el("td", { text: i.record_source === "search listing" ? "search listing only" : `full record (${i.record_source})` }),
    el("td", {}, i.doi ? el("a", { href: `https://doi.org/${i.doi}`, target: "_blank", rel: "noopener", text: i.doi, onclick: (e) => e.stopPropagation() }) : (i.record_source === "search listing" ? "not in snapshot" : "none recorded")),
    el("td", { text: i.license || (i.record_source === "search listing" ? "not in snapshot" : "none recorded by PSI") }),
    el("td", { text: i.tables_status.split(":")[0] }),
    el("td", { text: `${(i.method.labels || []).join(" + ") || "Not classified"}${i.method.status === "verified" ? " (checked)" : i.method.status === "team-confirmed" ? " (team)" : ""}` }));
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "PSI Source" }), el("h1", { text: "Where the data comes from, and how far it goes" }),
      el("p", { class: "lede", text: "Everything on this site comes from one place: NASA's Physical Sciences Informatics (PSI) repository. This page shows what we took from it, how much of it we could chart, and how the numbers are kept honest." })),
    el("div", { class: "grid cols-4" },
      tile(String(c.investigations), "investigations", "PSI's search for \"combustion\""),
      tile(fmt(c.tests), "comparable tests", `from ${c.investigations_with_tests} investigations with usable test tables`),
      tile(fmt(publications), "publications listed", "in the PSI records"),
      tile(fmt(s.documents.read), "documents read", `${s.documents.pages.toLocaleString("en-US")} pages of reports and science documents`)),
    step(1, "The source",
      el("ul", { class: "facts" },
        el("li", {}, "PSI is NASA's public repository of physical-science experiments. We use its search for \"combustion\": ", el("a", { href: s.source, target: "_blank", rel: "noopener", text: "PSI Data Repository" }), ` (${quality.investigations.length} investigations).`),
        el("li", { text: `This is a stored copy, taken ${s.fetched_at.replace("T", " ").replace("Z", " UTC")}. It is refreshed on demand with python -m app.psi.sync, and every calculation runs on it each time you use the app.` }),
        el("li", { text: `Records: ${Object.entries(s.record_sources).map(([k, n]) => `${n} ${k === "live" ? "full records fetched from PSI's record service" : `from ${k}`}`).join(", ")}. Every investigation is cited by its DOI (see step 5).` }),
        s.record_sources["search listing"] > 0 && el("li", { text: "PSI's record service was returning errors for some investigations when this snapshot was taken. Those marked \"search listing only\" have their text but no DOI, license or test tables yet. Run the sync again when PSI recovers: python -m app.psi.sync" }),
        el("li", { text: `Documents: ${s.documents.read} Reports, Science Documents and ReadMe files were read; ${s.documents.not_read} were listed but not read, each with its reason in the investigation's detail panel.` }),
        el("li", { text: "Contact details in PSI records (emails, phone numbers) are removed before anything is saved. Raw data and video are never downloaded." }))),
    step(2, "What PSI holds for each investigation",
      el("p", { class: "muted", text: "PSI holds each investigation's data at four levels. A chart of oxygen against pressure needs one row per test with both values. Many tables are only a summary of what was varied, and the measured data behind them is far bigger than a dashboard can carry." }),
      levels()),
    step(3, "What we could chart", ...funnel(state.meta, tbl, withTables)),
    step(4, "How the numbers are kept honest",
      el("ul", { class: "facts" },
        el("li", { text: "Every value keeps its raw text, parsed number, unit, quality flag, source file and row. Nothing is cleaned silently." }),
        el("li", { text: "Unknown stays unknown. A missing value is shown as unknown, never as zero or a guess." }),
        el("li", { text: "Different kinds of evidence are never added together: table tests, outcomes read from documents, the PSI-117 simulation list and analysis figures." })),
      el("h3", { text: "How SI (Super Intelligence) is used" }),
      el("ul", { class: "facts" },
        el("li", { text: "In the app: a local SI model (IBM Granite, run through Ollama on this machine) only ever points or writes short text, and code checks everything it does. It labels each investigation experimental or a simulation by pointing at one sentence (a failed check is shown as \"method not confirmed\"), proposes table-column mappings, points at the sentences that show fire-safety pillars and BASS burn outcomes, and explains Flame Sweeper patterns." }),
        el("li", { text: "In SI Insights the Investigator chooses which PSI lookup tools to call, and the Analyst writes short answers that cite numbered PSI evidence. Nimbus, fixed rules in code, checks every sentence: any sentence with a number, name, method claim or quotation its sources don't support, or that says a fire is occurring or gives advice, is removed and shown." }),
        el("li", { text: "SI never produces a number. Scores, counts, ranges and unit conversions are computed by code from PSI data." }),
        el("li", { text: `SI status: ${si.available ? `model ${si.model} is ready` : si.message}` }),
        el("li", { text: "In development: the code, tests and documentation were written with Claude Code (Anthropic), directed and reviewed by the team." }))),
    step(5, "Cite and check",
      el("h3", { text: "Each investigation, with its DOI and license" }),
      el("div", { class: "table-wrap" }, el("table", {},
        head(["Investigation", "Record", "DOI", "License", "Test tables", "Method"]),
        el("tbody", {}, ...quality.investigations.map(row)))),
      el("h3", { text: "Approved sources" }),
      el("ul", { class: "plain" }, ...sources.sources.map((src) => el("li", {},
        el("a", { href: src.url, target: "_blank", rel: "noopener", text: src.title }),
        el("span", { class: "badge plain", text: src.role === "data" ? "data" : "background reading" }), ` ${src.use}`))),
      el("p", { class: "muted", text: "NASA does not endorse any non-U.S. Government entity and is not responsible for information on non-U.S. Government websites. SpaceSweepers is not affiliated with or endorsed by NASA." })),
    audit(tbl, cx),
  );
}
