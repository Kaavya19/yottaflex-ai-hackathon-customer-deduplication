import csv
import json
from pathlib import Path

import pytest

from clearmerge.generate import generate
from clearmerge.pipeline import run_pipeline


@pytest.fixture
def sample():
    return Path(__file__).parents[1] / "data" / "sample_customers.csv"


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_sample_reconciles_and_writes_all_outputs(tmp_path, sample):
    metrics = run_pipeline(sample, tmp_path)
    assert metrics["input_rows"] == metrics["valid_rows"] + metrics["rejected_rows"]
    assert metrics["valid_rows"] == 9
    assert metrics["rejected_rows"] == 2
    assert metrics["merged_records"] == 8
    assert metrics["exact_duplicate_groups"] == 1
    assert metrics["probable_pairs_for_review"] >= 1
    assert {p.name for p in tmp_path.iterdir()} >= {
        "merged_customers.csv", "review_queue.csv", "rejected_records.csv", "lineage.csv", "run_report.json", "clearmerge.sqlite"
    }


def test_verified_latest_value_survives_exact_group(tmp_path, sample):
    run_pipeline(sample, tmp_path)
    merged = read_csv(tmp_path / "merged_customers.csv")
    asha = next(r for r in merged if "crm-001" in r["source_record_ids"])
    assert asha["source_count"] == "2"
    assert asha["email_survivor_source_id"] == "web-014"
    lineage = read_csv(tmp_path / "lineage.csv")
    assert {r["source_record_id"] for r in lineage if r["entity_id"] == asha["entity_id"]} == {"crm-001", "web-014"}
    assert len(lineage) == 9


def test_invalid_and_anomalous_records_are_traceable(tmp_path, sample):
    run_pipeline(sample, tmp_path)
    rejects = read_csv(tmp_path / "rejected_records.csv")
    assert {r["source_record_id"] for r in rejects} == {"crm-006", "crm-007"}
    assert any("invalid_updated_at" in r["reject_reason"] for r in rejects)
    assert any("missing_required_name" in r["reject_reason"] for r in rejects)


def test_rerun_replaces_outputs_but_records_each_run(tmp_path, sample):
    first = run_pipeline(sample, tmp_path)
    first_output = (tmp_path / "merged_customers.csv").read_bytes()
    second = run_pipeline(sample, tmp_path)
    assert first["run_id"] != second["run_id"]
    assert (tmp_path / "merged_customers.csv").read_bytes() == first_output
    import sqlite3
    with sqlite3.connect(tmp_path / "clearmerge.sqlite") as conn:
        assert conn.execute("select count(*) from run_history").fetchone()[0] == 2


def test_empty_input_is_valid(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_text("source_record_id,source_system,name,email,phone,address,updated_at\n", encoding="utf-8")
    metrics = run_pipeline(source, tmp_path / "out")
    assert metrics["input_rows"] == metrics["merged_records"] == metrics["rejected_rows"] == 0
    assert (tmp_path / "out" / "merged_customers.csv").read_text(encoding="utf-8") == ""


def test_unexpected_schema_fails_with_failure_report(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("source_record_id,name,unexpected\nx,A,B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected schema"):
        run_pipeline(source, tmp_path / "out")
    report = json.loads((tmp_path / "out" / "run_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "Unexpected schema" in report["failure_reason"]


def test_duplicate_event_key_quarantines_second_row(tmp_path):
    source = tmp_path / "duplicate.csv"
    source.write_text(
        "source_record_id,source_system,name,email,phone,address,updated_at\n"
        "same,crm,Alex Test,alex@example.test,4155550123,1 Main,2026-01-01T00:00:00Z\n"
        "same,web,Alex Test,alex@example.test,4155550123,1 Main,2026-01-02T00:00:00Z\n",
        encoding="utf-8",
    )
    metrics = run_pipeline(source, tmp_path / "out")
    assert metrics["valid_rows"] == 1
    assert metrics["rejected_rows"] == 1
    assert "duplicate_source_record_id" in read_csv(tmp_path / "out" / "rejected_records.csv")[0]["reject_reason"]


def test_malformed_row_column_count_is_quarantined(tmp_path):
    source = tmp_path / "malformed.csv"
    source.write_text(
        "source_record_id,source_system,name,email,phone,address,updated_at\n"
        "ok,crm,Alex Test,alex@example.test,4155550123,1 Main,2026-01-01T00:00:00Z,extra\n",
        encoding="utf-8",
    )
    metrics = run_pipeline(source, tmp_path / "out")
    assert metrics["valid_rows"] == 0
    assert "malformed_column_count" in read_csv(tmp_path / "out" / "rejected_records.csv")[0]["reject_reason"]


def test_generator_is_reproducible_and_scales(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generate(a, 500, 7)
    generate(b, 500, 7)
    assert a.read_bytes() == b.read_bytes()
    rows = read_csv(a)
    assert len(rows) == 500
    assert any(r["email"] == "not-an-email" for r in rows)

