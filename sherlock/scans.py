"""Scanned documents: image-only PDFs that never made it into the CSVs.

The page image goes to the model (vision) through the same cached client as everything else. The
reading becomes ExtractedField rows and, where it names a PO that has no invoice, a proposal on that
queued allocation line. It never becomes an Invoice row by itself; see review._materialize_scanned_invoice.
"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.llm import get_llm
from sherlock.llm.client import LLMResult
from sherlock.llm.prompts import SCAN_EXTRACT_SYSTEM, SCAN_EXTRACT_VERSION, scan_extract_user
from sherlock.models import Dataset, ExtractedField, ParsedDocument

SCAN_FIELDS = ("invoice_number", "po_number", "customer", "invoice_date", "amount_cents", "tariff_surcharge_cents")


def page_image_png(dataset_dir: Path, source_path: str, page: int = 0) -> bytes:
    """The embedded page image, re-encoded as PNG so the bytes (and the cache key) do not depend on the
    PDF container. Image-only PDFs carry exactly one image per page."""
    reader = PdfReader(str(Path(dataset_dir) / source_path))
    pg = reader.pages[page]
    if not pg.images:
        raise ValueError(f"{source_path} page {page + 1} has no embedded image")
    img = pg.images[0].image.convert("L")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def scan_cache_inputs(doc: ParsedDocument, dataset_dir: Path, hint: str = "") -> tuple[str, str, list[bytes]]:
    return SCAN_EXTRACT_SYSTEM, scan_extract_user(hint, doc.source_path), [page_image_png(dataset_dir, doc.source_path)]


def extract_scan(doc: ParsedDocument, dataset_dir: Path, hint: str = "") -> LLMResult:
    system, user, images = scan_cache_inputs(doc, dataset_dir, hint)
    return get_llm().complete_json("scan_extract", SCAN_EXTRACT_VERSION, system, user, stub_input=None, images=images)


def extract_scans(session: Session, dataset_dir: Path) -> dict:
    """Pipeline stage: read every scan with the model and store its fields with confidence and region."""
    dataset = session.scalar(select(Dataset))
    hints = {s["file"]: s.get("hint", "") for s in (dataset.manifest.get("scans", []) if dataset else [])}
    docs = session.scalars(select(ParsedDocument).where(ParsedDocument.doc_type == "scan")).all()
    sources: dict[str, int] = {}
    readable = 0
    for doc in docs:
        res = extract_scan(doc, Path(dataset_dir), hints.get(doc.source_path, ""))
        sources[res.source] = sources.get(res.source, 0) + 1
        doc.extract_source = res.source
        doc.extract_model = res.model
        out = res.output
        extractor = "llm" if res.model != "stub" else "llm_stub"
        session.add(ExtractedField(document_id=doc.id, record_type="scan", record_key=doc.source_path,
                                   field_name="document_type", value_raw=out["document_type"], value_norm=out["document_type"],
                                   confidence=1.0 if out["document_type"] != "unreadable" else 0.0, page=1,
                                   quoted_text=out.get("notes", ""), extractor=extractor, prompt_version=SCAN_EXTRACT_VERSION))
        for name in SCAN_FIELDS:
            f = out[name]
            session.add(ExtractedField(document_id=doc.id, record_type="scan", record_key=doc.source_path,
                                       field_name=name, value_raw=f["quoted_text"], value_norm=f["value"],
                                       confidence=f["confidence"], page=1, quoted_text=f"{f['region']}: {f['quoted_text']}".strip(": "),
                                       extractor=extractor, prompt_version=SCAN_EXTRACT_VERSION))
        if out["document_type"] != "unreadable":
            readable += 1
    session.flush()
    return {"scans": len(docs), "readable": readable, "llm_sources": sources}


def scanned_invoice_candidates(session: Session) -> dict[str, dict]:
    """po_number -> what the model read off a scanned invoice naming that PO. Used by the matching engine
    to attach a proposal to a missing_invoice line. Only invoices with a PO number, an invoice number and a
    total are candidates."""
    out: dict[str, dict] = {}
    docs = session.scalars(select(ParsedDocument).where(ParsedDocument.doc_type == "scan")).all()
    for doc in docs:
        fields = {f.field_name: f for f in doc.fields}
        if fields.get("document_type") is None or fields["document_type"].value_norm != "invoice":
            continue
        po = (fields["po_number"].value_norm or "").strip()
        inv = (fields["invoice_number"].value_norm or "").strip()
        amount = (fields["amount_cents"].value_norm or "").strip()
        if not (po and inv and amount.lstrip("-").isdigit()):
            continue
        surcharge = (fields["tariff_surcharge_cents"].value_norm or "0").strip()
        confs = [fields[n].confidence for n in ("invoice_number", "po_number", "amount_cents")]
        out[po] = {
            "document_id": doc.id,
            "invoice_number": inv,
            "po_number": po,
            "customer": fields["customer"].value_norm or "",
            "invoice_date": fields["invoice_date"].value_norm or "",
            "amount_cents": int(amount),
            "tariff_surcharge_cents": int(surcharge) if surcharge.lstrip("-").isdigit() else 0,
            "confidence": round(min(confs), 4),
            "evidence": {"source": doc.source_path, "locator": "page 1", "entity": "scan", "key": inv,
                         "document_id": doc.id,
                         "quoted_text": f"{inv} | PO {po} | total {fields['amount_cents'].value_raw} | "
                                        f"surcharge {fields['tariff_surcharge_cents'].value_raw} (read by {doc.extract_model})"},
        }
    return out
