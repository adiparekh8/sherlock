"""Tolerances and thresholds for the matching engine. This is the file to edit for a new dataset.

Confidence values are per hop; a record's confidence is the product of its hops. Anything below
`auto_threshold` is NOT allocated: it goes to the review queue as an unallocated line with a proposal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchConfig:
    # Below this a line is queued instead of auto-proposed.
    auto_threshold: float = 0.80

    # Shipment quantity vs PO quantity.
    quantity_tolerance_pct: float = 5.0
    # Invoice amount vs PO total (plus surcharge).
    amount_tolerance_pct: float = 5.0
    # A PO's order_date must fall within this many days before the shipment's ship_date to be a
    # fuzzy candidate. POs with no order_date are always candidates.
    po_date_window_days: int = 180
    # Max edit distance for rescuing a mistyped po_number.
    po_typo_max_edits: int = 2

    # Hop confidences.
    conf_entry_to_shipment: float = 1.0
    conf_po_by_number: float = 0.98
    conf_po_fuzzy_unique: float = 0.85
    conf_po_typo_rescue: float = 0.70
    conf_po_split: float = 0.55
    conf_invoice_by_po: float = 0.98
    conf_missing_invoice: float = 0.60

    # Multiplicative penalties.
    qty_within_tolerance_factor: float = 0.92
    qty_beyond_tolerance_factor: float = 0.65
    invoice_amount_mismatch_factor: float = 0.85


DEFAULT_CONFIG = MatchConfig()
