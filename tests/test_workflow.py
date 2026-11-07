import csv
import io
import uuid
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.db import Session, Allocation, Refund, Document, Artifact
from app.engine import snapshot, decide, propose
from app.main import app
from app.outputs import generate

client=TestClient(app)
def command(revision=1,**kwargs):
    return dict(allocation_id='E000',revision=revision,key=uuid.uuid4().hex,actor='Sid',reason='Reviewed shipment and both POs; allocate 50 units to each.',
        action='override',obligation_decision='confirmed',parts=[{'amount':5000,'disposition':'customer_payable','po':'PO000'}, {'amount':5000,'disposition':'customer_payable','po':'PO000B'}],**kwargs)

def test_seed_and_required_ambiguities(seeded):
    with Session() as s:
        state=snapshot(s)
        assert len(state['rows'])==200 and state['allocated']==0 and state['unallocated']==seeded
        for entry,issue in [('E000','split_shipment_requires_review'),('E001','vague_surcharge_clause'),('E002','missing_or_conflicting_invoice')]:
            a=s.get(Allocation,entry)
            assert a.status=='unallocated' and issue in a.issues
        assert all(a['evidence'] for a in state['rows'])
        assert s.get(Allocation,'E001').obligation['status']=='pending_review'

def test_override_memo_export_and_snapshot_immutability(seeded):
    response=client.post('/review-items/decisions',json=command())
    assert response.status_code==200,response.text
    state=response.json()
    assert state['allocated']==10000 and state['unallocated']==seeded-10000
    assert len(state['rows'])==201 and state['events'][0]['actor']=='Sid'
    assert client.post('/artifacts').status_code==409
    response=client.post('/review-items/hold-remaining',json={'revision':2,'actor':'Adi','reason':'Reject remaining draft claims pending further contractual evidence; retain funds in suspense.','reject_pending':True})
    assert response.status_code==200,response.text
    response=client.post('/artifacts'); assert response.status_code==200,response.text
    links=response.json(); memo=client.get(links['memo']).text
    assert 'Sid' in memo and 'PO000B' in memo and 'human-overridden' in memo
    assert f'{seeded} = 10000 allocated + {seeded-10000} unallocated' in memo
    rows=list(csv.DictReader(io.StringIO(client.get(links['csv']).text)))
    assert sum(int(r['debit_cents']) for r in rows)==sum(int(r['credit_cents']) for r in rows)==seeded
    assert any(r['allocation_id']=='E000' and r['credit_cents']=='5000' for r in rows)
    assert all(r['evidence'] and r['review_event_ids'] for r in rows[1:])
    assert all(int(r['revision'])==links['revision'] for r in rows)
    assert client.get(links['memo']).text==memo

@pytest.mark.parametrize('change',[{'parts':[{'amount':9999,'disposition':'customer_payable','po':'PO000'}]}, {'revision':0}, {'actor':' '}, {'obligation_decision':None}, {'parts':[{'amount':10000,'disposition':'customer_payable','po':'FAKE'}]}, {'obligation_decision':'rejected'}])
def test_invalid_decisions_leave_ledger_unchanged(seeded,change):
    body=command(); body.update(change)
    assert client.post('/review-items/decisions',json=body).status_code==409
    with Session() as s:
        assert snapshot(s)['revision']==1 and snapshot(s)['unallocated']==seeded

def test_float_cents_rejected(seeded):
    body=command();body['parts'][0]['amount']=5000.0
    assert client.post('/review-items/decisions',json=body).status_code==422

def test_duplicate_key_and_reprocessing(seeded):
    body=command()
    assert client.post('/review-items/decisions',json=body).status_code==200
    assert client.post('/review-items/decisions',json=body).status_code==409
    assert client.post('/imports/1/process').status_code==409

def test_incomplete_evidence_cannot_be_overridden(seeded):
    body=command();body.update(allocation_id='E002',parts=[{'amount':10074,'disposition':'importer_retained','po':'PO002'}])
    assert client.post('/review-items/decisions',json=body).status_code==409

def test_pending_obligation_cannot_be_held_without_decision(seeded):
    body=command();body.update(action='hold',parts=[])
    assert client.post('/review-items/decisions',json=body).status_code==409
    assert client.post('/review-items/hold-remaining',json={'revision':1,'actor':'Adi','reason':'Hold','reject_pending':False}).status_code==409
    with Session() as s: assert snapshot(s)['revision']==1

def test_ui_and_citations(seeded):
    assert client.get('/').status_code==200
    assert client.get('/review/E000').status_code==200
    assert client.get('/review/nope').status_code==404
    with Session() as s:
        d=s.scalar(select(Document))
        r=client.get('/documents/'+d.id)
        assert r.status_code==200 and r.content.startswith(b'%PDF')

def test_confirm_clean_match_still_requires_explicit_contract_decision(seeded):
    body=command();body.update(allocation_id='E003',action='confirm',parts=[{'amount':10111,'disposition':'customer_payable','po':'PO003'}])
    r=client.post('/review-items/decisions',json=body)
    assert r.status_code==200,r.text
    row=next(a for a in r.json()['rows'] if a['id']=='E003')
    assert row['status']=='human-confirmed' and row['obligation']['status']=='confirmed'

def test_missing_advice_holds_every_cent(seeded):
    from app.db import ExtractedFact
    with Session.begin() as s:
        for a in s.scalars(select(Allocation)): s.delete(a)
        advice=next(d for d in s.scalars(select(Document)) if d.parsed['kind']=='refund_advice')
        for fact in s.scalars(select(ExtractedFact).where(ExtractedFact.document_id==advice.id)): s.delete(fact)
        s.flush();s.delete(advice)
        s.get(Refund,1).revision=0
        s.add(Allocation(id='unallocated',amount=seeded,chain={},evidence=[],reason='Awaiting processing',issues=[],obligation={}))
        s.flush();state=propose(s)
        assert state['unallocated']==seeded and state['allocated']==0
        assert 'missing_or_conflicting_refund_advice' in state['rows'][0]['issues']

def test_unknown_upload_never_fabricates_matches(seeded):
    from app.db import Base, engine
    from reportlab.pdfgen import canvas
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    pdf=io.BytesIO();c=canvas.Canvas(pdf);c.drawString(30,750,'Unknown invoice without refund advice');c.save()
    r=client.post('/imports',data={'amount_cents':'12345','date':'2026-11-06','importer':'Test importer'},files=[('files',('unknown.pdf',pdf.getvalue(),'application/pdf'))])
    assert r.status_code==200,r.text
    assert r.json()['unallocated']==12345
    r=client.post('/imports/1/process')
    assert r.status_code==200 and r.json()['allocated']==0
    assert client.post('/artifacts').status_code==409
