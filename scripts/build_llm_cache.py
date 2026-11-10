#!/usr/bin/env python
"""Read every contract (and scan) in a dataset with the real model and write the results to llm_cache/.

Requires ANTHROPIC_API_KEY in the environment or .env. Afterwards, commit llm_cache/ so machines
without a key serve the same model output. Re-run after changing a prompt version or adding documents;
existing entries are reused, so only new work hits the API.

    make llm-cache DATASET=synthetic_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sherlock import db  # noqa: E402
from sherlock.config import get_settings  # noqa: E402
from sherlock.ingest import load_dataset  # noqa: E402
from sherlock.llm import get_llm  # noqa: E402
from sherlock.models import Base, ParsedDocument  # noqa: E402
from sherlock.normalize import extract_contract  # noqa: E402
from sherlock.parsing.stage import parse_documents  # noqa: E402
from sherlock.pipeline import resolve_dataset_dir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="synthetic_v1")
    args = ap.parse_args()
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set. Put it in .env (never commit it) and re-run.", file=sys.stderr)
        return 2
    dataset_dir = resolve_dataset_dir(args.dataset)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    scan_hints = {scan["file"]: scan.get("hint", "") for scan in manifest.get("scans", [])}
    engine = db.make_engine("sqlite://")
    Base.metadata.create_all(engine)
    db.set_engine(engine)
    llm = get_llm()
    print(f"model {settings.anthropic_model}, cache {settings.llm_cache_dir}/, dataset {dataset_dir}")
    with db.session_scope() as session:
        load_dataset(session, dataset_dir)
        parse_documents(session, dataset_dir)
        docs = session.query(ParsedDocument).order_by(ParsedDocument.id).all()
        for doc in docs:
            if doc.doc_type == "contract":
                res = extract_contract(doc)
                clauses = res.output["clauses"]
                head = clauses[0] if clauses else {}
                print(f"  {res.source:5} {doc.source_path}: {head.get('clause_type')} / "
                      f"{head.get('obligation_strength')} / owed={head.get('refund_owed_to_customer')} "
                      f"conf={head.get('confidence')}")
            elif doc.doc_type == "scan":
                from sherlock.scans import extract_scan  # imported lazily: Phase 2 module

                res = extract_scan(doc, dataset_dir, scan_hints.get(doc.source_path, ""))
                print(f"  {res.source:5} {doc.source_path}: {res.output.get('document_type')} "
                      f"{res.output.get('invoice_number', {}).get('value')}")
    print("done. commit llm_cache/ so the no-key demo serves these outputs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
