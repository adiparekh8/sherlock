"""CSV exports of the reviewed ledger. Both are labeled as exports; Sherlock posts nothing anywhere.

journal export   the close entry: the file an accounting sync (Ramp, NetSuite, QuickBooks) would consume
payables export  the customer money owed back: one row per human-confirmed contract obligation, shaped
                 for a bill-pay import. Pending and rejected obligations are excluded.

Entries (all in integer cents, debits = credits = refund total):
  Dr 1000 Cash                                  refund total
  Cr 4910 Tariff refund recovery                one line per allocated ledger line (customer/PO/invoice dims)
  Cr 2990 Unallocated tariff refund (suspense)  one line per unallocated ledger line (reason in memo)
and, for each human-confirmed contract obligation:
  Dr 4910 Tariff refund recovery / Cr 2410 Due to customers (tariff pass-through)
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.matching.engine import live_records
from sherlock.models import CandidateObligation, ObligationStatus, Refund, ReviewStatus

EXPORT_LABEL = "SHERLOCK JOURNAL ENTRY EXPORT - NOT POSTED TO ANY ERP"
PAYABLES_LABEL = "SHERLOCK PAYABLES EXPORT - NOT SENT TO ANY BILL-PAY SYSTEM"
PAYABLES_COLUMNS = ["export_label", "generated_at_utc", "refund_id", "line_no", "customer_id", "customer_name",
                    "amount_cents", "clause_type", "contract_file", "contract_page", "clause_excerpt", "decision_id",
                    "decided_by", "decided_at_utc", "reason", "memo"]
COLUMNS = ["export_label", "generated_at_utc", "refund_id", "line_no", "entry_date", "account", "account_name",
           "debit_cents", "credit_cents", "customer_id", "po_number", "invoice_number", "shipment_id",
           "ledger_line_id", "review_status", "confidence", "decision_id", "memo"]

ACCOUNTS = {
    "1000": "Cash",
    "4910": "Tariff refund recovery",
    "2990": "Unallocated tariff refund (suspense)",
    "2410": "Due to customers - tariff pass-through",
}


def generate_export(session: Session, now: datetime | None = None) -> str:
    refund = session.scalar(select(Refund))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    if refund is None:
        return buf.getvalue()
    now = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"export_label": EXPORT_LABEL, "generated_at_utc": now, "refund_id": refund.refund_id,
            "entry_date": refund.received_date.isoformat()}
    rows: list[dict] = []

    def add(**kw):
        row = {c: "" for c in COLUMNS}
        row.update(base)
        row.update(kw)
        row["account_name"] = ACCOUNTS[row["account"]]
        rows.append(row)

    add(account="1000", debit_cents=refund.amount_cents, credit_cents=0,
        memo=f"Tariff refund received from {refund.source or 'customs'} ({refund.reference or refund.refund_id})")
    for r in live_records(session, refund.refund_id):
        if r.review_status == ReviewStatus.UNALLOCATED.value:
            add(account="2990", debit_cents=0, credit_cents=r.amount_cents, shipment_id=r.shipment_id or "",
                po_number=r.po_number or "", ledger_line_id=r.id, review_status=r.review_status,
                confidence=f"{r.confidence:.2f}", decision_id=r.created_by_decision_id or "",
                memo=f"Unallocated: {r.unallocated_reason}")
        else:
            add(account="4910", debit_cents=0, credit_cents=r.amount_cents, customer_id=r.customer_id,
                po_number=r.po_number or "", invoice_number=r.invoice_number or "", shipment_id=r.shipment_id or "",
                ledger_line_id=r.id, review_status=r.review_status, confidence=f"{r.confidence:.2f}",
                decision_id=r.created_by_decision_id or "",
                memo=f"Refund share for {r.shipment_id or 'n/a'} ({r.match_method})")
    for o in session.scalars(select(CandidateObligation).where(CandidateObligation.status == ObligationStatus.CONFIRMED.value)
                             .order_by(CandidateObligation.customer_id)):
        if not o.confirmed_amount_cents:
            continue
        add(account="4910", debit_cents=o.confirmed_amount_cents, credit_cents=0, customer_id=o.customer_id,
            decision_id=o.decided_by_decision_id or "", review_status="human_confirmed",
            memo=f"Contract pass-through obligation ({o.clause_type}), confirmed by decision #{o.decided_by_decision_id}")
        add(account="2410", debit_cents=0, credit_cents=o.confirmed_amount_cents, customer_id=o.customer_id,
            decision_id=o.decided_by_decision_id or "", review_status="human_confirmed",
            memo=f"Due to {o.customer_id} under contract clause, decision #{o.decided_by_decision_id}")

    for i, row in enumerate(rows, start=1):
        row["line_no"] = i
        writer.writerow(row)
    return buf.getvalue()


def generate_payables(session: Session, now: datetime | None = None) -> str:
    """One row per human-confirmed customer obligation. Regenerates from the live ledger on every call."""
    from sherlock.models import Customer, ParsedDocument, ReviewDecision

    refund = session.scalar(select(Refund))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=PAYABLES_COLUMNS)
    writer.writeheader()
    if refund is None:
        return buf.getvalue()
    now = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    names = {c.customer_id: c.name for c in session.scalars(select(Customer))}
    docs = {d.id: d for d in session.scalars(select(ParsedDocument))}
    decisions = {d.id: d for d in session.scalars(select(ReviewDecision))}
    obligations = session.scalars(
        select(CandidateObligation).where(CandidateObligation.status == ObligationStatus.CONFIRMED.value)
        .order_by(CandidateObligation.customer_id, CandidateObligation.id)).all()
    n = 0
    for o in obligations:
        if not o.confirmed_amount_cents:
            continue
        n += 1
        d = decisions.get(o.decided_by_decision_id)
        doc = docs.get(o.contract_document_id)
        writer.writerow({
            "export_label": PAYABLES_LABEL, "generated_at_utc": now, "refund_id": refund.refund_id, "line_no": n,
            "customer_id": o.customer_id, "customer_name": names.get(o.customer_id, ""),
            "amount_cents": o.confirmed_amount_cents, "clause_type": o.clause_type,
            "contract_file": doc.source_path if doc else "", "contract_page": o.page or "",
            "clause_excerpt": " ".join(o.quoted_text.split())[:160], "decision_id": o.decided_by_decision_id or "",
            "decided_by": d.actor if d else "", "decided_at_utc": d.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if d else "",
            "reason": d.reason if d else "",
            "memo": f"Tariff refund share owed to {o.customer_id} under contract clause, per decision #{o.decided_by_decision_id}",
        })
    return buf.getvalue()


def export_totals(csv_text: str) -> tuple[int, int]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    return sum(int(r["debit_cents"]) for r in rows), sum(int(r["credit_cents"]) for r in rows)
