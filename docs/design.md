# Design and trade-off note

## Decisions

- Customer entity only, file-based CSV input, standard-library Python, and local SQLite keep setup fast and reproducible.
- Exact normalized email/phone links can merge automatically. Probable matches require corroborating evidence and go to review; this limits false-positive merges.
- Field-level survivorship ranks verified records, then recency, then a stable ID tie-break. Each chosen field records its winning source.
- Invalid rows are not discarded. Schema drift fails the batch; row-level faults are quarantined with source file and line.
- Run history is append-only; published tables and CSVs are current-state snapshots. Deterministic IDs and replacement snapshots make retries idempotent at the output level.

## Limits and next steps

This is a single-file batch demonstrator, not a multi-tenant identity graph. There is no manual review UI, cross-batch key registry, language-specific name parsing, calibrated probability model, or chunked streaming. Similarity thresholds need labeled examples and business approval before broader use. A next step for larger volume is chunked staging and persistent blocking indexes in SQLite, then query-plan/benchmark comparison. Late arriving data is handled by rerunning the source snapshot; source event history is not inferred or overwritten in an audit table.

## Failure/recovery

Unexpected columns or missing required headers fail early and record a failure report. Invalid rows do not fail the batch. A failed processing attempt does not replace successful SQLite output tables; successful retries create a new run-history row. To backfill, retain original files and use a separate output path/database for isolated review.

