"""Named matching rules, one per hop in refund -> entry -> shipment -> PO -> invoice -> customer.

Each rule is a pure function over an in-memory Index so it can be unit-tested and tuned without the
database. Evidence dicts have the shape {"source", "locator", "quoted_text", "entity", "key"}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sherlock.matching.config import DEFAULT_CONFIG, MatchConfig
from sherlock.models import Invoice, PurchaseOrder, RefundEntry, Shipment
from sherlock.money import fmt_usd, pct_diff, split_cents


@dataclass
class Index:
    shipments_by_entry: dict[str, list[Shipment]]
    pos: dict[str, PurchaseOrder]
    invoices_by_po: dict[str, list[Invoice]]
    claimed_pos: set[str]  # PO numbers referenced by some shipment's po_number


@dataclass
class POMatch:
    status: str  # matched | split | not_found | ambiguous
    lines: list[tuple[PurchaseOrder, int]] = field(default_factory=list)  # (po, quantity share)
    confidence: float = 0.0
    method: str = ""
    reasoning: str = ""
    conflicts: list[dict] = field(default_factory=list)


@dataclass
class InvoiceMatch:
    invoice: Invoice | None
    confidence: float
    method: str
    reasoning: str
    conflicts: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- evidence helpers


def ev_entry(e: RefundEntry) -> dict:
    return {"source": "refund.json", "locator": f"entries[{e.source_row}]", "entity": "refund_entry",
            "key": e.entry_number, "quoted_text": f"{e.entry_number}: {fmt_usd(e.amount_cents)} ({e.entry_date})"}


def ev_shipment(s: Shipment) -> dict:
    return {"source": "shipments.csv", "locator": f"row {s.source_row}", "entity": "shipment", "key": s.shipment_id,
            "quoted_text": f"{s.shipment_id} | entry {s.entry_number} | {s.supplier} | {s.description} | "
                           f"qty {s.quantity} | duty {fmt_usd(s.duty_paid_cents)} | po_number: {s.po_number or '(blank)'}"}


def ev_po(p: PurchaseOrder) -> dict:
    return {"source": "purchase_orders.csv", "locator": f"row {p.source_row}", "entity": "purchase_order",
            "key": p.po_number,
            "quoted_text": f"{p.po_number} | {p.customer_id} | {p.supplier} | {p.description} | qty {p.quantity} | "
                           f"total {fmt_usd(p.total_cents)} | ordered {p.order_date}"}


def ev_invoice(i: Invoice) -> dict:
    return {"source": "invoices.csv", "locator": f"row {i.source_row}", "entity": "invoice", "key": i.invoice_number,
            "quoted_text": f"{i.invoice_number} | PO {i.po_number} | {i.customer_id} | amount {fmt_usd(i.amount_cents)} | "
                           f"surcharge {fmt_usd(i.tariff_surcharge_cents)}"}


# --------------------------------------------------------------------------- rules


def shipments_for_entry(entry: RefundEntry, index: Index) -> list[Shipment]:
    """Hop 1: refund entry -> shipments, by exact entry number."""
    return sorted(index.shipments_by_entry.get(entry.entry_number, []), key=lambda s: s.shipment_id)


def share_entry_across_shipments(entry_amount_cents: int, shipments: list[Shipment]) -> dict[str, int]:
    """One customs entry may cover several shipments; share its refund by duty paid, exactly."""
    shares = split_cents(entry_amount_cents, [s.duty_paid_cents for s in shipments])
    return {s.shipment_id: c for s, c in zip(shipments, shares)}


def quantity_factor(ship_qty: int, po_qty: int, cfg: MatchConfig) -> tuple[float, str]:
    diff = pct_diff(ship_qty, po_qty)
    if diff == 0:
        return 1.0, "quantities match"
    if diff <= cfg.quantity_tolerance_pct:
        return cfg.qty_within_tolerance_factor, f"quantity differs by {diff:.1f}% (within {cfg.quantity_tolerance_pct:g}% tolerance)"
    return cfg.qty_beyond_tolerance_factor, f"quantity differs by {diff:.1f}% (beyond {cfg.quantity_tolerance_pct:g}% tolerance)"


def fuzzy_po_candidates(shipment: Shipment, index: Index, cfg: MatchConfig) -> list[PurchaseOrder]:
    """POs that could be this shipment's: same supplier and description, not claimed by another
    shipment, ordered within the date window before ship_date."""
    out = []
    for po in index.pos.values():
        if po.po_number in index.claimed_pos:
            continue
        if po.supplier.strip().lower() != shipment.supplier.strip().lower():
            continue
        if po.description.strip().lower() != shipment.description.strip().lower():
            continue
        if po.order_date and shipment.ship_date:
            if not (shipment.ship_date - timedelta(days=cfg.po_date_window_days) <= po.order_date <= shipment.ship_date):
                continue
        out.append(po)
    return sorted(out, key=lambda p: p.po_number)


def match_shipment_to_po(shipment: Shipment, index: Index, cfg: MatchConfig = DEFAULT_CONFIG) -> POMatch:
    """Hop 2: shipment -> PO(s). Exact po_number first, then typo rescue, then fuzzy, then split."""
    if shipment.po_number and shipment.po_number in index.pos:
        po = index.pos[shipment.po_number]
        factor, note = quantity_factor(shipment.quantity, po.quantity, cfg)
        return POMatch("matched", [(po, shipment.quantity)], cfg.conf_po_by_number * factor, "po_number_exact",
                       f"Shipment carries PO number {po.po_number}; {note}.")

    candidates = fuzzy_po_candidates(shipment, index, cfg)
    tol = cfg.quantity_tolerance_pct

    if shipment.po_number:  # dangling reference: try to rescue a typo among plausible candidates
        close = [p for p in candidates if _edits(p.po_number, shipment.po_number) <= cfg.po_typo_max_edits]
        if len(close) == 1:
            po = close[0]
            factor, note = quantity_factor(shipment.quantity, po.quantity, cfg)
            return POMatch("matched", [(po, shipment.quantity)], cfg.conf_po_typo_rescue * factor, "po_number_typo_rescue",
                           f"Shipment's PO number {shipment.po_number} matches nothing; {po.po_number} differs by "
                           f"{_edits(po.po_number, shipment.po_number)} character(s) and has the same supplier and "
                           f"product; {note}.", conflicts=[ev_shipment(shipment), ev_po(po)])
        if not candidates:
            return POMatch("not_found", [], 0.0, "po_not_found",
                           f"Shipment's PO number {shipment.po_number} matches no PO and no PO for the same supplier "
                           f"and product is unclaimed.", conflicts=[ev_shipment(shipment)])

    singles = [p for p in candidates if pct_diff(shipment.quantity, p.quantity) <= tol]
    if len(singles) == 1:
        po = singles[0]
        factor, note = quantity_factor(shipment.quantity, po.quantity, cfg)
        return POMatch("matched", [(po, shipment.quantity)], cfg.conf_po_fuzzy_unique * factor, "fuzzy_supplier_product_qty",
                       f"No PO number on the shipment; exactly one unclaimed PO ({po.po_number}) has the same supplier, "
                       f"product, and a quantity within tolerance ({note}).")

    pairs = [(a, b) for i, a in enumerate(candidates) for b in candidates[i + 1:]
             if pct_diff(shipment.quantity, a.quantity + b.quantity) <= tol]
    if len(pairs) == 1 and not singles:
        a, b = pairs[0]
        shares = split_cents(shipment.quantity, [a.quantity, b.quantity])
        return POMatch("split", [(a, shares[0]), (b, shares[1])], cfg.conf_po_split, "po_split_by_quantity",
                       f"No PO number on the shipment and no single PO matches its quantity of {shipment.quantity}, "
                       f"but {a.po_number} (qty {a.quantity}) and {b.po_number} (qty {b.quantity}) together do. "
                       f"They may belong to different customers, so the split is proposed, not applied.",
                       conflicts=[ev_shipment(shipment), ev_po(a), ev_po(b)])

    if candidates:
        return POMatch("ambiguous", [], 0.0, "po_ambiguous",
                       f"{len(candidates)} unclaimed POs share this shipment's supplier and product but none "
                       f"(alone or in pairs) match its quantity.", conflicts=[ev_shipment(shipment)] + [ev_po(p) for p in candidates])
    return POMatch("not_found", [], 0.0, "po_not_found",
                   "No PO number on the shipment and no unclaimed PO has the same supplier and product.",
                   conflicts=[ev_shipment(shipment)])


def match_po_to_invoice(po: PurchaseOrder, index: Index, cfg: MatchConfig = DEFAULT_CONFIG) -> InvoiceMatch:
    """Hop 3: PO -> invoice by PO number. Flags amount disagreement beyond tolerance."""
    invoices = index.invoices_by_po.get(po.po_number, [])
    if not invoices:
        return InvoiceMatch(None, cfg.conf_missing_invoice, "missing_invoice",
                            f"No invoice references {po.po_number}. The customer ({po.customer_id}) is known from the PO "
                            f"but was never billed, so it is unclear whether any tariff was passed through.",
                            conflicts=[ev_po(po)])
    inv = sorted(invoices, key=lambda i: i.invoice_number)[0]
    goods = inv.amount_cents - inv.tariff_surcharge_cents
    diff = pct_diff(goods, po.total_cents)
    if diff <= cfg.amount_tolerance_pct:
        return InvoiceMatch(inv, cfg.conf_invoice_by_po, "invoice_by_po",
                            f"Invoice {inv.invoice_number} references {po.po_number}; goods amount agrees with the PO total.")
    return InvoiceMatch(inv, cfg.conf_invoice_by_po * cfg.invoice_amount_mismatch_factor, "invoice_by_po_amount_mismatch",
                        f"Invoice {inv.invoice_number} references {po.po_number} but its goods amount "
                        f"({fmt_usd(goods)}) differs from the PO total ({fmt_usd(po.total_cents)}) by {diff:.1f}%.",
                        conflicts=[ev_po(po), ev_invoice(inv)])


def _edits(a: str, b: str) -> int:
    """Levenshtein distance; strings are short PO numbers."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
