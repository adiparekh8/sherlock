"""Workspace-scoped secretary TODO items derived from uploaded PDF analysis."""

from __future__ import annotations

import io
import re
import textwrap
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from html import escape

from fpdf import FPDF
import requests


TODO_COLUMNS = ["task", "urgency", "recipient", "email_subject", "email_body", "reason", "source_file", "page", "currency", "amount_original", "amount_usd", "fx_rate", "fx_rate_date", "status"]


def _party(records: list[dict]) -> str:
    for record_type in ("shipment", "invoice", "claim", "refund"):
        for record in records:
            if record.get("record_type") == record_type and record.get("counterparty"):
                return str(record["counterparty"])
    return next((str(r["counterparty"]) for r in records if r.get("counterparty")), "the exporter")


def _reason(record: dict, fallback: str) -> str:
    return str(record.get("evidence") or fallback or "Evidence needs review in the source PDF.")


def _currency(record: dict, fallback: str) -> str:
    text = f"{record.get('evidence', '')} {fallback}".upper()
    for marker, code in (("EUR", "EUR"), ("€", "EUR"), ("GBP", "GBP"), ("£", "GBP"), ("CAD", "CAD"), ("AUD", "AUD"), ("JPY", "JPY"), ("¥", "JPY"), ("USD", "USD"), ("$", "USD")):
        if marker in text:
            return code
    return "USD"


@lru_cache(maxsize=32)
def _fx_rate_to_usd(currency: str) -> tuple[Decimal | None, str]:
    if currency == "USD":
        return Decimal("1"), ""
    try:
        response = requests.get(f"https://api.frankfurter.dev/v2/rate/{currency}/USD", timeout=5)
        response.raise_for_status()
        data = response.json()
        return Decimal(str(data["rate"])), str(data.get("date", ""))
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None, ""


def _money(amount_cents: int | None, currency: str) -> dict:
    if amount_cents is None:
        return {"currency": currency, "amount_original": "", "amount_usd": "", "fx_rate": "", "fx_rate_date": ""}
    original = (Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
    rate, rate_date = _fx_rate_to_usd(currency)
    converted = (original * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if rate is not None else None
    return {"currency": currency, "amount_original": float(original), "amount_usd": float(converted) if converted is not None else "", "fx_rate": float(rate) if rate is not None else "", "fx_rate_date": rate_date}


def _amount_phrase(money: dict) -> str:
    original = f"{money['currency']} {money['amount_original']:,.2f}" if money.get("amount_original") != "" else "the amount shown in the packet"
    if money.get("currency") == "USD" or money.get("amount_usd") == "":
        return original if money.get("amount_usd") != "" else f"{original}; USD conversion unavailable"
    return f"{original} (approximately USD ${money['amount_usd']:,.2f} at {money['fx_rate']} on {money['fx_rate_date']})"


def _urgency(task: str, reason: str) -> str:
    """Give the secretary a small, understandable priority signal."""
    text = f"{task} {reason}".lower()
    if task.startswith(("Communication", "Confirm payment")) or re.search(
        r"refund|payment|settlement|credit memo|due|deadline", text
    ):
        return "high"
    if task.startswith("Request evidence") or re.search(
        r"missing|absent|not printed|not included|unable to verify", text
    ):
        return "medium"
    return "low"


def _email(task: str, recipient: str, reason: str, money: dict, source_file: str, page: int) -> tuple[str, str]:
    subject = task
    amount = _amount_phrase(money)
    if task.startswith("Communication"):
        ask = f"Please confirm the status of the refund or credit for {amount}, and let us know if any action is still needed from our team."
    elif task.startswith("Confirm payment"):
        ask = f"Please confirm whether payment of {amount} has been completed and share the payment reference if available."
    else:
        ask = "Could you please send the missing document or detail, or let us know where we can retrieve it?"
    body = (f"Hi {recipient},\n\nWe’re following up on this item from our document review:\n\n"
            f"{task}\n\nEvidence / warrant for this request:\n{reason}\n"
            f"Source: {source_file}, page {page}\n\n{ask}\n\n"
            "Thanks,\n[Your name]")
    return subject, body


def build_todos(uploads: list[dict]) -> list[dict]:
    """Create actionable, evidence-linked tasks without inventing a decision."""
    todos: list[dict] = []
    for upload in uploads:
        analysis = upload.get("analysis") or {}
        records = analysis.get("records") or []
        summary = str(analysis.get("summary") or "")
        source_file = upload.get("filename", "uploaded PDF")
        party = _party(records)
        refund_records = [r for r in records if re.search(r"refund|refund notice", _reason(r, summary), re.I)]
        if refund_records or re.search(r"refund", summary, re.I):
            evidence = refund_records[0] if refund_records else {"page": 1, "evidence": summary}
            task = f"Communication to {party} regarding refund"
            reason = _reason(evidence, summary)
            money = _money(evidence.get("amount_cents"), _currency(evidence, summary))
            page = evidence.get("page") or 1
            subject, body = _email(task, party, reason, money, source_file, page)
            todos.append({
                "task": task, "recipient": party, "email_subject": subject, "email_body": body, "reason": reason,
                "urgency": _urgency(task, reason),
                "source_file": source_file,
                "page": page,
                **money,
                "status": "Open",
            })
        for record in records:
            if record.get("direction") == "money_out":
                recipient = record.get("counterparty") or party
                task = f"Confirm payment to {recipient}"
                reason = _reason(record, summary)
                money = _money(record.get("amount_cents"), _currency(record, summary))
                page = record.get("page") or 1
                subject, body = _email(task, str(recipient), reason, money, source_file, page)
                todos.append({
                    "task": task, "recipient": recipient, "email_subject": subject, "email_body": body, "reason": reason,
                    "urgency": _urgency(task, reason),
                    "source_file": source_file,
                    "page": page,
                    **money,
                    "status": "Open",
                })
        for missing in analysis.get("missing_links") or []:
            task = f"Request evidence from {party}"
            reason = str(missing)
            subject, body = _email(task, party, reason, _money(None, "USD"), source_file, 1)
            todos.append({
                "task": task, "recipient": party, "email_subject": subject, "email_body": body, "reason": reason,
                "urgency": _urgency(task, reason),
                "source_file": source_file,
                "page": 1,
                "amount_usd": "",
                "status": "Open",
            })
    priority = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted(enumerate(todos), key=lambda pair: (priority.get(pair[1].get("urgency", "medium"), 1), pair[0]))
    return [row for _, row in ranked[:5]]


def _xml_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f'<c t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def generate_xlsx(rows: list[dict]) -> bytes:
    """Write a small dependency-free .xlsx workbook."""
    body = []
    header = "<row>" + "".join(_xml_cell(c.replace("_", " ").title()) for c in TODO_COLUMNS) + "</row>"
    body.append(header)
    for row in rows:
        body.append("<row>" + "".join(_xml_cell(row.get(c, "")) for c in TODO_COLUMNS) + "</row>")
    sheet = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>" + "".join(body) + "</sheetData></worksheet>"
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="TODO" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return out.getvalue()


def generate_pdf(rows: list[dict]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(True, 14)
    pdf.add_page()
    pdf.set_title("Sherlock TODO")
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Sherlock TODO")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 9)
    if not rows:
        pdf.cell(0, 8, "No open tasks.")
    for index, row in enumerate(rows, 1):
        def printable(value: object) -> str:
            text = str(value).encode("latin-1", "replace").decode("latin-1")
            return textwrap.fill(text, width=100, break_long_words=True, break_on_hyphens=True)

        task = printable(row.get("task", ""))
        urgency = printable(str(row.get("urgency", "medium")).title())
        reason = printable(row.get("reason", ""))
        source = printable(f"{row.get('source_file', '')} p.{row.get('page', '')}")
        width = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 6, f"{index}. [{urgency} priority] {task}")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 5, f"Why: {reason}")
        pdf.set_text_color(110, 110, 110)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 5, source)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
    return bytes(pdf.output())
