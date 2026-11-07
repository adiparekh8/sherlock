import json

from sqlalchemy import select

from sherlock.config import Settings
from sherlock.ingest import load_dataset
from sherlock.llm.client import LLMClient
from sherlock.llm.stub import contract_extract
from sherlock.models import ExtractedField, ParsedDocument
from sherlock.normalize import normalize_documents
from sherlock.parsing.stage import parse_documents
from sherlock.parsing.stub import StubParser
from tests.conftest import DATASET_DIR


def _pages(customer_id: str) -> list[dict]:
    m = json.loads((DATASET_DIR / "manifest.json").read_text())
    c = next(c for c in m["contracts"] if c["customer_id"] == customer_id)
    r = StubParser().parse(DATASET_DIR / c["file"])
    return [{"page": p.page, "text": p.text} for p in r.pages]


def test_no_key_uses_stub_then_cache(tmp_path):
    client = LLMClient(Settings(anthropic_api_key=None, llm_cache_dir=tmp_path))
    pages = _pages("CUST-001")
    first = client.complete_json("contract_extract", "v1", "sys", "user text", stub_input=pages)
    second = client.complete_json("contract_extract", "v1", "sys", "user text", stub_input=pages)
    assert first.source == "stub" and second.source == "cache"
    assert first.output == second.output
    assert list((tmp_path / "contract_extract").glob("*.json"))


def test_stub_classifies_planted_contracts():
    clear = contract_extract(_pages("CUST-001"))["clauses"][0]
    assert clear["clause_type"] == "refund_obligation" and clear["refund_owed_to_customer"] == "yes"
    keeps = contract_extract(_pages("CUST-002"))["clauses"][0]
    assert keeps["refund_owed_to_customer"] == "no"
    vague = contract_extract(_pages("CUST-003"))["clauses"][0]
    assert vague["obligation_strength"] == "ambiguous" and vague["refund_owed_to_customer"] == "unclear"
    assert vague["confidence"] < 0.5
    assert vague["page"] == 2 and "reasonable discretion" in vague["quoted_text"]


def test_normalize_stage_writes_fields_with_spans(session):
    load_dataset(session, DATASET_DIR)
    parse_documents(session, DATASET_DIR)
    summary = normalize_documents(session, DATASET_DIR)
    session.commit()
    assert summary["documents"] == 8
    doc = session.scalar(select(ParsedDocument).where(ParsedDocument.customer_id == "CUST-003"))
    fields = {f.field_name: f for f in session.scalars(select(ExtractedField).where(ExtractedField.document_id == doc.id))}
    assert fields["effective_date"].value_norm == "2022-11-01"
    assert fields["buyer_name"].value_norm == "Harbor & Vale Supply LLC"
    gl = fields["governing_law"]
    assert gl.span_start is not None and doc.pages[gl.page - 1]["text"][gl.span_start:gl.span_end] == gl.quoted_text
