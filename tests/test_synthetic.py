"""The committed synthetic dataset is internally consistent and the generator is deterministic."""

import csv
import json
import sys
from pathlib import Path

from tests.conftest import DATASET_DIR, REPO

sys.path.insert(0, str(REPO / "scripts"))
from make_synthetic import generate  # noqa: E402


def _rows(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def test_manifest_records_three_hard_cases():
    m = json.loads((DATASET_DIR / "manifest.json").read_text())
    kinds = {h["kind"] for h in m["hard_cases"]}
    assert kinds == {"shipment_split_across_pos", "vague_surcharge_clause", "missing_invoice"}
    for c in m["contracts"]:
        assert (DATASET_DIR / c["file"]).exists()


def test_refund_total_equals_entry_sum():
    r = json.loads((DATASET_DIR / "refund.json").read_text())
    assert r["amount_cents"] == sum(e["amount_cents"] for e in r["entries"])
    assert all(isinstance(e["amount_cents"], int) for e in r["entries"])


def test_planted_cases_exist_in_data():
    m = json.loads((DATASET_DIR / "manifest.json").read_text())
    ships = {s["shipment_id"]: s for s in _rows(DATASET_DIR / "shipments.csv")}
    pos = {p["po_number"]: p for p in _rows(DATASET_DIR / "purchase_orders.csv")}
    inv_by_po = {i["po_number"] for i in _rows(DATASET_DIR / "invoices.csv")}
    cases = {h["id"]: h for h in m["hard_cases"]}

    split = cases["split_po"]
    assert ships[split["shipment_id"]]["po_number"] == ""
    assert sum(int(pos[p]["quantity"]) for p in split["po_numbers"]) == int(ships[split["shipment_id"]]["quantity"])

    missing = cases["missing_invoice"]
    assert missing["po_number"] in pos
    assert missing["po_number"] not in inv_by_po


def test_generator_is_deterministic(tmp_path):
    generate(tmp_path / "synthetic_v1", seed=42)
    for name in ("shipments.csv", "purchase_orders.csv", "invoices.csv", "refund.json"):
        assert (tmp_path / "synthetic_v1" / name).read_text() == (DATASET_DIR / name).read_text()
