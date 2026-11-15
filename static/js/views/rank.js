// Rank: which investigations matter most for the chosen habitat, and why.
import { el, api, withTip, typeBadge, methodBadge, sourceBadges, fmt, title, hab, habName, PILLAR_LABEL } from "../ui.js";
import { habitatQuery, openDetail } from "../app.js";

const COMPONENTS = [
  ["proximity", "Condition match", "Tests in or near the habitat's oxygen and pressure"],
  ["fuel", "Fuel relevance", "Solids first, then liquids, then gases"],
  ["pillar", "Pillar match", "A quoted sentence from the record showing the research informs prevention, detection or suppression, plus measured results"],
  ["data", "Data richness", "Test-table rows, publications and documents read"],
];
let weights = null;       // kept while the page is open, so sliders survive re-renders
let measuredOnly = false;
let parts = COMPONENTS;   // the parts in use: all four, or three when the Habitat view is off

// Only the parts in use count, so with the Habitat view off the score is out of the other three.
function total(fit, w) {
  const sum = parts.reduce((acc, [key]) => acc + w[key], 0) || 1;
  const raw = parts.reduce((acc, [key]) => acc + w[key] * (fit.components[key].score ?? 0), 0) / sum;
  return 100 * raw * fit.factor;
}

function fitBar(fit, w) {
  const sum = parts.reduce((acc, [key]) => acc + w[key], 0) || 1;
  const bar = el("div", { class: "fitbar", role: "img", "aria-label": `Mission fit ${Math.round(total(fit, w))} of 100` });
  for (const [key, label] of parts) {
    const c = fit.components[key];
    const share = (w[key] / sum) * fit.factor;
    const unknown = c.score == null;
    const width = 100 * share * (unknown ? 1 : c.score);
    if (width < 0.5) continue;
    const seg = el("span", { class: unknown ? "unknown" : `c-${key}` });
    seg.style.width = `${width}%`;
    bar.append(withTip(seg, label, [unknown ? "Unknown, counted as zero" : `${Math.round(c.score * 100)}% of ${w[key]} points`, c.why]));
  }
  return bar;
}

export async function render(root, state) {
  const habitatOn = state.habitatView;
  parts = habitatOn ? COMPONENTS : COMPONENTS.filter(([key]) => key !== "proximity");
  const data = await api(`/api/investigations?${habitatQuery()}`);
  weights = weights || { ...data.weights };
  const names = Object.fromEntries(data.investigations.map((i) => [i.id, i.name]));
  const tbody = el("tbody");

  function drawRows() {
    const rows = data.investigations
      .filter((i) => !measuredOnly || i.method.flag !== "simulation")
      .map((i) => ({ i, score: total(i.fit, weights) }))
      .sort((a, b) => b.score - a.score || a.i.id.localeCompare(b.i.id, "en", { numeric: true }));
    tbody.replaceChildren(...rows.map(({ i, score }, n) => {
      const prox = i.fit.components.proximity;
      return el("tr", { class: `clickable${i.is_combustion ? "" : " offtopic"}`, tabindex: 0,
        onclick: () => openDetail(i.id),
        onkeydown: (e) => { if (e.key === "Enter") openDetail(i.id); } },
        el("td", { class: "num", text: n + 1 }),
        el("td", { class: "title-cell" }, el("strong", { text: title(i) }), el("span", { text: i.title })),
        el("td", {}, el("div", { class: "badges" }, typeBadge(i), methodBadge(i), ...sourceBadges(i, names),
          !i.is_combustion && withTip(el("span", { class: "badge offtopic", text: "Not combustion research" }),
            i.research_area, [i.fit.factor_reason]))),
        el("td", { text: i.hardware.join(", ") || "–" }),
        el("td", { text: i.fuel_classes.join(", ") + (i.solid_emulation ? " (emulates solids)" : "") || "–" }),
        withTip(el("td", { class: "num", text: fmt(i.table_rows) }), "Test-table rows downloaded from PSI", [i.fit.components.data.why]),
        habitatOn && withTip(el("td", { class: "num" }, hab(prox.score == null ? "?" : fmt(prox.inside ?? 0))), "Tests in the habitat box", [prox.why]),
        el("td", {}, fitBar(i.fit, weights)),
        el("td", { class: "num" }, habitatOn ? hab(Math.round(score)) : Math.round(score)));
    }));
  }

  const controls = {};
  const sliders = parts.map(([key, label, hint]) => {
    const value = el("span", { text: weights[key] });
    const input = el("input", { type: "range", min: 0, max: 100, step: 5, value: weights[key], "aria-label": `${label} weight`,
      oninput: (e) => { weights[key] = Number(e.target.value); value.textContent = weights[key]; drawRows(); } });
    controls[key] = { input, value };
    return el("div", { class: "weight" },
      el("label", {}, el("span", {}, el("span", { class: `swatch c-${key}` }), label), value), input,
      el("div", { class: "muted", text: hint }));
  });

  const unknown = data.investigations.filter((i) => i.fit.components.proximity.score == null && i.is_combustion).length;
  const pillarText = state.pillar ? `${PILLAR_LABEL[state.pillar].toLowerCase()} research` : "fire-safety research";
  const partsText = habitatOn ? "four parts" : "three parts (the Habitat view is off, so condition match isn't used)";
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "Mission fit" }),
      el("h1", {}, ...(habitatOn ? [`Which ${pillarText} matters for a `, hab(habName(data.habitat.label)), "?"]
                                 : [`Which ${pillarText} matters most for fire safety in space?`])),
      el("p", { class: "lede", text: `Each investigation gets a score from ${partsText}. Every part is computed from the PSI record or its test table, never by SI. Move the weights to see the ranking change; hover a bar to see why. These weights are our judgement, not NASA data.` })),
    el("div", { class: "card" }, el("div", { class: "weights" }, sliders),
      el("div", { class: "legend" },
        el("label", { class: "key" }, el("input", { type: "checkbox", onchange: (e) => { measuredOnly = e.target.checked; drawRows(); } }), "Measured work only (hide simulations and data analysis)"),
        el("button", { class: "btn-ghost", type: "button", text: "Reset weights",
          onclick: () => {
            weights = { ...data.weights };
            for (const [key, c] of Object.entries(controls)) { c.input.value = weights[key]; c.value.textContent = weights[key]; }
            drawRows();
          } })),
      habitatOn && unknown > 0 && el("details", { class: "unknown-note" },
        el("summary", {}, el("strong", { text: `Condition match unknown for ${unknown} of ${data.investigations.filter((i) => i.is_combustion).length} ` }), "(no placeable tests) · why?"),
        el("p", { class: "muted", text: "Their test tables haven't been mapped yet (or PSI lists none), or they record oxygen without pressure, so their oxygen and pressure values can't be placed. Unknown is drawn hatched and counted as zero, not as \"never tested\"." }))),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...[["#", "num"], ["Investigation"], ["Type and method"], ["Hardware"], ["Fuel"], ["Test rows", "num"], habitatOn && ["In box", "num"], ["Mission fit"], ["Score", "num"]]
        .filter(Boolean).map(([t, c]) => el("th", { class: [c, habitatOn && ["In box", "Mission fit", "Score"].includes(t) ? "hab-h" : null].filter(Boolean).join(" ") || null, text: t })))),
      tbody)),
  );
  drawRows();
}
