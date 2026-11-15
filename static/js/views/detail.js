// The investigation detail drawer: everything the snapshot holds about one investigation, with its evidence.
import { figureSection } from "./figures.js";
import { el, api, withTip, typeBadge, methodBadge, fmt, METHOD_LABEL, PILLAR_LABEL, ROLE_LABEL, fileHref } from "../ui.js";

const VARIABLE_LABEL = { o2_fraction: "oxygen fraction", pressure_psi: "pressure", burn_time_s: "burn time", fuel: "fuel",
  flame_temp_k: "flame temperature", fuel_flow_mg_s: "fuel flow", outcome: "outcome", ending: "how the flame ended" };

function section(title, ...children) {
  const kids = children.flat().filter(Boolean);
  return kids.length ? el("section", {}, el("p", { class: "eyebrow", text: title }), ...kids) : null;
}
const PILLAR_STATUS = { evidence: "Evidence", "data only": "Measured results only", none: "No evidence", "not assessed": "Not assessed", "not applicable": "Not applicable", stale: "Data refresh needed" };
function tags(items, label) {
  return items.map((i) => withTip(el("span", { class: "tag", text: label(i) }), `Found in the record's ${i.field.replace("_text", "")}`, [`"${i.quote}"`]));
}
function range(r, digits, unit) {
  return r ? (r[0] === r[1] ? `${fmt(r[0], digits)} ${unit}` : `${fmt(r[0], digits)} – ${fmt(r[1], digits)} ${unit}`) : "–";
}
function mb(bytes) {
  return bytes >= 1e9 ? `${fmt(bytes / 1e9, 1)} GB` : bytes >= 1e6 ? `${fmt(bytes / 1e6, 1)} MB` : `${fmt(bytes / 1e3, 0)} KB`;
}
// A long list shown as its first few items, with a button for the rest.
function shortList(items, render, first = 6) {
  if (!items.length) return null;
  const ul = el("ul", { class: "facts" }, ...items.slice(0, first).map(render));
  if (items.length <= first) return ul;
  const more = el("button", { class: "btn-ghost", type: "button", text: `Show all ${items.length}`,
    onclick: () => { ul.append(...items.slice(first).map(render)); more.remove(); } });
  return [ul, more];
}
function prose(text) {
  if (!text) return null;
  const p = el("p", { class: "prose clamp", text });
  const more = el("button", { class: "btn-ghost", type: "button", text: "Show all",
    onclick: () => { const open = p.classList.toggle("clamp"); more.textContent = open ? "Show all" : "Show less"; } });
  return [p, text.length > 500 && more];
}

export async function openDetail(id) {
  const drawer = document.getElementById("drawer"), body = document.getElementById("drawer-body");
  body.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
  drawer.hidden = false;
  let inv;
  try { inv = await api(`/api/investigations/${encodeURIComponent(id)}`); }
  catch (error) { body.replaceChildren(el("div", { class: "note", text: error.message })); return; }
  const a = inv.attributes, s = inv.stats, m = inv.method;
  const link = (pid) => el("a", { href: "#", text: `${inv.names[pid] || pid} (${pid})`, onclick: (e) => { e.preventDefault(); openDetail(pid); } });
  const list = (ids) => ids.flatMap((pid, n) => [n ? ", " : "", link(pid)]);
  const methodOk = m.status === "verified" || m.status === "team-confirmed";

  body.replaceChildren(...[
    el("p", { class: "eyebrow", text: `${inv.id}${inv.acronym ? " · " + inv.acronym : ""}` }),
    el("h2", { text: inv.title }),
    el("div", { class: "badges" }, typeBadge(inv), methodBadge(inv),
      !inv.is_combustion && el("span", { class: "badge offtopic", text: "Not combustion research" })),

    !inv.is_combustion && el("div", { class: "note" }, el("strong", { text: `${inv.research_area}. ` }),
      `This investigation is in the PSI search results because it ${inv.match_reason}. It isn't combustion research, so it ranks low.`),
    !inv.record_complete && el("div", { class: "note" }, el("strong", { text: "Partial record. " }),
      "PSI's full record wasn't available when the snapshot was taken, so the DOI, license, publications and test tables are missing here. The text below comes from PSI's search listing."),

    section("How it worked",
      el("p", {}, el("strong", { text: methodOk ? (m.labels || []).join(" + ") : "Not classified" }),
        methodOk ? (m.status === "team-confirmed" ? " — confirmed by the team." : ` — SI (${m.model || "local model"}) pointed at the sentences; rules checked them.`) : ""),
      ...(methodOk ? (m.labels || []).flatMap((label) => {
        const part = m[label.toLowerCase()] || {};
        return [el("p", { class: "muted", text: `${label}${part.field ? ` · from the ${part.field}` : ""}` }),
                part.quote ? el("blockquote", { text: part.quote }) : el("p", { class: "muted", text: part.basis || "" })];
      }) : []),
      !methodOk && el("p", { class: "muted", text: m.reason || "Not assessed yet." }),
      ...((m.review || []).map((r) => el("p", { class: "note", text: `Needs a person to decide. ${r}` }))),
      inv.uses_data_from.length > 0 && el("p", {}, "Uses flight data from ", ...list(inv.uses_data_from), "."),
      inv.data_used_by.length > 0 && el("p", {}, "Its flight data is used by ", ...list(inv.data_used_by), ".")),

    section("At a glance", el("dl", {},
      el("dt", { text: "Type" }), el("dd", { text: `${inv.project_type} investigation` }),
      el("dt", { text: "Platform" }), el("dd", { text: inv.platform || "–" }),
      el("dt", { text: "Dates" }), el("dd", { text: [inv.start_date, inv.end_date].filter(Boolean).join(" to ") || "–" }),
      el("dt", { text: "PSI topic" }), el("dd", { text: inv.sub_area || "–" }),
      el("dt", { text: "Related" }), el("dd", {}, ...(inv.related.length ? list(inv.related.filter((r) => inv.names[r])) : ["–"])),
      el("dt", { text: "Listed as related by" }), el("dd", {}, ...(inv.related_in.length ? list(inv.related_in) : ["–"])))),

    section("Project (from the PSI record)", el("dl", {},
      inv.proposal_title && [el("dt", { text: "Proposal title" }), el("dd", { text: inv.proposal_title })],
      inv.flight_program && [el("dt", { text: "Flight program" }), el("dd", { text: inv.flight_program })],
      inv.sponsor && [el("dt", { text: "Sponsor" }), el("dd", { text: inv.sponsor })],
      inv.nasa_center && [el("dt", { text: "NASA center" }), el("dd", { text: inv.nasa_center })],
      el("dt", { text: "Version" }), el("dd", { text: [inv.version && `Version ${inv.version}`, inv.version_reason,
        inv.release_date && `released ${inv.release_date}`, inv.modified_date && inv.modified_date !== inv.release_date && `modified ${inv.modified_date}`]
        .filter((x) => x && x !== "None").join(" · ") || "–" }),
      inv.hardware_links.length > 0 && [el("dt", { text: "Hardware pages" }), el("dd", {}, ...inv.hardware_links.flatMap((u, n) =>
        [n ? ", " : "", el("a", { href: u, target: "_blank", rel: "noopener", text: new URL(u).hostname })]))])),

    section("Objective", prose(inv.objective)),
    section("Approach", prose(inv.approach)),

    section("Fuels named in the record", a.fuels.length ? el("div", {}, ...tags(a.fuels, (f) => `${f.term} · ${f.fuel_class}`)) : el("p", { class: "muted", text: "No fuel term found." }),
      a.solid_emulation.length > 0 && el("p", { class: "muted", text: "Emulates burning solids with a gas burner." })),
    section("Hardware", a.hardware.length ? el("div", {}, ...tags(a.hardware, (h) => h.label)) : null,
      inv.hardware_text && el("p", { class: "muted", text: `PSI lists: ${inv.hardware_text}` })),
    section("Sensors and measurements", a.sensors.length ? el("div", {}, ...tags(a.sensors, (h) => h.label)) : null),
    inv.simulated_data && section("Simulated data (not experiments)",
      el("p", { class: "note", text: inv.simulated_data.note }),
      el("div", { class: "table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...Object.keys(inv.simulated_data.rows[0]).filter((k) => inv.simulated_data.rows.some((r) => r[k])).map((k) => el("th", { text: k })))),
        el("tbody", {}, ...inv.simulated_data.rows.map((r) => el("tr", {}, ...Object.keys(inv.simulated_data.rows[0]).filter((k) => inv.simulated_data.rows.some((x) => x[k])).map((k) =>
          el("td", {}, k === "Reference" && r[k] ? el("a", { href: r[k].trim(), target: "_blank", rel: "noopener", text: "DOI" }) : (r[k] || "")))))))),
      el("p", { class: "muted", text: "Values are shown exactly as the lab wrote them: ranges and mixed units (nitrogen is 0.5 in one row and 74 in another) are not converted." })),
    inv.analyzed?.length > 0 && figureSection(inv.id),
    section("Fire-safety pillars", el("dl", {}, ...Object.entries(inv.pillars).flatMap(([p, v]) => [
      el("dt", { text: PILLAR_LABEL[p] }),
      el("dd", {}, el("span", { class: `badge ${v.status === "evidence" ? "verified" : v.status === "data only" ? "plain" : "unverified"}`, text: PILLAR_STATUS[v.status] || v.status }),
        v.quote && el("blockquote", { text: `${v.field.replace(/^./, (c) => c.toUpperCase())}: ${v.quote}` }),
        v.data_link && el("p", { class: "muted", text: `Measured results: ${v.data_link.why}.` }),
        v.provenance && el("p", { class: "muted", text: v.provenance === "team-confirmed" ? "Confirmed by the team." : "SI pointed at this sentence; rules checked it." }))]))),
    a.equipment.length > 0 && section("Equipment and controls it informs", el("div", {}, ...tags(a.equipment, (e) => e.label))),
    (a.fuels.length || a.hardware.length || a.sensors.length) ? el("p", { class: "muted", text: "Tags are words matched in the record's own text. Hover one to see the sentence." }) : null,

    section("Test conditions", s ? [
      el("dl", {},
        el("dt", { text: "Tests" }), el("dd", { text: fmt(s.tests) }),
        ...Object.entries(s.o2_by_role).flatMap(([role, info]) => [
          el("dt", { text: `Oxygen (${ROLE_LABEL[role] || role})` }), el("dd", { text: range(info.range, 3, "mole fraction") })]),
        el("dt", { text: "Pressure" }), el("dd", { text: range(s.pressure_psi, 1, "psi") }),
        el("dt", { text: "Fuels tested" }), el("dd", { text: Object.entries(s.fuels).map(([k, n]) => `${k} (${n})`).join(", ") || "–" }),
        el("dt", { text: "Outcomes" }), el("dd", { text: Object.entries(s.outcomes).map(([k, n]) => `${k.replace("_", " ")} (${n})`).join(", ") || "–" }),
        el("dt", { text: "Varied between tests" }), el("dd", { text: s.varied.map((v) => `${VARIABLE_LABEL[v.variable] || v.variable} (${v.distinct} values)`).join(", ") || "–" }),
        el("dt", { text: "Held fixed" }), el("dd", { text: s.fixed.map((v) => `${VARIABLE_LABEL[v.variable] || v.variable} = ${v.value}`).join(", ") || "nothing" })),
      Object.keys(s.o2_by_role).includes("oxidizer_stream") && el("div", { class: "note" }, el("strong", { text: "Burner-stream oxygen. " }),
        "In these tests the oxygen value is the gas flowing out of the burner, not the air around the flame. It is never counted as habitat oxygen."),
      el("a", { class: "btn", href: fileHref(`/api/investigations/${inv.id}/tests.csv`), text: "Download harmonised tests (CSV with sources)" }),
    ] : [el("p", { class: "muted", text: `No test data: ${inv.tables_status}.` }),
         inv.tables.some((t) => t.status === "stale") && el("div", { class: "note refresh" }, el("strong", { text: "Data refresh needed. " }),
           "A test table changed after it was mapped. Its data is hidden until it is mapped again.")]),

    inv.tables.length > 0 && section("Data quality", el("ul", { class: "facts" }, ...inv.tables.map((t) => el("li", {},
      el("span", { class: "mono", text: t.file }), ` — ${t.status}`,
      t.status === "parsed" ? `: ${t.tests} tests, ${t.blank_rows} blank rows skipped, ${t.note_rows} note rows. Value flags: ${Object.entries(t.flags).map(([k, n]) => `${k} ${n}`).join(", ")}. Columns not mapped: ${t.columns_unmapped.length}.` : "")))),

    section("Earth and space benefits", prose(inv.impacts)),

    section(`Documents (${inv.documents.filter((d) => d.status === "read").length} read)`,
      shortList(inv.documents.filter((d) => d.status === "read"), (d) => el("li", {},
        el("span", { text: d.file.replace(`${inv.id}_`, "") }),
        el("span", { class: "muted", text: ` · ${d.folder} · ${d.pages} ${d.file.toLowerCase().endsWith(".xlsx") ? "sheet" : "page"}${d.pages === 1 ? "" : "s"} · ${mb(d.bytes)}` }))),
      inv.documents.some((d) => d.status !== "read") && el("details", {},
        el("summary", { class: "muted", text: `${inv.documents.filter((d) => d.status !== "read").length} not read, and why` }),
        el("ul", { class: "facts" }, ...inv.documents.filter((d) => d.status !== "read").map((d) =>
          el("li", {}, el("span", { text: d.file.replace(`${inv.id}_`, "") }), el("span", { class: "muted", text: ` — ${d.status.replace("not read: ", "")}` }))))),
      inv.documents.length > 0 && el("p", { class: "muted", text: "Their text is searchable in SI Insights. The files themselves are on the PSI page." })),

    section("Files PSI holds", Object.keys(inv.file_inventory).length > 0 && el("dl", {},
      ...Object.entries(inv.file_inventory).sort((a, b) => b[1].bytes - a[1].bytes).flatMap(([folder, f]) => [
        el("dt", { text: folder }), el("dd", { text: `${fmt(f.files)} file${f.files === 1 ? "" : "s"} · ${mb(f.bytes)}${folder === "Raw Data" ? " (never downloaded)" : ""}` })])),
      inv.modeling_tables.length > 0 && el("p", { text: `Modeling tables: ${inv.modeling_tables.map((m) => m.file).join(", ")}` })),

    section(`Publications (${inv.publications.length})`, shortList(inv.publications, (pub) => el("li", {},
      el("span", { text: pub.title || "Untitled" }),
      pub.doi && [" · ", el("a", { href: `https://doi.org/${pub.doi}`, target: "_blank", rel: "noopener", text: pub.doi })]))),

    section("Cite this investigation",
      el("p", { class: "cite", text: inv.cite }),
      el("dl", {},
        el("dt", { text: "DOI" }), el("dd", {}, inv.doi ? el("a", { href: `https://doi.org/${inv.doi}`, target: "_blank", rel: "noopener", text: inv.doi }) : (inv.record_complete ? "none recorded by PSI" : "not in this snapshot")),
        el("dt", { text: "License" }), el("dd", { text: inv.license || (inv.record_complete ? "none recorded by PSI" : "not in this snapshot") }),
        el("dt", { text: "PSI page" }), el("dd", {}, el("a", { href: inv.landing_url, target: "_blank", rel: "noopener", text: inv.landing_url })))),
  ].filter(Boolean));  // conditional sections are `false` or `null` when they don't apply
  drawer.scrollTop = 0;
  document.getElementById("drawer-close").focus();
}
