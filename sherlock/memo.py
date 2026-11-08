"""Audit memo in markdown, regenerated from the current ledger on every call. No state is kept."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock import ledger
from sherlock.matching.config import DEFAULT_CONFIG
from sherlock.matching.engine import live_records
from sherlock.models import (
    AllocationRecord,
    CandidateObligation,
    Customer,
    Dataset,
    ParsedDocument,
    Refund,
    ReviewDecision,
    ReviewStatus,
)
from sherlock.money import fmt_usd

STATUS_LABEL = {
    "auto_proposed": "Auto-proposed (above threshold, not yet human-reviewed)",
    "human_confirmed": "Human-confirmed",
    "human_overridden": "Human-overridden",
    "unallocated": "Unallocated",
}


def generate_memo(session: Session, now: datetime | None = None) -> str:
    refund = session.scalar(select(Refund))
    if refund is None:
        return "# Sherlock audit memo\n\nNo refund loaded.\n"
    now = now or datetime.now(timezone.utc)
    dataset = session.scalar(select(Dataset))
    s = ledger.summarize(session, refund.refund_id)
    records = live_records(session, refund.refund_id)
    names = {c.customer_id: c.name for c in session.scalars(select(Customer))}
    decisions = session.scalars(select(ReviewDecision).order_by(ReviewDecision.id)).all()
    by_target = {}
    for d in decisions:
        by_target.setdefault((d.target_type, d.target_id), []).append(d)
    obligations = session.scalars(select(CandidateObligation).order_by(CandidateObligation.customer_id)).all()
    docs = {d.id: d for d in session.scalars(select(ParsedDocument))}
    cfg = DEFAULT_CONFIG

    L: list[str] = []
    w = L.append
    w(f"# Sherlock audit memo: tariff refund {refund.refund_id}")
    w("")
    w(f"**Importer:** {refund.importer}  ")
    w(f"**Refund received:** {refund.received_date} from {refund.source or 'n/a'} ({refund.reference or 'no reference'})  ")
    w(f"**Dataset:** {dataset.name if dataset else 'n/a'}  ")
    w(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')} from the live reviewed ledger. Regenerating after any review "
      f"decision replaces this memo in full.")
    w("")

    # 1. Reconciliation
    w("## 1. Reconciliation")
    w("")
    w("Conservation: refund total = allocated + unallocated.")
    w("")
    w("| | Amount |")
    w("|---|---:|")
    w(f"| Refund total | {fmt_usd(s.refund_cents)} |")
    w(f"| Allocated (auto-proposed + human-confirmed + human-overridden) | {fmt_usd(s.allocated_cents)} |")
    w(f"| Unallocated (every line carries a reason) | {fmt_usd(s.unallocated_cents)} |")
    w(f"| Allocated + unallocated | {fmt_usd(s.allocated_cents + s.unallocated_cents)} |")
    w(f"| **Conservation holds** | **{'YES' if s.conserved else 'NO'}** |")
    w("")
    w("By review status:")
    w("")
    w("| Status | Lines | Amount |")
    w("|---|---:|---:|")
    for status in ("auto_proposed", "human_confirmed", "human_overridden", "unallocated"):
        b = s.by_status.get(status, {"count": 0, "cents": 0})
        w(f"| {STATUS_LABEL[status]} | {b['count']} | {fmt_usd(b['cents'])} |")
    w("")
    if s.by_reason:
        w("Unallocated by reason:")
        w("")
        w("| Reason | Lines | Amount |")
        w("|---|---:|---:|")
        for reason, b in sorted(s.by_reason.items()):
            w(f"| {reason} | {b['count']} | {fmt_usd(b['cents'])} |")
        w("")
    w(f"Open review queue: {s.queue_count} allocation line(s) and "
      f"{sum(1 for o in obligations if o.status == 'pending_review')} contract candidate(s).")
    w("")

    # 2. Method
    w("## 2. Method")
    w("")
    w("1. **Ingest.** refund.json, shipments.csv, purchase_orders.csv, invoices.csv and the contract PDFs were loaded "
      "from the dataset folder per docs/DATA_CONTRACT.md. Money is held as integer cents throughout.")
    parser = next(iter(docs.values())).parser if docs else "n/a"
    w(f"2. **Parse.** Contracts were read with the `{parser}` parser into per-page text; clause citations below refer "
      f"to those pages.")
    w(f"3. **Normalize.** {reader_sentence(list(docs.values()))} Every extracted value keeps its page, character "
      f"span and confidence.")
    w(f"4. **Match.** Each refund entry was linked to shipments by entry number and shared by duty paid; each shipment to "
      f"a PO by PO number, else by supplier, product, quantity (tolerance {cfg.quantity_tolerance_pct:g}%) and order "
      f"date (window {cfg.po_date_window_days} days); each PO to its invoice; each invoice to its customer. "
      f"Confidence is the product of per-hop confidences. Lines below {cfg.auto_threshold:.2f} were **not** allocated: "
      f"they were queued as unallocated with the engine's proposal attached. Nothing was force-matched.")
    w("5. **Contract reader.** Each contract's tariff clause was classified as a surcharge pass-through, a refund "
      "obligation, or no obligation, with a draft amount derived from the ledger. Candidates stay pending until a "
      "human decides; none were auto-confirmed or auto-released.")
    w("6. **Review.** Every approval, override and rejection is logged with actor, time, before/after and reason "
      "(section 4). Overrides supersede the reviewed line rather than editing it.")
    w("7. **Outputs.** The refund is cash in. The journal-entry CSV is the close entry: the file an accounting sync "
      "(Ramp, NetSuite, QuickBooks) would consume, labeled NOT POSTED. The payables CSV is the customer money owed "
      "back under human-confirmed contract clauses, shaped for a bill-pay import and labeled NOT SENT. Sherlock "
      "writes both and posts neither.")
    w("")

    # 3. Allocations by customer
    w("## 3. Allocation by customer")
    w("")
    w("| Customer | Name | Lines | Allocated |")
    w("|---|---|---:|---:|")
    for cid, b in s.by_customer.items():
        w(f"| {cid} | {b['name']} | {b['count']} | {fmt_usd(b['cents'])} |")
    w(f"| | **Total allocated** | {sum(b['count'] for b in s.by_customer.values())} | **{fmt_usd(s.allocated_cents)}** |")
    w("")

    # 4. Flagged items and resolutions
    w("## 4. Flagged items and resolutions")
    w("")
    flagged = [r for r in records if r.needs_review or r.review_status in ("human_confirmed", "human_overridden")
               or r.review_status == "unallocated"]
    superseded = session.scalars(select(AllocationRecord).where(AllocationRecord.refund_id == refund.refund_id,
                                                                AllocationRecord.superseded_by_decision_id.is_not(None))
                                 .order_by(AllocationRecord.id)).all()
    if not flagged and not superseded:
        w("None.")
    for r in superseded:
        ds = by_target.get(("allocation", r.id), [])
        w(f"- **Line #{r.id}** ({r.shipment_id or 'no shipment'}, {fmt_usd(r.amount_cents)}, was "
          f"{r.unallocated_reason or r.review_status}): " + _resolution(ds))
    for r in flagged:
        if r.created_by_decision_id and r.review_status != "unallocated":
            continue  # described under the line it replaced
        ds = by_target.get(("allocation", r.id), [])
        if r.needs_review:
            res = "**OPEN** in review queue. Engine proposal: " + (_proposal(r.proposal) if r.proposal else "none.")
        elif ds:
            res = _resolution(ds)
        elif r.unallocated_reason == "override_remainder":
            res = f"remainder left unallocated by decision #{r.created_by_decision_id}."
        else:
            res = "reviewed, left unallocated."
        w(f"- **Line #{r.id}** ({r.shipment_id or 'no shipment'}, {fmt_usd(r.amount_cents)}, "
          f"{r.unallocated_reason or r.review_status}, confidence {r.confidence:.2f}): {res}")
        if r.reasoning:
            w(f"  - Engine reasoning: {r.reasoning}")
    w("")

    # 5. Contract candidates
    w("## 5. Candidate customer obligations from contracts")
    w("")
    w("Status moves only by human decision. Draft amounts are recomputed from the live ledger.")
    w("")
    w("| Customer | Clause | Strength | Refund owed? | Conf. | Draft | Status | Confirmed | Citation |")
    w("|---|---|---|---|---:|---:|---|---:|---|")
    for o in obligations:
        d = docs.get(o.contract_document_id)
        cite = f"{d.source_path if d else '?'} p.{o.page}"
        confirmed = fmt_usd(o.confirmed_amount_cents) if o.confirmed_amount_cents is not None else ""
        w(f"| {o.customer_id} | {o.clause_type} | {o.obligation_strength} | {o.refund_owed_to_customer} | "
          f"{o.confidence:.2f} | {fmt_usd(o.draft_amount_cents or 0)} | {o.status} | {confirmed} | {cite} |")
    w("")
    for o in obligations:
        d = docs.get(o.contract_document_id)
        w(f"**{o.customer_id} ({names.get(o.customer_id, '')})**, {d.source_path if d else '?'} page {o.page}:")
        w("")
        w("> " + " ".join(o.quoted_text.split()))
        w("")
        w(f"Reading: {o.reasoning} Draft basis: {o.draft_basis}")
        ds = by_target.get(("obligation", o.id), [])
        if ds:
            w("")
            w("Decision: " + _resolution(ds))
        w("")

    # 6. Decision log
    w("## 6. Decision log")
    w("")
    if not decisions:
        w("No human decisions yet.")
    else:
        w("| # | When (UTC) | Who | Target | Action | What changed | Why |")
        w("|---|---|---|---|---|---|---|")
        for d in decisions:
            w(f"| {d.id} | {d.created_at.strftime('%Y-%m-%d %H:%M')} | {d.actor} | {d.target_type} #{d.target_id} | "
              f"{d.action} | {_what_changed(d)} | {d.reason} |")
    w("")

    # 7. Evidence appendix
    w("## 7. Ledger lines and evidence")
    w("")
    w("Every live line. Evidence cites the source file and row/page; the UI drills into each.")
    w("")
    w("| # | Entry | Shipment | PO | Invoice | Customer | Amount | Conf. | Status | Evidence |")
    w("|---|---|---|---|---|---|---:|---:|---|---|")
    entries = {}
    for r in records:
        if r.refund_entry_id and r.refund_entry_id not in entries:
            entries[r.refund_entry_id] = next((e.entry_number for e in refund.entries if e.id == r.refund_entry_id), "")
        ev = "; ".join(f"{e['source']} {e['locator']}" for e in r.evidence)
        status = r.review_status + (f" ({r.unallocated_reason})" if r.unallocated_reason else "")
        w(f"| {r.id} | {entries.get(r.refund_entry_id, '')} | {r.shipment_id or ''} | {r.po_number or ''} | "
          f"{r.invoice_number or ''} | {r.customer_id or ''} | {fmt_usd(r.amount_cents)} | {r.confidence:.2f} | "
          f"{status} | {ev} |")
    w("")
    return "\n".join(L)


def reader_sentence(docs: list[ParsedDocument]) -> str:
    """How the contracts were read: which model, from where, and whether anything fell back to the stub."""
    contracts = [d for d in docs if d.doc_type == "contract"]
    if not contracts:
        return "No contracts were loaded."
    models = sorted({d.extract_model for d in contracts if d.extract_model and d.extract_model != "stub"})
    by_src = {}
    for d in contracts:
        by_src[d.extract_source or "unknown"] = by_src.get(d.extract_source or "unknown", 0) + 1
    n = len(contracts)
    model = " / ".join(f"`{m}`" for m in models) if models else "the model"
    parts = []
    if by_src.get("cache"):
        parts.append(f"{by_src['cache']} of {n} contracts were read by {model}, served from the committed "
                     f"model-output cache (llm_cache/)")
    if by_src.get("api"):
        parts.append(f"{by_src['api']} of {n} were read by {model} live during this run")
    if by_src.get("stub"):
        parts.append(f"{by_src['stub']} of {n} fell back to the deterministic rule-based reader because no cached "
                     f"model output exists for them yet (run `make llm-cache` with a key to replace those readings)")
    return "Contract fields and tariff clauses: " + "; ".join(parts) + "."


def _proposal(lines: list[dict]) -> str:
    return "; ".join(f"{fmt_usd(l['amount_cents'])} to {l.get('customer_id') or '?'} via PO {l.get('po_number') or '?'}"
                     + (f" / {l['invoice_number']}" if l.get('invoice_number') else " (no invoice)") for l in lines) + "."


def _resolution(ds: list[ReviewDecision]) -> str:
    return " ".join(f"**{d.action.upper()}** by {d.actor} on {d.created_at.strftime('%Y-%m-%d %H:%M UTC')} "
                    f"(decision #{d.id}): {d.reason}. {_what_changed(d)}" for d in ds)


def _what_changed(d: ReviewDecision) -> str:
    after = d.after or {}
    if d.target_type == "allocation":
        made = "".join(f" Created invoice {i['invoice_number']} ({fmt_usd(i['amount_cents'])}, surcharge "
                       f"{fmt_usd(i['tariff_surcharge_cents'])}) from the scanned document the model read."
                       for i in after.get("created_invoices", []))
        if "lines" in after:
            return f"Replaced line #{d.target_id} with {_proposal(after['lines'])} New line ids {after.get('record_ids')}.{made}"
        if after.get("acknowledged_unallocated"):
            return "Acknowledged; stays unallocated."
        return f"Status now {after.get('review_status', '?')}."
    if "changed" in after:
        return f"Confirmed at {fmt_usd(after['confirmed_amount_cents'])} (draft was {fmt_usd(after['changed']['from'] or 0)})."
    return f"Status now {after.get('status', '?')}" + (
        f" at {fmt_usd(after['confirmed_amount_cents'])}." if after.get("confirmed_amount_cents") is not None else ".")
