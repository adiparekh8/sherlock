"""Human review: the queue and the three actions (approve, override, reject) for allocations and
candidate obligations. Every action writes a ReviewDecision (who, when, what changed, why).

Allocation records are never edited in place when money moves. The reviewed record is marked
superseded by the decision and replacement lines are created with created_by_decision_id, so the
ledger history is reconstructible from the decision log alone.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.ledger import record_dict
from sherlock.matching.engine import assert_conservation, live_records
from sherlock.models import (
    AllocationRecord,
    CandidateObligation,
    Customer,
    DecisionAction,
    Invoice,
    ObligationStatus,
    PurchaseOrder,
    Refund,
    ReviewDecision,
    ReviewStatus,
)
from sherlock.obligations import obligation_dict, refresh_draft_amounts


class ReviewError(ValueError):
    pass


# --------------------------------------------------------------------------- queue


def queue(session: Session) -> dict:
    refund = session.scalar(select(Refund))
    allocations = [record_dict(r) for r in live_records(session, refund.refund_id) if r.needs_review] if refund else []
    obligations = [obligation_dict(o) for o in session.scalars(
        select(CandidateObligation).where(CandidateObligation.status == ObligationStatus.PENDING_REVIEW.value)
        .order_by(CandidateObligation.customer_id))]
    return {"allocations": allocations, "obligations": obligations,
            "count": len(allocations) + len(obligations)}


def decisions(session: Session) -> list[dict]:
    return [decision_dict(d) for d in session.scalars(select(ReviewDecision).order_by(ReviewDecision.id))]


def decision_dict(d: ReviewDecision) -> dict:
    return {"id": d.id, "target_type": d.target_type, "target_id": d.target_id, "action": d.action,
            "actor": d.actor, "reason": d.reason, "before": d.before, "after": d.after,
            "created_at": d.created_at.isoformat() if d.created_at else None}


# --------------------------------------------------------------------------- allocations


def _live_record(session: Session, record_id: int) -> AllocationRecord:
    r = session.get(AllocationRecord, record_id)
    if r is None or not r.is_live:
        raise ReviewError(f"allocation {record_id} not found or already superseded")
    return r


def _require(actor: str, reason: str) -> None:
    if not actor.strip():
        raise ReviewError("actor is required")
    if not reason.strip():
        raise ReviewError("reason is required")


def approve_allocation(session: Session, record_id: int, actor: str, reason: str) -> ReviewDecision:
    """Accept the engine's proposal. For an auto-proposed line that is confirmation in place; for a
    queued unallocated line the proposal becomes human-confirmed lines."""
    _require(actor, reason)
    r = _live_record(session, record_id)
    before = record_dict(r)
    decision = ReviewDecision(target_type="allocation", target_id=r.id, action=DecisionAction.APPROVE.value,
                              actor=actor, reason=reason, before=before)
    session.add(decision)
    session.flush()

    if r.review_status != ReviewStatus.UNALLOCATED.value:
        r.review_status = ReviewStatus.HUMAN_CONFIRMED.value
        r.needs_review = False
        decision.after = {"record_ids": [r.id], "review_status": r.review_status}
    elif r.proposal:
        created = _replace_with_lines(session, r, r.proposal, decision, ReviewStatus.HUMAN_CONFIRMED.value,
                                      f"Approved by {actor}: {reason}")
        decision.after = {"record_ids": [c.id for c in created], "lines": r.proposal}
    else:
        r.needs_review = False  # acknowledged: stays unallocated with its reason
        decision.after = {"record_ids": [r.id], "review_status": r.review_status, "acknowledged_unallocated": True}
    _finish(session, r.refund_id)
    return decision


def override_allocation(session: Session, record_id: int, actor: str, reason: str, lines: list[dict]) -> ReviewDecision:
    """Replace a line with human-specified allocation lines. Any amount not covered by the lines stays
    unallocated with reason override_remainder, so conservation holds by construction."""
    _require(actor, reason)
    r = _live_record(session, record_id)
    lines = _validate_lines(session, lines, r.amount_cents)
    before = record_dict(r)
    decision = ReviewDecision(target_type="allocation", target_id=r.id, action=DecisionAction.OVERRIDE.value,
                              actor=actor, reason=reason, before=before)
    session.add(decision)
    session.flush()
    created = _replace_with_lines(session, r, lines, decision, ReviewStatus.HUMAN_OVERRIDDEN.value,
                                  f"Overridden by {actor}: {reason}")
    decision.after = {"record_ids": [c.id for c in created], "lines": lines,
                      "changed": _diff(before, lines)}
    _finish(session, r.refund_id)
    return decision


def reject_allocation(session: Session, record_id: int, actor: str, reason: str) -> ReviewDecision:
    """Decline the proposal: the amount stays (or becomes) unallocated, reviewed, with the reason kept."""
    _require(actor, reason)
    r = _live_record(session, record_id)
    before = record_dict(r)
    decision = ReviewDecision(target_type="allocation", target_id=r.id, action=DecisionAction.REJECT.value,
                              actor=actor, reason=reason, before=before)
    session.add(decision)
    session.flush()
    if r.review_status == ReviewStatus.UNALLOCATED.value:
        r.needs_review = False
        decision.after = {"record_ids": [r.id], "review_status": r.review_status}
    else:
        new = AllocationRecord(
            refund_id=r.refund_id, refund_entry_id=r.refund_entry_id, shipment_id=r.shipment_id,
            amount_cents=r.amount_cents, confidence=r.confidence, match_method=r.match_method, evidence=r.evidence,
            reasoning=f"Rejected by {actor}: {reason}. Previous reasoning: {r.reasoning}",
            review_status=ReviewStatus.UNALLOCATED.value, unallocated_reason="rejected_by_reviewer",
            needs_review=False, created_by_decision_id=decision.id)
        session.add(new)
        r.superseded_by_decision_id = decision.id
        session.flush()
        decision.after = {"record_ids": [new.id], "review_status": new.review_status}
    _finish(session, r.refund_id)
    return decision


def _validate_lines(session: Session, lines: list[dict], max_cents: int) -> list[dict]:
    if not lines:
        raise ReviewError("override needs at least one line (use reject to leave the amount unallocated)")
    out, total = [], 0
    for raw in lines:
        amount = raw.get("amount_cents")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ReviewError(f"amount_cents must be a positive integer, got {amount!r}")
        po = session.get(PurchaseOrder, raw["po_number"]) if raw.get("po_number") else None
        if raw.get("po_number") and po is None:
            raise ReviewError(f"unknown po_number {raw['po_number']}")
        customer_id = raw.get("customer_id") or (po.customer_id if po else None)
        if not customer_id or session.get(Customer, customer_id) is None:
            raise ReviewError("each line needs a customer_id (directly or via po_number)")
        inv = session.get(Invoice, raw["invoice_number"]) if raw.get("invoice_number") else None
        if raw.get("invoice_number") and inv is None:
            raise ReviewError(f"unknown invoice_number {raw['invoice_number']}")
        if inv is None and po is not None:
            # Convenience: a PO with exactly one invoice implies it.
            invs = session.scalars(select(Invoice).where(Invoice.po_number == po.po_number)).all()
            inv = invs[0] if len(invs) == 1 else None
        total += amount
        out.append({"po_number": po.po_number if po else None, "customer_id": customer_id,
                    "invoice_number": inv.invoice_number if inv else None, "amount_cents": amount})
    if total > max_cents:
        raise ReviewError(f"lines sum to {total} cents, more than the {max_cents} cents being reviewed")
    return out


def _replace_with_lines(session, r: AllocationRecord, lines: list[dict], decision: ReviewDecision,
                        status: str, note: str) -> list[AllocationRecord]:
    created = []
    for line in lines:
        created.append(AllocationRecord(
            refund_id=r.refund_id, refund_entry_id=r.refund_entry_id, shipment_id=r.shipment_id,
            po_number=line.get("po_number"), invoice_number=line.get("invoice_number"),
            customer_id=line["customer_id"], amount_cents=line["amount_cents"], confidence=r.confidence,
            match_method=r.match_method, evidence=r.evidence, reasoning=f"{note} Engine reasoning: {r.reasoning}",
            review_status=status, needs_review=False, conflicts=r.conflicts, created_by_decision_id=decision.id))
    remainder = r.amount_cents - sum(line["amount_cents"] for line in lines)
    if remainder > 0:
        created.append(AllocationRecord(
            refund_id=r.refund_id, refund_entry_id=r.refund_entry_id, shipment_id=r.shipment_id,
            amount_cents=remainder, confidence=r.confidence, match_method=r.match_method, evidence=r.evidence,
            reasoning=f"{note} Remainder not covered by the reviewer's lines.",
            review_status=ReviewStatus.UNALLOCATED.value, unallocated_reason="override_remainder",
            needs_review=False, created_by_decision_id=decision.id))
    session.add_all(created)
    r.superseded_by_decision_id = decision.id
    r.needs_review = False
    session.flush()
    return created


def _diff(before: dict, lines: list[dict]) -> dict:
    proposal = before.get("proposal") or [{"po_number": before.get("po_number"), "customer_id": before.get("customer_id"),
                                           "invoice_number": before.get("invoice_number"),
                                           "amount_cents": before.get("amount_cents")}]
    return {"from": proposal, "to": lines}


def _finish(session: Session, refund_id: str) -> None:
    session.flush()
    assert_conservation(session, refund_id)
    refresh_draft_amounts(session)


# --------------------------------------------------------------------------- obligations


def _pending(session: Session, ob_id: int) -> CandidateObligation:
    ob = session.get(CandidateObligation, ob_id)
    if ob is None:
        raise ReviewError(f"obligation {ob_id} not found")
    if ob.status != ObligationStatus.PENDING_REVIEW.value:
        raise ReviewError(f"obligation {ob_id} already decided ({ob.status})")
    return ob


def approve_obligation(session: Session, ob_id: int, actor: str, reason: str) -> ReviewDecision:
    """Human confirms the clause reading at the draft amount."""
    _require(actor, reason)
    ob = _pending(session, ob_id)
    d = ReviewDecision(target_type="obligation", target_id=ob.id, action=DecisionAction.APPROVE.value, actor=actor,
                       reason=reason, before=obligation_dict(ob))
    session.add(d)
    session.flush()
    ob.status = ObligationStatus.CONFIRMED.value
    ob.confirmed_amount_cents = ob.draft_amount_cents or 0
    ob.decided_by_decision_id = d.id
    d.after = {"status": ob.status, "confirmed_amount_cents": ob.confirmed_amount_cents}
    session.flush()
    return d


def override_obligation(session: Session, ob_id: int, actor: str, reason: str, amount_cents: int) -> ReviewDecision:
    """Human confirms the obligation at an amount of their choosing."""
    _require(actor, reason)
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < 0:
        raise ReviewError("amount_cents must be a non-negative integer")
    ob = _pending(session, ob_id)
    d = ReviewDecision(target_type="obligation", target_id=ob.id, action=DecisionAction.OVERRIDE.value, actor=actor,
                       reason=reason, before=obligation_dict(ob))
    session.add(d)
    session.flush()
    ob.status = ObligationStatus.CONFIRMED.value
    ob.confirmed_amount_cents = amount_cents
    ob.decided_by_decision_id = d.id
    d.after = {"status": ob.status, "confirmed_amount_cents": amount_cents,
               "changed": {"from": ob.draft_amount_cents, "to": amount_cents}}
    session.flush()
    return d


def reject_obligation(session: Session, ob_id: int, actor: str, reason: str) -> ReviewDecision:
    _require(actor, reason)
    ob = _pending(session, ob_id)
    d = ReviewDecision(target_type="obligation", target_id=ob.id, action=DecisionAction.REJECT.value, actor=actor,
                       reason=reason, before=obligation_dict(ob))
    session.add(d)
    session.flush()
    ob.status = ObligationStatus.REJECTED.value
    ob.confirmed_amount_cents = 0
    ob.decided_by_decision_id = d.id
    d.after = {"status": ob.status, "confirmed_amount_cents": 0}
    session.flush()
    return d
