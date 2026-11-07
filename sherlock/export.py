"""Journal-entry CSV export of the reviewed ledger. Labeled as an export; nothing is posted anywhere.

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


def export_totals(csv_text: str) -> tuple[int, int]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    return sum(int(r["debit_cents"]) for r in rows), sum(int(r["credit_cents"]) for r in rows)
