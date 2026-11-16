// The static (GitHub Pages) copy has no server. Every API answer is a pre-computed file, and this module says which file answers
// which request. It is pure (no DOM, no fetch) and mirrors app/static_export.py exactly; a test runs both on the same inputs.

const WANTED = {
  "/api/investigations": ["habitat", "pillar"],
  "/api/envelope": ["habitat", "measured_only"],
  "/api/sweeper": ["habitat", "habitat_view", "family", "fuel", "diluent"],
  "/api/sweeper/explain": ["family", "fuel", "diluent"],
};
const DEFAULTS = {
  "/api/investigations": { habitat: "moon" },
  "/api/envelope": { habitat: "moon", measured_only: "false" },
  "/api/sweeper": { habitat: "moon", habitat_view: "on", family: "droplet_end_state" },
  "/api/sweeper/explain": { family: "droplet_end_state" },
};

// The key the demo's SI Insights page looks an answer up by. Mirrors normalise_question in app/static_export.py.
export const normQuestion = (q) => String(q).toLowerCase().replace(/\s+/g, " ").trim().replace(/[?.!]+$/, "").trim();

const slug = (v) => String(v).trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

export function staticFile(path, params = {}) {
  const base = path.replace(/\/+$/, "");
  if (base.endsWith(".csv")) return base.slice(1);                    // "api/investigations/PSI-10/tests.csv" is a real file
  const wanted = WANTED[base];
  if (!wanted) return `${base.slice(1)}.json`;                        // "api/sources.json", "api/investigations/PSI-10.json"
  const defaults = DEFAULTS[base] || {};
  const given = { ...defaults };
  for (const k of wanted) {
    const v = params[k];
    if (v !== undefined && v !== null && v !== "" && v !== false) given[k] = v === true ? "true" : String(v);
  }
  if (base === "/api/sweeper" && slug(given.habitat_view) === "off") given.habitat = defaults.habitat;   // no habitat is used, so none is named
  const parts = wanted.filter((k) => given[k] !== undefined).map((k) => `${k}-${slug(given[k])}`);
  return `${base.slice(1)}.${parts.join(".")}.json`;
}

// Side-by-side comparison, computed in the browser from each investigation's pre-computed profile. Mirrors app/analysis/compare.py.
export function compareFromProfiles(data, ids) {
  const profiles = data.profiles;
  const names = [];
  for (const k of new Set(ids.flatMap((i) => Object.keys(profiles[i])))) names.push(k);
  const attributes = names.map((attribute) => {
    const cells = {};
    for (const i of ids) cells[i] = profiles[i][attribute] || null;
    const known = ids.filter((i) => cells[i] && cells[i].length).map((i) => new Set(cells[i]));
    const every = known.length === ids.length;
    const shared = every ? [...known[0]].filter((x) => known.every((s) => s.has(x))).sort() : [];
    const sameSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));
    const allSame = known.length > 0 && every && known.every((s) => sameSet(s, known[0]));
    const out = {};
    for (const i of ids) out[i] = cells[i] || [];
    return { attribute, cells: out, shared, all_same: allSame };
  });
  const links = data.lineage.filter((e) => ids.includes(e.from) && ids.includes(e.to));
  return { investigations: ids.map((i) => data.names[i]), attributes, links };
}
