"""Output shapes for every LLM task. The JSON schema sent to the API and the validator for
cached/stub outputs are both generated from these, so the three can never drift apart."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContractField(Strict):
    name: Literal["buyer_name", "seller_name", "effective_date", "governing_law", "payment_terms_days",
                  "tariff_clause_heading"]
    value: str = Field(description="Normalized value: ISO date for dates, plain integer for day counts")
    quoted_text: str = Field(description="Exact text from the document that supports the value")
    page: int = Field(description="1-based page the quote appears on")
    confidence: float = Field(description="0 to 1")


class ContractClause(Strict):
    clause_type: Literal["surcharge_passthrough", "refund_obligation", "no_refund_obligation", "no_tariff_clause"]
    page: int
    quoted_text: str = Field(description="The full clause text, verbatim from the document")
    obligation_strength: Literal["clear", "conditional", "ambiguous", "none"] = Field(
        description="clear: unambiguous duty to pass a refund to the customer or unambiguous that none is owed; "
                    "conditional: owed subject to stated conditions (net of costs, upon request); "
                    "ambiguous: discretionary or good-faith language that does not decide the question; "
                    "none: no tariff language")
    refund_owed_to_customer: Literal["yes", "no", "unclear"]
    confidence: float = Field(description="0 to 1: how sure the reading of refund_owed_to_customer is")
    reasoning: str = Field(description="Two or three sentences a reviewer can check against the quote")


class ContractExtraction(Strict):
    fields: list[ContractField]
    clauses: list[ContractClause]


class ScanField(Strict):
    value: str = Field(description="Normalized value; money as integer cents with no symbols, dates as ISO, "
                                   "empty string if not present on the page")
    confidence: float = Field(description="0 to 1")
    quoted_text: str = Field(description="The text on the page that supports the value, as printed")
    region: str = Field(description="Where on the page it appears, e.g. 'top right header', 'line items table'")


class ScanExtraction(Strict):
    document_type: Literal["invoice", "purchase_order", "bill_of_lading", "other", "unreadable"]
    invoice_number: ScanField
    po_number: ScanField
    customer: ScanField = Field(description="Customer id if printed, else the bill-to name")
    invoice_date: ScanField
    amount_cents: ScanField = Field(description="Total due, integer cents")
    tariff_surcharge_cents: ScanField = Field(description="Any separately stated tariff/duty surcharge line, integer cents; "
                                                          "'0' if none is printed")
    notes: str = Field(description="One or two sentences on legibility and anything a reviewer should check")


TASK_SCHEMAS: dict[str, type[BaseModel]] = {"contract_extract": ContractExtraction, "scan_extract": ScanExtraction}
