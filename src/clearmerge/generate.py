"""Reproducible synthetic customer data generator."""
from __future__ import annotations
import argparse
import csv
import random
from pathlib import Path

FIRST = ["Asha", "Rahul", "Maya", "Noah", "Isha", "Liam", "Nina", "Omar", "Priya", "Ethan"]
LAST = ["Kumar", "Shah", "Patel", "Reed", "Chen", "Singh", "Diaz", "Brooks", "Rao", "Kim"]
FIELDS = ["source_record_id", "source_system", "name", "email", "phone", "address", "updated_at", "email_verified"]

def generate(path: str | Path, count: int = 1000, seed: int = 42) -> None:
    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    rows = []
    base_count = max(1, int(count * 0.88))
    for i in range(base_count):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        rows.append({"source_record_id": f"crm-{i:07d}", "source_system": "crm",
                     "name": f"{first} {last}", "email": f"{first}.{last}.{i}@example.test".lower(),
                     "phone": f"+1-555-{i // 10000:01d}-{i % 10000:04d}",
                     "address": f"{100 + i} Sample Street, Test City", "updated_at": f"2026-01-{i % 28 + 1:02d}T09:00:00Z",
                     "email_verified": "true" if i % 3 == 0 else "false"})
    for j in range(count - base_count):
        original = rows[j % len(rows)]
        duplicate = dict(original)
        duplicate["source_record_id"] = f"web-{j:07d}"
        duplicate["source_system"] = "web"
        duplicate["updated_at"] = f"2026-02-{j % 28 + 1:02d}T10:00:00Z"
        if j % 2:
            duplicate["phone"] = duplicate["phone"].replace("+1-", "")
        rows.append(duplicate)
    rng.shuffle(rows)
    for row in rows:
        if rng.random() < 0.01:
            row["address"] = ""
    if count >= 20:
        rows[-1]["source_record_id"] = ""
        rows[-2]["email"] = "not-an-email"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows[:count])

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/generated_customers.csv")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.output, args.rows, args.seed)
    print(f"Wrote {args.rows} synthetic rows to {args.output} (seed={args.seed})")

if __name__ == "__main__":
    main()

