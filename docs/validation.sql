-- Run with: sqlite3 outputs/clearmerge.sqlite < docs/validation.sql
-- Counts reconcile to the run report for the successful input snapshot.
SELECT 'merged_entities' AS check_name, COUNT(*) AS observed FROM merged_customers;
SELECT 'review_pairs' AS check_name, COUNT(*) AS observed FROM review_queue;
SELECT 'rejected_rows' AS check_name, COUNT(*) AS observed FROM rejected_records;
SELECT 'lineage_rows' AS check_name, COUNT(*) AS observed FROM lineage;
SELECT 'sources_in_entities' AS check_name, SUM(CAST(source_count AS INTEGER)) AS observed FROM merged_customers;
-- Every published entity has at least one source lineage row.
SELECT m.entity_id FROM merged_customers m
LEFT JOIN lineage l USING (entity_id)
GROUP BY m.entity_id HAVING COUNT(l.source_record_id) = 0;
-- Detect duplicate entity keys (must return no rows).
SELECT entity_id, COUNT(*) FROM merged_customers GROUP BY entity_id HAVING COUNT(*) > 1;

