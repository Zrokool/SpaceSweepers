# Nimbus: SI proposes, PSI data decides

Nimbus is the part of SpaceSweepers that keeps SI honest. A small local SI model
is good at reading messy prose and bad at arithmetic, and it will invent facts if
allowed to. So Nimbus gives it narrow jobs with a fixed output format, and checks
every answer with deterministic rules before anything is shown as fact.

| Step | Who | What |
|---|---|---|
| Evidence | code | Facts computed from the PSI snapshot: record text, test statistics, lineage |
| Proposal | SI | A structured answer chosen from fixed options, pointing at its evidence |
| Checks | code | Rules compare the proposal with the evidence |
| Report | code | Passed proposals are shown as checked; failed ones as "not confirmed", with the reason |

Rules that apply to every agent:
- **Structured output only.** The model answers in JSON that fits a schema. It can only point at evidence that exists.
- **Temperature 0, fixed seed.** The same input gives the same answer.
- **SI never produces a number.** Counts, ranges, scores and unit conversions come from code.
- **Unknown is said out loud.** A failed check is shown with its reason, never hidden.
- **The specs are the source of truth.** Prompts, schemas and rule tables live in `Nimbus/agents/*.md` and are loaded at run time. Each result records a hash of these files.

## Agents

| Spec | Status | Job |
|---|---|---|
| [10-investigator.md](agents/10-investigator.md) | built | (1) Points at the sentences in each investigation's Approach and Objective that show a physical test or a computer model; code decides Experimental, Simulation, both or Not classified. (2) In SI Insights, chooses which read-only tools to call for a question |
| [12-analyst.md](agents/12-analyst.md) | built | In SI Insights, writes the answer: a short answer, each sentence citing numbered PSI evidence. The model is asked for at most three sentences, and Nimbus keeps at most five |
| [13-table-mapper.md](agents/13-table-mapper.md) | built | Maps PSI test-table headers to the variable registry. Code finds candidates; SI only breaks ties; rules M-1 to M-5 decide; the ledger is keyed by the table's SHA-256 |
| [14-micro-flame.md](agents/14-micro-flame.md) | built (replaces the former `micro-flame` skill) | In Flame Sweeper, explains the computed patterns in physical terms: at most three sentences, each anchored to a computed pattern, naming a mechanism only if a PSI passage does |
| [15-pillar-pointer.md](agents/15-pillar-pointer.md) | built | Points at the sentence in each record that shows the research informs prevention, detection or suppression; code finds the candidates and checks the pointer; measured results add a separate data link |
| [16-outcome-pointer.md](agents/16-outcome-pointer.md) | built | Points at the sentence in a BASS run's lab notes that says whether the sample ignited and burned; code finds the candidates, classifies the sentence (burned / no ignition), leaves contradictions unlabelled, and keeps the quote. Result: a separate *document* evidence layer, never mixed into table statistics |
| [17-definition-pointer.md](agents/17-definition-pointer.md) | built | Points at the one candidate sentence, found by code in PSI's reports and science documents, that best defines a term the user asked about ("What is a cool flame?"); code checks the term and a defining cue (rules D-1 to D-3), falls back to its own top candidate when SI is slow (20 s), and shows the sentence verbatim with its document and page |

Stage numbers are identifiers, not a sequence: 11 is unused.

**Where an agent's code lives.** The spec is always `Nimbus/agents/NN-name.md`, and everything configurable (prompt, schema, options, search queries) is in it. Agents that need only the catalog and the SI runtime keep their code in `app/nimbus/` (`method.py`, `tables.py`). Agents that write sentences from evidence and are checked by the Nimbus rule engine keep theirs in `app/insights/`, next to the evidence library and the checker they share (`pipeline.py` for the Analyst, `micro_flame.py` for Micro-Flame). `app/nimbus/runtime.py` holds what every agent shares: the single model lock and the cache fingerprint. Each agent has its own test file.

## SI Insights: how one question is answered

```
question ─ read (code) ─ Investigator picks tools (SI) ─ tools run (code) ─ Analyst writes (SI) ─ Nimbus checks (code) ─ report (code)
```
1. **Read (code).** Finds the investigations named, topics, fuels, numbers, and carries over the last answer's investigation for follow-ups. `app/insights/frame.py`.
2. **Investigator (SI).** Chooses up to three tool calls. Every argument is validated; code also adds its own searches so a weak choice never leaves the answer without evidence. `app/insights/tools.py`.
3. **Tools (code).** Twelve read-only tools over the PSI library (8,077 evidence items: record passages, labels, lineage, test summaries, every test row, document passages, publications, file lists). Counts and comparisons are computed by code. `app/insights/library.py`.
4. **Analyst (SI).** Sees only the question and a numbered evidence list (about 1,300 words).
5. **Nimbus checks every sentence (code).** `app/insights/verify.py`.
6. **Report (code).** Verified sentences with renumbered citations; sources with DOIs; the removed sentences and why; what the data doesn't cover; a computed table or list for comparisons and counts.

### The checks

A sentence is kept only if it passes all of these. The model can't switch them off.

| Rule | A sentence is removed when… |
|---|---|
| C-CITE | it cites nothing, or evidence that doesn't exist |
| C-SCOPE | it says a fire is occurring, predicts an outcome, or tells someone what to do |
| C-NAME | it names an investigation, PSI ID or acronym the evidence it cites isn't about |
| C-COVER | it compares investigations but doesn't cite evidence about each one |
| C-NUM | it has a number that isn't in the evidence it cites (only "85%" for 0.85 and atm/bar/psi are converted, and only when the sentence states that unit) |
| C-METHOD | it says an investigation ran experiments (or simulations) when its record and label don't support it: a Ground study is never "experimental" without a checked label |
| C-QUOTE | quoted text isn't word for word in the evidence it cites |
| C-SUPPORT | at least half of its content words aren't found in the evidence it cites |
| C-MECH | it names a physical mechanism (radiative extinction, buoyancy, chemical kinetics…, listed in `data/vocabulary.yaml`) that no PSI document passage it cites mentions |
| C-ANCHOR | (Flame Sweeper explanations only) it cites no computed pattern, so it doesn't explain what the tests show |

C-SCOPE is independent of the evidence: even if a PDF says "a fire is occurring now", no answer may. Evidence text, including document text, is data and never instructions.

What the checks do **not** prove: that a number belongs to the right column of a table row, or that a paraphrase keeps the exact meaning. The row or passage is always shown in the sources so a reader can check.

## Run log
Every question writes `.cache/nimbus-runs/insights-<time>-<hash>.json`: the question, how it was read, the tools, the evidence, the model's raw answer, every check, timings, the model and a hash of the spec files. Each log also records who asked (`origin`: `user` for a person using the app, `evaluation` or `development`) and the date of the PSI snapshot it ran against. Only real questions are written to `.cache/nimbus-runs/`; evaluation runs go to `nimbus-runs/evaluation/` and development runs to `nimbus-runs/development/`, so a measurement is never mixed with something else. Set `SS_RUN_ORIGIN=development` for scripts and manual testing.

## Measuring it
`python -m app.insights.evaluate` runs the questions in `data/insights_eval.yaml` against the real model and reports how many answered, how many sentences Nimbus removed (and under which rule), and any unsafe phrases. Its run logs are tagged `evaluation`.

## Evidence layers and the one-copy rule
Every fact is stored once, derived once, with a pointer to its source. Outcomes come in two typed layers that are **never pooled**:
- **Table tests** (CSV or converted workbook columns) feed counts, the skill check, the model and the patterns.
- **Document-derived outcomes** (agent 16, `data/outcome_evidence.json`) are references (table row + the table's SHA-256 -> class + quote). They carry the quality flag `document_text`, which every table statistic ignores, and are shown as outlined tiles with observed counts only. If the table changes, the SHA no longer matches and the layer is switched off until it is re-read.
- **Simulated data lists** (PSI-117) are metadata only, kept apart from tests, labelled as simulations. Their figure data files are stored unchanged (data/snapshot/analyzed, CC0, SHA-256 in the manifest); two are drawn as experiment against simulation and never enter a count, estimate or pattern.

Regenerate the document layer with `python -m app.nimbus.outcomes --out staging.json`, review the labels and quotes, then copy the file to `data/outcome_evidence.json`.

## Security review: OWASP Top 10 for LLM Applications (2025)
SI Insights treats the model as untrusted: it never decides anything that matters, and every check is fixed rules in code. No SI is asked "is this an attack?", because a guard that depends on the model can be talked out of its job and would add a slow second model call to every question. The hardening below adds no model call (scrubbing the 12 passages of an answer takes about 0.7 milliseconds).

| OWASP LLM risk | In SI Insights | Status |
|---|---|---|
| **LLM01 Prompt injection** | The question and the PSI passages are data. The prompts say so. Evidence passages that read like instructions to an assistant (`ignore your previous instructions`, forged `system:` or `<\|im_start\|>` markers, a fake `E9. [record]` entry, "reveal your prompt") are **held back from the prompt** and noted (`app/insights/hygiene.py`). A passage that imitates a numbered entry or a chat role is held back, so what remains cannot forge one. The rules held back **0 of 8,077** real passages. Even if a poisoned passage got through, Nimbus removes any sentence its sources do not back, any prediction or advice, and any claim of a fire | Mitigated |
| **LLM02 Sensitive information** | Contact details are removed from PSI records at sync; login details found in one lab spreadsheet were purged and a detector blocks them. Rule **C-LINK** removes an email address or phone number the cited evidence does not contain. Run logs hold the question and answer in `.cache/` (git-ignored) | Mitigated; logs are local |
| **LLM03 Supply chain** | Open-licence model only (Granite, Apache-2.0), pinned Python packages, licence list, signed container image, SAST/SCA/secret scans in CI. The model is pulled by name through Ollama and its digest is not pinned | Residual: model digest not pinned |
| **LLM04 Data and model poisoning** | Data comes only from PSI. Each table is pinned by SHA-256, a changed table blocks its mappings ("Data refresh needed"), every mapping needs a verbatim document quote, and the evidence hygiene above holds back instruction-like text. There is no fine-tuning and no user-supplied training data | Mitigated |
| **LLM05 Improper output handling** | The page sets all text with `textContent` and a strict CSP forbids inline script. Link addresses that come from data are used only if they are `http`, `https`, `blob` or local (`safeHref` in `static/js/ui.js`). Rule **C-LINK** removes any link, markup, code or shell command in an answer that the cited evidence does not contain. | Mitigated |
| **LLM06 Excessive agency** | Twelve tools, all read-only. The model picks at most three; every argument is checked against fixed lists (investigation ids must exist, sections and filters come from fixed sets). The model cannot write, run code, call the network or change data | Mitigated by design |
| **LLM07 System prompt leakage** | The prompts are in the public repository, so they hold no secret. Nothing sensitive is in any prompt | Not applicable by design |
| **LLM08 Vector and embedding weaknesses** | There are no embeddings; retrieval is SQLite full-text search with a query built from plain words only (no operators). If embeddings are added later, the same evidence hygiene must run on what they retrieve | Not applicable today |
| **LLM09 Misinformation** | The core of Nimbus: every sentence needs citations and passes number, name, method, quote and support checks. Removed sentences are shown with the reason. The chat says it is research context and never declares a fire | Mitigated |
| **LLM10 Unbounded consumption** | Questions are limited to 500 characters and 10 per minute per visitor. The one model runs one call at a time; a question now **waits at most 90 seconds, at most 4 may wait, and the rest are answered from evidence alone** instead of piling up (`model_slot` in `app/nimbus/runtime.py`). Answers are cached. Output length is capped per agent | Mitigated |

Tests: `tests/test_hardening.py` (queue limit, injected passages, C-LINK). The residual risks above are the model digest, and that a determined visitor can still fill the 10-per-minute allowance from several addresses.

## The scenario analyst: answering what the user actually asked
Researchers and engineers ask scenarios, not keywords: "What is the lowest oxygen where methanol droplets burned in FLEX?", "How do CO2 and helium compare as suppressants?", "Which tested conditions are closest to a cabin at 34% oxygen and 8.2 psi?". A 2B model paraphrasing retrieved text answered none of ten such questions correctly (wrong, irrelevant or 35 to 116 seconds), so these are now answered **by code from the tests** and SI is not involved in the answer:
- `app/insights/scenario.py` reads the question (or the Scenario form's validated fields) into a fuel or material, a gas, an oxygen and pressure range, an outcome and a goal: *threshold*, *compare*, *nearest*, *outcomes* or *profile*.
- `app/analysis/queries.py` computes it over the harmonised tests: the lowest or highest value at which an outcome was seen with what happened beyond it, observed counts with Wilson ranges for a comparison (always with the caveat that PSI's tests did not vary one gas at a time), the nearest tested conditions, outcome shares by oxygen or pressure band. A range is never presented as a limit.
- The answer card shows the sentences, key numbers, a table of the tests with their file and row, a link to the Flame Sweeper preset to that family, fuel and gas, and "What this does not tell you", computed from the data (for example the 154 tests whose oxygen is the burner stream and are left out). When no test matches every condition, it says which condition removes them and what exists without it.
- Concept questions show PSI's own sentence (agent 17). Questions the tests cannot answer (documents, lineage, lists) keep the retrieval path, the Investigator and the Analyst, with every Nimbus check.
- `python -m app.insights.evaluate --scenarios` runs 20 audience questions from `data/scenario_eval.yaml` against the live chat (expected numbers checked against plain loops in `tests/test_scenario.py`).

### Guided and Expert modes
SI Insights has two presentations of the same answers. **Expert** is the full screen and is unchanged. **Guided** (the default) shows a plain chat and, on the right, the PSI details behind the selected answer. The request carries `audience: "guided" | "expert"` (default `expert`). For guided only:
- code-written sentences use everyday words ("9 investigations labelled simulation: ...");
- the answer returns its conditions (`report.scenario`) and the page sends them back as `context`, so a short follow-up ("what about heptane?", "and for carbon dioxide?") keeps the goal and outcome and changes only what the user changed. It is computed by code (no extra model call), validated by pydantic (`ScenarioContext`), and Expert ignores any `context` it is sent;
- follow-up suggestions are tried before they are offered, so each one produces an answer.
Expert is proven unchanged by rendering 12 saved answers before and after: the screen text is identical apart from the mode switch. Two shared fixes apply to both modes: the empty "()" in the count sentence, and computed evidence ids that are now stable between runs.
Known limit: a question that is not about combustion can still reach the retrieval path and get a thin, loosely related answer.
