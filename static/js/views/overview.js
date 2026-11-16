// Overview: the mission brief. With the Habitat view on, it is written for the chosen habitat. Every statement is computed from the data.
import { el, api, fmt, pct, hab, habName } from "../ui.js";
import { habitatQuery, navigate, openDetail } from "../app.js";

// Who the dashboard is written for. Shown as its own block under the intro, on both versions of the Overview.
const AUDIENCE = ["Professors", "Graduate students", "Undergraduate students", "Aerospace researchers", "Aerospace engineers"];

function tile(value, label, sub, onclick, accent = false) {
  return el(onclick ? "button" : "div", { class: "tile btn-tile", type: onclick ? "button" : null, onclick },
    el("div", { class: "value" }, accent ? hab(value) : value), el("div", { class: "label" }, accent ? hab(label) : label), sub && el("div", { class: "sub", text: sub }));
}

export async function render(root, state) {
  const [list, env, sources] = await Promise.all([
    api(`/api/investigations?${habitatQuery()}`), api(`/api/envelope?${habitatQuery()}`), api("/api/sources")]);
  const habitatOn = state.habitatView;
  const c = state.meta.counts, h = list.habitat, invs = list.investigations;
  const combustion = invs.filter((i) => i.is_combustion);
  const ground = combustion.filter((i) => i.project_type === "Ground");
  const solids = combustion.filter((i) => i.fuel_classes.includes("solid") && i.project_type === "Microgravity");
  const withTests = combustion.filter((i) => i.tests);
  const flagged = invs.filter((i) => ["verified", "team-confirmed"].includes(i.method.status));
  const byMethod = {};
  for (const i of flagged) for (const label of i.method.labels || []) byMethod[label] = (byMethod[label] || 0) + 1;
  const names = Object.fromEntries(invs.map((i) => [i.id, i.name]));
  const link = (i) => el("a", { href: "#", text: i.name, onclick: (e) => { e.preventDefault(); openDetail(i.id); } });
  const joined = (items) => items.flatMap((i, n) => [n ? ", " : "", link(i)]);
  const top = invs.slice(0, 3);
  // With the Habitat view off, the best fit leaves out condition match, the one part that uses the habitat.
  const noHabitat = (i) => {
    const w = list.weights, keys = ["fuel", "pillar", "data"];
    return keys.reduce((a, k) => a + w[k] * (i.fit.components[k].score ?? 0), 0) / keys.reduce((a, k) => a + w[k], 0) * i.fit.factor;
  };
  const topNoHabitat = [...invs].sort((a, b) => noHabitat(b) - noHabitat(a) || a.id.localeCompare(b.id, "en", { numeric: true })).slice(0, 3);
  const withoutTables = env.gaps.investigations_without_tables.length;

  const know = [
    el("li", {}, `PSI's combustion search returns ${c.investigations} investigations. ${c.combustion} are combustion science: ${combustion.length - ground.length} flown in microgravity and ${ground.length} ground studies.`),
    ground.length > 0 && el("li", {}, "Every ground study builds on flight data: ", ...ground.flatMap((g, n) => [n ? "; " : "", link(g), g.uses_data_from.length ? ` uses ${g.uses_data_from.map((s) => names[s] || s).join(" and ")}` : ""]), "."),
    solids.length > 0 && el("li", {}, `${solids.length} flight investigations name solid materials, the main fire load in ${habitatOn ? "a habitat" : "a crewed spacecraft"}: `, ...joined(solids), "."),
    habitatOn ? el("li", {}, "Best fit for a ", hab(habName(h.label)), " so far: ", hab(...joined(top)), ".")
              : el("li", {}, "Highest relevance so far: ", ...joined(topNoHabitat), "."),
  ];
  const dont = [
    habitatOn && el("li", {}, "Tests inside the ", hab(habName(h.label)), " box (", hab(h.summary), "): ", hab(String(env.gaps.in_box)), " in the data we hold."),
    habitatOn && env.gaps.look_alike_note && el("li", { text: env.gaps.look_alike_note }),
    habitatOn && env.gaps.caveat && el("li", { text: env.gaps.caveat }),
    !habitatOn && withoutTables > 0 && el("li", { text: `${withoutTables} of the combustion investigations have no plotted tests in the charts yet: their tables aren't mapped yet, or PSI lists none.` }),
    el("li", { text: "PSI holds no partial-gravity combustion data yet (Moon or Mars gravity). Microgravity and normal-gravity results can only bound what happens in between." }),
  ];
  const sure = [
    el("li", { text: c.complete_records === c.investigations
      ? `All ${c.investigations} full PSI records are in this snapshot, each with its DOI.`
      : `${c.complete_records} of ${c.investigations} full PSI records are in this snapshot; the rest come from PSI's search listing (no DOI, license or tables yet).` }),
    el("li", { text: `${withTests.length} of ${c.combustion} combustion investigations have a parsed test table (${fmt(c.tests)} tests).` }),
    el("li", { text: flagged.length
      ? `Method confirmed for ${flagged.length} of ${c.investigations}: ${Object.entries(byMethod).map(([k, n]) => `${n} ${k}`).join(", ")} (an investigation can have both labels).`
      : "No investigation has a confirmed experimental-or-simulation flag yet: the Investigator hasn't run." }),
    el("li", { text: "Scores, counts and ranges are computed by code from PSI data. SI never produces a number." }),
  ];

  root.append(
    el("div", { class: "hero" }, el("p", { class: "eyebrow", text: "Mission brief" }),
      el("h1", { text: habitatOn ? "Before we raise the oxygen on the Moon, what do we know about fire in that air?"
                                 : "What does NASA's microgravity combustion research tell us about fire safety in space?" }),
      el("p", { class: "lede" }, habitatOn
        ? ["NASA has studied flames in microgravity for decades. This dashboard ranks, compares and explains that research for a ", hab(habName(h.label), " (", h.summary, ")"), ", and shows where the data stops."]
        : "NASA has studied flames in microgravity for decades. This dashboard ranks, compares and explains that research, and shows where the data stops."),
      el("div", { class: "audience" },
        el("p", { class: "audience-label", text: "Built for" }),
        el("ul", { class: "audience-list" }, ...AUDIENCE.map((who) => el("li", { text: who }))),
        el("p", { class: "audience-note", text: "Analyzing NASA PSI data" })),
      el("div", { class: "hero-actions" },
        el("button", { class: "btn-primary", type: "button", text: "Explore the Flame Sweeper", onclick: () => navigate("sweeper") }),
        el("button", { class: "btn", type: "button", text: "Ask SI Insights", onclick: () => navigate("insights") }))),
    el("div", { class: "grid cols-3" },
      tile(fmt(c.combustion), "combustion investigations", `${c.by_type.Microgravity} microgravity · ${c.by_type.Ground} ground in all ${c.investigations}`, () => navigate("rank")),
      tile(fmt(c.tests), "tests harmonised", `${withTests.length} of ${c.combustion} investigations have a table here`, () => navigate("sources")),
      tile(fmt(ground.length), "ground studies reusing flight data", "simulations and re-analysis", () => navigate("compare"))),
    el("div", { class: "grid cols-3" },
      el("div", { class: "card" }, el("h2", { text: "What we know" }), el("ul", { class: "facts" }, know)),
      el("div", { class: "card" }, el("h2", { text: "What we don't" }), el("ul", { class: "facts" }, dont)),
      el("div", { class: "card" }, el("h2", { text: "How sure we are" }), el("ul", { class: "facts" }, sure))),
    el("div", { class: "card" }, el("h2", { text: "Why oxygen matters" }),
      el("p", { class: "muted", text: habitatOn
        ? "Fire in an oxygen-rich cabin has cost lives. A Moon base is expected to hold 30% oxygen or more, over 40% above Earth's air."
        : "Fire in an oxygen-rich cabin has cost lives." }),
      el("ul", { class: "plain" }, ...sources.sources.filter((s) => s.topic === "lesson").map((s) =>
        el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.title }), ` — ${s.use}`)))),
  );
}
