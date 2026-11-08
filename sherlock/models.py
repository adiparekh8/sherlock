"""SQLAlchemy tables.

Money is always integer cents (BigInteger). Confidence is a float in [0, 1] and is not money.
One dataset is loaded at a time; seeding resets every table.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ReviewStatus(str, enum.Enum):
    AUTO_PROPOSED = "auto_proposed"
    HUMAN_CONFIRMED = "human_confirmed"
    HUMAN_OVERRIDDEN = "human_overridden"
    UNALLOCATED = "unallocated"


class ObligationStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class DecisionAction(str, enum.Enum):
    APPROVE = "approve"
    OVERRIDE = "override"
    REJECT = "reject"


# --------------------------------------------------------------------------- dataset entities


class Dataset(Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    path: Mapped[str] = mapped_column(String(500))
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    seeded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Refund(Base):
    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    importer: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    received_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    source: Mapped[str] = mapped_column(String(200), default="")
    reference: Mapped[str] = mapped_column(String(200), default="")

    entries: Mapped[list["RefundEntry"]] = relationship(back_populates="refund", cascade="all, delete-orphan")


class RefundEntry(Base):
    """A customs entry line on the refund notice. The refund total should equal the sum of these."""

    __tablename__ = "refund_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_id: Mapped[str] = mapped_column(ForeignKey("refunds.refund_id"))
    entry_number: Mapped[str] = mapped_column(String(50), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_row: Mapped[int] = mapped_column(Integer, default=0)

    refund: Mapped[Refund] = relationship(back_populates="entries")


class Shipment(Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    entry_number: Mapped[str] = mapped_column(String(50), index=True)
    bill_of_lading: Mapped[str] = mapped_column(String(50), default="")
    ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    hts_code: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    declared_value_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    duty_paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    po_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_row: Mapped[int] = mapped_column(Integer, default=0)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(50), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    supplier: Mapped[str] = mapped_column(String(200), default="")
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    source_row: Mapped[int] = mapped_column(Integer, default=0)

    customer: Mapped[Customer] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    tariff_surcharge_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    source_row: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- documents


class ParsedDocument(Base):
    """A document after the DocumentParser ran on it. Pages hold the raw text per page."""

    __tablename__ = "parsed_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(50))  # contract | refund_notice | shipments_csv | ...
    source_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser: Mapped[str] = mapped_column(String(50))  # stub | docai | csv
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[list] = mapped_column(JSON, default=list)  # [{"page": 1, "text": "..."}]
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"), nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    extract_source: Mapped[str] = mapped_column(String(20), default="")  # api | cache | stub, set by normalization
    extract_model: Mapped[str] = mapped_column(String(100), default="")  # model id, or "stub"

    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ExtractedField(Base):
    """One normalized field pulled from a document, with where it came from and how sure we are."""

    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("parsed_documents.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(50))  # contract | refund | ...
    record_key: Mapped[str] = mapped_column(String(100))  # e.g. customer_id
    field_name: Mapped[str] = mapped_column(String(100))
    value_raw: Mapped[str] = mapped_column(Text, default="")
    value_norm: Mapped[dict | list | str | int | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quoted_text: Mapped[str] = mapped_column(Text, default="")
    extractor: Mapped[str] = mapped_column(String(50), default="rule")  # rule | llm | llm_stub
    prompt_version: Mapped[str] = mapped_column(String(50), default="")

    document: Mapped[ParsedDocument] = relationship(back_populates="fields")


# --------------------------------------------------------------------------- ledger


class AllocationRecord(Base):
    """One line of the allocation ledger.

    Conservation: for a refund, the sum of amount_cents over live (non-superseded) records equals
    the refund amount. Allocated lines carry a customer; unallocated lines carry a reason.
    """

    __tablename__ = "allocation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_id: Mapped[str] = mapped_column(ForeignKey("refunds.refund_id"), index=True)
    refund_entry_id: Mapped[int | None] = mapped_column(ForeignKey("refund_entries.id"), nullable=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.shipment_id"), nullable=True)
    po_number: Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.po_number"), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(ForeignKey("invoices.invoice_number"), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"), nullable=True)

    amount_cents: Mapped[int] = mapped_column(BigInteger)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_method: Mapped[str] = mapped_column(String(100), default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{"source": ..., "locator": ..., "quoted_text": ...}]
    reasoning: Mapped[str] = mapped_column(Text, default="")

    review_status: Mapped[str] = mapped_column(String(30), default=ReviewStatus.AUTO_PROPOSED.value, index=True)
    unallocated_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    proposal: Mapped[list] = mapped_column(JSON, default=list)  # candidate lines the AI suggests for a queued item
    conflicts: Mapped[list] = mapped_column(JSON, default=list)  # evidence that disagrees, shown side by side

    superseded_by_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_decisions.id"), nullable=True, index=True
    )
    created_by_decision_id: Mapped[int | None] = mapped_column(ForeignKey("review_decisions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_live(self) -> bool:
        return self.superseded_by_decision_id is None


class CandidateObligation(Base):
    """A contract clause that may oblige the importer to pass a refund share to a customer."""

    __tablename__ = "candidate_obligations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    contract_document_id: Mapped[int] = mapped_column(ForeignKey("parsed_documents.id"))
    clause_type: Mapped[str] = mapped_column(String(50))  # surcharge_passthrough | refund_obligation
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quoted_text: Mapped[str] = mapped_column(Text, default="")
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    draft_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    draft_basis: Mapped[str] = mapped_column(Text, default="")
    obligation_strength: Mapped[str] = mapped_column(String(30), default="")  # clear | conditional | ambiguous | none
    refund_owed_to_customer: Mapped[str] = mapped_column(String(10), default="unclear")  # yes | no | unclear
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # the clause citation plus surcharge invoices
    confirmed_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # set by a human decision
    status: Mapped[str] = mapped_column(String(30), default=ObligationStatus.PENDING_REVIEW.value, index=True)
    decided_by_decision_id: Mapped[int | None] = mapped_column(ForeignKey("review_decisions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewDecision(Base):
    """Who did what, when, to which item, and why. Before/after snapshots make overrides traceable."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(30))  # allocation | obligation
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
