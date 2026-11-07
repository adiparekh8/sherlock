"""End-to-end through HTTP: seed, ledger, queue, override, memo, export."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from sherlock.api.app import app
from tests.conftest import DATASET_DIR


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(DATASET_DIR.parent))
    from sherlock.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_full_flow_over_http(client):
    assert client.get("/health").json()["ok"]
    ds = client.get("/datasets").json()
    assert any(d["name"] == "synthetic_v1" and d["hard_cases"] == 3 for d in ds["datasets"])
    assert client.get("/ledger").status_code == 404  # nothing seeded yet

    r = client.post("/datasets/synthetic_v1/seed")
    assert r.status_code == 200, r.text
    assert r.json()["stages"]["match"]["records"] > 170

    led = client.get("/ledger").json()
    assert led["summary"]["conserved"]
    assert led["summary"]["refund_cents"] == led["summary"]["allocated_cents"] + led["summary"]["unallocated_cents"]

    q = client.get("/review/queue").json()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    cases = {h["id"]: h for h in manifest["hard_cases"]}
    queued_ships = {a["shipment_id"] for a in q["allocations"]}
    assert cases["split_po"]["shipment_id"] in queued_ships
    assert cases["missing_invoice"]["shipment_id"] in queued_ships
    assert any(o["customer_id"] == cases["vague_surcharge"]["customer_id"] for o in q["obligations"])

    split = next(a for a in q["allocations"] if a["shipment_id"] == cases["split_po"]["shipment_id"])
    detail = client.get(f"/allocations/{split['id']}").json()
    assert len(detail["related"]["purchase_orders"]) == 2 and detail["record"]["evidence"]

    bad = client.post(f"/review/allocations/{split['id']}/override",
                      json={"actor": "adi", "reason": "x", "lines": [{"po_number": "PO-NOPE", "amount_cents": 1}]})
    assert bad.status_code == 422

    ok = client.post(f"/review/allocations/{split['id']}/override",
                     json={"actor": "adi", "reason": "BOL says PO A",
                           "lines": [{"po_number": cases["split_po"]["po_numbers"][0], "amount_cents": split["amount_cents"]}]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["summary"]["conserved"]
    assert client.get("/decisions").json()["decisions"][0]["actor"] == "adi"
    assert split["id"] not in {a["id"] for a in client.get("/review/queue").json()["allocations"]}

    memo = client.get("/memo").text
    assert "OVERRIDE** by adi" in memo and "Conservation holds** | **YES" in memo

    exp = client.get("/export.csv")
    assert exp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exp.text)))
    assert sum(int(r["debit_cents"]) for r in rows) == sum(int(r["credit_cents"]) for r in rows)
    assert any(r["review_status"] == "human_overridden" for r in rows)

    ob = next(o for o in client.get("/obligations").json()["obligations"] if o["customer_id"] == "CUST-003")
    assert ob["status"] == "pending_review"
    doc = client.get(f"/documents/{ob['contract_document_id']}").json()
    assert doc["pages"][ob["page"] - 1]["text"][ob["span_start"]:ob["span_end"]] == ob["quoted_text"]
