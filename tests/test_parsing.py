import json

from sqlalchemy import select

from sherlock.config import Settings
from sherlock.ingest import load_dataset
from sherlock.models import ParsedDocument
from sherlock.parsing import get_parser
from sherlock.parsing.stage import parse_documents
from sherlock.parsing.stub import StubParser
from tests.conftest import DATASET_DIR


def test_stub_parser_reads_contract_pages():
    m = json.loads((DATASET_DIR / "manifest.json").read_text())
    vague = next(h for h in m["hard_cases"] if h["id"] == "vague_surcharge")
    result = StubParser().parse(DATASET_DIR / vague["contract_file"])
    assert result.page_count >= 2
    assert "at its reasonable discretion" in result.pages[1].text  # page 2


def test_parser_selection_defaults_to_stub():
    assert get_parser(Settings(google_application_credentials=None, docai_processor_name=None)).name == "stub"


def test_parse_stage_stores_documents(session):
    load_dataset(session, DATASET_DIR)
    summary = parse_documents(session, DATASET_DIR)
    session.commit()
    docs = session.scalars(select(ParsedDocument)).all()
    assert summary["documents"] == len(docs) == 10
    d = docs[0]
    assert d.customer_id and d.sha256 and d.pages[0]["text"]
