"""Approve / override / reject flow into the ledger with a decision log; conservation survives."""

import json

import pytest
from sqlalchemy import select

from sherlock import ledger, review
from sherlock.models import AllocationRecord, CandidateObligation
from sherlock.pipeline import seed
from tests.conftest import DATASET_DIR


@pytest.fixture
def seeded(engine):
    seed(str(DATASET_DIR), engine)
    from sherlock import db

    s = db.get_sessionmaker()()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    yield s, {h["id"]: h for h in manifest["hard_cases"]}
    s.close()


def _rec(session, shipment_id):
    return session.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == shipment_id,
                                                         AllocationRecord.superseded_by_decision_id.is_(None)))


def test_override_split_flows_into_ledger_with_log(seeded):
    session, cases = seeded
    case = cases["split_po"]
    queued = _rec(session, case["shipment_id"])
    before_summary = ledger.summarize(session)
    a, b = case["po_numbers"]
    # Human decides the whole shipment belongs to PO A's customer, not the proportional split.
    d = review.override_allocation(session, queued.id, actor="adi", reason="BOL names only PO A's consignee",
                                   lines=[{"po_number": a, "amount_cents": queued.amount_cents}])
    session.commit()

    live = session.scalars(select(AllocationRecord).where(AllocationRecord.shipment_id == case["shipment_id"],
                                                          AllocationRecord.superseded_by_decision_id.is_(None))).all()
    assert len(live) == 1 and live[0].review_status == "human_overridden"
    assert live[0].po_number == a and live[0].customer_id and live[0].created_by_decision_id == d.id
    assert live[0].invoice_number == f"INV-{a[3:]}"  # single invoice on the PO is implied
    assert queued.superseded_by_decision_id == d.id

    after = ledger.summarize(session)
    assert after.conserved and after.refund_cents == before_summary.refund_cents
    assert after.allocated_cents == before_summary.allocated_cents + queued.amount_cents
    assert after.queue_count == before_summary.queue_count - 1

    log = review.decisions(session)
    assert len(log) == 1
    assert log[0]["actor"] == "adi" and log[0]["action"] == "override" and log[0]["created_at"]
    assert log[0]["reason"] == "BOL names only PO A's consignee"
    assert log[0]["before"]["unallocated_reason"] == "ambiguous_po_split"
    assert log[0]["after"]["changed"]["to"][0]["po_number"] == a
    assert b not in [l["po_number"] for l in log[0]["after"]["lines"]]


def test_partial_override_leaves_remainder_unallocated(seeded):
    session, cases = seeded
    queued = _rec(session, cases["split_po"]["shipment_id"])
    a = cases["split_po"]["po_numbers"][0]
    review.override_allocation(session, queued.id, "adi", "only part is ours to allocate",
                               [{"po_number": a, "amount_cents": queued.amount_cents // 2}])
    session.commit()
    live = session.scalars(select(AllocationRecord).where(AllocationRecord.shipment_id == queued.shipment_id,
                                                          AllocationRecord.superseded_by_decision_id.is_(None))).all()
    statuses = sorted((r.review_status, r.unallocated_reason) for r in live)
    assert statuses == [("human_overridden", None), ("unallocated", "override_remainder")]
    assert sum(r.amount_cents for r in live) == queued.amount_cents
    assert ledger.summarize(session).conserved


def test_approve_missing_invoice_proposal(seeded):
    session, cases = seeded
    queued = _rec(session, cases["missing_invoice"]["shipment_id"])
    review.approve_allocation(session, queued.id, "sid", "customer confirmed receipt; invoice was never raised")
    session.commit()
    live = _rec(session, queued.shipment_id)
    assert live.review_status == "human_confirmed" and live.customer_id and live.invoice_number is None
    assert ledger.summarize(session).conserved


def test_reject_keeps_amount_unallocated_and_reviewed(seeded):
    session, cases = seeded
    queued = _rec(session, cases["split_po"]["shipment_id"])
    review.reject_allocation(session, queued.id, "adi", "need the BOL before deciding")
    session.commit()
    assert queued.review_status == "unallocated" and not queued.needs_review
    assert ledger.summarize(session).conserved


def test_override_validation(seeded):
    session, cases = seeded
    queued = _rec(session, cases["split_po"]["shipment_id"])
    with pytest.raises(review.ReviewError):
        review.override_allocation(session, queued.id, "adi", "x", [{"po_number": "PO-NOPE", "amount_cents": 1}])
    with pytest.raises(review.ReviewError):
        review.override_allocation(session, queued.id, "adi", "x",
                                   [{"po_number": cases["split_po"]["po_numbers"][0], "amount_cents": queued.amount_cents + 1}])
    with pytest.raises(review.ReviewError):
        review.override_allocation(session, queued.id, "", "x", [])


def test_obligation_decisions_are_logged_and_drafts_refresh(seeded):
    session, _ = seeded
    ob = session.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-003"))
    assert ob.status == "pending_review"
    d = review.override_obligation(session, ob.id, "adi", "counsel read clause as owing 50%", amount_cents=12345)
    session.commit()
    assert ob.status == "confirmed" and ob.confirmed_amount_cents == 12345 and ob.decided_by_decision_id == d.id
    with pytest.raises(review.ReviewError):
        review.approve_obligation(session, ob.id, "adi", "twice")
    assert review.queue(session)["obligations"] == [o for o in review.queue(session)["obligations"] if o["id"] != ob.id]
