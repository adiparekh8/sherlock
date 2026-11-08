"""HTTP API. One refund is loaded at a time, so routes are unprefixed by refund id.

GET  /                                      the console (frontend/index.html); /static/* serves its files
GET  /config                                confidence threshold and demo actor for the frontend
GET  /health
GET  /datasets                              folders under DATA_DIR, with which one is loaded
POST /datasets/{name}/seed                  reset + ingest + parse + normalize + match + obligations
GET  /refund                                refund header + ledger summary
GET  /ledger?status=&customer_id=           summary + live ledger lines
GET  /allocations/{id}                      one line with evidence, related rows, decisions, history
GET  /review/queue
POST /review/allocations/{id}/{approve|override|reject}
GET  /obligations
POST /review/obligations/{id}/{approve|override|reject}
GET  /decisions
GET  /memo                                  text/markdown
GET  /export.csv                            journal entries, text/csv (attachment)
GET  /payables.csv                          human-confirmed customer obligations, text/csv (attachment)
GET  /documents/{id}                        parsed document pages
GET  /manifest                              dataset manifest (planted cases panel)
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sherlock import db, ledger, review
from sherlock.config import get_settings
from sherlock.export import generate_export, generate_payables
from sherlock.ingest import ContractError
from sherlock.ledger import record_dict
from sherlock.matching.config import DEFAULT_CONFIG
from sherlock.matching.engine import live_records
from sherlock.memo import generate_memo
from sherlock.models import (
    AllocationRecord,
    CandidateObligation,
    Customer,
    Dataset,
    Invoice,
    ParsedDocument,
    PurchaseOrder,
    Refund,
    RefundEntry,
    ReviewDecision,
    Shipment,
)
from sherlock.obligations import obligation_dict
from sherlock.pipeline import seed as run_seed

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Sherlock", version="0.1.0", lifespan=lifespan)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/config")
def config():
    """What the frontend needs to render honestly: the threshold that colors confidence, and the demo actor."""
    s = get_settings()
    return {"auto_threshold": DEFAULT_CONFIG.auto_threshold, "demo_actor": s.sherlock_demo_actor,
            "model": s.anthropic_model}


def get_db() -> Iterator[Session]:
    session = db.get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class DecisionIn(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class OverrideLine(BaseModel):
    po_number: str | None = None
    customer_id: str | None = None
    invoice_number: str | None = None
    amount_cents: int


class OverrideIn(DecisionIn):
    lines: list[OverrideLine]


class ObligationOverrideIn(DecisionIn):
    amount_cents: int


def _refund(session: Session) -> Refund:
    r = session.scalar(select(Refund))
    if r is None:
        raise HTTPException(404, "no dataset seeded; POST /datasets/{name}/seed first")
    return r


# --------------------------------------------------------------------------- datasets


@app.get("/health")
def health():
    return {"ok": True, "database": get_settings().database_url.split("@")[-1]}


@app.get("/datasets")
def list_datasets(session: Session = Depends(get_db)):
    data_dir = get_settings().data_dir
    loaded = session.scalar(select(Dataset))
    out = []
    for p in sorted(x for x in data_dir.iterdir() if x.is_dir()) if data_dir.is_dir() else []:
        mpath = p / "manifest.json"
        m = json.loads(mpath.read_text()) if mpath.exists() else {}
        out.append({"name": p.name, "importer": m.get("importer"), "counts": m.get("counts", {}),
                    "hard_cases": len(m.get("hard_cases", [])), "valid": mpath.exists(),
                    "loaded": bool(loaded and loaded.name == p.name)})
    return {"datasets": out, "loaded": loaded.name if loaded else None}


@app.post("/datasets/{name}/seed")
def seed_dataset(name: str):
    try:
        report = run_seed(name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ContractError as e:
        raise HTTPException(422, str(e))
    return {"ingest": report.ingest.__dict__, "stages": report.stages}


@app.get("/manifest")
def manifest(session: Session = Depends(get_db)):
    d = session.scalar(select(Dataset))
    if d is None:
        raise HTTPException(404, "no dataset seeded")
    return d.manifest


# --------------------------------------------------------------------------- ledger


@app.get("/refund")
def refund(session: Session = Depends(get_db)):
    r = _refund(session)
    return {"refund": {"refund_id": r.refund_id, "importer": r.importer, "amount_cents": r.amount_cents,
                       "received_date": r.received_date.isoformat(), "currency": r.currency, "source": r.source,
                       "reference": r.reference, "entries": len(r.entries)},
            "summary": ledger.summarize(session, r.refund_id).as_dict()}


@app.get("/ledger")
def get_ledger(status: str | None = Query(None), customer_id: str | None = Query(None),
               needs_review: bool | None = Query(None), session: Session = Depends(get_db)):
    r = _refund(session)
    recs = live_records(session, r.refund_id)
    if status:
        recs = [x for x in recs if x.review_status == status]
    if customer_id:
        recs = [x for x in recs if x.customer_id == customer_id]
    if needs_review is not None:
        recs = [x for x in recs if x.needs_review == needs_review]
    names = {c.customer_id: c.name for c in session.scalars(select(Customer))}
    return {"summary": ledger.summarize(session, r.refund_id).as_dict(), "customers": names,
            "records": [record_dict(x) for x in recs]}


@app.get("/allocations/{record_id}")
def get_allocation(record_id: int, session: Session = Depends(get_db)):
    rec = session.get(AllocationRecord, record_id)
    if rec is None:
        raise HTTPException(404, "no such allocation")
    related = {}
    if rec.refund_entry_id:
        e = session.get(RefundEntry, rec.refund_entry_id)
        related["refund_entry"] = {"entry_number": e.entry_number, "amount_cents": e.amount_cents,
                                   "entry_date": e.entry_date.isoformat() if e.entry_date else None, "row": e.source_row}
    if rec.shipment_id:
        related["shipment"] = _row(session.get(Shipment, rec.shipment_id))
    po_numbers = {rec.po_number} | {l.get("po_number") for l in rec.proposal} | {c["key"] for c in rec.conflicts if c.get("entity") == "purchase_order"}
    related["purchase_orders"] = [_row(session.get(PurchaseOrder, p)) for p in sorted(x for x in po_numbers if x) if session.get(PurchaseOrder, p)]
    inv_numbers = {rec.invoice_number} | {l.get("invoice_number") for l in rec.proposal}
    related["invoices"] = [_row(session.get(Invoice, i)) for i in sorted(x for x in inv_numbers if x) if session.get(Invoice, i)]
    decisions = session.scalars(select(ReviewDecision).where(ReviewDecision.target_type == "allocation",
                                                             ReviewDecision.target_id == record_id)).all()
    replaced_by = session.scalars(select(AllocationRecord).where(
        AllocationRecord.created_by_decision_id.in_([d.id for d in decisions]))).all() if decisions else []
    return {"record": record_dict(rec), "related": related, "decisions": [review.decision_dict(d) for d in decisions],
            "replaced_by": [record_dict(x) for x in replaced_by]}


def _row(obj) -> dict | None:
    if obj is None:
        return None
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


# --------------------------------------------------------------------------- review


@app.get("/review/queue")
def get_queue(session: Session = Depends(get_db)):
    _refund(session)
    return review.queue(session)


def _act(fn, *args):
    try:
        return fn(*args)
    except review.ReviewError as e:
        raise HTTPException(422, str(e))


@app.post("/review/allocations/{record_id}/approve")
def approve_allocation(record_id: int, body: DecisionIn, session: Session = Depends(get_db)):
    d = _act(review.approve_allocation, session, record_id, body.actor, body.reason)
    return {"decision": review.decision_dict(d), "summary": ledger.summarize(session).as_dict()}


@app.post("/review/allocations/{record_id}/override")
def override_allocation(record_id: int, body: OverrideIn, session: Session = Depends(get_db)):
    lines = [l.model_dump() for l in body.lines]
    d = _act(review.override_allocation, session, record_id, body.actor, body.reason, lines)
    return {"decision": review.decision_dict(d), "summary": ledger.summarize(session).as_dict()}


@app.post("/review/allocations/{record_id}/reject")
def reject_allocation(record_id: int, body: DecisionIn, session: Session = Depends(get_db)):
    d = _act(review.reject_allocation, session, record_id, body.actor, body.reason)
    return {"decision": review.decision_dict(d), "summary": ledger.summarize(session).as_dict()}


@app.get("/obligations")
def get_obligations(session: Session = Depends(get_db)):
    obs = session.scalars(select(CandidateObligation).order_by(CandidateObligation.customer_id)).all()
    names = {c.customer_id: c.name for c in session.scalars(select(Customer))}
    return {"obligations": [obligation_dict(o) | {"customer_name": names.get(o.customer_id, "")} for o in obs]}


@app.post("/review/obligations/{ob_id}/approve")
def approve_obligation(ob_id: int, body: DecisionIn, session: Session = Depends(get_db)):
    d = _act(review.approve_obligation, session, ob_id, body.actor, body.reason)
    return {"decision": review.decision_dict(d)}


@app.post("/review/obligations/{ob_id}/override")
def override_obligation(ob_id: int, body: ObligationOverrideIn, session: Session = Depends(get_db)):
    d = _act(review.override_obligation, session, ob_id, body.actor, body.reason, body.amount_cents)
    return {"decision": review.decision_dict(d)}


@app.post("/review/obligations/{ob_id}/reject")
def reject_obligation(ob_id: int, body: DecisionIn, session: Session = Depends(get_db)):
    d = _act(review.reject_obligation, session, ob_id, body.actor, body.reason)
    return {"decision": review.decision_dict(d)}


@app.get("/decisions")
def get_decisions(session: Session = Depends(get_db)):
    return {"decisions": review.decisions(session)}


# --------------------------------------------------------------------------- outputs


@app.get("/memo", response_class=PlainTextResponse)
def get_memo(session: Session = Depends(get_db)):
    _refund(session)
    return PlainTextResponse(generate_memo(session), media_type="text/markdown")


@app.get("/export.csv")
def get_export(session: Session = Depends(get_db)):
    r = _refund(session)
    return Response(generate_export(session), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="sherlock_journal_export_{r.refund_id}.csv"'})


@app.get("/payables.csv")
def get_payables(session: Session = Depends(get_db)):
    r = _refund(session)
    return Response(generate_payables(session), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="sherlock_payables_export_{r.refund_id}.csv"'})


@app.get("/documents/{doc_id}/image")
def get_document_image(doc_id: int, session: Session = Depends(get_db)):
    """First page of a scanned document as PNG, for the review queue."""
    d = session.get(ParsedDocument, doc_id)
    if d is None or d.doc_type != "scan":
        raise HTTPException(404, "no such scanned document")
    ds = session.scalar(select(Dataset))
    from sherlock.scans import page_image_png

    return Response(page_image_png(Path(ds.path), d.source_path), media_type="image/png")


@app.get("/documents/{doc_id}")
def get_document(doc_id: int, session: Session = Depends(get_db)):
    d = session.get(ParsedDocument, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    return {"id": d.id, "doc_type": d.doc_type, "source_path": d.source_path, "sha256": d.sha256, "parser": d.parser,
            "customer_id": d.customer_id, "page_count": d.page_count, "pages": d.pages,
            "fields": [{"field_name": f.field_name, "value_norm": f.value_norm, "confidence": f.confidence,
                        "page": f.page, "span_start": f.span_start, "span_end": f.span_end,
                        "quoted_text": f.quoted_text, "extractor": f.extractor} for f in d.fields]}
