"""payables.csv: only human-confirmed obligations, regenerated from the live ledger."""

import csv
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from sherlock import db, review
from sherlock.export import PAYABLES_LABEL, generate_payables
from sherlock.models import CandidateObligation
from sherlock.pipeline import seed
from tests.conftest import DATASET_DIR

NOW = datetime(2025, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def seeded(engine):
    seed(str(DATASET_DIR), engine)
    s = db.get_sessionmaker()()
    yield s
    s.close()


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_payables_empty_until_a_human_confirms(seeded):
    s = seeded
    assert _rows(generate_payables(s, NOW)) == []  # everything is pending

    clear = s.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-001"))
    vague = s.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-003"))
    nothing = s.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-002"))
    d = review.approve_obligation(s, clear.id, "sid", "clause 4 is unambiguous")
    review.reject_obligation(s, nothing.id, "sid", "seller keeps refunds per clause 4")
    s.commit()

    rows = _rows(generate_payables(s, NOW))
    assert len(rows) == 1
    r = rows[0]
    assert r["export_label"] == PAYABLES_LABEL
    assert r["customer_id"] == "CUST-001" and int(r["amount_cents"]) == clear.confirmed_amount_cents > 0
    assert r["decision_id"] == str(d.id) and r["decided_by"] == "sid" and r["reason"] == "clause 4 is unambiguous"
    assert r["contract_file"].endswith(".pdf") and r["contract_page"] == "2" and "Tariff" in r["clause_excerpt"]
    assert vague.status == "pending_review"  # untouched, and absent from the file

    # Regenerates from the ledger: an override at a different amount replaces the row's amount.
    assert generate_payables(s, NOW) == generate_payables(s, NOW)
    cond = s.scalar(select(CandidateObligation).where(CandidateObligation.customer_id == "CUST-007"))
    review.override_obligation(s, cond.id, "adi", "net of 5% admin costs", amount_cents=123_456)
    s.commit()
    rows = _rows(generate_payables(s, NOW))
    assert [(r["customer_id"], int(r["amount_cents"])) for r in rows] == [("CUST-001", clear.confirmed_amount_cents), ("CUST-007", 123_456)]
