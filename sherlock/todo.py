"""Workspace-scoped secretary TODO items derived from uploaded PDF analysis."""

from __future__ import annotations

import io
import re
import textwrap
import zipfile
from html import escape

from fpdf import FPDF


TODO_COLUMNS = ["task", "recipient", "email_subject", "email_body", "reason", "source_file", "page", "amount_usd", "status"]


def _party(records: list[dict]) -> str:
    for record_type in ("shipment", "invoice", "claim", "refund"):
        for record in records:
            if record.get("record_type") == record_type and record.get("counterparty"):
                return str(record["counterparty"])
    return next((str(r["counterparty"]) for r in records if r.get("counterparty")), "the exporter")


def _reason(record: dict, fallback: str) -> str:
    return str(record.get("evidence") or fallback or "Evidence needs review in the source PDF.")


def _email(task: str, recipient: str, reason: str, amount_usd: float | str) -> tuple[str, str]:
    subject = task
    amount = f"EUR {amount_usd:,.2f}" if isinstance(amount_usd, (int, float)) and amount_usd else "the amount shown in the packet"
    if task.startswith("Communication"):
        ask = f"Please confirm the status of the refund or credit for {amount}, and let us know if any action is still needed from our team."
    elif task.startswith("Confirm payment"):
        ask = f"Please confirm whether payment of {amount} has been completed and share the payment reference if available."
    else:
        ask = "Could you please send the missing document or detail, or let us know where we can retrieve it?"
    body = (f"Hi {recipient},\n\nWe’re following up on this item from our document review:\n\n"
            f"{task}\n\nEvidence noted in the packet: {reason}\n\n{ask}\n\n"
            "Thanks,\n[Your name]")
    return subject, body


def build_todos(uploads: list[dict]) -> list[dict]:
    """Create actionable, evidence-linked tasks without inventing a decision."""
    todos: list[dict] = []
    for upload in uploads:
        analysis = upload.get("analysis") or {}
        records = analysis.get("records") or []
        summary = str(analysis.get("summary") or "")
        party = _party(records)
        refund_records = [r for r in records if re.search(r"refund|refund notice", _reason(r, summary), re.I)]
        if refund_records or re.search(r"refund", summary, re.I):
            evidence = refund_records[0] if refund_records else {"page": 1, "evidence": summary}
            task = f"Communication to {party} regarding refund"
            reason = _reason(evidence, summary)
            amount_usd = (evidence.get("amount_cents") or 0) / 100
            subject, body = _email(task, party, reason, amount_usd)
            todos.append({
                "task": task, "recipient": party, "email_subject": subject, "email_body": body, "reason": reason,
                "source_file": upload.get("filename", "uploaded PDF"),
                "page": evidence.get("page") or 1,
                "amount_usd": amount_usd,
                "status": "Open",
            })
        for record in records:
            if record.get("direction") == "money_out":
                recipient = record.get("counterparty") or party
                task = f"Confirm payment to {recipient}"
                reason = _reason(record, summary)
                amount_usd = (record.get("amount_cents") or 0) / 100
                subject, body = _email(task, str(recipient), reason, amount_usd)
                todos.append({
                    "task": task, "recipient": recipient, "email_subject": subject, "email_body": body, "reason": reason,
                    "source_file": upload.get("filename", "uploaded PDF"),
                    "page": record.get("page") or 1,
                    "amount_usd": amount_usd,
                    "status": "Open",
                })
        for missing in analysis.get("missing_links") or []:
            task = f"Request evidence from {party}"
            reason = str(missing)
            subject, body = _email(task, party, reason, "")
            todos.append({
                "task": task, "recipient": party, "email_subject": subject, "email_body": body, "reason": reason,
                "source_file": upload.get("filename", "uploaded PDF"),
                "page": 1,
                "amount_usd": "",
                "status": "Open",
            })
    return todos


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
        reason = printable(row.get("reason", ""))
        source = printable(f"{row.get('source_file', '')} p.{row.get('page', '')}")
        width = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 6, f"{index}. {task}")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 5, f"Why: {reason}")
        pdf.set_text_color(110, 110, 110)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, 5, source)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
    return bytes(pdf.output())
