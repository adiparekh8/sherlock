from pathlib import Path
from typing import Literal
import uuid
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import select
from .db import DATA, Session, Refund, Allocation, Document, Artifact, init
from .engine import snapshot, ingest, propose, decide
from .outputs import generate

app=FastAPI(title='Sherlock',description='Local evidence-backed refund review. No external writes.')
templates=Jinja2Templates(directory=str(Path(__file__).parent/'templates'))
init()
class Part(BaseModel):
    amount: StrictInt = Field(gt=0)
    disposition: Literal['importer_retained','customer_payable']
    po: str
class Decision(BaseModel):
    allocation_id: str
    revision: int
    key: str = Field(min_length=1,max_length=100)
    actor: str = Field(min_length=1,max_length=100)
    reason: str = Field(min_length=1,max_length=2000)
    action: Literal['confirm','override','hold','reject_obligation_hold']
    obligation_decision: Literal['confirmed','rejected'] | None = None
    parts: list[Part] = []
class BulkHold(BaseModel):
    revision: int
    actor: str = Field(min_length=1,max_length=100)
    reason: str = Field(min_length=1,max_length=2000)
    reject_pending: bool = False

def transaction(fn):
    try:
        with Session.begin() as s: return fn(s)
    except ValueError as e: raise HTTPException(409,str(e))

@app.get('/',response_class=HTMLResponse)
def home(request:Request):
    with Session() as s:
        return templates.TemplateResponse(request=request,name='index.html',context={'state':snapshot(s)})
@app.get('/ledger')
def ledger():
    with Session() as s: return snapshot(s)
@app.get('/review-items')
def review_items():
    with Session() as s: return [a for a in snapshot(s)['rows'] if not a['reviewed_hold'] and a['status'] in ('unallocated','auto-proposed')]
@app.get('/review/{allocation_id}',response_class=HTMLResponse)
def review(request:Request,allocation_id:str):
    with Session() as s:
        a=s.get(Allocation,allocation_id)
        if not a: raise HTTPException(404)
        return templates.TemplateResponse(request=request,name='review.html',context={'row':a,'revision':s.get(Refund,1).revision})
@app.get('/documents/{document_id}')
def document(document_id:str):
    with Session() as s:
        d=s.get(Document,document_id)
        if not d: raise HTTPException(404)
        return FileResponse(d.path,media_type='application/pdf',filename=d.name,content_disposition_type='inline')
@app.post('/imports')
async def imports(amount_cents:int=Form(...),date:str=Form(...),importer:str=Form(...),files:list[UploadFile]=File(...)):
    from datetime import date as Date
    if amount_cents <= 0 or amount_cents > 10**12 or not importer.strip(): raise HTTPException(422,'Invalid refund')
    try: Date.fromisoformat(date)
    except ValueError: raise HTTPException(422,'Use ISO date')
    with Session() as s:
        if s.get(Refund,1): raise HTTPException(409,'Single-refund demo already contains a refund. Use a fresh data volume for another import.')
    paths=[]
    for upload in files:
        content=await upload.read(20*1024*1024+1)
        if len(content)>20*1024*1024: raise HTTPException(413,'Maximum 20 MB per file')
        if not content.startswith(b'%PDF'): raise HTTPException(422,'Only PDFs, including scanned PDFs, are supported')
        folder=DATA/'uploads'; folder.mkdir(exist_ok=True)
        path=folder/f'{uuid.uuid4().hex}.pdf'; path.write_bytes(content)
        paths.append((path,Path(upload.filename or 'document.pdf').name))
    def save(s):
        s.add(Refund(id=1,amount=amount_cents,date=date,importer=importer.strip()))
        s.add(Allocation(id='unallocated',amount=amount_cents,chain={},evidence=[],issues=[],obligation={},reason='Awaiting processing'))
        for path,name in paths: ingest(s,path,name)
        s.flush(); return snapshot(s)
    return transaction(save)
@app.post('/imports/1/process')
def process(): return transaction(propose)
@app.post('/review-items/decisions')
def decision(command:Decision): return transaction(lambda s:decide(s,command.model_dump()))
@app.post('/review-items/hold-remaining')
def hold_remaining(command:BulkHold):
    def work(s):
        state=snapshot(s)
        if command.revision!=state['revision']: raise ValueError('Stale revision')
        for row in state['rows']:
            if row['status'].startswith('human-') or row['reviewed_hold']: continue
            pending=row['obligation'].get('status')=='pending_review'
            if pending and not command.reject_pending: raise ValueError('Explicit rejection of pending candidates is required')
            decide(s,{'allocation_id':row['id'],'revision':s.get(Refund,1).revision,'key':uuid.uuid4().hex,
                'actor':command.actor,'reason':command.reason,'action':'reject_obligation_hold' if pending else 'hold'})
        return snapshot(s)
    return transaction(work)
@app.post('/artifacts')
def artifacts():
    def work(s):
        a=generate(s)
        return {'revision':a.revision,'memo':f'/artifacts/{a.id}/memo','csv':f'/artifacts/{a.id}/csv'}
    return transaction(work)
@app.get('/artifacts/{artifact_id}/{kind}')
def download(artifact_id:str,kind:Literal['csv','memo']):
    with Session() as s:
        a=s.get(Artifact,artifact_id)
        if not a: raise HTTPException(404)
        ext='csv' if kind=='csv' else 'md'
        return Response(getattr(a,kind),media_type='text/csv' if kind=='csv' else 'text/markdown',headers={'Content-Disposition':f'attachment; filename="sherlock-r{a.revision}.{ext}"'})
@app.get('/health')
def health():
    with Session() as s: s.execute(select(Refund.id).limit(1))
    return {'status':'ok'}

@app.post('/documents/{document_id}/analyze')
def analyze(document_id:str):
    from .ai import ResponsesAdapter
    with Session() as s:
        d=s.get(Document,document_id)
        if not d: raise HTTPException(404)
        parsed=d.parsed
    try: return ResponsesAdapter().extract(parsed)
    except ValueError as e: raise HTTPException(409,str(e))
