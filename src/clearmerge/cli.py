from __future__ import annotations
import argparse
import logging
from pathlib import Path
from .pipeline import run_pipeline

def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate synthetic or authorized customer records")
    parser.add_argument("--input", default="data/sample_customers.csv")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        metrics = run_pipeline(Path(args.input), Path(args.output), args.database)
    except Exception as exc:
        parser.exit(2, f"Pipeline failed: {exc}\n")
    print(f"Completed {metrics['run_id']}: {metrics['input_rows']} input, {metrics['merged_records']} entities, "
          f"{metrics['probable_pairs_for_review']} review pairs, {metrics['rejected_rows']} rejects")

if __name__ == "__main__":
    main()

