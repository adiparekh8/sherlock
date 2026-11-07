"""The vague surcharge clause lands in review and nothing is auto-confirmed."""

import json

import pytest
from sqlalchemy import select

from sherlock.ingest import load_dataset
from sherlock.matching.engine import run_matching
from sherlock.models import CandidateObligation, Invoice
from sherlock.normalize import normalize_documents
from sherlock.obligations import extract_obligations
from sherlock.parsing.stage import parse_documents
from tests.conftest import DATASET_DIR


@pytest.fixture
def seeded(session):
    load_dataset(session, DATASET_DIR)
    parse_documents(session, DATASET_DIR)
    normalize_documents(session, DATASET_DIR)
    run_matching(session, DATASET_DIR)
    extract_obligations(session, DATASET_DIR)
    session.commit()
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())
    return session, {h["id"]: h for h in manifest["hard_cases"]}


def test_vague_clause_is_pending_with_low_confidence(seeded):
    session, cases = seeded
    case = cases["vague_surcharge"]
    obs = session.scalars(select(CandidateObligation).where(CandidateObligation.customer_id == case["customer_id"])).all()
    assert len(obs) == 1
    ob = obs[0]
    assert ob.status == "pending_review"
    assert ob.refund_owed_to_customer == "unclear" and ob.obligation_strength == "ambiguous"
    assert ob.confidence < 0.5
    assert ob.page == case["page"]
    assert ob.evidence[0]["source"] == case["contract_file"]
    assert ob.span_start is not None


def test_nothing_is_auto_confirmed_and_drafts_trace_to_ledger(seeded):
    session, _ = seeded
    obs = session.scalars(select(CandidateObligation)).all()
    assert obs and all(o.status == "pending_review" for o in obs)
    assert all(o.confirmed_amount_cents is None for o in obs)
    clear = next(o for o in obs if o.customer_id == "CUST-001")
    assert clear.refund_owed_to_customer == "yes" and clear.draft_amount_cents > 0
    assert any(e["entity"] == "invoice" for e in clear.evidence)
    # A customer that never paid a surcharge (DDP) has a zero draft.
    ddp = next(o for o in obs if o.customer_id == "CUST-008")
    assert ddp.draft_amount_cents == 0
    assert all(i.tariff_surcharge_cents == 0 for i in session.scalars(select(Invoice).where(Invoice.customer_id == "CUST-008")))
