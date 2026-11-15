// Small DOM helpers. All text goes in through textContent, so record or SI text can never become HTML.

// A value that depends on the chosen habitat: drawn in the habitat colour, and it flashes once when the page redraws after a change.
// A habitat's name inside a sentence: lower-case words, but acronyms such as ISS and EVA keep their capitals.
export const habName = (label) => String(label).replace(/\b[A-Za-z]+\b/g, (w) => (w.length > 1 && w === w.toUpperCase() ? w : w.toLowerCase()));
export const hab = (...content) => el("span", { class: "hab" }, ...content);

// A link address that came from data (a record, a publication, a CSV cell) is used only if it is http, https, blob, or local to this page.
export function safeHref(value) {
  const v = String(value ?? "").trim();
  if (/^(#|\/(?!\/))/.test(v)) return v;
  try { const u = new URL(v); return ["http:", "https:", "blob:"].includes(u.protocol) ? u.href : null; } catch { return null; }
}

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "href") { const safe = safeHref(value); if (safe) node.setAttribute("href", safe); }
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

export async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return resp.json();
}

// ---- tooltip: one shared element, positioned next to the pointer ----
const tip = () => document.getElementById("tooltip");
export function showTip(event, title, lines = []) {
  const t = tip();
  t.replaceChildren(el("strong", { text: title }), ...lines.filter(Boolean).map((l) => el("span", { text: l })));
  t.hidden = false;
  const pad = 14, rect = t.getBoundingClientRect();
  let x = event.clientX + pad, y = event.clientY + pad;
  if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
  t.style.left = `${Math.max(8, x)}px`;
  t.style.top = `${Math.max(8, y)}px`;
}
export function hideTip() { tip().hidden = true; }
export function withTip(node, title, lines) {
  node.addEventListener("mousemove", (e) => showTip(e, title, typeof lines === "function" ? lines() : lines));
  node.addEventListener("mouseleave", hideTip);
  return node;
}

// ---- shared labels ----
export const METHOD_LABEL = {
  "experimental": "Experimental",
  "simulation": "Simulation",
  "both": "Experimental + Simulation",   // two separate labels, each with its own evidence
  "unverified": "Not classified",
};
export const PILLAR_LABEL = { prevention: "Prevention", detection: "Detection", suppression: "Suppression" };
export const ROLE_LABEL = { ambient: "room air", oxidizer_stream: "burner stream" };

export function typeBadge(inv) {
  const micro = inv.project_type === "Microgravity";
  return el("span", { class: `badge ${micro ? "micro" : "ground"}`, text: micro ? "Microgravity" : inv.project_type });
}

// One badge per label (Experimental, Simulation), each with its own evidence. "Not classified" when neither could be checked.
export function methodBadge(inv) {
  const m = inv.method;
  const ok = m.status === "verified" || m.status === "team-confirmed";
  if (!ok || !(m.labels || []).length) {
    return withTip(el("span", { class: "badge unverified", text: "Not classified" }), "How this investigation worked", [m.reason || "Not assessed yet."]);
  }
  const who = m.status === "team-confirmed" ? "Confirmed by the team." : "SI pointed at the sentence; rules checked it.";
  const badges = m.labels.map((label) => {
    const part = m[label.toLowerCase()] || {};
    return withTip(el("span", { class: "badge verified", text: label }), `${label}: why`,
      [who, part.quote ? `"${part.quote}"` : part.basis]);
  });
  return badges.length === 1 ? badges[0] : el("span", { class: "badges" }, ...badges);
}

export function sourceBadges(inv, names = {}) {
  return (inv.uses_data_from || []).map((id) =>
    el("span", { class: "badge plain", text: `uses ${names[id] || id} flight data` }));
}

// "FLEX · PSI-69", or just "PSI-117" when PSI gives no acronym.
export function title(inv) { return inv.name && inv.name !== inv.id ? `${inv.name} · ${inv.id}` : inv.id; }

export function fmt(n, digits = 0) {
  return n == null ? "–" : Number(n).toLocaleString("en-US", { maximumFractionDigits: digits });
}
export function pct(fraction) { return `${Math.round(fraction * 100)}%`; }

export function loading(root, text = "Loading…") { root.replaceChildren(el("p", { class: "muted", text })); }
export function failed(root, error) {
  root.replaceChildren(el("div", { class: "note" }, el("strong", { text: "Couldn't load this view. " }), error.message));
}
