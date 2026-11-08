"""The AI must actually have read synthetic_v1.

With no key, every contract must be served from the committed model-output cache, never the stub.
Until llm_cache/ has been populated once (make llm-cache with a key) the cache-dependent tests skip with
a message; the stub-misclassification test always runs, because it is what the cache is there to fix.
"""

import json

import pytest
from sqlalchemy import select

from sherlock.config import get_settings
from sherlock.ingest import load_dataset
from sherlock.llm.client import CacheMiss, LLMClient
from sherlock.llm.prompts import CONTRACT_EXTRACT_SYSTEM, CONTRACT_EXTRACT_VERSION, contract_extract_user
from sherlock.llm.stub import contract_extract as stub_extract
from sherlock.models import ParsedDocument
from sherlock.parsing.stage import parse_documents
from sherlock.pipeline import seed
from tests.conftest import DATASET_DIR, REPO

CACHE = REPO / "llm_cache" / "contract_extract"
MANIFEST = json.loads((DATASET_DIR / "manifest.json").read_text())
OFF_TEMPLATE = [c for c in MANIFEST["contracts"] if c.get("off_template")]

needs_cache = pytest.mark.skipif(
    not CACHE.exists() or not any(CACHE.glob("*.json")),
    reason="llm_cache/ has no model output yet: run `make llm-cache` with ANTHROPIC_API_KEY, then commit llm_cache/",
)


def _contract_docs(session):
    load_dataset(session, DATASET_DIR)
    parse_documents(session, DATASET_DIR)
    return session.scalars(select(ParsedDocument).where(ParsedDocument.doc_type == "contract")).all()


@needs_cache
def test_every_contract_is_served_from_cache_without_a_key(session):
    client = LLMClient(get_settings(), allow_stub=False)  # no key in tests; a miss raises instead of stubbing
    assert not client.has_key
    for doc in _contract_docs(session):
        try:
            res = client.complete_json("contract_extract", CONTRACT_EXTRACT_VERSION, CONTRACT_EXTRACT_SYSTEM,
                                       contract_extract_user(doc.pages))
        except CacheMiss as e:
            pytest.fail(f"{doc.source_path} would hit the stub: {e}")
        assert res.source == "cache" and res.model != "stub"


@needs_cache
def test_seed_report_contains_no_stub_readings(engine):
    report = seed(str(DATASET_DIR), engine)
    sources = report.stages["normalize"]["llm_sources"]
    assert "stub" not in sources, sources
    assert report.stages["normalize"]["models"], "no model recorded"


def test_stub_misclassifies_an_off_template_contract(session):
    """Rule-based reading fails on contracts that do not follow the template. This is why the model is needed."""
    assert len(OFF_TEMPLATE) == 2
    docs = {d.customer_id: d for d in _contract_docs(session)}
    wrong = 0
    for c in OFF_TEMPLATE:
        clause = stub_extract(docs[c["customer_id"]].pages)["clauses"][0]
        if clause["refund_owed_to_customer"] != c["expect"]["refund_owed_to_customer"]:
            wrong += 1
    assert wrong >= 1


@needs_cache
def test_model_reads_both_off_template_contracts_correctly(session):
    client = LLMClient(get_settings(), allow_stub=False)
    docs = {d.customer_id: d for d in _contract_docs(session)}
    for c in OFF_TEMPLATE:
        out = client.complete_json("contract_extract", CONTRACT_EXTRACT_VERSION, CONTRACT_EXTRACT_SYSTEM,
                                   contract_extract_user(docs[c["customer_id"]].pages)).output
        owed = [cl for cl in out["clauses"] if cl["refund_owed_to_customer"] == c["expect"]["refund_owed_to_customer"]]
        assert owed, f"{c['customer_id']}: model did not find the refund obligation: {out['clauses']}"


@needs_cache
def test_vague_clause_still_ambiguous_after_model_read(session):
    case = next(h for h in MANIFEST["hard_cases"] if h["id"] == "vague_surcharge")
    client = LLMClient(get_settings(), allow_stub=False)
    doc = next(d for d in _contract_docs(session) if d.customer_id == case["customer_id"])
    out = client.complete_json("contract_extract", CONTRACT_EXTRACT_VERSION, CONTRACT_EXTRACT_SYSTEM,
                               contract_extract_user(doc.pages)).output
    tariff = [cl for cl in out["clauses"] if cl["clause_type"] != "no_tariff_clause"]
    assert tariff and tariff[0]["refund_owed_to_customer"] == "unclear"
    assert tariff[0]["obligation_strength"] == "ambiguous" and tariff[0]["confidence"] < 0.6
