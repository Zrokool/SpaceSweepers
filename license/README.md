# SpaceSweepers: licenses and sources

This folder documents every license and source used by SpaceSweepers, as the NASA Space Apps Challenge rules require. Every non-NASA material listed here is OSI open source or freely available, and every source is cited.

| File | Contents |
|---|---|
| [`README.md`](README.md) | This list: what is used, its license, and where it comes from |
| [`../LICENSE.txt`](../LICENSE.txt) | The license for the SpaceSweepers code (Apache-2.0) |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | The full license text of every Python package the server runs |

---

## 1. SpaceSweepers code

**Apache License 2.0**, copyright 2026 SpaceSweepers team. See [`LICENSE.txt`](../LICENSE.txt). This covers everything in `app/`, `static/`, `Nimbus/`, `data/` (the mapping, vocabulary and source files written by the team), `tests/` and `.github/`.

**Logos and icons** (`static/brand/`): original work by the SpaceSweepers team, released under the same Apache-2.0 license. *(Team: confirm this. If any logo was made with an SI image tool or from a template, name the tool or source here.)*

---

## 2. NASA data and resources

SpaceSweepers uses only the sources approved for the Flame in Freefall challenge (its Resources tab). The machine-readable list is [`../data/sources.yaml`](../data/sources.yaml). NASA does not endorse SpaceSweepers. No NASA logo or insignia is used.

### NASA PSI (Physical Sciences Informatics): the data
The 26 investigations returned by the PSI Data Repository search for "combustion":
<https://psi.nasa.gov/physci/repo/search?q=combustion&data_source=psi&data_type=investigation>

A snapshot of their records, test tables and document text is stored in `data/snapshot/` (taken 2026-11-14). It holds every record field except contact details, every *Experimental table*, the list of every file PSI holds, every publication entry, and the text of 47 Reports, Science Documents and ReadMe files (1,593 pages). It also holds: two test tables built from the labs' own workbooks (CFI Data Summary, BASS As Run; the workbooks' original bytes are not stored, only the joined table); PSI-117's "List of Data" (a list of its simulated data files, kept apart from tests); and 10 small *Analyzed Data* files stored unchanged in `data/snapshot/analyzed/` (PSI-117's nine figure-data CSVs and PSI-142's data-summary workbook), each with its SHA-256 and its record's DOI and licence (CC0-1.0) in the manifest. Raw Data (terabytes) and video are never downloaded. Login details that appeared in one lab spreadsheet were removed and are never stored.

**Citation.** In line with NASA's SMD Open Source Science guidance, every PSI investigation is cited by its DOI. The dashboard's detail panel gives a "Cite this investigation" block for each one.

| Investigation | DOI | License |
|---|---|---|
| PSI-10 ACME/Flame Design · Advanced Combustion via Microgravity Experiments / Flame Design | [10.60555/w4zy-bt45](https://doi.org/10.60555/w4zy-bt45) | **none recorded by PSI** |
| PSI-20 ACME BRE · Advanced Combustion via Microgravity Experiments - Burning Rate Emulator | [10.60555/vb93-3y72](https://doi.org/10.60555/vb93-3y72) | CC0-1.0 |
| PSI-21 ACME CLD Flame · Advanced Combustion via Microgravity Experiments / Coflow Laminar Diffusion Flame | [10.60555/23e1-9950](https://doi.org/10.60555/23e1-9950) | CC0-1.0 |
| PSI-22 ACME E-FIELD Flames · Advanced Combustion via Microgravity Experiments Electric-Field Effects on Laminar Diffusion Flames | [10.60555/se5a-8c73](https://doi.org/10.60555/se5a-8c73) | CC0-1.0 |
| PSI-23 ACME s-Flame · Advanced Combustion via Microgravity Experiments-Structure and Response of Spherical Diffusion Flames | [10.60555/k57n-p030](https://doi.org/10.60555/k57n-p030) | CC0-1.0 |
| PSI-25 BASS-II · Burning and Suppression of Solids - II | [10.60555/4qc4-de67](https://doi.org/10.60555/4qc4-de67) | CC0-1.0 |
| PSI-26 BASS · Burning and Suppression of Solids | [10.60555/58h4-dy80](https://doi.org/10.60555/58h4-dy80) | CC0-1.0 |
| PSI-39 CFI · Cool Flames Investigation | [10.60555/m6pj-a914](https://doi.org/10.60555/m6pj-a914) | CC0-1.0 |
| PSI-47 DAFT / DAFT-2 · Dust and Aerosol Measurement Feasibility Test / Dust and Aerosol Measurement Feasibility Test-2 | [10.60555/ztgj-d202](https://doi.org/10.60555/ztgj-d202) | CC0-1.0 |
| PSI-60 Computational and Experimental Analysis of SPICE Data Sets | [10.60555/mzjm-yv57](https://doi.org/10.60555/mzjm-yv57) | CC0-1.0 |
| PSI-62 Concurrent Flame Spread Modeling using Flamelet Generated Manifolds in Microgravity with Comparison to BASS Experiments using Two-Color Tomography | [10.60555/e9xp-ex83](https://doi.org/10.60555/e9xp-ex83) | CC0-1.0 |
| PSI-68 FLEX-2 · Flame Extinguishment Experiment - 2 | [10.60555/byp8-h018](https://doi.org/10.60555/byp8-h018) | CC0-1.0 |
| PSI-69 FLEX · Flame Extinguishment Experiment | [10.60555/mbq8-0451](https://doi.org/10.60555/mbq8-0451) | CC0-1.0 |
| PSI-98 SAFFIRE-I · Spacecraft Fire Safety Experiment-I | [10.60555/0t15-1z43](https://doi.org/10.60555/0t15-1z43) | CC0-1.0 |
| PSI-99 SAFFIRE-II · Spacecraft Fire Experiment-II | [10.60555/2chp-m469](https://doi.org/10.60555/2chp-m469) | CC0-1.0 |
| PSI-100 SAFFIRE-III · Spacecraft Fire Experiment-III | [10.60555/040q-4h36](https://doi.org/10.60555/040q-4h36) | CC0-1.0 |
| PSI-101 SAME-R · Smoke Aerosol Measurement Experiment-Reflight | [10.60555/2np7-jv14](https://doi.org/10.60555/2np7-jv14) | CC0-1.0 |
| PSI-102 SAME · Smoke and Aerosol Measurement Experiment | [10.60555/gd4k-8h62](https://doi.org/10.60555/gd4k-8h62) | CC0-1.0 |
| PSI-106 SLICE · Structure and Liftoff In Combustion Experiment | [10.60555/pm12-rg61](https://doi.org/10.60555/pm12-rg61) | CC0-1.0 |
| PSI-107 SPICE · Smoke Point In Co-flow Experiment | [10.60555/9kbh-e962](https://doi.org/10.60555/9kbh-e962) | CC0-1.0 |
| PSI-108 STDCE-1 · Surface Tension Driven Convection Experiment-1 | [10.60555/j1z3-bw42](https://doi.org/10.60555/j1z3-bw42) | CC0-1.0 |
| PSI-115 Utilization of the Smoke Aerosol Measurement Experiment Data for Advanced Modeling and Simulation of Smoke Generation in Micro-Gravity | [10.60555/q0v5-1v28](https://doi.org/10.60555/q0v5-1v28) | CC0-1.0 |
| PSI-117 Effect of External Thermo-Convective Perturbation on Cool Flame Dynamics: A Multidimensional Multi-Physics CFD Analysis | [10.60555/gz0q-b577](https://doi.org/10.60555/gz0q-b577) | CC0-1.0 |
| PSI-142 Quantitative Studies of Cool Flame Transitions at Radiation / Stretch Extinction Using Counterflow Flames | [10.60555/80qf-vj95](https://doi.org/10.60555/80qf-vj95) | CC0-1.0 |
| PSI-159 ACME CFI-G · Advanced Combustion via Microgravity Experiments / Cool Flames Investigation with Gases | [10.60555/cyt1-kh64](https://doi.org/10.60555/cyt1-kh64) | CC0-1.0 |
| PSI-181 Structure and Properties of Pb-Sn and Pb-free Sn-Ag-Cu Solders Produced in Terrestrial vs. Microgravity Environments under Extremes of Elevated and Cryo Temperatures | [10.60555/td9e-cz97](https://doi.org/10.60555/td9e-cz97) | CC0-1.0 |

⚠️ **To do before submitting:** PSI records no license for PSI-10 (ACME Flame Design). Confirm its terms with PSI, or leave its data out of the submission.

### Background reading (linked, never a source of numbers)
| Resource | URL |
|---|---|
| NASA Combustion Science | <https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/> |
| NASA ScienceCasts: The Power of Studying Combustion on the ISS | <https://www.youtube.com/watch?v=W1oXykoz9zg> |
| A Researcher's Guide to ISS Combustion Science | <https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/> |
| Apollo 1 | <https://sma.nasa.gov/sma-disciplines/accllp/apollo-1> |
| Apollo 13 | <https://sma.nasa.gov/sma-disciplines/accllp/apollo-13> |
| 25 Years Ago: Fire Aboard Space Station Mir | <https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/> |
| NASA Spinoff: Fireman's Air Tanks | <https://spinoff.nasa.gov/node/9582> |
| NASA Spinoff: Fire Detector | <https://spinoff.nasa.gov/node/9407> |
| NASA Spinoff: New Technology for the Fire Attire | <https://spinoff.nasa.gov/node/9918> |
| The challenge text (habitat oxygen and pressure values) | <https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/> |

---

## 3. Third-party code shipped with SpaceSweepers

No third-party JavaScript is shipped: the dashboard is plain JavaScript written for this project.

### Python packages (server runtime)
Pinned in `requirements.txt`. Transitive dependencies are included. Full texts are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.6 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| click | 8.5.1 | BSD-3-Clause |
| Deprecated | 3.0.1 | MIT |
| fastapi | 0.143.0 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| limits | 5.8.0 | MIT |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pydantic | 2.14.0 | MIT |
| pydantic_core | 2.50.0 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| pypdf | 7.0.1 | BSD-3-Clause (reads the text of PSI's PDF documents) |
| PyYAML | 6.0.3 | MIT |
| slowapi | 0.1.10 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.5 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| uvloop | 0.23.0 | MIT OR Apache-2.0 |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.4 | BSD-3-Clause |
| wrapt | 2.5.2 | BSD-2-Clause |

---

## 4. Loaded by the browser at run time (not shipped)

| Material | License | Source |
|---|---|---|
| Geist (font) | SIL Open Font License 1.1 | Google Fonts, <https://vercel.com/font> |
| Geist Mono (font) | SIL Open Font License 1.1 | Google Fonts, <https://vercel.com/font> |
| Swagger UI (API docs page at `/docs` only) | Apache-2.0 | cdn.jsdelivr.net, served by FastAPI, <https://github.com/swagger-api/swagger-ui> |

---

## 5. SI models (downloaded by the user through Ollama, not shipped)

| Material | Role | License | Source |
|---|---|---|---|
| Ollama | Local model runtime | MIT | <https://ollama.com> |
| **IBM Granite 3.3 2B** (`granite3.3:2b`) | The one SI model the app uses (the Investigator) | **Apache-2.0** | <https://ollama.com/library/granite3.3> |

SpaceSweepers uses only this model. No other model is used, shipped or recommended.

All SI results stored in `data/` were produced by this model: the method flags, the pillar evidence and the BASS outcome labels each record `granite3.3:2b` in their `model` field. (An 8B Granite model may be installed locally for experiments; the app does not use it.) Regenerate any of them with `python -m app.nimbus.method`, `python -m app.nimbus.pillars` or `python -m app.nimbus.outcomes`.

---

## 6. Development, test and CI tools (not shipped)

| Tool | Use | License |
|---|---|---|
| pytest 9.1.1 (with pluggy, iniconfig, Pygments) | Unit tests | MIT (Pygments: BSD-2-Clause) |
| Semgrep Community Edition 1.180.0 | SAST | LGPL-2.1 |
| Bandit 1.9.4 | SAST (Python) | Apache-2.0 |
| pip-audit 2.10.1 | Dependency audit | Apache-2.0 |
| OSV-Scanner | Dependency audit | Apache-2.0 |
| Gitleaks | Secret scan | MIT |
| TruffleHog | Secret scan | AGPL-3.0 |
| Grype (`anchore/scan-action`) | Container image scan | Apache-2.0 (action: MIT) |
| cosign (`sigstore/cosign-installer`) | Image signing | Apache-2.0 |
| GitHub Actions: `actions/checkout`, `setup-python`, `upload-artifact`, `download-artifact`, `github/codeql-action` | CI | MIT |
| GitHub Actions: `docker/setup-buildx-action`, `metadata-action`, `login-action`, `build-push-action` | Image build | Apache-2.0 |
| Docker base image `python:3.14-slim` | Production image | PSF-2.0 (Python); Debian packages under their own free licenses |

### SI assistance in development
The code, documentation, tests and CI workflows were written with the help of **Claude Code** (Anthropic), an SI coding assistant, working with the team. The team directed and reviewed the work and checked it against live PSI data.

---

## Export control
SpaceSweepers contains no export-controlled information under ITAR or the EAR. It only uses public NASA research data and public open-source software.

## Keeping this list current
- After changing `requirements.txt`, update the package table above and regenerate `THIRD_PARTY_NOTICES.md` from the installed packages' own license files.
- After each PSI sync, update the investigation DOI and license table in section 2.
