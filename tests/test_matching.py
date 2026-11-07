"""Conservation and the three planted hard cases."""

import json

import pytest
from sqlalchemy import select

from sherlock import ledger
from sherlock.ingest import load_dataset
from sherlock.matching.engine import assert_conservation, live_records, run_matching
from sherlock.models import AllocationRecord, Refund
from sherlock.money import split_cents
from tests.conftest import DATASET_DIR


@pytest.fixture
def matched(session):
    load_dataset(session, DATASET_DIR)
    summary = run_matching(session, DATASET_DIR)
    session.commit()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    return session, summary, {h["id"]: h for h in manifest["hard_cases"]}


def test_split_cents_is_exact():
    assert sum(split_cents(1000, [3, 3, 3])) == 1000
    assert split_cents(1000, [3, 3, 3]) == [334, 333, 333]
    assert split_cents(7, [0, 0]) == [4, 3]
    assert split_cents(0, [5, 5]) == [0, 0]


def test_conservation_holds(matched):
    session, summary, _ = matched
    refund = session.scalar(select(Refund))
    s = ledger.summarize(session)
    assert s.conserved
    assert s.allocated_cents + s.unallocated_cents == refund.amount_cents
    assert_conservation(session, refund.refund_id)
    for r in live_records(session, refund.refund_id):
        assert isinstance(r.amount_cents, int)
        if r.review_status == "unallocated":
            assert r.unallocated_reason
        else:
            assert r.customer_id and r.evidence and r.confidence >= 0.8
    assert summary["auto_proposed"] > 150


def _record_for_shipment(session, shipment_id):
    recs = session.scalars(select(AllocationRecord).where(AllocationRecord.shipment_id == shipment_id)).all()
    assert len(recs) == 1
    return recs[0]


def test_split_po_lands_in_queue_not_allocated(matched):
    session, _, cases = matched
    case = cases["split_po"]
    r = _record_for_shipment(session, case["shipment_id"])
    assert r.needs_review and r.review_status == "unallocated"
    assert r.unallocated_reason == "ambiguous_po_split"
    assert r.customer_id is None
    assert sorted(p["po_number"] for p in r.proposal) == sorted(case["po_numbers"])
    assert sum(p["amount_cents"] for p in r.proposal) == r.amount_cents
    assert {c["key"] for c in r.conflicts} >= set(case["po_numbers"])


def test_missing_invoice_lands_in_queue_not_allocated(matched):
    session, _, cases = matched
    case = cases["missing_invoice"]
    r = _record_for_shipment(session, case["shipment_id"])
    assert r.needs_review and r.review_status == "unallocated"
    assert r.unallocated_reason == "missing_invoice"
    assert r.po_number == case["po_number"] and r.invoice_number is None and r.customer_id is None
    assert r.proposal and r.proposal[0]["po_number"] == case["po_number"]


def test_other_planted_mismatches_are_handled(matched):
    session, summary, _ = matched
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    for m in manifest["other_mismatches"]:
        if m.get("expect") == "review_queue":
            r = _record_for_shipment(session, m["shipment_id"])
            assert r.needs_review, m
        elif m.get("expect") == "unallocated":
            recs = [r for r in live_records(session, session.scalar(select(Refund)).refund_id)
                    if r.unallocated_reason == "no_shipment_for_entry"]
            assert recs and recs[0].evidence[0]["key"] == m["entry_number"]
        elif m["kind"] == "quantity_drift_within_tolerance":
            r = _record_for_shipment(session, m["shipment_id"])
            assert r.review_status == "auto_proposed", m
        elif m["kind"] == "blank_po_number_fuzzy_match":
            r = _record_for_shipment(session, m["shipment_id"])
            assert r.po_number == m["po_number"], m
    assert summary["queued"] >= 8
