"""Pipeline stage: parse every contract in the manifest into ParsedDocument rows."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from sherlock.models import Dataset, ParsedDocument
from sherlock.parsing.base import get_parser, sha256_of


def parse_documents(session: Session, dataset_dir: Path) -> dict:
    dataset = session.get(Dataset, Path(dataset_dir).name)
    manifest = dataset.manifest if dataset else {}
    parser = get_parser()
    count = 0
    for c in manifest.get("contracts", []):
        path = Path(dataset_dir) / c["file"]
        result = parser.parse(path)
        session.add(ParsedDocument(
            doc_type="contract",
            source_path=c["file"],
            sha256=sha256_of(path),
            parser=result.parser,
            page_count=result.page_count,
            pages=[{"page": p.page, "text": p.text} for p in result.pages],
            customer_id=c["customer_id"],
        ))
        count += 1
    session.flush()
    return {"parser": parser.name, "documents": count}
