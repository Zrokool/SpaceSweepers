# SpaceSweepers: fire-safety insights from microgravity combustion data

SpaceSweepers is an SI-powered dashboard for the NASA Space Apps 2026 challenge **Flame in Freefall**. It summarises, ranks and interprets NASA's microgravity combustion research for crewed habitats: spacecraft, space stations, Moon and Mars bases, and pressurized rovers. ("SI", Super Intelligence, is the challenge's term for what was formerly called AI.)

The idea in one line: **SI proposes, PSI data decides.** A local SI model reads and suggests; fixed rules check every suggestion against NASA's data before it's shown as fact. Scores, counts and ranges are computed by code, never by SI.

Data: NASA Physical Sciences Informatics (PSI). SpaceSweepers is not affiliated with or endorsed by NASA.

**Live demo:** <https://zrokool.github.io/SpaceSweepers/>, a static copy of the dashboard on GitHub Pages (no SI model).

| Branch | What it is |
|---|---|
| `demo` (default) | The static GitHub Pages demo. This branch. Merge `production` into it to refresh the demo. |
| `production` | The full app: the dashboard plus the SI chat, run locally with the SI model. |

---

## Status

Working now:

| Part | What it does |
|---|---|
| **PSI sync** | Fetches the 26 investigations returned by the [PSI "combustion" search](https://psi.nasa.gov/physci/repo/search?q=combustion&data_source=psi&data_type=investigation) into a committed snapshot |
| **Overview** | The mission brief for a habitat: what we know, what we don't, how sure we are |
| **Rank** | Mission Fit score per investigation, with adjustable weights and the reason for every part |
| **Compare** | 2–4 investigations side by side, plus a graph of how all 26 relate |
| **Flame Sweeper** | An oxygen × pressure field for one experiment family at a time (FLEX droplets: how flames ended; CFI-G: did a hot flame light; CFI: did the flame reignite; BASS solid samples: did it burn, read from the lab's notes). Tested cells are revealed with their test count and the share where the flame kept burning; untested cells stay hidden. A model estimate appears in an untested cell only if the model beat guessing in cross-validation (FLEX yes, CFI-G no) and only inside the tested range. "What to test next" and "Explain these patterns" (Micro-Flame, checked by Nimbus) are included |
| **Envelope** | Every harmonised test plotted by oxygen and pressure against the habitat's atmosphere |
| **Fire Safety** | NASA spinoffs and each investigation's own Earth-benefits statement |
| **Sources** | What the snapshot holds, what's missing, licenses, why only part of PSI can be charted (data complexity), and how SI is used |
| **SI Insights** | A chat over all the PSI data. Scenario questions ("lowest oxygen where methanol burned", "CO2 vs helium", "closest tested conditions to my cabin") are answered by code from the 1,411 tests in under a second, with a table of the tests behind each number and a Scenario form for choosing conditions; concept questions quote PSI's own sentence. Other questions are answered by Granite from retrieved passages and every sentence is checked by Nimbus. **Two modes** (switch at the top of the page, remembered in the browser): **Guided** (the default) is a plain chat on the left with the PSI details behind each answer on the right (PSI's own words, the tests with file and row, things to keep in mind, sources) and follow-ups that build on your last question ("what about heptane?"); **Expert** is the full screen with the Scenario form, answer cards, per-source checks and the Nimbus verification panel |
| **Investigator (SI)** | Points at the sentence that shows an investigation's own physical test, and the one that shows its own computer model; code checks them and decides the labels (Experimental, Simulation, both, or Not classified). Also chooses tools for SI Insights |

Not built yet: predictive models and the full-dataset export.

**The data.** The snapshot (taken 2026-11-14) holds all 26 full PSI records with their DOIs, all 25 CSV test tables plus 2 tables built from lab workbooks (27 tables, one of them superseded), every file list and publication entry, and the text of 47 documents (1,593 pages). 17 documents are listed but not read, each with its reason (over 5 MB, old `.doc` format, or missing on PSI's side); 5 workbooks are recorded as converted, duplicate or plan-only. 10 small PSI "Analyzed Data" files (PSI-117's figure data and PSI-142's data summary workbook, CC0) are stored unchanged under `data/snapshot/analyzed/` with their SHA-256 in the manifest (`python -m app.psi.analyzed`, recipe in `data/analyzed.yaml`); The detail panels of PSI-117 and PSI-142 draw those files as figure data from reviewed specs (`data/figures.yaml`): PSI-117's as experiment against simulation, PSI-142's as published (its workbook does not say measured or computed), each series checked against the file's own headers and dropped, never guessed, when they disagree. An optional switch overlays CFI (PSI-39) measured n-dodecane tests on the extinction-diameter figure. All of it stays apart from every count and model. Six investigations' tables are mapped so far (PSI-10, 25, 26, 39, 69, 159: 1,411 tests); the other tables are downloaded but their columns aren't mapped yet, and the dashboard shows those as "unknown", never as "zero tests".

---

## Run it

Requirements: Python 3.14, and optionally [Ollama](https://ollama.com) for the SI parts.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
```
Open http://localhost:8000. API docs are at http://localhost:8000/docs.

The dashboard works from the committed snapshot in `data/`, so it runs offline and without Ollama.

**Refresh the PSI data** (needs PSI to be up):
```bash
.venv/bin/python -m app.psi.sync
```

**Run the Investigator** (needs Ollama and the model):
```bash
ollama pull granite3.3:2b
.venv/bin/python -m app.nimbus.method
```

**Tests** (offline):
```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

---

## Deploy

The image is self-contained: `data/` (the PSI snapshot, workbook tables, simulation list, reviewed mappings, the table-mapping ledger, method flags, pillar and outcome evidence), `Nimbus/` (agent specs), `static/` and `app/` are copied in, so it needs no network and no Ollama. There is nothing else to cache: the test catalog and the search library (about 8,000 evidence items) are rebuilt in memory from `data/` in about a second. The `.cache/` folder (raw downloads, backups, run logs) is development-only, is git-ignored and is never copied into the image.

```bash
docker build -t spacesweepers .
docker run --rm -p 8000:8000 -e 'SS_ALLOWED_HOSTS=["localhost","127.0.0.1","your.domain"]' spacesweepers
```

- **`python -m app.warm`** loads the packaged data and fails if it is incomplete (not 26 investigations, no tests) or a mapped table changed after it was mapped (the "Data refresh needed" state). It runs in the Docker build, in CI, and at start-up, so the first visitor never waits for the catalog and a broken snapshot never ships.
- **CI** (`.github/workflows/deploy.yml`): security gate (SAST, SCA, secrets) → unit tests and the packaged-data check → build the image → smoke-test the running container (`/api/meta`, `/api/sweeper`) → Grype scan → push to GHCR with SBOM and provenance → cosign signature. A weekly security scan runs on its own.
- **Updating the data:** run `python -m app.psi.sync` (and `python -m app.nimbus.method`, `app.nimbus.tables`, `app.nimbus.pillars` as needed), review the tables it prints, commit `data/`, push. The pipeline rebuilds the image from the committed data. The SI parts that need Granite (chat, Micro-Flame explanations) work only where Ollama is reachable at `SS_OLLAMA_URL`; everything else works without it.

### GitHub Pages (static demo, `demo` branch)
The static demo lives on the **`demo` branch**. `production` is the full app that runs locally with the SI model and contains none of this. Merge `production` into `demo` to refresh the demo after a change.

GitHub Pages serves files only, so it can't run the Python server or the local SI model. The exporter therefore runs the app once, in-process, and writes every answer of its API to a file. `python -m app.static_export --publish` writes `index.html`, `api/` and `.nojekyll` at the repository root, next to `static/` (which the page uses as is). Pages set to **Deploy from a branch → `demo` → `/ (root)`** serves them; no workflow or environment setting is needed. A test fails if those files are out of date, so run `--publish` and commit after any change to the data or the dashboard. The dashboard views (Overview, Fire Safety, Rank, Correlation, Envelope, Flame Sweeper, References and the investigation panels) are the same data and the same calculations as the live app, for each habitat, pillar and Flame Sweeper selection the page offers. Two things differ:

- **SI Insights** (the chat) needs the model, so the static page shows a notice with the commands to run it locally.
- **Flame Sweeper's "Explain these patterns (SI)"** is left off the demo, with a note. The patterns, skill check and suggestions are computed by code and are the same. Nimbus checks a sentence's words and numbers, not its meaning, and in a trial of pre-computed explanations (`python -m app.static_export --explain`, kept in `data/static_explanations.json` with the model, spec hash and time) some kept sentences read wrongly against the computed patterns, so they are not published. `--with-explanations` includes them if you want to.

To preview locally: `python -m app.static_export --out _site && python -m http.server -d _site 8080`.

---

## How it works

```
Browser   static/index.html · css/style.css · js/app.js · js/views/*.js   (plain JS modules, no build step)
             │  same origin only, strict CSP, REST
FastAPI   app/main.py            security headers, trusted hosts, rate limits
          app/routes/dashboard.py   the read-only API
          app/catalog.py         loads the snapshot into memory: investigations, tests, lineage
          app/psi/               client.py · sync.py · harmonise.py · units.py
          app/analysis/          attributes.py · habitats.py · rank.py · compare.py · envelope.py · sweeper.py (Flame Sweeper) · taxonomy.py (table families and tiers) · outcome_layer.py (BASS outcomes read from lab notes) · complexity.py (why only part of PSI can be charted) · extinction.py and figures.py (figure data from stored Analyzed Data files)
          app/nimbus/            spec.py (loads agent specs) · runtime.py (one model call at a time, cache fingerprint) · method.py (Investigator + its checks) · tables.py (Table mapper + its checks) · pillars.py (Pillar pointer + its checks) · outcomes.py (Outcome pointer + its checks)
          app/psi/analyzed.py    stores the few PSI Analyzed Data files listed in data/analyzed.yaml, with SHA-256 · data/figures.yaml the reviewed figure specs
          app/psi/ledger.py      the variable registry loader and the table-mapping ledger (SHA-256 keyed)
          app/psi/workbooks.py   turns a lab workbook into one data table, once, at sync · data/workbooks.yaml the reviewed recipes
          app/insights/          SI Insights: library.py · frame.py · tools.py · pipeline.py · verify.py (Nimbus checks) · hygiene.py (holds back instruction-like PSI passages) · answers.py (answers written by code) · report.py · evaluate.py · micro_flame.py (Micro-Flame agent)
          app/si/ollama.py       the local SI runtime
          app/routes/insights.py the chat API (streamed) and the Flame Sweeper explanation (/api/sweeper/explain)
Data      data/snapshot/         records, test tables and manifest from PSI (committed)
          data/mappings/         what each table column means, reviewed by hand
          data/vocabulary.yaml   the terms used to tag fuels, hardware, sensors and pillars
          data/method_flags.json Investigator results · data/method_flags.yaml team confirmations
          data/variables.yaml registry · data/table_mappings.json ledger · data/mappings/ hand-reviewed
          data/pillar_evidence.json Pillar pointer results · data/pillar_evidence.yaml team confirmations
          data/outcome_evidence.json BASS outcome labels with quotes · data/snapshot/analyzed/ stored figure data (CC0) · data/snapshot/simulations/ PSI-117 list of data
          data/sources.yaml      the approved sources
Root      LICENSE.txt (Apache-2.0) · license/ (licence list and third-party notices) · Dockerfile · .github/workflows/ (security gate, tests, image build)
Specs     Nimbus/agents/         SI agent prompts, schemas and check rules, loaded at run time
```

### The data rules
- **Scope:** only the 26 investigations PSI's search page returns for "combustion". Two of them (PSI-108, PSI-181) aren't combustion research; they're kept, labelled, and ranked low.
- **Nothing is silently cleaned.** Every test value keeps its raw text, parsed number, unit, quality flag (`ok`, `approx`, `range`, `multi`, `missing`, `implausible`, `unparsed`), source file and row.
- **Unknown is not zero, and not guessed.** A component that can't be computed is shown as unknown. The Rank score counts it as zero (the proven fit, which is what ranks the rows), and each row also shows "up to N", the score if the unknown part were perfect. Unknown parts are never re-weighted away, because that would rank an investigation with no condition evidence above one with proven tests.
- **Oxygen has a role.** In CFI-G inverse flames the oxygen value is the gas leaving the burner, not the air around the flame. Such tests are drawn hollow and never counted as habitat air.
- **Ground studies are traced to their flight data.** PSI's "Related Investigations" field names the flight investigation a ground study builds on.
- **Contact details are removed** from PSI records before anything is saved. Raw data and video are never downloaded.

### Mission Fit score
Four parts, each 0–1, weighted in the browser (defaults 40 / 25 / 20 / 15):

| Part | Computed from |
|---|---|
| Condition match | Tests inside or near the habitat's oxygen and pressure box (room-air oxygen only) |
| Fuel relevance | Fuels named in the record text and in each test table's own Fuel/Material column: solid 1.0, liquid 0.6, gas 0.4; a gas burner that emulates solids (ACME BRE) 0.8 |
| Pillar match | Mentions of prevention, detection or suppression terms |
| Data richness | Test-table rows downloaded (mapped or not, full marks at 100), publications (10) and documents read (5); stored Analyzed Data figures add up to 20% extra (full at 5). Figures are data we hold, never condition evidence |

Investigations outside Combustion Science are multiplied by 0.25. The Rank page has a "How the score works" panel written from the same constants, and shows how often each investigation stays in the top five when the weights are varied at random (400 seeded runs).

### SI Insights (the chat)
Open the **SI Insights** tab and ask a question, for example "What did FLEX find about extinction?", "Compare BASS and BASS-II" or "Which BASS-II tests recorded carbon monoxide?".

- **What it searches:** 8,077 evidence items built from the snapshot: record text, method labels, related investigations, test summaries, all 2,353 test-table rows, 4,977 passages of 47 documents (with page numbers), 367 publications, the file lists and the PSI-117 simulated-data list (9 entries).
- **How it answers:** code reads the question and gathers evidence; the Investigator (SI) can add tool calls; the Analyst (SI) writes at most five sentences that cite numbered evidence; **Nimbus checks every sentence** and removes any it can't support. You see the answer with its sources, the removed sentences and why, what the data doesn't cover, and a computed table or list for comparisons and counts.
- **Rules and limits:** see [Nimbus/README.md](Nimbus/README.md). It gives research context only: it never says a fire is occurring, predicts an outcome or gives instructions.
- **Speed:** the model runs on your computer's CPU. With the model loaded an answer takes about 40 to 70 seconds; the first question after a long pause can take minutes while the model loads (the tab warms it up when it opens).
- **Without Ollama:** the tab still shows the evidence found, labelled "SI offline".
- **Share a question:** a link like `#/insights?q=What did FLEX find about extinction?` asks it on load.
- **Measure it:** `python -m app.insights.evaluate` runs 15 questions against the real model.

### Test-table mapping (registry and ledger)
PSI test tables use different headers. Three files say what each column means:
- `data/variables.yaml` is the **variable registry**: each variable the dashboard computes with, its unit, plausible limits and the header wording that signals it.
- `data/table_mappings.json` is the **ledger**, generated by `python -m app.nimbus.tables`. It is keyed by each table's file name and SHA-256, and records which header maps to which variable, the evidence rows, and, for tables it can't map, a reason (`multi_value_cells`, `no_unit_in_header`, `sparse_or_non_numeric`, `oxygen_role_unknown`, `ambiguous_columns`, `no_condition_columns`…).
- `data/mappings/PSI-*.yaml` are **hand-reviewed** mappings (PSI-159). They win over the ledger and are pinned to their table's SHA-256.

Code finds candidate headers from the registry and rules M-1 to M-5 check them (a header must state its unit; values must parse and be physically plausible; oxygen counts as room air only if the table says *ambient*). SI is only asked to choose between two headers that both qualify, and the rules check its choice. A mapping applies only to the exact table it was made for: if a table's SHA-256 changes, its mapping is blocked and the dashboard shows an orange **Data refresh needed** note until `python -m app.nimbus.tables` is run again. Every downloaded table gets an explicit status; a test fails if one is skipped.

**Outcomes and categories.** The registry also defines the outcome columns (how a flame ended: FLEX `Test end`; did it light: CFI-G `Hot ignition`; extinction mode) with a vocabulary of the raw values PSI uses. A column is mapped only if every raw value in it is in the vocabulary (rule M-6); unknown values are listed for review. Gas columns (oxygen, nitrogen, helium, CO2) are accepted only if they add up to 1 (M-8). `data/taxonomy.yaml` places every table in an experiment family (droplet combustion, gas diffusion flames, solid-fuel flammability, smoke and aerosol) and a readiness tier (A outcome-ready · B outcomes recorded · C conditions only · D test plan · E no oxygen or pressure), shown on the References page. Families are never pooled.

**Lab workbooks (spreadsheets) become tables, once.** PSI's CSV "Experimental table" is often a subset of the lab's own workbook in Science Documents. `data/workbooks.yaml` holds reviewed recipes that join a workbook's sheets on a test key into **one** CSV table in `data/snapshot/tables/` (CFI: 227 tests where the CSV has 79 distinct; BASS as-run: 121 runs with oxygen, pressure and cabin CO2). The rule is one stored copy of every fact: a converted workbook's text is no longer stored or indexed, a CSV it fully contains is marked *superseded* and not counted again, a duplicate workbook (BASS-II) or a plan (BASS planned matrix) is recorded under `workbooks` in the manifest and never stored, and every row is kept even when a test number repeats. A single reader (`documents.read_sheets`) places each value by its cell reference, so a blank cell never shifts later columns. The conversion runs inside `python -m app.psi.sync`, and offline from the local cache with `python -m app.psi.workbooks`. A pattern detector removes login details from any document text; nothing secret is stored anywhere, not even in a block list.

**Hand-reviewed mappings carry document evidence.** Meanings the rules can't know (for example that in CFI-G *normal* flames the oxygen is the chamber atmosphere, but in *inverse* flames it is the burner stream) are written by hand in `data/mappings/` with `evidence:` quotes from the PSI documents. Code checks each quote against the document and page every time the app loads; if one is missing the mapping is blocked and marked "data refresh needed".

### Fire-safety pillars (prevention, detection, suppression)
A pillar is shown for an investigation only with **its own quoted sentence** from the PSI record (Research Impacts, Objective, Hypothesis or, as a last resort, Approach). Code lists candidate sentences from cue words (`pillar_cues` in `data/vocabulary.yaml`), screens out negations, other work, program names and look-alikes such as "smoke point", and the Pillar pointer (SI) points at one per pillar or none; rules P-1 to P-4 check it (`Nimbus/agents/15-pillar-pointer.md`). Measured results add a separate **data link** (FLEX's extinction outcomes for suppression, CFI-G's ignition outcomes for prevention, the SAME smoke-particle tables for detection). The score is points, not keyword counts: Research Impacts 3, Objective or Hypothesis 2, Approach 1, plus 2 for a data link (5 is full). The team can settle a pillar in `data/pillar_evidence.yaml`. Equipment and controls a record says it informs (detectors, suppressant agents, material screening, atmosphere limits, fire models) are tagged the same way, each with its sentence.

### The Investigator (SI)
Spec: [Nimbus/agents/10-investigator.md](Nimbus/agents/10-investigator.md). SI never creates an experiment or a simulation and never writes a label. For each investigation it sees numbered sentences from the Approach and Objective and answers two questions by pointing at a sentence id (or "none"): which sentence shows the investigators' own physical test, and which shows their own computer model. Code checks each sentence (it must exist, hold the right kind of word, and for a ground study built on flight data describe a test the investigators ran themselves) and decides. Labels are **Experimental**, **Simulation**, both (two separate labels, each with its own quoted sentence), or **Not classified** with the reason. A Microgravity investigation flown on the ISS, Cygnus or Space Shuttle is Experimental from PSI's own type and platform. A sentence that only says a model is validated or compared is listed as "needs review", never labelled. A failed pointer gets one second chance. The team can settle a label in `data/method_flags.yaml`.

---

## Configuration
Environment variables with the prefix `SS_`, or lines in `.env`.

| Variable | Default | Notes |
|---|---|---|
| `SS_SI_MODEL` | `granite3.3:2b` | The one SI model the app uses (IBM Granite 3.3 2B, Apache-2.0) |
| `SS_OLLAMA_URL` | `http://127.0.0.1:11434` | Keep it local |
| `SS_ALLOWED_HOSTS` | `["localhost","127.0.0.1"]` | Add your domain when deploying |
| `SS_DATA_DIR` | `data` | Snapshot, mappings, vocabulary |
| `SS_API_RATE_LIMIT` | `120/minute` | Per IP |

## Security
- The browser only calls this app. Every PSI URL is built by the server from fixed hosts; download links are followed only to PSI's own bucket.
- Strict Content-Security-Policy: scripts from this origin only, no inline scripts or styles, no `eval`.
- All text is rendered with `textContent`, so record or SI text can never become HTML.
- Trusted-host check, per-IP rate limits, `nosniff`, `frame-ancestors 'none'`, `no-referrer`.
- CI runs SAST, dependency and secret scanning (`.github/workflows/`).
- SI Insights is reviewed against the OWASP Top 10 for LLM Applications (2025) in [Nimbus/README.md](Nimbus/README.md#security-review-owasp-top-10-for-llm-applications-2025): instruction-like PSI passages are held back from the prompt, answers cannot add links or commands, link addresses from data are checked, and a wait limit keeps a flood of questions from piling up. No SI is used to guard SI.

## SI use, sources and licenses
- **In the app:** a local SI model run through Ollama acts as the Investigator. Its output is checked by deterministic rules before it's shown. No cloud SI service is used at run time.
- **In development:** the code, tests and documentation were written with Claude Code (Anthropic), directed and reviewed by the team.
- **Sources and licenses:** see [license/README.md](license/README.md). The SpaceSweepers code is Apache-2.0 ([LICENSE.txt](LICENSE.txt)).
- **Cite PSI data by DOI.** Each investigation's detail panel has a "Cite this investigation" block.


## Flame Sweeper: how the numbers are made
- **Cells** are 0.02 oxygen × 0.25 atm. Every usable test (oxygen, pressure and outcome all recorded) is in exactly one cell; left-out tests are counted with the reason (for example CFI-G inverse flames: their oxygen is the burner stream).
- **Intervals** are 95% Wilson intervals for observed shares. A flag needs 3 or more tests that all agree.
- **The model** is a logistic regression on oxygen and pressure (pure Python, no new dependency), checked by 10-fold cross-validation with a fixed seed. Its estimates are shown only if accuracy beats always guessing the commoner outcome by 5 points and AUC is at least 0.70, and only for untested cells inside the tested range and beside a tested cell. FLEX droplets: about 78% against 68%. CFI-G ignition: 74% against 74%, so only observed counts are shown.
- **Evidence layers.** Table tests feed the counts, model and patterns. The BASS 'did it burn' family is a separate *document-derived* layer: SI (agent 16) points at the sentence in each run's notes and fixed rules classify it (49 burned, 4 did not ignite, 1 contradictory and 67 unclear runs left out). It is drawn as outlined tiles with observed counts only, never fitted by a model and never pooled with table tests. PSI-117's simulated data list appears only as an optional, labelled pressure-range strip and in the Detail view.
- **What it is not:** a safety rating or a forecast. It summarises what NASA tested in two experiment families.
