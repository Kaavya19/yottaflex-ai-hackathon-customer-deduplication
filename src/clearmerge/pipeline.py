"""Deterministic customer deduplication with review and lineage outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

LOGGER = logging.getLogger("clearmerge")
REQUIRED = ("source_record_id", "source_system", "name", "email", "phone", "address", "updated_at")
OPTIONAL = ("email_verified",)
ALLOWED = set(REQUIRED + OPTIONAL)
SCHEMA_VERSION = "1.0"


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def normalize_email(value: str) -> str:
    return (value or "").strip().casefold()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    valid: list[dict[str, str]] = []
    rejects: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not set(REQUIRED).issubset(headers) or set(headers) - ALLOWED:
            raise ValueError(f"Unexpected schema. Required={list(REQUIRED)} optional={list(OPTIONAL)} received={headers}")
        seen: set[str] = set()
        for line, raw in enumerate(reader, start=2):
            if None in raw or any(raw.get(column) is None for column in headers):
                rejects.append({"source_record_id": (raw.get("source_record_id") or "").strip(),
                                "source_system": (raw.get("source_system") or "").strip(),
                                "name": (raw.get("name") or "").strip(), "email": (raw.get("email") or "").strip(),
                                "phone": (raw.get("phone") or "").strip(), "address": (raw.get("address") or "").strip(),
                                "updated_at": (raw.get("updated_at") or "").strip(),
                                "email_verified": (raw.get("email_verified") or "").strip(),
                                "source_file": path.name, "source_line": str(line),
                                "reject_reason": "malformed_column_count"})
                continue
            record = {key: (raw.get(key) or "").strip() for key in REQUIRED + OPTIONAL}
            record["source_file"] = path.name
            record["source_line"] = str(line)
            record["email_verified"] = record["email_verified"].casefold() in {"true", "1", "yes"}
            problems = []
            if not record["source_record_id"]:
                problems.append("missing_source_record_id")
            elif "|" in record["source_record_id"]:
                problems.append("invalid_source_record_id_delimiter")
            elif record["source_record_id"] in seen:
                problems.append("duplicate_source_record_id")
            else:
                seen.add(record["source_record_id"])
            if not record["source_system"]:
                problems.append("missing_source_system")
            if not record["name"]:
                problems.append("missing_required_name")
            email = normalize_email(record["email"])
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                problems.append("invalid_email")
            phone = normalize_phone(record["phone"])
            if phone and not 7 <= len(phone) <= 15:
                problems.append("invalid_phone")
            if record["updated_at"]:
                try:
                    datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
                except ValueError:
                    problems.append("invalid_updated_at")
            if problems:
                rejects.append({**record, "reject_reason": ";".join(problems)})
            else:
                record["email_norm"] = email
                record["phone_norm"] = phone
                record["name_norm"] = normalize_text(record["name"])
                record["address_norm"] = normalize_text(record["address"])
                valid.append(record)
    return valid, rejects, digest


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _exact_groups(rows: list[dict]) -> list[list[int]]:
    uf = _UnionFind(len(rows))
    keys: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows):
        for kind in ("email", "phone"):
            value = row[f"{kind}_norm"]
            if value:
                key = (kind, value)
                if key in keys:
                    uf.union(i, keys[key])
                else:
                    keys[key] = i
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(rows)):
        groups[uf.find(i)].append(i)
    return [members for members in groups.values() if len(members) > 1]


def _probable_pairs(rows: list[dict], exact_groups: list[list[int]]) -> list[dict]:
    blocked: dict[str, set[int]] = defaultdict(set)
    for i, row in enumerate(rows):
        name = row["name_norm"]
        if len(name) >= 4:
            blocked[name[:4]].add(i)
        phone = row["phone_norm"]
        if len(phone) >= 4:
            blocked["p:" + phone[-4:]].add(i)
    exact_member = {i for group in exact_groups for i in group}
    candidates: set[tuple[int, int]] = set()
    for members in blocked.values():
        if len(members) <= 200:
            ordered = sorted(members)
            candidates.update((a, b) for pos, a in enumerate(ordered) for b in ordered[pos + 1:])
        else:
            # Avoid pathological blocks; bounded local comparisons remain deterministic.
            ordered = sorted(members, key=lambda i: rows[i]["source_record_id"])
            for pos, a in enumerate(ordered):
                candidates.update((a, b) for b in ordered[pos + 1:pos + 21])
    result = []
    for a, b in sorted(candidates):
        if a in exact_member and b in exact_member:
            continue
        x, y = rows[a], rows[b]
        name_score = SequenceMatcher(None, x["name_norm"], y["name_norm"]).ratio() if x["name_norm"] and y["name_norm"] else 0
        same_phone = bool(x["phone_norm"] and x["phone_norm"] == y["phone_norm"])
        same_email_domain = bool(x["email_norm"] and y["email_norm"] and x["email_norm"].split("@")[-1] == y["email_norm"].split("@")[-1])
        same_address = bool(x["address_norm"] and x["address_norm"] == y["address_norm"])
        score = min(0.99, 0.60 * name_score + 0.25 * same_phone + 0.10 * same_address + 0.05 * same_email_domain)
        # A shared email domain is common in synthetic and business data, so it only
        # contributes a small score. Require stronger phone/address evidence to queue.
        if name_score >= 0.78 and (same_phone or same_address):
            result.append({"record_id_a": x["source_record_id"], "record_id_b": y["source_record_id"],
                           "match_score": round(score, 4), "match_reason": ";".join(
                               ["similar_name" if name_score >= 0.78 else "", "same_phone" if same_phone else "",
                                "same_address" if same_address else "", "same_email_domain" if same_email_domain else ""]
                           ).strip(";"), "review_status": "pending"})
    return result


def _timestamp(row: dict) -> float:
    try:
        dt = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return 0.0


def _merge(group: list[dict]) -> dict:
    # The entity ID is derived from sorted source keys; it is stable across reruns and input order.
    ids = sorted(row["source_record_id"] for row in group)
    entity_id = "cus_" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
    ordered = sorted(group, key=lambda r: (bool(r["email_verified"]), _timestamp(r), r["source_record_id"]), reverse=True)
    result = {"entity_id": entity_id, "source_record_ids": "|".join(ids), "source_count": len(group)}
    for field in ("name", "email", "phone", "address"):
        winner = next((r[field] for r in ordered if r[field]), "")
        result[field] = winner
        result[field + "_survivor_source_id"] = next((r["source_record_id"] for r in ordered if r[field]), "")
    result["updated_at"] = max((r["updated_at"] for r in group), key=lambda value: _timestamp({"updated_at": value}), default="")
    return result


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_pipeline(input_path: str | Path, output_dir: str | Path, db_path: str | Path | None = None) -> dict:
    start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = str(uuid.uuid4())
    source = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows, rejects, input_hash = _read_csv(source)
        groups = _exact_groups(rows)
        grouped_indices = {i for group in groups for i in group}
        merged = [_merge([rows[i] for i in group]) for group in groups]
        merged.extend(_merge([row]) for i, row in enumerate(rows) if i not in grouped_indices)
        review = _probable_pairs(rows, groups)
        row_by_id = {row["source_record_id"]: row for row in rows}
        lineage = [{"entity_id": record["entity_id"], "source_record_id": source_id,
                    "source_system": row_by_id[source_id]["source_system"], "source_file": row_by_id[source_id]["source_file"],
                    "source_line": row_by_id[source_id]["source_line"], "run_id": run_id}
                   for record in merged for source_id in record["source_record_ids"].split("|")]
        metrics = {"run_id": run_id, "status": "success", "started_at": started_at,
                   "input_file": source.name, "input_sha256": input_hash, "input_rows": len(rows) + len(rejects),
                   "valid_rows": len(rows), "merged_records": len(merged), "exact_duplicate_groups": len(groups),
                   "probable_pairs_for_review": len(review), "rejected_rows": len(rejects),
                   "elapsed_seconds": round(time.perf_counter() - start, 6), "schema_version": SCHEMA_VERSION}
        # CSV outputs are replaced deterministically on every successful rerun.
        for name, dataset in (("merged_customers.csv", merged), ("review_queue.csv", review), ("rejected_records.csv", rejects), ("lineage.csv", lineage)):
            _write_csv(out / name, dataset)
        metrics["elapsed_seconds"] = round(time.perf_counter() - start, 6)
        (out / "run_report.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        database = Path(db_path) if db_path else out / "clearmerge.sqlite"
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS run_history (run_id TEXT PRIMARY KEY, started_at TEXT, status TEXT, metrics_json TEXT)")
            conn.execute("INSERT INTO run_history VALUES (?, ?, ?, ?)", (run_id, started_at, "success", json.dumps(metrics, sort_keys=True)))
            for table, dataset in (("merged_customers", merged), ("review_queue", review), ("rejected_records", rejects), ("lineage", lineage)):
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
                if dataset:
                    columns = list(dataset[0])
                    conn.execute(f'CREATE TABLE "{table}" ({", ".join(chr(34)+c+chr(34)+" TEXT" for c in columns)})')
                    conn.executemany(f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in columns)})',
                                     [[str(record.get(col, "")) for col in columns] for record in dataset])
                else:
                    conn.execute(f'CREATE TABLE "{table}" (empty_batch INTEGER)')
            conn.commit()
        LOGGER.info("run_id=%s status=success input=%d merged=%d review=%d rejected=%d",
                    run_id, metrics["input_rows"], len(merged), len(review), len(rejects))
        return metrics
    except Exception as exc:
        metrics = {"run_id": run_id, "status": "failed", "started_at": started_at,
                   "input_file": source.name, "failure_reason": str(exc),
                   "elapsed_seconds": round(time.perf_counter() - start, 6), "schema_version": SCHEMA_VERSION}
        (out / "run_report.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        LOGGER.exception("run_id=%s status=failed reason=%s", run_id, exc)
        raise

