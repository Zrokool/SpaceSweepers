# Data Deconstruction

How NASA's data comes into SpaceSweepers, how it is taken apart, and how each view uses it.

**In one line:** the data is fetched from NASA's PSI repository, stored with fingerprints, broken into labelled pieces, and every number on screen is calculated from those pieces when you ask for it. Nothing is typed in by hand, and no page shows a canned picture.

## Is it live or a snapshot?

Both, at different layers.

| Layer | When it happens |
|---|---|
| **Fetch from PSI** | On demand, by running `python -m app.psi.sync`. It is not called on every page view. The last fetch is stamped in the page footer (**2026-11-14**). |
| **Store** | The fetched records, tables and document text are saved with a SHA-256 fingerprint each, so any change is detectable. |
| **Deconstruct** | Once per fetch: tables become tests, text becomes labelled evidence. |
| **Calculate** | **Every time you use the app.** Rank, Envelope, Flame Sweeper, Correlation and the chat's scenario answers are computed from the stored pieces for the habitat, pillar and weights you choose. |

So the source is a stored copy of PSI, but the results are never stored answers. Change a weight or a habitat and the numbers are recomputed.

## 1. How the data comes in

- PSI's public service lists every investigation for the search "combustion": **26 investigations** (24 combustion science, 2 not).
- For each one we save the full record, its test tables, its reports and science documents (as extracted text), and its publications list.
- We never download raw data, video or images. Contact details are removed before saving.
- Every file's SHA-256 and the fetch time go into a manifest.

## 2. How it is deconstructed

| Raw PSI item | What it becomes | How |
|---|---|---|
| **Test table (CSV)** | Comparable tests (1,411 so far) | A human-reviewed mapping says which column is oxygen, pressure, fuel or outcome. Each value keeps its raw text, number, unit, a quality flag, its file and row. |
| **Record text** | Labels: experimental or simulation, which fire-safety pillar, fuels, hardware | The SI model points at a sentence, then fixed rules check it. |
| **Lab notes and documents** | Quoted passages with page numbers, and outcomes | 47 documents are split into passages. Outcomes read from notes are kept as their own layer. |

Together with the records, test rows and publications, these form **8,077 searchable evidence items**.
| **Simulation list (PSI-117)** | A separate, labelled layer | Never counted as a test. |

Quality flags: `ok`, `approx`, `range`, `multi`, `missing`, `implausible`, `unparsed`. Nothing is cleaned silently.

**Only 6 of the 26 investigations have mapped tables today**, which is why most gaps read "unknown", not "never tested".

## 3. How each view uses it

| View | Uses | Calculated on demand |
|---|---|---|
| **Overview** | Counts and the top Rank result | What we know, what we don't, what we're sure of. |
| **Rank** | Tests, fuels, pillar quotes, documents | Four scores, weighted. Unknown parts are shown, not guessed. |
| **Envelope** (hidden from the navigation for now) | Tests with oxygen and pressure | One dot per test (1,270), checked against the habitat box. |
| **Flame Sweeper** | Tests with an outcome, one family at a time | Counts per oxygen and pressure cell. A model estimates gaps only if it beats guessing. |
| **Correlation** | Each investigation's profile | Shared and different conditions, fuels, hardware, methods. |
| **Fire Safety** | Checked pillar quotes | Points for the record's own words. |
| **SI Insights** | All 8,077 evidence items | Code finds evidence and computes numbers; the SI phrases it; Nimbus checks every sentence. |
| **PSI Source** | The manifest, table statuses, DOIs and licenses | The funnel from 26 investigations to the tables to the comparable tests, and the reason each unusable table was left out. |

The habitat atmospheres come from the challenge text, not PSI, and are labelled that way.

## 4. Keeping it honest

- **Fingerprints:** if a stored table changes after it was mapped, the app flags "data refresh needed", and the packaged-data check (`python -m app.warm`) fails.
- **Refreshing:** run `python -m app.psi.sync`, re-run the label steps (`app.nimbus.method`, `tables`, `pillars`), review what they print, commit.
- **Layers stay apart:** tests, document outcomes, simulations and analysis figures are never added together.
- **The SI never makes a number.** It points and phrases; code decides.
- **The GitHub Pages demo** is the same calculations run once and saved as files. It lives on the `demo` branch; rebuild it there with `python -m app.static_export --publish` after any data change.

## Limits

- The fetch is manual, not automatic, so the data is as fresh as the last sync.
- PSI holds no partial-gravity (Moon or Mars) combustion data yet.
- Habitat bands, Rank weights and fuel scores are our judgement, and the pages say so.
