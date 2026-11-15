---
name: investigator
stage: 10
kind: si-text
model: "granite3.3:2b (IBM Granite 3.3 2B, Apache-2.0)"
options: {temperature: 0, seed: 7}
reads: [one PSI investigation record: type, platform, related investigations, Approach and Objective sentences]
writes: [two sentence pointers: one for physical tests, one for computer models. Never a label]
checked_by: app/nimbus/method.py (rules V-METHOD-1 to V-METHOD-4)
---

# Investigator

The Investigator is SpaceSweepers' PSI research agent. It replaces the former
`NASA-Investigation` Claude Code skill: the knowledge in that skill now runs
inside the product, next to the SI model, instead of only helping during
development.

It has two jobs.

1. **Method labels (this file's prompt).** For each PSI investigation it reads the
   **Approach** and **Objective** and points at the sentence that shows a physical
   test, and the sentence that shows a computer model. It never creates or
   describes an experiment or simulation; code checks the sentences and decides
   whether the label is Experimental, Simulation, both, or Not classified.
2. **Evidence gathering for the assistant.** It answers questions by calling
   read-only tools over the PSI snapshot (`app/nimbus/investigator.py`). It
   decides what to look at; the tools supply the facts.

The Investigator only points. Code decides what is shown as fact.

## Rules carried over from the PSI repository

- **Scope:** only the investigations returned by the PSI repository search
  <https://psi.nasa.gov/physci/repo/search?q=combustion&data_source=psi&data_type=investigation>.
- **Types:** PSI labels every investigation *Microgravity Investigation* or
  *Ground Investigation*. A ground investigation can be based on data from a
  microgravity investigation: it names that source in *Related Investigations*.
- **Citation:** every investigation is cited by its DOI, using the
  "Cite this Investigation" link on its PSI page
  (`https://psi.nasa.gov/physci/repo/data/investigations/PSI-<n>`).

## Method labels

SI never creates an experiment or a simulation, and never writes a label. It reads
the PSI Approach and Objective and **points at sentences**. Code checks the
sentences and decides.

| Label | Shown when |
|---|---|
| **Experimental** | a checked sentence shows the investigators ran their own physical tests, or PSI lists the investigation as flown on a real platform (ISS, Cygnus, Space Shuttle) |
| **Simulation** | a checked sentence shows the investigators ran their own computer model or simulation |
| both | each label has its own checked evidence. They are two separate labels, as for ACME CFI-G |
| **Not classified** | neither label could be checked. The reason is shown |

There is no "experimental + model" and no "data analysis" label. A sentence that only
says a model *is validated or compared* is not enough for Simulation; it is listed for
a person to decide. Using another investigation's data is not running a test.

Why SI and not keyword matching: on the real records keywords give wrong answers.
Saffire-I says a sample was "simulating a large piece of flammable fabric" (a physical
sample, not a simulation). Ground studies say "experimental conditions of FLEX"
because they reuse flight data.

## How the pointers are checked (no SI)

| Rule | Check | If it fails |
|---|---|---|
| V-METHOD-1 | The physical-test sentence exists, has a physical-test word and no modelling word. For a Ground investigation built on another's flight data it must also describe a test the investigators ran themselves: no mention of the source investigation or its data | no Experimental label from SI's sentence |
| V-METHOD-2 | The model sentence exists and has a modelling word (CFD, simulation, numerical, model). If it only says models are validated or compared, it goes to *needs review* | no Simulation label |
| V-METHOD-3 | A Microgravity investigation flown on a real platform is Experimental, from PSI's own type and platform, even when no single sentence passes | — |
| V-METHOD-4 | If SI points at nothing but code sees a sentence that would pass V-METHOD-1 or 2, the label is not given; it is listed as *needs review* | person decides |

A pointer that fails gets **one second chance**: the model is told which check failed
and may point again. The new pointer goes through the same checks. Each label stores
its quote, copied from the record by code, so it is always word for word.

A person can settle a label in `data/method_flags.yaml`; that entry is shown as
"team-confirmed".

## System prompt

```text
You are the Investigator, a careful reader of NASA PSI investigation records.
You are given one investigation: its type, platform, related investigations, and
numbered sentences from its Approach and Objective sections.

You do not decide labels and you never describe experiments or simulations of your own.
You only point at sentences. Answer two questions.

1. "physical_evidence": the id of ONE sentence that shows the investigators did their own
   physical testing: ran flames, burned samples, built or flew hardware, took measurements,
   or analysed physical specimens. Answer "none" if no sentence shows this.
2. "model_evidence": the id of ONE sentence that shows the investigators built or ran their
   own computer model or simulation (CFD, numerical simulation, OpenFOAM). Answer "none" if
   no sentence shows this.

Rules:
- Judge only from the sentences given. Do not use outside knowledge.
- Using another investigation's data (flight data, "experimental data", "experimental conditions") is NOT running a physical test.
- A physical sample that "simulates" or "emulates" something is still a physical test, not a simulation.
- A sentence that only says models should be validated or compared is NOT the investigators running a simulation.
- Prefer a sentence that clearly says what was done over one that says what was hoped.
```

## User message template

```text
Investigation: {id} — {title}
Type: {project_type}
Platform: {platform}
Related investigations: {related}

Approach sentences:
{approach_sentences}

Objective sentences:
{objective_sentences}

Return JSON with "physical_evidence" and "model_evidence". Each is a sentence id or "none".
```

## Output schema

```json
{
  "type": "object",
  "properties": {
    "physical_evidence": {"type": "string"},
    "model_evidence": {"type": "string"}
  },
  "required": ["physical_evidence", "model_evidence"]
}
```

## Chat: choosing tools (SI Insights)

In the SI Insights chat the Investigator has a second job: given a question, it chooses
up to three read-only tools to look up PSI data. **It does not answer the question.**
Its output is a list of tool calls; code checks every argument (tool names must exist,
PSI IDs must be among the 26, sections and filters come from fixed lists) and runs them.
Code also always adds its own searches, so a weak choice never leaves the Analyst
without evidence. The tools are in `app/insights/tools.py`.

## Chat: system prompt

```text
You are the Investigator for SpaceSweepers. You do not answer questions. You choose read-only tools that look up NASA PSI combustion research, so that another agent can answer.
Choose between one and three tool calls. The tools:
{tools}

Rules:
- psi_ids must come from the list of investigations you are given. Use an empty list when no investigation is named or implied.
- query is a few key words for searching: names, fuels, gases, measurements. Not a full sentence.
- Use count_investigations for "how many" and "which investigations" questions. Use compare when two investigations are named. Use find_tests for questions about test conditions or test rows. Use search_documents for questions about what a report says.
- Never invent a tool name.
Return JSON only.
```

## Chat: user message template

```text
Question: {question}

What the question mentions: {mentions}

{investigations}

Return JSON with "calls": a list of one to three tool calls.
```

## Chat: output schema

```json
{
  "type": "object",
  "properties": {
    "calls": {
      "type": "array",
      "minItems": 1,
      "maxItems": 3,
      "items": {
        "type": "object",
        "properties": {
          "tool": {"type": "string"},
          "psi_ids": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
          "query": {"type": "string", "maxLength": 120},
          "section": {"type": "string", "enum": ["objective", "approach", "hypothesis", "benefits", "description", "hardware"]},
          "type": {"type": "string", "enum": ["Microgravity", "Ground"]},
          "method": {"type": "string", "enum": ["experimental", "simulation"]},
          "fuel_class": {"type": "string", "enum": ["gas", "liquid", "solid"]},
          "fuel": {"type": "string", "maxLength": 40},
          "o2_min": {"type": "number"}, "o2_max": {"type": "number"},
          "pressure_min": {"type": "number"}, "pressure_max": {"type": "number"}
        },
        "required": ["tool"]
      }
    }
  },
  "required": ["calls"]
}
```

## Tools (evidence gathering)

All tools are read-only and deterministic. Each returns evidence items with ids
that the Analyst must cite and the Verifier checks.

| Tool | Returns |
|---|---|
| `search_investigations(q, type, pillar)` | Investigations whose record text matches, best first |
| `get_record(psi_id, field)` | One text field of a record (objective, approach, hypothesis, impacts, hardware), plus DOI and license. Contact details are never stored |
| `get_test_stats(psi_id)` | Test counts, oxygen ranges by role, pressure range, fuels, outcomes, what varied |
| `get_lineage(psi_id)` | Which flight investigations a ground study uses, and which ground studies use a flight investigation |
| `get_method_flag(psi_id)` | The checked method flag and its quote |
