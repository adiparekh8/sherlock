"""The seed pipeline: reset -> ingest -> parse -> normalize -> match -> obligations.

Each stage is a function in its own module; this file only orders them. Later stages are
registered as they are built so `make seed` always runs everything that exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine

from sherlock import db
from sherlock.config import get_settings
from sherlock.ingest import IngestReport, load_dataset


@dataclass
class SeedReport:
    ingest: IngestReport
    stages: dict[str, dict] = field(default_factory=dict)


def resolve_dataset_dir(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.is_dir():
        return p
    candidate = get_settings().data_dir / name_or_path
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(f"dataset {name_or_path!r} not found (looked in {candidate.parent}/)")


def seed(dataset: str, engine: Engine | None = None) -> SeedReport:
    dataset_dir = resolve_dataset_dir(dataset)
    engine = engine or db.get_engine()
    db.reset_db(engine)
    with db.session_scope() as session:
        report = SeedReport(ingest=load_dataset(session, dataset_dir))
        for name, stage in STAGES:
            report.stages[name] = stage(session, dataset_dir)
    return report


from sherlock.matching.engine import run_matching  # noqa: E402
from sherlock.normalize import normalize_documents  # noqa: E402
from sherlock.parsing.stage import parse_documents  # noqa: E402

# (name, callable(session, dataset_dir) -> summary dict), in run order.
STAGES: list[tuple[str, object]] = [
    ("parse", parse_documents),
    ("normalize", normalize_documents),
    ("match", run_matching),
]
