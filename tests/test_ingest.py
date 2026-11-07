import csv
import json
import shutil

import pytest
from sqlalchemy import func, select

from sherlock.ingest import ContractError, load_dataset
from sherlock.models import Customer, Invoice, PurchaseOrder, Refund, RefundEntry, Shipment
from tests.conftest import DATASET_DIR


def test_ingest_loads_every_row(session):
    report = load_dataset(session, DATASET_DIR)
    session.commit()
    m = json.loads((DATASET_DIR / "manifest.json").read_text())["counts"]

    assert session.scalar(select(func.count()).select_from(Shipment)) == m["shipments"] == report.shipments
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == m["purchase_orders"]
    assert session.scalar(select(func.count()).select_from(Invoice)) == m["invoices"]
    assert session.scalar(select(func.count()).select_from(RefundEntry)) == m["refund_entries"]
    assert session.scalar(select(func.count()).select_from(Customer)) == m["contracts"]
    refund = session.scalar(select(Refund))
    assert refund.amount_cents == m["refund_amount_cents"]
    assert report.warnings == []

    blank = session.get(Shipment, "SHP-0057")
    assert blank.po_number is None  # blank CSV cell becomes NULL, not ""


def test_ingest_rejects_non_integer_money(session, tmp_path):
    bad = tmp_path / "bad_v1"
    shutil.copytree(DATASET_DIR, bad)
    rows = list(csv.DictReader((bad / "invoices.csv").open()))
    rows[0]["amount_cents"] = "1234.56"
    with (bad / "invoices.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ContractError, match="integer cents"):
        load_dataset(session, bad)


def test_ingest_rejects_missing_file(session, tmp_path):
    bad = tmp_path / "bad_v2"
    shutil.copytree(DATASET_DIR, bad)
    (bad / "refund.json").unlink()
    with pytest.raises(ContractError, match="refund.json"):
        load_dataset(session, bad)
