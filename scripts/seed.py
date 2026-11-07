#!/usr/bin/env python
"""Seed the database from a dataset folder. `make seed DATASET=<name>` is the entire dataset swap."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sherlock.config import get_settings  # noqa: E402
from sherlock.pipeline import seed  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="synthetic_v1", help="folder name under DATA_DIR, or a path")
    args = ap.parse_args()
    s = get_settings()
    print(f"database: {s.database_url}")
    report = seed(args.dataset)
    print(json.dumps({"ingest": asdict(report.ingest), "stages": report.stages}, indent=2, default=str))


if __name__ == "__main__":
    main()
