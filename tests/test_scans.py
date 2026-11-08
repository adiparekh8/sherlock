"""The scanned-invoice path: the model reads the page, the proposal attaches to the queued line, and only a
human decision creates the invoice and the allocation.

The real model output lives in llm_cache/ once make llm-cache has run. These tests write a known cache
entry into a temporary cache dir so the no-key cache path is exercised exactly as in the demo."""

import json

import pytest
from sqlalchemy import select

from sherlock import db, ledger, review
from sherlock.config import get_settings
from sherlock.export import generate_export
from sherlock.ingest import load_dataset
from sherlock.llm import client as llm_client
from sherlock.llm.client import LLMClient
from sherlock.llm.prompts import SCAN_EXTRACT_VERSION
from sherlock.memo import generate_memo
from sherlock.models import AllocationRecord, Invoice, ParsedDocument
from sherlock.parsing.stage import parse_documents
from sherlock.pipeline import seed
from sherlock.scans import page_image_png, scan_cache_inputs
from tests.conftest import DATASET_DIR

MANIFEST = json.loads((DATASET_DIR / "manifest.json").read_text())
CASE = next(h for h in MANIFEST["hard_cases"] if h["id"] == "missing_invoice")
TRUTH = CASE["scan_truth"]


def _field(value, conf=0.96, quote="", region="header"):
    return {"value": str(value), "confidence": conf, "quoted_text": quote or str(value), "region": region}


MODEL_READING = {
    "document_type": "invoice",
    "invoice_number": _field(TRUTH["invoice_number"], region="top right"),
    "po_number": _field(TRUTH["po_number"], region="bill-to block"),
    "customer": _field(TRUTH["customer_id"], 0.9, region="bill-to block"),
    "invoice_date": _field(TRUTH["invoice_date"], 0.93, region="top right"),
    "amount_cents": _field(TRUTH["amount_cents"], 0.95, "TOTAL DUE $75,036.07", "totals box"),
    "tariff_surcharge_cents": _field(TRUTH["tariff_surcharge_cents"], 0.94, "Tariff Surcharge $12,103.87", "line items"),
    "notes": "Slight skew and grain; all figures legible.",
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """A temp llm_cache holding the model's reading of the scan, and nothing else."""
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    llm_client._default = None
    yield tmp_path / "cache"
    get_settings.cache_clear()
    llm_client._default = None


def _write_scan_cache(session, cache_dir):
    doc = session.scalar(select(ParsedDocument).where(ParsedDocument.doc_type == "scan"))
    system, user, images = scan_cache_inputs(doc, DATASET_DIR, "invoice")
    path = LLMClient(get_settings()).cache_path("scan_extract", SCAN_EXTRACT_VERSION, system, user, images)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": "claude-opus-5-5", "source": "api", "output": MODEL_READING}))


def test_scan_pdf_has_no_text_layer_but_an_image():
    from pypdf import PdfReader

    reader = PdfReader(str(DATASET_DIR / CASE["scan_file"]))
    assert reader.pages[0].extract_text().strip() == ""
    assert len(page_image_png(DATASET_DIR, CASE["scan_file"])) > 10_000


def test_without_cache_the_scan_is_unreadable_and_line_stays_queued(engine, cache_dir):
    seed(str(DATASET_DIR), engine)
    with db.session_scope() as s:
        doc = s.scalar(select(ParsedDocument).where(ParsedDocument.doc_type == "scan"))
        assert doc.extract_source == "stub"
        rec = s.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == CASE["shipment_id"]))
        assert rec.needs_review and rec.unallocated_reason == "missing_invoice"
        assert "invoice_from_scan" not in rec.proposal[0]


def _seed_with_reading(engine, cache_dir):
    # Pass 1 parses the scan so its cache key can be computed; pass 2 seeds for real with the cache in place.
    db.reset_db(engine)
    with db.session_scope() as s:
        load_dataset(s, DATASET_DIR)
        parse_documents(s, DATASET_DIR)
        _write_scan_cache(s, cache_dir)
    return seed(str(DATASET_DIR), engine)


def test_cached_reading_attaches_as_a_proposal_not_an_invoice(engine, cache_dir):
    report = _seed_with_reading(engine, cache_dir)
    assert report.stages["scans"] == {"scans": 1, "readable": 1, "llm_sources": {"cache": 1}}
    with db.session_scope() as s:
        assert s.get(Invoice, TRUTH["invoice_number"]) is None  # nothing created automatically
        rec = s.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == CASE["shipment_id"]))
        assert rec.needs_review and rec.review_status == "unallocated" and rec.unallocated_reason == "missing_invoice"
        line = rec.proposal[0]
        assert line["invoice_number"] == TRUTH["invoice_number"]
        assert line["invoice_from_scan"]["amount_cents"] == TRUTH["amount_cents"]
        assert any(e["entity"] == "scan" and e["source"] == CASE["scan_file"] and e["locator"] == "page 1" for e in rec.evidence)
        assert "read by the model" in rec.reasoning
        queued = {a["id"] for a in review.queue(s)["allocations"]}
        assert rec.id in queued


def test_approving_creates_invoice_and_allocation_with_decision_logged(engine, cache_dir):
    _seed_with_reading(engine, cache_dir)
    with db.session_scope() as s:
        rec = s.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == CASE["shipment_id"]))
        before = ledger.summarize(s)
        d = review.approve_allocation(s, rec.id, "adi", "scan matches the PO quantities and the AP stamp")
        s.flush()

        inv = s.get(Invoice, TRUTH["invoice_number"])
        assert inv is not None
        assert inv.amount_cents == TRUTH["amount_cents"] and inv.tariff_surcharge_cents == TRUTH["tariff_surcharge_cents"]
        assert inv.po_number == TRUTH["po_number"] and inv.created_by_decision_id == d.id and inv.source_document_id

        live = s.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == CASE["shipment_id"],
                                                       AllocationRecord.superseded_by_decision_id.is_(None)))
        assert live.review_status == "human_confirmed" and live.invoice_number == TRUTH["invoice_number"]
        assert live.customer_id == TRUTH["customer_id"] and live.created_by_decision_id == d.id
        assert d.after["created_invoices"][0]["invoice_number"] == TRUTH["invoice_number"]

        after = ledger.summarize(s)
        assert after.conserved and after.allocated_cents == before.allocated_cents + rec.amount_cents
        assert rec.id not in {a["id"] for a in review.queue(s)["allocations"]}

        memo = generate_memo(s)
        assert f"Created invoice {TRUTH['invoice_number']}" in memo and "adi" in memo
        rows = [r for r in generate_export(s).splitlines() if TRUTH["invoice_number"] in r]
        assert rows and "human_confirmed" in rows[0]


def test_rejecting_leaves_it_unallocated_and_creates_nothing(engine, cache_dir):
    _seed_with_reading(engine, cache_dir)
    with db.session_scope() as s:
        rec = s.scalar(select(AllocationRecord).where(AllocationRecord.shipment_id == CASE["shipment_id"]))
        review.reject_allocation(s, rec.id, "adi", "want the original before booking")
        assert s.get(Invoice, TRUTH["invoice_number"]) is None
        assert rec.review_status == "unallocated" and not rec.needs_review
        assert ledger.summarize(s).conserved
