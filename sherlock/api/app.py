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

import hashlib
from functools import lru_cache
from threading import Lock
import searoute
import json
import re
import requests
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
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
from sherlock.llm import get_llm
from sherlock.uploads import analyze_pdf
from sherlock.todo import build_todos, generate_pdf, generate_xlsx

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
            "model": s.anthropic_model, "mapbox_access_token": s.mapbox_access_token}


# --------------------------------------------------------------------------- document intake

_route_lock = Lock()


@lru_cache(maxsize=256)
def _sea_geometry(lon1: float, lat1: float, lon2: float, lat2: float):
    # The routing library shares a mutable graph: serialize its use.
    with _route_lock:
        route = searoute.searoute([lon1, lat1], [lon2, lat2], append_orig_dest=False)
    if len(route['geometry']['coordinates']) < 2:
        raise ValueError('No sea route between these locations')
    return route['geometry']


@app.get('/sea-route')
def sea_route(lon1: float = Query(..., ge=-180, le=180), lat1: float = Query(..., ge=-90, le=90),
              lon2: float = Query(..., ge=-180, le=180), lat2: float = Query(..., ge=-90, le=90)):
    try:
        return {'geometry': _sea_geometry(lon1, lat1, lon2, lat2), 'estimated': True}
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, 'Sea route unavailable for these locations') from exc


def _workspace_path() -> Path:
    return get_settings().uploaded_documents_dir.parent / "workspaces.json"


def _workspaces() -> list[dict]:
    path = _workspace_path()
    try:
        return json.loads(path.read_text()) if path.exists() else []
    except json.JSONDecodeError:
        return []


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ChatIn(BaseModel):
    workspace_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)


@app.get("/workspaces")
def list_workspaces():
    return {"workspaces": _workspaces()}


@app.post("/workspaces")
def create_workspace(body: WorkspaceIn):
    name = body.name.strip()
    workspace_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    if not workspace_id:
        raise HTTPException(422, "document set name needs letters or numbers")
    workspaces = _workspaces()
    if any(w.get("id") == workspace_id for w in workspaces):
        raise HTTPException(409, "a document set with that name already exists")
    created = {"id": workspace_id, "name": name}
    path = _workspace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(workspaces + [created], indent=2) + "\n")
    return created


SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "CNY", "INR", "MXN", "SGD"}


@lru_cache(maxsize=32)
def _fx_rate(currency: str) -> tuple[float, str]:
    if currency == "USD":
        return 1.0, ""
    response = requests.get(f"https://api.frankfurter.dev/v2/rate/USD/{currency}", timeout=5)
    response.raise_for_status()
    data = response.json()
    return float(data["rate"]), str(data.get("date", ""))


@app.get("/fx-rate")
def fx_rate(currency: str = Query("USD", min_length=3, max_length=3)):
    code = currency.upper()
    if code not in SUPPORTED_CURRENCIES:
        raise HTTPException(422, f"unsupported display currency: {code}")
    try:
        rate, date = _fx_rate(code)
        return {"currency": code, "rate": rate, "date": date}
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "currency conversion is temporarily unavailable") from exc


@app.post("/chat")
def chat(body: ChatIn):
    """Ask Claude Dr. Watson about only the selected document set."""
    _workspace(body.workspace_id)
    if not get_settings().anthropic_api_key:
        raise HTTPException(503, "Claude Dr. Watson needs ANTHROPIC_API_KEY in .env")
    uploads = _workspace_uploads(body.workspace_id)
    context = []
    for upload in uploads:
        analysis = upload.get("analysis") or {}
        context.append({
            "file": upload.get("filename", "uploaded PDF"),
            "summary": analysis.get("summary", ""),
            "records": analysis.get("records", []),
            "missing_links": analysis.get("missing_links", []),
        })
    system = ("You are Claude Dr. Watson, Sherlock's careful finance and shipment assistant. "
              "Answer only from the uploaded document set context. Do not invent facts. "
              "If the documents do not establish an answer, say what is unknown and what evidence is needed. "
              "Use plain language. When answering, cite the relevant filename and page through the sources list. "
              "Amounts are printed values unless the context explicitly includes a conversion.")
    user = f"Question:\n{body.question.strip()}\n\nUploaded document set context:\n{json.dumps(context, ensure_ascii=False, default=str)[:60000]}"
    try:
        result = get_llm().complete_json("chat", "chat-v1", system, user, stub_input=body.question)
    except Exception as exc:
        raise HTTPException(502, f"Claude Dr. Watson could not answer: {exc}") from exc
    return {"answer": result.output["answer"], "sources": result.output.get("sources", []), "model": result.model, "source": result.source}


def _workspace_uploads(workspace_id: str) -> list[dict]:
    return list_uploads(scope="active", workspace_id=workspace_id)["uploads"]


def _workspace(workspace_id: str) -> dict:
    workspace = next((w for w in _workspaces() if w.get("id") == workspace_id), None)
    if not workspace:
        raise HTTPException(404, "document set not found")
    return workspace


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    workspace = _workspace(workspace_id)
    directory = get_settings().uploaded_documents_dir
    removed = 0
    if directory.exists():
        for path in directory.glob("*.json"):
            try:
                upload = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if upload.get("workspace_id") == workspace_id:
                path.unlink()
                pdf = directory / f"{path.stem}.pdf"
                if pdf.exists():
                    pdf.unlink()
                removed += 1
    remaining = [w for w in _workspaces() if w.get("id") != workspace_id]
    path = _workspace_path()
    path.write_text(json.dumps(remaining, indent=2) + "\n")
    return {"deleted": workspace, "uploads_removed": removed}


@app.get("/todo")
def todo(workspace_id: str = Query(...)):
    _workspace(workspace_id)
    return {"workspace_id": workspace_id, "todos": build_todos(_workspace_uploads(workspace_id))}


@app.get("/todo.pdf")
def todo_pdf(workspace_id: str = Query(...)):
    workspace = _workspace(workspace_id)
    content = generate_pdf(build_todos(_workspace_uploads(workspace_id)))
    filename = re.sub(r"[^a-z0-9]+", "-", workspace["name"].lower()).strip("-") or "document-set"
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}-todo.pdf"'})


@app.get("/todo.xlsx")
def todo_xlsx(workspace_id: str = Query(...)):
    workspace = _workspace(workspace_id)
    content = generate_xlsx(build_todos(_workspace_uploads(workspace_id)))
    filename = re.sub(r"[^a-z0-9]+", "-", workspace["name"].lower()).strip("-") or "document-set"
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}-todo.xlsx"'})


@app.get("/uploads")
def list_uploads(scope: str = Query("active", pattern="^(active|history|all)$"), workspace_id: str | None = None):
    directory = get_settings().uploaded_documents_dir
    if not directory.exists():
        return {"uploads": []}
    uploads = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            upload = json.loads(path.read_text())
            archived = bool(upload.get("archived", False))
            belongs = workspace_id is None or upload.get("workspace_id") == workspace_id
            if belongs and (scope == "all" or (scope == "history" and archived) or (scope == "active" and not archived)):
                uploads.append(upload)
        except json.JSONDecodeError:
            continue
    return {"uploads": uploads}


@app.post("/uploads/archive")
def archive_uploads():
    """Move every active packet out of the worker desktop and into read-only history."""
    directory = get_settings().uploaded_documents_dir
    moved = 0
    for path in directory.glob("*.json") if directory.exists() else []:
        try:
            upload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not upload.get("archived", False):
            upload["archived"] = True
            path.write_text(json.dumps(upload, indent=2) + "\n")
            moved += 1
    return {"archived": moved}


def _pdfs_from_upload(content: bytes, filename: str) -> list[tuple[str, bytes]]:
    """Accept one PDF or a small ZIP of PDFs, without extracting archive paths to disk."""
    if content.startswith(b"%PDF-"):
        return [(filename, content)]
    if not zipfile.is_zipfile(__import__("io").BytesIO(content)):
        raise HTTPException(415, "upload a PDF or a ZIP containing PDFs")
    archive = zipfile.ZipFile(__import__("io").BytesIO(content))
    files = [info for info in archive.infolist() if not info.is_dir() and info.filename.lower().endswith(".pdf")]
    if not files:
        raise HTTPException(422, "ZIP has no PDFs")
    if len(files) > 12:
        raise HTTPException(422, "ZIP has more than 12 PDFs; split it into smaller uploads")
    if sum(info.file_size for info in files) > 50 * 1024 * 1024:
        raise HTTPException(413, "PDFs inside the ZIP exceed 50 MB")
    return [(Path(info.filename).name, archive.read(info)) for info in files]


@app.post("/uploads")
async def upload_documents(request: Request):
    """The browser sends bytes only after the user presses Analyze. Incomplete packets remain useful."""
    content = await request.body()
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(413, "upload is larger than 30 MB")
    if not get_llm().has_key:
        raise HTTPException(422, "Add ANTHROPIC_API_KEY to .env before analyzing documents")
    filename = Path(request.headers.get("x-filename", "upload")).name or "upload"
    workspace_id = request.headers.get("x-workspace-id", "")
    if workspace_id not in {w.get("id") for w in _workspaces()}:
        raise HTTPException(422, "choose a document set before uploading")
    packets = _pdfs_from_upload(content, filename)
    directory = get_settings().uploaded_documents_dir
    directory.mkdir(parents=True, exist_ok=True)
    uploads = []
    for pdf_name, pdf in packets:
        try:
            analysis = analyze_pdf(pdf, pdf_name)
        except ValueError as exc:
            raise HTTPException(422, f"{pdf_name}: {exc}") from exc
        except Exception as exc:
            raise HTTPException(502, f"could not analyze {pdf_name}: {exc}") from exc
        upload_id = hashlib.sha256(pdf).hexdigest()[:16]
        payload = {"id": upload_id, "filename": pdf_name, "analysis": analysis, "archived": False, "workspace_id": workspace_id}
        (directory / f"{upload_id}.pdf").write_bytes(pdf)
        (directory / f"{upload_id}.json").write_text(json.dumps(payload, indent=2) + "\n")
        uploads.append(payload)
    return {"uploads": uploads}


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
