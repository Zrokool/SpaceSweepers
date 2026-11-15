// Earth: how this research pays off on the ground.
import { el, api, title, PILLAR_LABEL } from "../ui.js";
import { openDetail } from "../app.js";

export async function render(root, state) {
  const [sources, list] = await Promise.all([api("/api/sources"), api("/api/investigations")]);
  const details = await Promise.all(list.investigations.filter((i) => i.is_combustion).map((i) => api(`/api/investigations/${i.id}`)));
  const spinoffs = sources.sources.filter((s) => s.topic === "earth");
  // The pillar an investigation's evidence supports most: a quoted sentence from its record plus measured results.
  const topPillar = (inv) => Object.entries(inv.pillars).filter(([, v]) => v.score).sort((a, b) => b[1].score - a[1].score)[0];
  const pillars = state.pillar ? [state.pillar] : state.meta.pillars;
  // The Earth part of "Research Impacts/Earth Benefits", when the record labels it.
  const earthText = (text) => {
    const m = text.match(/Earth (?:Benefits?|applications?)\s*:?\s*([\s\S]+)/i);
    return (m ? m[1] : text).trim();
  };
  root.append(
    el("div", {}, el("p", { class: "eyebrow", text: "Fire safety" }), el("h1", { text: "What does space fire research do for fire safety on Earth?" }),
      el("p", { class: "lede", text: "NASA technology has improved firefighters' air tanks, smoke detectors and protective clothing. Below, each investigation's own statement of its benefits, quoted from its PSI record." })),
    el("div", { class: "grid cols-3" }, ...spinoffs.map((s) => el("div", { class: "card" },
      el("p", { class: "eyebrow", text: `NASA spinoff · ${PILLAR_LABEL[s.pillar] || ""}` }), el("h3", { text: s.title }), el("p", { class: "muted", text: s.use }),
      el("a", { href: s.url, target: "_blank", rel: "noopener", text: "Read at spinoff.nasa.gov" })))),
    ...pillars.map((p) => {
      const group = details.filter((d) => d.impacts && topPillar(d)?.[0] === p);
      return el("div", {}, el("h2", { text: `${PILLAR_LABEL[p]} (${group.length})` }),
        group.length ? el("div", { class: "grid cols-3" }, ...group.map((d) => {
          const text = earthText(d.impacts);
          return el("div", { class: "card" },
            el("h3", {}, el("a", { href: "#", text: title(d), onclick: (e) => { e.preventDefault(); openDetail(d.id); } })),
            el("blockquote", { text: text.length > 420 ? text.slice(0, 420).replace(/\s+\S*$/, "") + "…" : text }),
            el("p", { class: "muted", text: "Quoted from the PSI record's Research Impacts / Earth Benefits." }),
            d.pillars[p].quote && el("p", { class: "muted", text: `Why ${PILLAR_LABEL[p].toLowerCase()}: “${d.pillars[p].quote.slice(0, 200)}”` }));
        })) : el("p", { class: "muted", text: "No investigation's record shows evidence for this pillar yet." }));
    }));
}
