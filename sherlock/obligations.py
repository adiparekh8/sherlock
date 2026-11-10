"""Pipeline stage: contract clauses -> CandidateObligation rows (always pending_review).

Draft amounts are derived from the live ledger: the refund dollars allocated to a customer on invoices
that carried a tariff surcharge. They are recomputed whenever the ledger changes; nothing here ever
confirms or releases an obligation.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.llm.spans import locate_span
from sherlock.matching.engine import live_records
from sherlock.models import CandidateObligation, Invoice, ObligationStatus, ParsedDocument, Refund, ReviewStatus
from sherlock.money import fmt_usd
from sherlock.normalize import extract_contract

# Clause types that create a reviewable candidate. A contract with no tariff language creates none.
CANDIDATE_TYPES = {"surcharge_passthrough", "refund_obligation", "no_refund_obligation"}


def extract_obligations(session: Session, dataset_dir: Path | None = None) -> dict:
    docs = session.scalars(select(ParsedDocument).where(ParsedDocument.doc_type == "contract")).all()
    created = 0
    for doc in docs:
        result = extract_contract(doc)  # cache hit: same call normalization made
        page_text = {p["page"]: p["text"] for p in doc.pages}
        for clause in result.output["clauses"]:
            if clause["clause_type"] not in CANDIDATE_TYPES:
                continue
            span = locate_span(page_text.get(clause["page"], ""), clause["quoted_text"])
            quote = page_text[clause["page"]][span[0]:span[1]] if span else clause["quoted_text"]
            session.add(CandidateObligation(
                customer_id=doc.customer_id, contract_document_id=doc.id, clause_type=clause["clause_type"],
                page=clause["page"], quoted_text=quote,
                span_start=span[0] if span else None, span_end=span[1] if span else None,
                confidence=clause["confidence"], reasoning=clause["reasoning"],
                obligation_strength=clause["obligation_strength"],
                refund_owed_to_customer=clause["refund_owed_to_customer"],
                status=ObligationStatus.PENDING_REVIEW.value,
                evidence=[{"source": doc.source_path, "locator": f"page {clause['page']}", "entity": "contract",
                           "key": doc.customer_id, "document_id": doc.id, "quoted_text": quote}],
            ))
            created += 1
    session.flush()
    refresh_draft_amounts(session)
    return {"documents": len(docs), "candidates": created}


def refresh_draft_amounts(session: Session) -> None:
    """Recompute draft amounts from the live ledger. Called after seeding and after every review decision."""
    refund = session.scalar(select(Refund))
    if refund is None:
        return
    invoices = {i.invoice_number: i for i in session.scalars(select(Invoice))}
    per_customer: dict[str, list] = {}
    for r in live_records(session, refund.refund_id):
        if r.review_status == ReviewStatus.UNALLOCATED.value or not r.customer_id:
            continue
        inv = invoices.get(r.invoice_number) if r.invoice_number else None
        if inv and inv.tariff_surcharge_cents > 0:
            per_customer.setdefault(r.customer_id, []).append((r, inv))

    for ob in session.scalars(select(CandidateObligation)):
        lines = per_customer.get(ob.customer_id, [])
        total = sum(min(r.amount_cents, inv.tariff_surcharge_cents) for r, inv in lines)
        if ob.refund_owed_to_customer == "no":
            ob.draft_amount_cents = 0
            ob.draft_basis = (f"Clause read as no obligation. For reference, {len(lines)} allocated lines "
                              f"({fmt_usd(total)}) to this customer carried a tariff surcharge.")
        else:
            ob.draft_amount_cents = total
            ob.draft_basis = (f"Sum over {len(lines)} allocated ledger lines to this customer whose invoice carried a "
                              f"tariff surcharge, each capped at the surcharge billed. Recomputed from the live ledger.")
        surcharge_ev = [{"source": "invoices.csv", "locator": f"row {inv.source_row}", "entity": "invoice",
                         "key": inv.invoice_number,
                         "quoted_text": f"{inv.invoice_number} | surcharge {fmt_usd(inv.tariff_surcharge_cents)} | "
                                        f"allocated {fmt_usd(r.amount_cents)} (ledger #{r.id})"}
                        for r, inv in lines[:25]]
        ob.evidence = [e for e in ob.evidence if e.get("entity") == "contract"] + surcharge_ev
    session.flush()


def obligation_dict(ob: CandidateObligation) -> dict:
    return {
        "id": ob.id, "customer_id": ob.customer_id, "contract_document_id": ob.contract_document_id,
        "clause_type": ob.clause_type, "page": ob.page, "quoted_text": ob.quoted_text,
        "span_start": ob.span_start, "span_end": ob.span_end, "confidence": ob.confidence,
        "reasoning": ob.reasoning, "obligation_strength": ob.obligation_strength,
        "refund_owed_to_customer": ob.refund_owed_to_customer, "draft_amount_cents": ob.draft_amount_cents,
        "draft_basis": ob.draft_basis, "status": ob.status, "confirmed_amount_cents": ob.confirmed_amount_cents,
        "decided_by_decision_id": ob.decided_by_decision_id, "evidence": ob.evidence,
        "created_at": ob.created_at.isoformat() if ob.created_at else None,
    }
