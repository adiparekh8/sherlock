"""Read-side view of the ledger: totals, conservation, and per-record detail for API, memo, export, UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.matching.engine import live_records
from sherlock.models import AllocationRecord, Customer, Refund, ReviewStatus


@dataclass
class LedgerSummary:
    refund_id: str
    refund_cents: int
    allocated_cents: int
    unallocated_cents: int
    conserved: bool
    by_status: dict[str, dict] = field(default_factory=dict)  # status -> {count, cents}
    by_reason: dict[str, dict] = field(default_factory=dict)  # unallocated reason -> {count, cents}
    by_customer: dict[str, dict] = field(default_factory=dict)  # customer -> {name, count, cents}
    queue_count: int = 0

    def as_dict(self) -> dict:
        return self.__dict__


def summarize(session: Session, refund_id: str | None = None) -> LedgerSummary:
    refund = session.get(Refund, refund_id) if refund_id else session.scalar(select(Refund))
    records = live_records(session, refund.refund_id)
    names = {c.customer_id: c.name for c in session.scalars(select(Customer))}
    s = LedgerSummary(refund.refund_id, refund.amount_cents, 0, 0, False)
    for r in records:
        bucket = s.by_status.setdefault(r.review_status, {"count": 0, "cents": 0})
        bucket["count"] += 1
        bucket["cents"] += r.amount_cents
        if r.review_status == ReviewStatus.UNALLOCATED.value:
            s.unallocated_cents += r.amount_cents
            rb = s.by_reason.setdefault(r.unallocated_reason or "", {"count": 0, "cents": 0})
            rb["count"] += 1
            rb["cents"] += r.amount_cents
        else:
            s.allocated_cents += r.amount_cents
            cb = s.by_customer.setdefault(r.customer_id, {"name": names.get(r.customer_id, r.customer_id), "count": 0, "cents": 0})
            cb["count"] += 1
            cb["cents"] += r.amount_cents
        if r.needs_review:
            s.queue_count += 1
    s.conserved = s.allocated_cents + s.unallocated_cents == s.refund_cents
    s.by_customer = dict(sorted(s.by_customer.items()))
    return s


def record_dict(r: AllocationRecord) -> dict:
    return {
        "id": r.id, "refund_id": r.refund_id, "refund_entry_id": r.refund_entry_id, "shipment_id": r.shipment_id,
        "po_number": r.po_number, "invoice_number": r.invoice_number, "customer_id": r.customer_id,
        "amount_cents": r.amount_cents, "confidence": r.confidence, "match_method": r.match_method,
        "evidence": r.evidence, "reasoning": r.reasoning, "review_status": r.review_status,
        "unallocated_reason": r.unallocated_reason, "needs_review": r.needs_review, "proposal": r.proposal,
        "conflicts": r.conflicts, "superseded_by_decision_id": r.superseded_by_decision_id,
        "created_by_decision_id": r.created_by_decision_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
