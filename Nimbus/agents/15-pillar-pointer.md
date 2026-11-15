---
name: pillar-pointer
stage: 15
kind: si-text
model: "granite3.3:2b (IBM Granite 3.3 2B, Apache-2.0)"
options: {temperature: 0, seed: 7}
reads: [one PSI investigation record: Research Impacts, Objective, Hypothesis and Approach sentences, with the candidates code found for each pillar]
writes: [for each fire-safety pillar, the id of one sentence that shows the research informs it, or none. Never a label or a score]
checked_by: app/nimbus/pillars.py (rules P-1 to P-4)
---

# Pillar pointer

NASA divides spacecraft fire safety into three pillars: **prevention** (keeping a fire from
starting or growing: material flammability, ignition, flame spread, safe atmospheres),
**detection** (smoke and combustion-product sensing) and **suppression** (putting a fire out:
extinguishment, suppressant agents, extinction limits).

The Investigator's keyword counts could not tell research *about* a pillar from a record that
merely used a word ("material" for a sample, "extinction" for a droplet). The Pillar pointer
reads the record the way a person would and **points at the sentence** that shows the research
informs a pillar. It never writes a label or a score: code finds the candidate sentences, checks
the pointer, and scores from the verified quote and from measured results.

## How the pointers are checked (no SI)

| Rule | Check | If it fails |
|---|---|---|
| P-1 | The sentence is one of the candidates code found for that pillar: it is in the record's Research Impacts, Objective, Hypothesis or Approach and contains one of the pillar's cue words (`pillar_cues` in `data/vocabulary.yaml`) | no evidence for that pillar |
| P-2 | The cue word is not negated ("not", "no", "never", "without" within four words before it) | the sentence is not a candidate |
| P-3 | Outside Research Impacts, the sentence states a purpose or an activity (improve, determine, measure, develop, evaluate…) and is not about earlier work ("based on", "previously"). Approach sentences, which describe how a test is run, are candidates only when no Impacts, Objective or Hypothesis sentence fits | the sentence is not a candidate |
| P-4 | The investigation is combustion research (PSI's research area). Others get "not applicable" | no pillars |

A pillar is shown only with its quoted sentence. Measured results add a separate **data link**
(for example FLEX's extinction outcomes for suppression), computed by code from the tests. The
team can settle a pillar in `data/pillar_evidence.yaml`; that entry is shown as "team-confirmed".

## System prompt

```text
You are the Pillar reader, a careful reader of NASA PSI investigation records.
You are given numbered sentences from one investigation and, for each fire-safety pillar, the
ids of sentences that contain one of its cue words.

The pillars:
- prevention: keeping a fire from starting or growing (material flammability, ignition, flame spread, safe oxygen and pressure limits).
- detection: sensing a fire early (smoke, particles, detectors, combustion products).
- suppression: putting a fire out (extinguishment, suppressant agents, extinction limits).

For each pillar answer with the id of ONE sentence that shows the research informs that pillar's
fire-safety work, or "none".

Rules:
- Judge only from the sentences given. Do not use outside knowledge.
- Pick a sentence only if it says what the research does or provides for that pillar. A sentence that uses a cue word for another purpose does not count.
- Prefer a sentence from Research Impacts (ids start with I) when it fits, then Objective (O).
- Answer "none" when no listed sentence fits. A wrong pointer is worse than none.
```

## User message template

```text
Investigation: {id} — {title}
Type: {project_type}

Sentences:
{sentences}

Candidates (ids of sentences that contain a cue word for the pillar):
PREVENTION: {prevention}
DETECTION: {detection}
SUPPRESSION: {suppression}

Return JSON with "prevention", "detection" and "suppression". Each is a sentence id from that pillar's candidates, or "none".
```

## Output schema

```json
{
  "type": "object",
  "properties": {
    "prevention": {"type": "string"},
    "detection": {"type": "string"},
    "suppression": {"type": "string"}
  },
  "required": ["prevention", "detection", "suppression"]
}
```
