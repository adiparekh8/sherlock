"""Deterministic no-key fallback for each LLM task.

Rule-based and intentionally conservative: it finds the tariff paragraph by keywords and classifies it by
the presence of mandatory vs. discretionary language. Outputs are validated against the same schema as the
API output, and are tagged source="stub" in the cache so a real key replaces them.
"""

from __future__ import annotations

import re

MANDATORY_REFUND = re.compile(
    r"shall (pass through|credit|reimburse|refund|pay)[^.]*?(refund|credit|recover|decrease)", re.I | re.S)
MANDATORY_REFUND_ALT = re.compile(r"(refund|recovery|credit)[^.]*?shall (pass through|credit|reimburse|refund)", re.I | re.S)
SELLER_KEEPS = re.compile(r"(retained by seller|for seller'?s account|waives any claim)", re.I)
DDP = re.compile(r"(delivered duty paid|DDP|inclusive of all customs duties)", re.I)
DISCRETIONARY = re.compile(r"(at its (reasonable )?discretion|good faith|will discuss|may request|equitable adjustment)", re.I)
NET_OF = re.compile(r"net of", re.I)
SURCHARGE = re.compile(r"(surcharge|recovery charge|reimburse seller|separate (invoice )?line)", re.I)
TARIFF_WORDS = re.compile(r"(tariff|duties|duty|customs)", re.I)
REFUND_WORDS = re.compile(r"(refund|drawback|reliquidation|recover|decrease|reduction)", re.I)


def _paragraphs(text: str) -> list[str]:
    """Group pypdf's hard-wrapped lines into paragraphs: a line that starts with a section number starts one."""
    paras: list[list[str]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        if re.match(r"^\d{1,2}\.\s+[A-Z]", line) or not paras:
            paras.append([line])
        else:
            paras[-1].append(line)
    return ["\n".join(p) for p in paras]


def _first(pattern: re.Pattern, text: str, default: str = "") -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else default


def contract_extract(pages: list[dict]) -> dict:
    full = "\n".join(p["text"] for p in pages)
    fields = []

    def add(name, value, quote, page, conf):
        if value:
            fields.append({"name": name, "value": value, "quoted_text": quote, "page": page, "confidence": conf})

    m = re.search(r"between (.+?) \(\"Seller\"\), and (.+?) \(\"Buyer\"\)", full, re.S)
    if m:
        seller = re.sub(r",\s*a .*", "", m.group(1).replace("\n", " ")).strip()
        buyer = m.group(2).replace("\n", " ").strip()
        add("seller_name", seller, m.group(0).replace("\n", " ")[:200], 1, 0.9)
        add("buyer_name", buyer, m.group(0).replace("\n", " ")[:200], 1, 0.9)
    m = re.search(r"as of ([A-Z][a-z]+ \d{1,2}, \d{4})", full)
    if m:
        from datetime import datetime
        try:
            iso = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            iso = ""
        add("effective_date", iso, m.group(0), 1, 0.9)
    m = re.search(r"governed by the laws of (the State of [A-Z][a-z]+)", full)
    if m:
        page = next((p["page"] for p in pages if m.group(0) in p["text"]), 2)
        add("governing_law", m.group(1), m.group(0), page, 0.9)
    m = re.search(r"within (\w+) \((\d+)\) days of the invoice date", full)
    if m:
        page = next((p["page"] for p in pages if m.group(0) in p["text"]), 2)
        add("payment_terms_days", m.group(2), m.group(0), page, 0.85)

    clauses = []
    heading = ""
    for p in pages:
        for para in _paragraphs(p["text"]):
            if not TARIFF_WORDS.search(para):
                continue
            if re.match(r"^\d+\.\s+(Scope|Term|Pricing|Payment|Delivery|Warranty|Limitation|Governing|Entire)", para):
                continue
            head_m = re.match(r"^(\d+\.\s+[^\n]+)", para)
            heading = heading or (head_m.group(1) if head_m else "")
            clauses.append(_classify(para, p["page"]))
    if not clauses:
        clauses.append({"clause_type": "no_tariff_clause", "page": 1, "quoted_text": "", "obligation_strength": "none",
                        "refund_owed_to_customer": "no", "confidence": 0.7,
                        "reasoning": "No clause mentions tariffs, duties, or surcharges."})
    add("tariff_clause_heading", heading, heading, 2 if heading else 1, 0.8 if heading else 0.5)
    return {"fields": fields, "clauses": clauses}


def _classify(para: str, page: int) -> dict:
    base = {"page": page, "quoted_text": para}
    para = re.sub(r"\s+", " ", para)  # pypdf hard-wraps lines; classify on flattened text
    if DDP.search(para):
        return {**base, "clause_type": "no_refund_obligation", "obligation_strength": "clear",
                "refund_owed_to_customer": "no", "confidence": 0.85,
                "reasoning": "Prices are delivered duty paid, so the customer never bore the tariff; nothing to pass back."}
    if SELLER_KEEPS.search(para):
        return {**base, "clause_type": "no_refund_obligation", "obligation_strength": "clear",
                "refund_owed_to_customer": "no", "confidence": 0.88,
                "reasoning": "The clause states that any refund is retained by Seller and the Buyer waives claims to it."}
    if DISCRETIONARY.search(para) and not (MANDATORY_REFUND.search(para) or MANDATORY_REFUND_ALT.search(para)):
        return {**base, "clause_type": "surcharge_passthrough", "obligation_strength": "ambiguous",
                "refund_owed_to_customer": "unclear", "confidence": 0.35,
                "reasoning": "Price adjustments are at Seller's discretion and the clause promises only good-faith "
                             "discussion of reductions. The text does not decide whether a refund share is owed."}
    if MANDATORY_REFUND.search(para) or MANDATORY_REFUND_ALT.search(para):
        if NET_OF.search(para):
            return {**base, "clause_type": "refund_obligation", "obligation_strength": "conditional",
                    "refund_owed_to_customer": "yes", "confidence": 0.75,
                    "reasoning": "Seller must reimburse refunds, but net of administrative costs; the amount owed "
                                 "depends on a deduction the clause caps but does not fix."}
        return {**base, "clause_type": "refund_obligation", "obligation_strength": "clear",
                "refund_owed_to_customer": "yes", "confidence": 0.9,
                "reasoning": "The clause uses mandatory language (shall) requiring Seller to pass refunded duties "
                             "to Buyer within a stated period."}
    if SURCHARGE.search(para) and not REFUND_WORDS.search(para):
        return {**base, "clause_type": "surcharge_passthrough", "obligation_strength": "ambiguous",
                "refund_owed_to_customer": "unclear", "confidence": 0.5,
                "reasoning": "Tariffs were passed through as a surcharge but the clause is silent on refunds."}
    return {**base, "clause_type": "no_tariff_clause", "obligation_strength": "none",
            "refund_owed_to_customer": "no", "confidence": 0.6,
            "reasoning": "Tariff language is present but creates neither a surcharge nor a refund obligation."}


STUBS = {"contract_extract": contract_extract}
