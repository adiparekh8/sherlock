"""Memo and CSV regenerate from the reviewed ledger and reflect a human override."""

import csv
import io
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from sherlock import db, review
from sherlock.export import EXPORT_LABEL, export_totals, generate_export
from sherlock.memo import generate_memo
from sherlock.models import AllocationRecord, CandidateObligation, Refund
from sherlock.pipeline import seed
from tests.conftest import DATASET_DIR

NOW = datetime(2025, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def seeded(engine):
    seed(str(DATASET_DIR), engine)
    s = db.get_sessionmaker()()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    yield s, {h["id"]: h for h in manifest["hard_cases"]}
    s.close()


def _queued(session, shipment_id):
    return session.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == shipment_id,
                                                         AllocationRecord.superseded_by_decision_id.is_(None)))


def test_memo_shows_conservation_and_flagged_items(seeded):
    session, cases = seeded
    memo = generate_memo(session, NOW)
    refund = session.scalar(select(Refund))
    assert "**Conservation holds** | **YES**" in memo
    assert f"{refund.amount_cents // 100:,}" in memo
    assert "ambiguous_po_split" in memo and "missing_invoice" in memo
    assert cases["vague_surcharge"]["customer_id"] in memo and "pending_review" in memo
    assert "No human decisions yet." in memo


def test_export_is_balanced_and_labeled(seeded):
    session, _ = seeded
    text = generate_export(session, NOW)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert all(r["export_label"] == EXPORT_LABEL for r in rows)
    debits, credits = export_totals(text)
    refund = session.scalar(select(Refund))
    assert debits == credits == refund.amount_cents
    assert all("." not in r["debit_cents"] and "." not in r["credit_cents"] for r in rows)
    suspense = [r for r in rows if r["account"] == "2990"]
    assert suspense and all(r["memo"].startswith("Unallocated:") for r in suspense)


def test_override_flows_into_memo_and_export_and_regenerates(seeded):
    session, cases = seeded
    memo_before = generate_memo(session, NOW)
    csv_before = generate_export(session, NOW)
    assert generate_memo(session, NOW) == memo_before and generate_export(session, NOW) == csv_before

    case = cases["split_po"]
    queued = _queued(session, case["shipment_id"])
    a = case["po_numbers"][0]
    d = review.override_allocation(session, queued.id, "adi", "BOL consignee is PO A customer",
                                   [{"po_number": a, "amount_cents": queued.amount_cents}])
    ob = session.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-001"))
    review.approve_obligation(session, ob.id, "sid", "clause 4 is unambiguous")
    session.commit()

    memo = generate_memo(session, NOW)
    assert memo != memo_before
    assert "OVERRIDE** by adi" in memo and "BOL consignee is PO A customer" in memo
    assert f"| {d.id} | {d.created_at.strftime('%Y-%m-%d')}" in memo  # decision log row
    assert "No human decisions yet." not in memo
    assert "**Conservation holds** | **YES**" in memo

    text = generate_export(session, NOW)
    assert text != csv_before
    rows = list(csv.DictReader(io.StringIO(text)))
    over = [r for r in rows if r["review_status"] == "human_overridden"]
    assert len(over) == 1 and over[0]["po_number"] == a and over[0]["decision_id"] == str(d.id)
    assert not any(r["ledger_line_id"] == str(queued.id) for r in rows)  # superseded line is gone
    pass_through = [r for r in rows if r["account"] == "2410"]
    assert len(pass_through) == 1 and pass_through[0]["customer_id"] == "CUST-001"
    debits, credits = export_totals(text)
    assert debits == credits
    assert generate_export(session, NOW) == text  # deterministic regeneration
