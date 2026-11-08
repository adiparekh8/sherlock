"""Builds the allocation ledger for the loaded refund.

For every refund entry the engine walks the hops in rules.py and writes AllocationRecords. Lines whose
confidence clears the threshold are `auto_proposed`. Everything else is written as `unallocated` with a
reason, a proposal (what the engine would do), and `needs_review=True`, so the queue is simply
"live records where needs_review is true". Conservation is asserted before returning.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.matching.config import DEFAULT_CONFIG, MatchConfig
from sherlock.matching import rules
from sherlock.matching.rules import Index, ev_entry, ev_invoice, ev_po, ev_shipment
from sherlock.models import AllocationRecord, Invoice, PurchaseOrder, Refund, RefundEntry, ReviewStatus, Shipment
from sherlock.money import fmt_usd, split_cents
from sherlock.scans import scanned_invoice_candidates


class ConservationError(AssertionError):
    pass


def build_index(session: Session) -> Index:
    shipments = session.scalars(select(Shipment)).all()
    pos = {p.po_number: p for p in session.scalars(select(PurchaseOrder))}
    by_entry: dict[str, list[Shipment]] = {}
    for s in shipments:
        by_entry.setdefault(s.entry_number, []).append(s)
    inv_by_po: dict[str, list[Invoice]] = {}
    for i in session.scalars(select(Invoice)):
        inv_by_po.setdefault(i.po_number, []).append(i)
    claimed = {s.po_number for s in shipments if s.po_number and s.po_number in pos}
    return Index(by_entry, pos, inv_by_po, claimed, scanned_invoice_candidates(session))


def run_matching(session: Session, dataset_dir: Path | None = None, cfg: MatchConfig = DEFAULT_CONFIG) -> dict:
    refund = session.scalar(select(Refund))
    if refund is None:
        return {"records": 0}
    index = build_index(session)
    records: list[AllocationRecord] = []

    for entry in sorted(refund.entries, key=lambda e: e.entry_number):
        records.extend(_allocate_entry(refund, entry, index, cfg))

    entry_sum = sum(e.amount_cents for e in refund.entries)
    if entry_sum != refund.amount_cents:
        records.append(AllocationRecord(
            refund_id=refund.refund_id, amount_cents=refund.amount_cents - entry_sum, confidence=1.0,
            match_method="refund_total_vs_entries", review_status=ReviewStatus.UNALLOCATED.value,
            unallocated_reason="refund_total_not_supported_by_entries", needs_review=True,
            evidence=[{"source": "refund.json", "locator": "amount_cents", "entity": "refund", "key": refund.refund_id,
                       "quoted_text": f"amount_cents {refund.amount_cents} vs entries {entry_sum}"}],
            reasoning=f"The refund notice total {fmt_usd(refund.amount_cents)} differs from the sum of its entry "
                      f"lines {fmt_usd(entry_sum)}. The difference has no entry to trace, so it stays unallocated.",
        ))

    session.add_all(records)
    session.flush()
    assert_conservation(session, refund.refund_id)
    allocated = [r for r in records if r.review_status != ReviewStatus.UNALLOCATED.value]
    queued = [r for r in records if r.needs_review]
    return {
        "records": len(records),
        "auto_proposed": len(allocated),
        "auto_proposed_cents": sum(r.amount_cents for r in allocated),
        "queued": len(queued),
        "unallocated_cents": sum(r.amount_cents for r in records if r.review_status == ReviewStatus.UNALLOCATED.value),
        "reasons": _count(r.unallocated_reason for r in records if r.unallocated_reason),
    }


def _allocate_entry(refund: Refund, entry: RefundEntry, index: Index, cfg: MatchConfig) -> list[AllocationRecord]:
    shipments = rules.shipments_for_entry(entry, index)
    if not shipments:
        return [AllocationRecord(
            refund_id=refund.refund_id, refund_entry_id=entry.id, amount_cents=entry.amount_cents, confidence=1.0,
            match_method="no_shipment_for_entry", review_status=ReviewStatus.UNALLOCATED.value,
            unallocated_reason="no_shipment_for_entry", needs_review=True, evidence=[ev_entry(entry)],
            conflicts=[ev_entry(entry)],
            reasoning=f"Refund entry {entry.entry_number} appears on the CBP notice but no shipment in shipments.csv "
                      f"carries that entry number. Nothing can be matched; a human must source the entry.",
        )]

    shares = rules.share_entry_across_shipments(entry.amount_cents, shipments)
    out = []
    for shipment in shipments:
        out.append(_allocate_shipment(refund, entry, shipment, shares[shipment.shipment_id], index, cfg, len(shipments)))
    return out


def _allocate_shipment(refund, entry, shipment, amount, index, cfg, n_in_entry) -> AllocationRecord:
    base_evidence = [ev_entry(entry), ev_shipment(shipment)]
    base_reason = (f"Entry {entry.entry_number} refunded {fmt_usd(entry.amount_cents)}; "
                   + (f"shared across {n_in_entry} shipments by duty paid, {fmt_usd(amount)} to {shipment.shipment_id}. "
                      if n_in_entry > 1 else f"single shipment {shipment.shipment_id}. "))
    pm = rules.match_shipment_to_po(shipment, index, cfg)
    common = dict(refund_id=refund.refund_id, refund_entry_id=entry.id, shipment_id=shipment.shipment_id,
                  amount_cents=amount)

    if pm.status == "matched":
        po, _ = pm.lines[0]
        im = rules.match_po_to_invoice(po, index, cfg)
        conf = round(cfg.conf_entry_to_shipment * pm.confidence * im.confidence, 4)
        reasoning = base_reason + pm.reasoning + " " + im.reasoning
        evidence = base_evidence + [ev_po(po)] + ([ev_invoice(im.invoice)] if im.invoice else [])
        proposal = [_line(po, im.invoice, amount)]
        if im.invoice is None:
            scan = index.scanned_invoices.get(po.po_number)
            if scan:
                proposal[0]["invoice_number"] = scan["invoice_number"]
                proposal[0]["invoice_from_scan"] = scan
                evidence = evidence + [scan["evidence"]]
                reasoning += (f" A scanned paper invoice ({scan['evidence']['source']}, page 1) was read by the model: "
                              f"{scan['invoice_number']} for {po.po_number}, total {fmt_usd(scan['amount_cents'])} with "
                              f"tariff surcharge {fmt_usd(scan['tariff_surcharge_cents'])} (field confidence "
                              f"{scan['confidence']:.2f}). Approving creates that invoice record; it is not created automatically.")
            return AllocationRecord(**common, po_number=po.po_number, customer_id=None, confidence=conf,
                                    match_method=f"{pm.method}+{im.method}", evidence=evidence, reasoning=reasoning,
                                    review_status=ReviewStatus.UNALLOCATED.value, unallocated_reason="missing_invoice",
                                    needs_review=True, proposal=proposal, conflicts=pm.conflicts + im.conflicts)
        if conf < cfg.auto_threshold:
            return AllocationRecord(**common, po_number=po.po_number, invoice_number=im.invoice.invoice_number,
                                    customer_id=None, confidence=conf, match_method=f"{pm.method}+{im.method}",
                                    evidence=evidence, reasoning=reasoning + f" Confidence {conf:.2f} is below the "
                                    f"{cfg.auto_threshold:.2f} threshold, so this is proposed for review rather than allocated.",
                                    review_status=ReviewStatus.UNALLOCATED.value, unallocated_reason="low_confidence",
                                    needs_review=True, proposal=proposal, conflicts=pm.conflicts + im.conflicts)
        return AllocationRecord(**common, po_number=po.po_number, invoice_number=im.invoice.invoice_number,
                                customer_id=po.customer_id, confidence=conf, match_method=f"{pm.method}+{im.method}",
                                evidence=evidence, reasoning=reasoning, review_status=ReviewStatus.AUTO_PROPOSED.value,
                                needs_review=False, conflicts=pm.conflicts + im.conflicts)

    if pm.status == "split":
        qty_shares = [q for _, q in pm.lines]
        cents = split_cents(amount, qty_shares)
        proposal, evidence, reasoning = [], list(base_evidence), base_reason + pm.reasoning
        for (po, q), c in zip(pm.lines, cents):
            im = rules.match_po_to_invoice(po, index, cfg)
            proposal.append(_line(po, im.invoice, c))
            evidence.append(ev_po(po))
            if im.invoice:
                evidence.append(ev_invoice(im.invoice))
        return AllocationRecord(**common, customer_id=None, confidence=pm.confidence, match_method=pm.method,
                                evidence=evidence, reasoning=reasoning, review_status=ReviewStatus.UNALLOCATED.value,
                                unallocated_reason="ambiguous_po_split", needs_review=True, proposal=proposal,
                                conflicts=pm.conflicts)

    # not_found or ambiguous: nothing to propose.
    return AllocationRecord(**common, customer_id=None, confidence=0.0, match_method=pm.method,
                            evidence=base_evidence, reasoning=base_reason + pm.reasoning,
                            review_status=ReviewStatus.UNALLOCATED.value, unallocated_reason=pm.method,
                            needs_review=True, proposal=[], conflicts=pm.conflicts)


def _line(po: PurchaseOrder, invoice: Invoice | None, amount: int) -> dict:
    return {"po_number": po.po_number, "customer_id": po.customer_id,
            "invoice_number": invoice.invoice_number if invoice else None, "amount_cents": amount}


def live_records(session: Session, refund_id: str) -> list[AllocationRecord]:
    return session.scalars(
        select(AllocationRecord)
        .where(AllocationRecord.refund_id == refund_id, AllocationRecord.superseded_by_decision_id.is_(None))
        .order_by(AllocationRecord.id)
    ).all()


def assert_conservation(session: Session, refund_id: str) -> None:
    refund = session.get(Refund, refund_id)
    total = sum(r.amount_cents for r in live_records(session, refund_id))
    if total != refund.amount_cents:
        raise ConservationError(f"ledger sums to {total} but refund is {refund.amount_cents}")
    for r in live_records(session, refund_id):
        if r.review_status == ReviewStatus.UNALLOCATED.value and not r.unallocated_reason:
            raise ConservationError(f"unallocated record {r.id} has no reason")
        if r.review_status != ReviewStatus.UNALLOCATED.value and not r.customer_id:
            raise ConservationError(f"allocated record {r.id} has no customer")


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))
