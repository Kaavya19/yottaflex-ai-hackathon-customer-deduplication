# ClearMerge — Customer Record Deduplication

ClearMerge is a small, reproducible data engineering pipeline for identifying duplicate customer records. It favors explainability: **only exact normalized email or phone matches are auto-merged**. Similar names with corroborating evidence are sent to a human review queue. Invalid input is retained with reject reasons. Every merged entity carries source lineage.

## Quick start

Requires Python 3.10+. The runtime uses only the Python standard library; pytest is needed only for tests.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m clearmerge.cli --input data/sample_customers.csv --output outputs
pytest
```

Without installing the package, run with `PYTHONPATH=src python -m clearmerge.cli`. The run writes `merged_customers.csv`, `review_queue.csv`, `rejected_records.csv`, `lineage.csv`, `run_report.json`, and `clearmerge.sqlite` in the output directory.

## Architecture

```text
CSV source → schema gate → row validation/quarantine → normalize keys
                                                ↓
                         exact email/phone groups → survivorship merge
                         fuzzy blocked candidates → human review queue
                                                ↓
              CSV snapshots + SQLite run history/current outputs + metrics
```

The command exits non-zero on an unexpected schema or processing failure and writes a failure report with the run ID and reason. On success, output CSVs and current-state SQLite tables are replaced as one logical snapshot. SQLite `run_history` retains each successful run. This gives safe repeatable output on retry while preserving operational history. Keep source files immutable for backfills and pass the desired file explicitly.

## Data and rules

Input grain is one source-system customer record. Required fields: `source_record_id`, `source_system`, `name`, `email`, `phone`, `address`, `updated_at`; optional: `email_verified`. `source_record_id` must be unique within a file. Name, source system, and source record ID are required. Email and phone may be blank; when supplied they must be well-formed. Timestamps accept ISO-8601; timestamps without timezone are treated as UTC for ordering. Unexpected or missing columns fail the whole batch. Bad rows are quarantined with line number and reason. Blank address is allowed.

Normalization trims/lowercases email and strips punctuation from phone (also removes a leading US country code `1` from 11-digit values). Exact links on email **or** phone are transitively grouped. Candidate review uses a first-four-character normalized-name block or last-four-phone block; name similarity must be at least 0.78 and a matching phone or address must corroborate it. A shared email domain contributes only a small score because common domains are weak evidence. Scores are prioritization aids, not probabilities. Fuzzy matches are never auto-merged. Large blocks are bounded to avoid explosive pair generation; this can miss candidates in unusually common-name data.

Survivorship is field-level and deterministic: verified-email records rank first, then newest valid `updated_at`, then lexicographically descending source ID. For each field, the first nonblank value wins. `*_survivor_source_id` records the source for each chosen field. Entity IDs are SHA-256-derived from the sorted member source IDs, so reruns and input ordering do not change them. Reuse of the same source IDs for different people across separate extracts is outside this starter's identity scope.

See [docs/data_dictionary.md](docs/data_dictionary.md) for columns, constraints, relationships, and output grain. Expected-answer labels are not included in input data.

## Reproducible data and scale

`data/sample_customers.csv` is synthetic and deliberately includes an exact duplicate, a probable match, null optional values, and invalid records. Generate a deterministic larger file:

```bash
PYTHONPATH=src python -m clearmerge.generate --rows 100000 --seed 42 --output data/generated_customers.csv
PYTHONPATH=src python -m clearmerge.cli --input data/generated_customers.csv --output outputs/large
```

The generator includes duplicate pairs, optional blanks, and labeled-by-pattern invalid rows (the invalidity is in the data, not an expected-answer label). No external data or credentials are used.

## Correctness and operations

Run `pytest` for happy path, empty batch, malformed schema, invalid fields, duplicate source keys, exact match survivorship/lineage, reproducible generator, and rerun safety. `docs/validation.sql` contains example reconciliation queries against SQLite. The run report records run ID, UTC start, input hash, counts, schema version, and elapsed time. Input count reconciles as `valid_rows + rejected_rows`; lineage rows reconcile to valid source rows; merged count equals exact duplicate groups collapsed plus unmatched valid rows.

For retry, rerun the same command: deterministic CSV snapshots are replaced, while `run_history` adds an attempt. A failed run does not publish partial current tables (the CSV snapshot is written after all matching logic succeeds). For backfill, rerun against the archived source file and a dedicated output/database path to preserve the prior snapshot.

## Performance and trade-offs

The sample is optimized for clarity and standard-library portability. Candidate matching uses blocking rather than an all-pairs comparison, and exact keys use hash maps. On the included environment (Python 3.13, Windows), the fixed-seed 100,000-row synthetic run took 42.7 seconds end-to-end; its reproducible run report is [outputs/large/run_report.json](outputs/large/run_report.json). The largest remaining cost is Python object memory when reading a very large CSV. A reasonable next optimization is chunked ingestion with persisted normalized keys/candidate blocks in SQLite; for production fuzzy matching, use a reviewed, language-aware library and calibrated labeled data. This implementation deliberately avoids probabilistic auto-merges and is not a cross-file master-data registry.

## Project layout

```text
src/clearmerge/  reusable pipeline, CLI, synthetic generator
data/            synthetic starter input
tests/           automated acceptance and edge-case tests
docs/            data dictionary, design note, SQL checks
outputs/         generated local run artifacts (ignored by Git)
```

See [docs/design.md](docs/design.md) for the design/trade-off note.
