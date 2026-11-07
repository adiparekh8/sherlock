"""Read a dataset folder (see docs/DATA_CONTRACT.md) into the database.

This is the only module that knows the on-disk layout. Swapping datasets means pointing
`load_dataset` at a different folder; nothing downstream reads files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from sherlock.models import Customer, Dataset, Invoice, PurchaseOrder, Refund, RefundEntry, Shipment

REQUIRED_FILES = ["manifest.json", "refund.json", "shipments.csv", "purchase_orders.csv", "invoices.csv"]

SHIPMENT_COLS = {
    "shipment_id": str, "entry_number": str, "bill_of_lading": str, "ship_date": "date", "arrival_date": "date",
    "supplier": str, "description": str, "hts_code": str, "quantity": int, "declared_value_cents": int,
    "duty_paid_cents": int, "po_number": str,
}
PO_COLS = {
    "po_number": str, "customer_id": str, "customer_name": str, "supplier": str, "order_date": "date",
    "description": str, "quantity": int, "unit_price_cents": int, "total_cents": int,
}
INVOICE_COLS = {
    "invoice_number": str, "po_number": str, "customer_id": str, "invoice_date": "date", "amount_cents": int,
    "tariff_surcharge_cents": int,
}
REFUND_KEYS = {"refund_id", "importer", "amount_cents", "received_date", "entries"}


class ContractError(ValueError):
    """The dataset folder does not match docs/DATA_CONTRACT.md."""


@dataclass
class IngestReport:
    dataset: str
    customers: int = 0
    refund_entries: int = 0
    shipments: int = 0
    purchase_orders: int = 0
    invoices: int = 0
    warnings: list[str] = field(default_factory=list)


def validate_layout(dataset_dir: Path) -> dict:
    missing = [f for f in REQUIRED_FILES if not (dataset_dir / f).exists()]
    if missing:
        raise ContractError(f"{dataset_dir}: missing {missing}")
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    contracts_dir = dataset_dir / manifest.get("files", {}).get("contracts_dir", "contracts")
    if not contracts_dir.is_dir():
        raise ContractError(f"{dataset_dir}: contracts directory {contracts_dir.name}/ not found")
    return manifest


def _read_csv(path: Path, spec: dict[str, object]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in spec if c not in df.columns]
    if missing:
        raise ContractError(f"{path.name}: missing columns {missing}")
    for col, typ in spec.items():
        if typ is int:
            bad = df[col][~df[col].str.fullmatch(r"-?\d+")]
            if len(bad):
                raise ContractError(f"{path.name}.{col}: non-integer values, e.g. {bad.iloc[0]!r} (money is integer cents)")
            df[col] = df[col].astype("int64")
    return df


def _d(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_dataset(session: Session, dataset_dir: Path) -> IngestReport:
    """Insert every record from the folder. Assumes empty tables (call db.reset_db first)."""
    dataset_dir = Path(dataset_dir)
    manifest = validate_layout(dataset_dir)
    report = IngestReport(dataset=dataset_dir.name)

    session.add(Dataset(name=dataset_dir.name, path=str(dataset_dir), manifest=manifest))

    pos = _read_csv(dataset_dir / "purchase_orders.csv", PO_COLS)
    ships = _read_csv(dataset_dir / "shipments.csv", SHIPMENT_COLS)
    invs = _read_csv(dataset_dir / "invoices.csv", INVOICE_COLS)

    # Customers come from PO rows plus any contract-only customers named in the manifest.
    customers: dict[str, str] = {}
    for _, r in pos.iterrows():
        customers.setdefault(r.customer_id, r.customer_name)
    for c in manifest.get("contracts", []):
        customers.setdefault(c["customer_id"], c.get("customer_name", c["customer_id"]))
    for cid, name in customers.items():
        session.add(Customer(customer_id=cid, name=name))
    report.customers = len(customers)
    session.flush()

    refund_json = json.loads((dataset_dir / "refund.json").read_text())
    missing_keys = REFUND_KEYS - set(refund_json)
    if missing_keys:
        raise ContractError(f"refund.json: missing keys {sorted(missing_keys)}")
    if not isinstance(refund_json["amount_cents"], int):
        raise ContractError("refund.json.amount_cents must be an integer (cents)")
    refund = Refund(
        refund_id=refund_json["refund_id"],
        importer=refund_json["importer"],
        amount_cents=refund_json["amount_cents"],
        received_date=date.fromisoformat(refund_json["received_date"]),
        currency=refund_json.get("currency", "USD"),
        source=refund_json.get("source", ""),
        reference=refund_json.get("reference", ""),
    )
    for i, e in enumerate(refund_json["entries"]):
        if not isinstance(e["amount_cents"], int):
            raise ContractError(f"refund.json.entries[{i}].amount_cents must be an integer (cents)")
        refund.entries.append(RefundEntry(entry_number=e["entry_number"], amount_cents=e["amount_cents"],
                                          entry_date=_d(e.get("entry_date", "")), source_row=i))
    session.add(refund)
    report.refund_entries = len(refund.entries)
    entry_sum = sum(e.amount_cents for e in refund.entries)
    if entry_sum != refund.amount_cents:
        report.warnings.append(
            f"refund amount {refund.amount_cents} != sum of entries {entry_sum}; the difference will be unallocated")

    for i, r in pos.iterrows():
        session.add(PurchaseOrder(po_number=r.po_number, customer_id=r.customer_id, supplier=r.supplier,
                                  order_date=_d(r.order_date), description=r.description, quantity=int(r.quantity),
                                  unit_price_cents=int(r.unit_price_cents), total_cents=int(r.total_cents),
                                  source_row=i + 2))
    report.purchase_orders = len(pos)
    session.flush()

    for i, r in ships.iterrows():
        session.add(Shipment(shipment_id=r.shipment_id, entry_number=r.entry_number, bill_of_lading=r.bill_of_lading,
                             ship_date=_d(r.ship_date), arrival_date=_d(r.arrival_date), supplier=r.supplier,
                             description=r.description, hts_code=r.hts_code, quantity=int(r.quantity),
                             declared_value_cents=int(r.declared_value_cents), duty_paid_cents=int(r.duty_paid_cents),
                             po_number=r.po_number or None, source_row=i + 2))
    report.shipments = len(ships)

    known_pos = set(pos.po_number)
    for i, r in invs.iterrows():
        if r.po_number not in known_pos:
            report.warnings.append(f"invoices.csv row {i + 2}: po_number {r.po_number} not in purchase_orders.csv; skipped")
            continue
        session.add(Invoice(invoice_number=r.invoice_number, po_number=r.po_number, customer_id=r.customer_id,
                            invoice_date=_d(r.invoice_date), amount_cents=int(r.amount_cents),
                            tariff_surcharge_cents=int(r.tariff_surcharge_cents), source_row=i + 2))
        report.invoices += 1
    session.flush()
    return report
