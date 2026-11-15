# Vision: SpaceSweepers
**Fire-safety Learning from Reduced-gravity Experiments**
NASA Space Apps 2026 · Challenge: *Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data*

> Numbers marked **(first pass, 2026-11-04)** come from a live survey of NASA's PSI database. They must be re-confirmed by the full data pipeline in phase P0 before they appear in the product or the pitch.

> **Decisions made since this was written (2026-11-14).** Where the text below disagrees, these win. The current state of the build is in [README.md](README.md).
> - **A fresh build.** SpaceSweepers is a new project. The earlier satellite-globe app is removed, so the sections about keeping its globe, tile proxy or code (§6, §9, §14) no longer apply.
> - **Scope: 26 investigations.** The data is exactly what the [PSI "combustion" search](https://psi.nasa.gov/physci/repo/search?q=combustion&data_source=psi&data_type=investigation) returns: the 24 Combustion Science investigations below, plus PSI-108 and PSI-181, which only mention combustion. Those two are kept, labelled and ranked low.
> - **Approved sources only.** NTRS, Cantera and NASA GIBS are not used. The Earth tab is cards, with no globe.
> - **Experimental or simulation.** Every investigation gets a method flag read from its Approach text by the Investigator (an SI agent) and checked by rules. Ground investigations are traced to the flight data they build on.
> - **Model.** The app uses one SI model: IBM Granite 3.3 2B (`granite3.3:2b`, Apache-2.0).
> - **No pull-request roadmap.** The phases in §11 are built in order, without git branches.
> - **Also built since:** the Flame Sweeper (oxygen × pressure field per experiment family, with a skill-checked model and the Micro-Flame explainer agent), lab workbooks turned into one table each, a document-derived outcome layer for BASS (agent 16), PSI-117's simulated-data list, and the stored *Analyzed Data* figure files drawn in the PSI-117 and PSI-142 detail panels (as published, never pooled with counts). The look was redesigned (dark, Geist type). Habitat atmospheres are the challenge text's reference values, labelled as not PSI data.
> - **SI Insights is built** (the chat over all PSI data, checked by Nimbus). It is the app's "Grounded SI Analyst" (F4): see README.md and Nimbus/README.md. Its rules differ from the sketch below: it uses no NTRS and its checks are the C- rules in Nimbus/README.md.

---

## 1. Mission
NASA has flown more than two dozen combustion investigations on the ISS and other spacecraft. The results are public in the Physical Sciences Informatics (PSI) database, but they're hard to find, hard to compare and hard to interpret.

**SpaceSweepers turns that archive into answers a mission designer can act on.** It answers four questions:
- Which experiments matter for *my* habitat's atmosphere?
- How do they compare?
- What does the data predict, and where does it stop?
- What should the next fire-safety system be built on?

Every answer is grounded in NASA data and cites its source.

**Who it's for:** professors, graduate and undergraduate students, aerospace researchers and aerospace engineers designing spacecraft, Moon-base, pressurized-rover and Mars-habitat fire safety. A secondary audience is fire-safety practitioners on Earth.

SI (Super Intelligence) is the challenge's term for what was formerly called AI.

---

## 2. The WHY
The Space Apps judging criteria are impact, creativity, validity, relevance and presentation.

| Our edge | What judges see | Criteria |
|---|---|---|
| **Grounded SI** | Every SI sentence carries a citation (PSI DOI, test-table row or NASA report ID). Unsupported claims are visibly removed, not hidden. We built and battle-tested this "evidence-first" pattern in World View (Nimbus) | Validity, creativity |
| **Mission fit** | Pick "Moon base: ≥ 30% O₂, ≤ 10.2 psi" and the dashboard ranks all 24 combustion investigations by relevance, showing *why* | Relevance, impact |
| **Honest gaps** | A flammability envelope shows where NASA *has* and *hasn't* tested. Example (first pass): **no solid-material test at ≥ 30% O₂**, even though fabrics and plastics are the main habitat fire load | Impact, validity |
| **Data you can reuse** | One click exports harmonised, sourced test data for predictive modelling | Impact |
| **Earth benefits** | The 3D globe from our previous project shows today's real fires on Earth, next to the PSI research that improves fire safety here | Presentation, impact |

**The one-line pitch:** *"Before we raise the oxygen on the Moon, SpaceSweepers shows what we know about fire in that air, what we don't, and how sure we are."*

---

## 3. Data reality (what we verified)
### The PSI REST API is public, needs no login, and returns JSON
- **Search:** `GET https://psi.nasa.gov/geode-py/ws/repo/search?q=&size=200&ffield=Research%20Area&fvalue=Combustion%20Science`
- **Investigation record:** `GET https://psi.nasa.gov/geode-py/ws/repo/investigations/{PSI-id}`
  - Includes: objective, approach, hypothesis, hardware, keywords, Research Impacts / Earth Benefits, publications, related investigations, file list, license and DOI.
- **File download:** `GET https://psi.nasa.gov/geode-py/ws/studies/{PSI-id}/download?file={file_name}&redirect=false`
  - Returns a temporary (presigned) S3 link. Works anonymously.

This is the same backend NASA's Open Science Data Repository (OSDR) uses. It isn't officially documented, so we cache a snapshot (see §13).

### What's in it (first pass, 2026-11-04)
| Item | Count |
|---|---|
| Combustion investigations | **24** |
| Investigations with a test-table CSV | **20** |
| Individual test rows | **1,735** |
| Licensed CC0-1.0 with a DOI (10.60555/…) | **23 of 24**. PSI-10 (ACME Flame Design) has no license recorded, so confirm before using |
| Total file volume | **About 8 TB**, mostly video. We download tables, metadata and small reports only |

**The 24 investigations:**
- **ACME** (all in the Combustion Integrated Rack, CIR):
  - Flame Design PSI-10
  - BRE PSI-20
  - CLD PSI-21
  - E-FIELD Flames PSI-22
  - s-Flame PSI-23
  - CFI-G PSI-159
- **Droplets** (Multi-user Droplet Combustion Apparatus, MDCA):
  - FLEX PSI-69
  - FLEX-2 PSI-68
  - CFI PSI-39
- **Solids and gas flames** (Microgravity Science Glovebox, MSG, with the SPICE flow duct):
  - BASS PSI-26
  - BASS-II PSI-25
  - SPICE PSI-107
  - SLICE PSI-106
- **Large-scale fire:** Saffire I–III (PSI-98, 99, 100)
- **Detection:** SAME PSI-102, SAME-R PSI-101, DAFT PSI-47
- **Analysis and ground studies:** PSI-60, 62, 115, 117, 142

### The data is messy, and we show it
In line with our *data-driven decision* rule, nothing is silently cleaned. Examples from the real tables:
- **O₂ in at least 7 forms:**
  - `XO2 (init)`
  - `Percent O2`
  - `Oxygen`
  - `O initial ambient composition; mole fraction`
  - "~21% O2 with N2"
  - lists like "0.17; 0.21; 0.25"
  - ranges like "21.5 - 21.7"
- **Pressure in atm, bar or mmHg**, or as a string ("1 atm"). **Flow** in cm/s, fan settings or sccm.
- **Odd cells:** "none", "~", negative CO readings (−1 ppm), and note rows mixed in with tests.
- **A wrong unit:** FLEX's "Burning rate; mm" is almost certainly mm²/s. We'll confirm against the FLEX reports.

**Rule:** every value keeps its **raw text, parsed number, unit, quality flag, source file, row and DOI**.

### What the data covers (first pass)
| Investigation | Tests | O₂ (mole fraction) | Pressure (psi) | Tests ≥ 30% O₂ | …and ≤ 10.2 psi (Moon-base-like) |
|---|---|---|---|---|---|
| ACME Flame Design (PSI-10) | 207 | 0.20–0.40 | 13.7–19.1 | 131 | 0 |
| ACME CFI-G (PSI-159) | 179 | 0.18–0.40 | 7.3–44.1 | 115 | **20** |
| FLEX (PSI-69) | 274 | 0.12–0.34 | 10.2–44.9 | 24 | 0 (at the boundary) |
| CFI (PSI-39) | 87 | 0.17–0.21 | 7.3–73.5 | 0 | 0 |
| ACME BRE (PSI-20) | 16 | 0.21–0.40 | not in table | 16 | unknown |
| BASS-II (PSI-25) | 129 | 0.14–0.22 | not in table | **0** | — |
| Saffire-II (PSI-99) | 9 | ~0.21 | not in table | **0** | — |

**What this means:**
- **Solid materials**, the real habitat fire load, were only tested near Earth-normal O₂.
- **ACME BRE**, which emulates burning solids with gaseous fuel, reaches 40% O₂. That makes it the key bridge.
- **CFI-G** is the only data near Moon-base conditions.

That's the story the dashboard should tell, honestly.

---

## 4. Data sources
| Source | Access | License | Used for |
|---|---|---|---|
| **NASA PSI** (REST API above) | Public, no key | CC0-1.0 (per investigation; check each one) | Primary: investigations, test tables, reports |
| **NASA Technical Reports Server (NTRS)**: `https://ntrs.nasa.gov/api/citations/search?q=…` | Public, no key; PDF links | NASA public reports | Papers and reports behind each investigation (e.g. 20170008805 *Results of Large-Scale Spacecraft Flammability Tests*; 20240008623 *Flammability of Materials on the Moon*; 20080013149 *Piloted Ignition Delay of PMMA in Space Exploration Atmospheres*) |
| **Cantera** (Python library) | pip | BSD-3-Clause | Optional: computed flame temperature and equilibrium for any habitat atmosphere, labelled "computed", not "measured" |
| **NASA GIBS**: VIIRS thermal anomalies, GOES GeoColor | Public (already used in World View) | NASA open data | Earth Benefits tab |
| **Challenge Resources tab** | Public | Varies | **To do:** review it for extra datasets before P0 ends |
| MAPTIS / NASA-STD-6001 materials database | **NASA access only** | — | Not usable. Cite the published NTRS summaries instead |

---

## 5. The four core functions
### F1 · Mission Fit Ranker: "Which research matters for my habitat?"
**Inputs:**
- A **habitat profile**:
  - **ISS / spacecraft:** 21% O₂, 14.7 psi (nominal).
  - **Moon base / pressurized rover:** ≥ 30% O₂, ≤ 10.2 psi (from the challenge).
  - **Mars habitat:** assumed similar to the Moon base, labelled *assumption*.
  - **EVA suit:** 100% O₂, 4.3 psi (from the challenge).
  - **Custom:** set your own O₂, pressure and airflow.
- A **fire-safety pillar:** prevention (materials), detection or suppression.

**Logic:** a transparent, deterministic score for each investigation. Starting weights, to be tuned with the team:
- **Condition proximity (40%):** how many of its tests fall inside or near the habitat's O₂, pressure and flow, from the harmonised tables.
- **Fuel relevance (25%):** solids and fabrics first, then liquids, then gases. ACME BRE gets "solid-emulation" credit.
- **Pillar match (20%):** from the objectives, keywords and hardware. Examples: SAME and SAME-R mean detection; FLEX means suppression; BASS and Saffire mean prevention.
- **Data richness (15%):** number of tests, analysed data, and reports.

**Output:** a ranked list with a "why" breakdown for each score, plus a short SI summary card per investigation (from F4).

**Endpoints (new):** `GET /api/habitats`, `GET /api/investigations?habitat=&pillar=&q=`

### F2 · Investigation Compare: "How are these alike, and how do they differ?"
**Inputs:** 2–4 investigations.

**Logic:**
- Builds a side-by-side matrix covering:
  - objectives;
  - hardware (CIR/MDCA, MSG with the SPICE duct, ACME modules);
  - fuel type, shape and size;
  - O₂, pressure and flow ranges;
  - diluents (CO₂, He);
  - sensors and measurements;
  - outcomes measured.
- Highlights what's shared and what differs.
- **Within one investigation:** shows which test variables changed and which stayed fixed (the challenge's "how did tests differ?").
- **Knowledge graph view:** investigations connected to hardware, fuels, instruments and related investigations. For example, SAME's smoke instrument was reused for dust in DAFT, and all six ACME experiments share the CIR hardware.

**Output:** a comparison matrix, a variables panel and a relationship graph.

**Endpoints (new):** `POST /api/compare`, `GET /api/investigations/{id}`

### F3 · Flammability Envelope and Data Extractor: "Where has NASA tested, and what does the data predict?"
**Inputs:** the axes (O₂ against pressure, or O₂ against flow), the fuel class, and the habitat profile.

**Logic:**
- **Envelope.** Plots every harmonised test, coloured by outcome (ignited, extinguished, cool flame, disrupted), with the habitat target as a shaded box. **Gap statistics** say how many tests fall in or near the box.
- **Predictions**, only where the data supports them, each with an uncertainty band and an **"extrapolation" warning** outside the tested range:
  - **FLEX droplet burning rate** against O₂, pressure and diluent, compared with the d²-law physics baseline (K = 8ρD/ρₗ · ln(1+B)).
  - **FLEX suppression:** extinction against disruption under CO₂/He dilution.
  - **CFI-G outcome** (cool flame, hot ignition or self-extinction) against O₂.
- **Partial gravity.** There's no partial-gravity data in PSI yet (LUCI and FM2 are future). Microgravity and 1-g results are shown as **bounds**: Saffire-II has both microgravity and 1-g burn lengths for the same materials.

**Output:** an interactive chart, model cards (training data, accuracy, valid range) and **one-click export** (CSV/JSON plus a provenance manifest with DOIs, files and rows).

**Endpoints (new):** `GET /api/envelope?x=&y=&fuel_class=`, `POST /api/predict`, `GET /api/investigations/{id}/tests[.csv]`, `GET /api/export`

### F4 · Grounded SI Analyst: "Explain it to me, with sources."
**Inputs:** a question, or a brief template:
- "Next-gen smoke detection"
- "Suppression options for a Moon base"
- "Material selection at 30% O₂"
- "Earth applications"

**Logic:** the Nimbus evidence-first pattern from World View, moved to combustion:
1. **Retrieve** PSI records, table statistics and NTRS abstracts (SQLite full-text search).
2. A **local Ollama model** (`granite3.3:2b`) writes the answer, with a citation tag on every sentence, in structured output.
3. **Deterministic checks:**
   - every cited source exists;
   - every number appears in the cited source;
   - no claim restates something that was contradicted;
   - no invented experiment names.
4. Anything that fails is **removed and listed**, or marked *"not established by the data"*.

**Persona:** Micro-Flame is a Nimbus agent (`Nimbus/agents/14-micro-flame.md`, code in `app/insights/micro_flame.py`) that explains the Flame Sweeper's computed patterns in physical terms. It writes no numbers, names a mechanism only if a cited PSI passage does (rule C-MECH), and every sentence must cite a computed pattern (C-ANCHOR). It replaced the earlier `micro-flame` skill, whose unsourced numbers were not carried over.

**Output:** a streamed answer with clickable citations and a "removed claims" panel.

**Endpoint (new):** `POST /api/ask` (Server-Sent Events)

---

## 6. Earth Benefits tab (kept from World View)
The World View 3D globe stays as one tab:
- **Today's active fires on Earth:** VIIRS thermal anomalies, rendered as a PNG through GIBS WMS (verified working), plus the live GOES imagery.
- **Beside it, cards** built from each investigation's *Research Impacts / Earth Benefits* field. Examples: fine-water-mist extinguishers, smoke detection, firefighter gear and air tanks.

This reuses the existing tile proxy and globe code.

---

## 7. Prediction approach (and why not a GNN)
- **Knowledge graph** (networkx): investigations, fuels, hardware, instruments, conditions and publications. Used for compare, similarity and "related research".
- **Interpretable models** (scikit-learn):
  - regularised regression, logistic regression, and Gaussian processes for uncertainty;
  - fitted **per investigation**, because the hardware differs;
  - cross-validated;
  - every model ships a card listing its training rows, error, and valid input range.
- **Physics baselines.** The d²-law and Spalding B are not built: their property constants (liquid density, latent heat, heating value) are not in an approved source. They can be added if PSI documents supply them, and would be validated against FLEX before being shown.
- **Why no GNN.** About 1,735 rows spread across 20 differently designed tables is too little for a graph neural network to beat simpler, explainable models, and judges must be able to follow every prediction. Revisit if partial-gravity data (LUCI, FM2) is added.

---

## 8. Architecture and REST API
```
Browser (dashboard: Ranker · Compare · Envelope · Analyst · Earth tab)
        │  same-origin REST + SSE, strict CSP (kept from World View)
FastAPI backend
  app/psi/        client (search, record, download) · sync · harmonise · quality flags   [new]
  app/ntrs/       NTRS search and abstracts                                                [new]
  app/analysis/   rank · compare · envelope · predict · export                             [new]
  app/analyst/    grounded Q&A: retrieval → Ollama → citation and number checks            [new; reuses app/models/ollama.py and Nimbus ideas]
  app/routes/     tiles.py and layers.py kept for the Earth tab                            [kept]
  storage         SQLite + FTS5 (records, harmonised tests, sources, cached briefs)        [new]
        │
NASA PSI REST · NASA NTRS REST · NASA GIBS (Earth tab) · Ollama on 127.0.0.1
```
- **Sync job (weekly, plus on demand):** fetch the 24 records and 20 test tables, and selected small PDFs. Never video. Store raw files and a snapshot, so the demo works offline.
- **Planned endpoints (all new):**
  - `GET /api/habitats`
  - `GET /api/investigations`
  - `GET /api/investigations/{id}`
  - `GET /api/investigations/{id}/tests[.csv]`
  - `POST /api/compare`
  - `GET /api/envelope`
  - `POST /api/predict`
  - `POST /api/ask`
  - `GET /api/export`
  - `GET /api/sources`
- **Existing endpoints kept:** `/tiles/{layer}/{time}/{z}/{y}/{x}`, `/api/layers`, `/api/ollama/status`

---

## 9. What we keep from World View
| Keep as-is | Adapt | Retire (archived; tag `world-view-v1` first) |
|---|---|---|
| FastAPI core, CSP and security headers, trusted hosts, rate limits, `defusedxml`; config, cache, Docker image | The globe and tile proxy, which become the Earth Benefits tab | Satellite-specific Nimbus evidence layers and rules (`app/nimbus/evidence.py`, `verify.py`, cloud rules) |
| Ollama model selection and structured output (`app/models/ollama.py`) | The Nimbus contract, spec loader and reporter checks, which become the F4 grounding layer | The Analyze-view satellite pipeline UI |
| CI: `security.yml` (SAST, SCA, secret scanning), `deploy.yml`, Dependabot, PR template | NASA-style design tokens, which carry into the new dashboard layout | |
| Offline-fake testing style (`tests/nimbus_fakes.py` pattern) | | |

---

## 10. Data quality and provenance rules
1. **Never silently clean.** Keep the raw text. The parsed value gets a flag: `ok`, `approx` (~), `range`, `multi`, `missing`, `implausible` or `note_row`.
2. **Write unit conversions as explicit, unit-tested functions:** mmHg, bar and atm to psi; % to mole fraction. Known header errors are fixed only after checking the source report (e.g. FLEX's "Burning rate; mm" → mm²/s), and the fix is recorded.
3. **Store column mappings per investigation** as reviewed spec files (e.g. `mappings/PSI-69.yaml`), not hidden in code.
4. **Coverage report.** Every sync writes one: tests parsed, values flagged, and columns not mapped.
5. **Link every chart, prediction and SI sentence to its sources:** DOI, file and row.

---

## 11. Roadmap
Each phase is one pull request from `sandbox`, using the PR template.

| Phase | Builds | Done when |
|---|---|---|
| **P0 · Ingest** | PSI client, sync, harmonise, quality flags, SQLite, coverage report | All 24 records and 20 tables stored; the first-pass numbers in §3 are re-confirmed; PSI-10's license is resolved |
| **P1 · Rank and compare** | F1 and F2 APIs plus UI | Moon-base ranking explains every score; compare shows shared and differing attributes and "what varied" |
| **P2 · Envelope and predict** | F3 charts, gap statistics, models with cards, export | Models validated (cross-validation); extrapolation flagged; export includes provenance |
| **P3 · SI analyst** | F4 retrieval, Ollama, checks, briefs | Every displayed sentence passes the citation and number checks on a test set of questions |
| **P4 · Earth tab and demo** | Globe tab, UI polish, cached demo data, submission text | The 3-minute demo runs offline; the SI-use statement and license table are complete |

---

## 12. Risks and mitigations
| Risk | Mitigation |
|---|---|
| The PSI API is undocumented and could change | Cache a snapshot; offline fixtures for tests and the demo; a clear error if the API changes |
| Messy or partial tables | Quality flags, a coverage report, and per-investigation mappings reviewed by the team |
| Not enough data for some predictions | Only model where data supports it; otherwise show the data, the gap, and "not predictable from current data" |
| Cantera may lack Python 3.14 wheels | Use a pinned Python 3.12 container for that step, or a precomputed table |
| SI could be is slow on CPU (1–3 min) | Precompute and cache the briefs; stream progress |
| PSI-10 has no license recorded | Confirm with PSI, or exclude its data |
| Model licenses must be OSI-approved | Done: the app uses only IBM Granite 3.3 2B (`granite3.3:2b`, Apache-2.0) |
| Unsourced numbers in the former micro-flame skill | Skill removed. The Micro-Flame agent writes no numbers and cites PSI passages (rules C-NUM, C-MECH, C-ANCHOR) |

---

## 13. Space Apps compliance
- **Cite** every PSI dataset by DOI, every NTRS report by ID, and every NASA product used. NASA doesn't endorse the project.
- **License table** for all third-party materials: CesiumJS, Python packages, fonts, Ollama, models. Flag the non-OSI model licenses.
- **SI-use statement:**
  - **Development:** with Claude Code (Anthropic), the team directed, reviewed and checked the work against live data.
  - **Runtime:** a local SI model, used only behind deterministic citation and number checks.

---

## 14. Origins
This project uses NASA-style design, a Python/FastAPI backend chosen for security, and room for future SI models. Its secure backend, CI pipeline, local-SI integration and evidence-first verification pattern are the foundation SpaceSweepers is built on.
