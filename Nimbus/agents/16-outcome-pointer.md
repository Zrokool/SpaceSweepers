---
name: outcome-pointer
stage: 16
kind: si-text
model: "granite3.3:2b (IBM Granite 3.3 2B, Apache-2.0)"
options: {temperature: 0, seed: 7}
reads: [one test's free-text observations (BASS as-run matrix), split into numbered sentences, with the ids of sentences that contain an ignition or burning cue]
writes: [the id of one sentence that states whether the sample ignited and burned, or none. Never an outcome label]
checked_by: app/nimbus/outcomes.py (rules O-1 to O-4)
---

# Outcome pointer

Some PSI tables record a test's outcome only as free text. BASS's as-run matrix has an
"observations and anomalies" note for each run. The Outcome pointer **points at the sentence**
that says whether the sample ignited and burned. It never writes an outcome: code reads the
class from the pointed-at sentence and keeps the quote.

Two outcomes only, because they are the only ones that are comparable from the text:
`burned` (it ignited and burned) and `no_ignition` (it did not ignite). What happened after
ignition (blow-off, extinguishing by turning the fan or nitrogen on) is part of the procedure
and is not classified.

## How the pointer is checked (no SI)

| Rule | Check | If it fails |
|---|---|---|
| O-1 | The sentence is one of the candidates code found: it contains an ignition or burning cue (`ignited`, `burn`, `spread`, or a negated ignition phrase such as `did not ignite`) | no outcome |
| O-2 | The class comes from that sentence alone: a negated ignition phrase is `no_ignition`; otherwise an ignition or burning word that is not itself negated is `burned` | no outcome |
| O-3 | No other sentence of the same observation gives the opposite class. A note that says both "did not ignite" and "burned" is a contradiction a person must read | left unlabelled, listed for review |
| O-4 | The class and the quoted sentence are stored against the table row and the table's SHA-256. If the table changes, the outcome is not applied (data refresh needed) | not applied |

These outcomes are **document-derived**: they are counted and drawn in Flame Sweeper as their
own layer, and are **never** part of its model, skill check or patterns.

## System prompt

```text
You are the Outcome reader, a careful reader of lab notes from NASA PSI test tables.
You are given the numbered sentences of one test's observation note, and the ids of the
sentences that contain an ignition or burning word.

Answer with the id of ONE sentence that states whether the sample ignited and burned
(for example "ignited and burned for 40 s", "steady spreading", or "did not ignite"),
or "none".

Rules:
- Judge only from the sentences given.
- What happened after ignition (blow-off, turning the fan or nitrogen on or off to extinguish) is not the answer.
- Camera, igniter or setup remarks are not the answer.
- Answer "none" when no listed sentence states the ignition outcome. A wrong pointer is worse than none.
```

## User message template

```text
Test: {test}
Material: {material}

Sentences:
{sentences}

Candidates (ids of sentences that contain an ignition or burning word): {candidates}

Return JSON with "evidence": a sentence id from the candidates, or "none".
```

## Output schema

```json
{
  "type": "object",
  "properties": {
    "evidence": {"type": "string"}
  },
  "required": ["evidence"]
}
```
