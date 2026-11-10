# Data dictionary

All column names are snake_case. Input timestamps are ISO-8601; run timestamps are UTC ISO-8601. CSV blanks represent null/missing values. Source records are immutable input facts; output IDs are deterministic for a given group.

## Input: `customers.csv`

| Column | Type | Nullability | Key / rule | Meaning |
|---|---|---:|---|---|
| `source_record_id` | string | No | Unique within batch | Stable ID assigned by source |
| `source_system` | string | No | — | Source name, e.g. `crm` |
| `name` | string | No | Required nonblank | Customer display name |
| `email` | string | Yes | Valid email if present | Source email |
| `phone` | string | Yes | 7–15 digits after normalization if present | Source phone |
| `address` | string | Yes | — | Source mailing address |
| `updated_at` | ISO-8601 string | Yes | Parsed if present | Source update time |
| `email_verified` | boolean string | Yes | Optional; true/1/yes means true | Trust signal used by survivorship |

Relationships: each source record belongs to exactly one output entity (entity-to-source is 1:N). Invalid records have no entity assignment and remain in reject output. The sample has no external reference keys; reference integrity is therefore not applicable.

## Outputs

| Dataset | Grain / key | Important columns |
|---|---|---|
| `merged_customers.csv` | One row per entity; `entity_id` | Surviving business fields, `source_record_ids`, count, per-field survivor source IDs |
| `review_queue.csv` | One candidate pair; record ID pair | Similarity score, evidence reasons, pending status; no auto-merge |
| `rejected_records.csv` | One rejected input row; source ID + source line | Original values, source file/line, semicolon-separated `reject_reason` |
| `lineage.csv` | One output entity/source record pair | Entity ID, source key/system/file/line, run ID |
| SQLite `run_history` | One pipeline attempt; `run_id` | UTC start, status, serialized metrics |
| SQLite output tables | Same grain as corresponding CSV | Current successful snapshot |

Derived `entity_id` is `cus_` + first 16 hex characters of SHA-256 over the sorted source IDs joined with `|`. Inputs should avoid `|` in IDs. `match_score` is a deterministic heuristic for review prioritization, not a calibrated probability.

