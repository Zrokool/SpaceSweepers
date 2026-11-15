<!--
PR title: <type>(<area>): <short summary in plain words>
  Types: feat · fix · docs · refactor · test · ci · security · deps · chore
  Areas: globe · api · nimbus · evidence · verifier · ollama · ci · docs
  Examples:
    feat(nimbus): add Skeptic yes/no probes
    fix(evidence): treat unpublished IMERG days as unavailable, not dry
-->

## Summary
<!-- 1–3 sentences: what this PR does and why. Link the issue if there is one. -->

Closes #

## Type of change
<!-- Tick every box that applies. -->
- [ ] ✨ New feature (adds behaviour)
- [ ] 🐛 Bug fix (fixes wrong behaviour; describe the bug below)
- [ ] 🛰️ Data / evidence change (new or changed NASA layer, colormap, threshold or publish-date logic)
- [ ] 🧠 SI / model change (Ollama model, Observer prompt, schema or options)
- [ ] 📐 Nimbus spec change (`Nimbus/*.md`: taxonomy, contract, rules)
- [ ] 🎨 UI change (globe, panel, report rendering)
- [ ] 🔒 Security fix or hardening
- [ ] 📦 Dependency update
- [ ] ⚙️ CI/CD or build change
- [ ] 📝 Documentation only
- [ ] ♻️ Refactor (no behaviour change)
- [ ] 💥 **Breaking change** (API response, config variable or report format changes; describe the migration below)

## What changed
### Added
<!-- New files, endpoints, layers, rules, settings… -->
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
<!-- Delete this section if the PR doesn't touch app/nimbus/, Nimbus/ or evidence layers. -->
- Rules or thresholds changed (rule IDs, old → new values):
- Evidence layers added or removed:
- Can this change what appears under **Verified** or **Removed**? ☐ yes ☐ no. If yes, show one before/after example:

| Scene (layer, date, bbox) | Before | After |
|---|---|---|
| | | |

- [ ] Spec files in `Nimbus/` and the code agree (rule IDs, thresholds, layer names)

## How it was tested
- [ ] `pytest` passes locally (`.venv/bin/python -m pytest`)
- [ ] New or updated tests cover this change
- [ ] Checked in the browser at http://localhost:8000 (describe what you did)
- [ ] Ran **Analyze view** on live NASA data (layer, date and area):

<!-- Paste relevant output, timings or test names. -->

## Screenshots
<!-- For UI or report changes: before/after screenshots of the globe or panel. -->

## Security checklist
- [ ] No secrets, tokens or `.env` values in the code, logs or screenshots
- [ ] New outbound requests use fixed hosts and validated inputs (no user-controlled URLs)
- [ ] User or model text is rendered with `textContent`, never `innerHTML`
- [ ] No new inline scripts or external script sources (the CSP is unchanged, or the change is explained above)
- [ ] New dependencies are pinned, and `pip-audit` reports no known vulnerabilities

## Space Apps compliance
- [ ] New non-NASA materials (code, data, fonts, models) are added to the license table in `README.md`
- [ ] New NASA data sources are cited in `README.md` § Sources
- [ ] If SI tools helped with this PR, say how (required in the submission):

## Reviewer notes
<!-- Anything reviewers should look at first, known limitations, or follow-up work. -->
