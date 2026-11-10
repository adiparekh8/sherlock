"""Pipeline stage: LLM field normalization of parsed contracts into ExtractedField rows."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock.llm import get_llm
from sherlock.llm.prompts import CONTRACT_EXTRACT_SYSTEM, CONTRACT_EXTRACT_VERSION, contract_extract_user
from sherlock.llm.spans import locate_span
from sherlock.models import ExtractedField, ParsedDocument


def extract_contract(doc: ParsedDocument):
    """One LLM call per contract, shared by normalization and obligation extraction via the cache."""
    return get_llm().complete_json(
        task="contract_extract",
        prompt_version=CONTRACT_EXTRACT_VERSION,
        system=CONTRACT_EXTRACT_SYSTEM,
        user=contract_extract_user(doc.pages),
        stub_input=doc.pages,
    )


def normalize_documents(session: Session, dataset_dir: Path) -> dict:
    docs = session.scalars(select(ParsedDocument).where(ParsedDocument.doc_type == "contract")).all()
    n_fields = 0
    sources: dict[str, int] = {}
    for doc in docs:
        result = extract_contract(doc)
        sources[result.source] = sources.get(result.source, 0) + 1
        doc.extract_source = result.source
        doc.extract_model = result.model
        extractor = "llm" if result.model != "stub" else "llm_stub"
        page_text = {p["page"]: p["text"] for p in doc.pages}
        for f in result.output["fields"]:
            span = locate_span(page_text.get(f["page"], ""), f["quoted_text"])
            session.add(ExtractedField(
                document_id=doc.id, record_type="contract", record_key=doc.customer_id or "",
                field_name=f["name"], value_raw=f["quoted_text"], value_norm=f["value"],
                confidence=f["confidence"], page=f["page"],
                span_start=span[0] if span else None, span_end=span[1] if span else None,
                quoted_text=page_text[f["page"]][span[0]:span[1]] if span else f["quoted_text"], extractor=extractor, prompt_version=CONTRACT_EXTRACT_VERSION,
            ))
            n_fields += 1
    session.flush()
    models = sorted({d.extract_model for d in docs if d.extract_model and d.extract_model != "stub"})
    return {"documents": len(docs), "fields": n_fields, "llm_sources": sources, "models": models}
