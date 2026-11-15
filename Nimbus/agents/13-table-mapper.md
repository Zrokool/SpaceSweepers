---
name: table-mapper
stage: 13
kind: si-text
model: "granite3.3:2b (IBM Granite 3.3 2B, Apache-2.0)"
options: {temperature: 0, seed: 7}
reads: [one PSI test table: its column headers and the first three rows]
writes: [column pointers: which header holds the test id, fuel, oxygen, pressure and burn time. Never a value]
checked_by: app/nimbus/tables.py (rules M-1 to M-5); stored in the ledger app/psi/ledger.py
---

# Table mapper

PSI test tables come as CSV files with different headers. Code first finds the headers
that could hold each variable in the registry (`data/variables.yaml`). Only when two
headers both qualify does the Table mapper point at one of them. It never reads,
writes or changes a value, and it can say `none`. Code checks every pointer and writes
the mapping to the ledger (`data/table_mappings.json`), keyed by the table's file name
and SHA-256, so the dashboard's numbers still come only from the PSI file.

## How the pointers are checked (no SI)

| Rule | Check | If it fails |
|---|---|---|
| M-1 | The header exists in the table, and one header is not used for two quantities | pointer dropped |
| M-2 | The header itself states the unit: `mmHg`, `atm`, `bar`, `psi`, `kPa`, `torr` for pressure; `mole fraction`, `percent`, `%` for oxygen; seconds for burn time. A header without a unit is never guessed | pointer dropped |
| M-2b | If the header has no unit, the cells may state it themselves ("1 atm"): at least 95% of the filled cells must state one and the same unit | pointer dropped |
| M-3 | At least 80% of the non-blank rows parse as numbers in that column, and at least 95% of those fall inside physical limits (pressure 0.05 to 300 psi, oxygen 0 to 1 once converted) | pointer dropped |
| M-4 | An oxygen pointer is kept only when the table says the oxygen is the surrounding air: the word "ambient" appears in a header, and the oxygen header doesn't say stream, burner, oxidizer or flow. Otherwise the role is unknown and oxygen is not mapped | oxygen not mapped |
| M-5 | The test-id column has a value on every row and at least 90% of them are different | table not mapped |
| M-6 | An outcome column is mapped only if every raw value in it is defined in the registry's vocabulary for that outcome. Unknown values are reported and the column waits for review | outcome not mapped |
| M-8 | Gas columns (oxygen, nitrogen, helium, CO2) must add up to 1 within 0.03 in at least 95% of rows; that proves they are mole fractions of one mixture. Otherwise the minor gases are not mapped | minor gases dropped |

A table is mapped only with a valid test id and a valid oxygen or pressure pointer.
Everything else is recorded as "not mappable" with a reason code (`no_unit_in_header`,
`multi_value_cells`, `sparse_or_non_numeric`, `oxygen_role_unknown`, `no_condition_columns`,
`no_test_id`, `test_id_not_unique`). A mapping applies only to the exact table it was made
for: if the table's SHA-256 changes, the mapping is blocked ("stale") until it is mapped
again, and the dashboard shows "data refresh needed". Hand-reviewed mappings
(`data/mappings/PSI-*.yaml`, e.g. PSI-159) are never overwritten and win over the ledger.

## System prompt

```text
You are the Table mapper, a careful reader of NASA PSI test tables.
You are given one table: its column headers (numbered) and its first three rows.

You never read out, change or invent values. You only point at column headers.
For each quantity answer with the exact header text, or "none" if no header holds it.

- "test_id": the column that numbers or names each test or sample.
- "fuel": the column naming the fuel or material burned.
- "oxygen": the column with the oxygen amount in the air or gas mixture.
- "pressure": the column with the pressure.
- "burn_time": the column with how long it burned, in seconds.
- "nitrogen", "helium", "co2": the columns with the nitrogen, helium or carbon dioxide amount in the gas mixture.
- "diameter": the column with the starting droplet diameter.
- "end_state": the column saying how each flame ended (extinction, completion, disruption).
- "ignition": the column saying whether a flame lit.
- "extinction_mode": the column saying whether the flame went out by itself or was stopped.

Rules:
- Judge only from the headers and rows given.
- Answer "none" when you are not sure. A wrong pointer is worse than none.
```

## User message template

```text
Investigation: {id} — {title}
Table file: {file}

Column headers:
{headers}

First rows:
{rows}

Return JSON with every key of the schema. Each is a header or "none".
```

## Output schema

```json
{
  "type": "object",
  "properties": {
    "test_id": {"type": "string"},
    "fuel": {"type": "string"},
    "oxygen": {"type": "string"},
    "pressure": {"type": "string"},
    "burn_time": {"type": "string"},
    "nitrogen": {"type": "string"},
    "helium": {"type": "string"},
    "co2": {"type": "string"},
    "diameter": {"type": "string"},
    "end_state": {"type": "string"},
    "ignition": {"type": "string"},
    "extinction_mode": {"type": "string"}
  },
  "required": ["test_id", "fuel", "oxygen", "pressure", "burn_time", "nitrogen", "helium", "co2", "diameter", "end_state", "ignition", "extinction_mode"]
}
```
