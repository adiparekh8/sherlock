"""Prompt text per task. Bump the version when the wording changes so cache keys roll over."""

CONTRACT_EXTRACT_VERSION = "v1"

CONTRACT_EXTRACT_SYSTEM = """You read customer supply contracts for an importer that has just received a lump-sum
tariff refund from U.S. Customs. The importer needs to know, per customer, whether any part of the refund is
contractually owed to that customer.

Extract:
1. fields: buyer_name, seller_name, effective_date (ISO), governing_law, payment_terms_days, and
   tariff_clause_heading (the heading of the section that addresses duties/tariffs/surcharges, or "" if none).
2. clauses: every clause that bears on tariffs, duties, surcharges, or refunds of them. For each, classify:
   - clause_type: surcharge_passthrough (tariffs billed to the customer as a surcharge), refund_obligation
     (seller must pass refunds to the customer), no_refund_obligation (seller keeps refunds, or prices were
     DDP so the customer never bore the tariff), or no_tariff_clause.
   - obligation_strength and refund_owed_to_customer as defined in the schema. Discretionary wording ("may",
     "at its discretion", "good faith", "discuss") is ambiguous and must be marked unclear with low confidence.
   Quote the clause verbatim. Never infer an obligation that the text does not state.

Return only the JSON object described by the schema."""


def contract_extract_user(pages: list[dict]) -> str:
    parts = []
    for p in pages:
        parts.append(f"=== Page {p['page']} ===\n{p['text']}")
    return "\n\n".join(parts)


SCAN_EXTRACT_VERSION = "v1"

SCAN_EXTRACT_SYSTEM = """You are reading a scanned business document (an image with no text layer) for an importer
reconciling a tariff refund. Read it carefully and extract the fields in the schema exactly as printed, then
normalize: money as integer cents, dates as ISO. Quote the printed text that supports each value and say where
on the page it sits. If a field is not on the page, return an empty value with confidence 0. If the page is not
legible enough to read a field with confidence, say so in notes and keep that field's confidence low. Never
invent a value. Return only the JSON object described by the schema."""


def scan_extract_user(hint: str, source_path: str) -> str:
    return (f"Document file: {source_path}. The person who scanned it labelled it as: {hint or 'unknown'}. "
            f"The page image is attached. Extract the fields.")
