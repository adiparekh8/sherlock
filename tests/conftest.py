"""Shared fixtures. Every test runs against a throwaway SQLite database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ["LLM_CACHE_DIR"] = str(Path(__file__).resolve().parents[1] / "llm_cache")

from sherlock import db as dbmod  # noqa: E402
from sherlock.models import Base  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO / "data" / "synthetic_v1"


@pytest.fixture
def engine(tmp_path):
    eng = dbmod.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    dbmod.set_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    Session = dbmod.get_sessionmaker()
    s = Session()
    yield s
    s.close()
