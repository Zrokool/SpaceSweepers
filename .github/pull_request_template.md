<!--
PR title: <type>(<area>): <short summary in plain words>
  Types: feat · fix · docs · refactor · test · ci · security · deps · chore
  Areas: rank · envelope · sweeper · insights · nimbus · data · ui · api · ci · docs
  Examples:
    feat(insights): add a Guided mode beside Expert
    fix(data): map the Flame Design fuel column as gas
-->

## Summary
<!-- 1–3 sentences: what this PR does and why. Link the issue if there is one. -->

Closes #

## Type of change
<!-- Tick every box that applies. -->
- [ ] ✨ New feature (adds behaviour)
- [ ] 🐛 Bug fix (fixes wrong behaviour; describe the bug below)
- [ ] 🔥 PSI data change (snapshot refresh, table mapping, evidence quote, vocabulary, taxonomy)
- [ ] 🧠 SI / model change (Ollama model, an agent spec in `Nimbus/agents/`, prompt, schema or options)
- [ ] 📐 Nimbus rule change (`Nimbus/README.md`, check rules C-*, mapping rules M-*, definition rules D-*)
- [ ] 🎨 UI change (Overview, Fire Safety, Rank, Correlation, Envelope, Flame Sweeper, SI Insights, References)
- [ ] 🔒 Security fix or hardening
- [ ] 📦 Dependency update
- [ ] ⚙️ CI/CD or build change (Dockerfile, GitHub Actions)
- [ ] 📝 Documentation only
- [ ] ♻️ Refactor (no behaviour change)
- [ ] 💥 **Breaking change** (API response, config variable or file format changes; describe the migration below)

## What changed
### Added
<!-- New files, endpoints, views, rules, mappings, settings… -->
-

### Changed
<!-- Existing behaviour that now works differently. -->
-

### Removed
<!-- Anything deleted or no longer used. -->
-

## Why
<!-- The problem, motivation or context. For bug fixes: what went wrong, how you found it, and the root cause. -->

## Impact on analysis results
<!-- Delete this section if the PR doesn't touch app/analysis/, app/nimbus/, app/insights/, Nimbus/ or data/. -->
- Rules or thresholds changed (rule IDs or constants, old → new values):
- Evidence layers changed (table tests, document-derived outcomes, simulated list, analyzed-data figures; they are never pooled in a count):
- Does any number, ranking or count shown to the user change? ☐ yes ☐ no. If yes, show one before/after example:
- Can this change what appears under **Verified** or **Removed** in SI Insights? ☐ yes ☐ no. If yes, show one before/after example:

| Question or view | Before | After |
|---|---|---|
| | | |

- [ ] Unknown is still shown as unknown, never as zero or a guess
- [ ] Spec files in `Nimbus/` and the code agree (rule IDs, thresholds, agent names)
- [ ] Any new or changed mapping keeps its SHA-256 pin and a verbatim evidence quote, and was reviewed before it was installed

## How it was tested
- [ ] `pytest` passes locally (`.venv/bin/python -m pytest`)
- [ ] New or updated tests cover this change
- [ ] Checked in the browser at http://localhost:8000 (which views, with Habitat view on and off)
- [ ] Ran the SI Insights evaluation (`python -m app.insights.evaluate` and `--scenarios`) against the local model
- [ ] Docker image builds and starts (`docker build -t spacesweepers .`)

<!-- Paste relevant output, timings or test names. -->

## Screenshots
<!-- For UI changes: before/after screenshots of the view that changed. -->

## Security checklist
- [ ] No secrets, tokens or `.env` values in the code, logs or screenshots
- [ ] New outbound requests use fixed hosts and validated inputs (no user-controlled URLs)
- [ ] User, model or PSI text is rendered with `textContent` (or `safeHref` for links), never `innerHTML`
- [ ] No new inline scripts or styles, or external script sources (the CSP is unchanged, or the change is explained above)
- [ ] New dependencies are pinned, and `pip-audit` reports no known vulnerabilities

## Space Apps compliance
- [ ] New non-NASA materials (code, data, fonts, models) are open source (OSI) and added to the license table in `README.md` and `license/README.md`
- [ ] Every PSI dataset or document used is cited by its DOI
- [ ] If SI tools helped with this PR, say how (required in the submission):

## Reviewer notes
<!-- Anything reviewers should look at first, known limitations, or follow-up work. -->
