import hashlib
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from .db import Refund, Allocation, Document, Event, ExtractedFact
from .parsing import LocalParser, LocalNormalizer, LocalContractReader
from .matching import index_documents

THRESHOLD = 9500

def record(a):
    return {k: getattr(a, k) for k in ('id','amount','status','disposition','confidence','chain','evidence','reason','issues','obligation','reviewed_hold')}

def snapshot(s):
    r = s.scalar(select(Refund).where(Refund.id == 1).with_for_update())
    rows = [record(a) for a in s.scalars(select(Allocation).order_by(Allocation.id))]
    allocated = sum(a['amount'] for a in rows if a['status'] != 'unallocated')
    unallocated = sum(a['amount'] for a in rows if a['status'] == 'unallocated')
    if r and allocated + unallocated != r.amount: raise ValueError('Conservation failed')
    events = [{k:getattr(e,k) for k in ('id','allocation_id','actor','at','reason','before','after','revision')} for e in s.scalars(select(Event).order_by(Event.revision, Event.at))]
    return {'refund': {'amount':r.amount,'importer':r.importer,'date':r.date} if r else None,
            'revision':r.revision if r else 0,'allocated':allocated,'unallocated':unallocated,
            'rows':rows,'events':events,'mode':'demo-stub / local-text',
            'reviewed':sum(a['amount'] for a in rows if a['status'].startswith('human-'))}

def ingest(s, path, name=None):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = s.scalar(select(Document).where(Document.sha256 == digest))
    if existing: return existing
    parsed = LocalNormalizer().normalize(LocalParser().parse(path))
    d = Document(id=uuid.uuid4().hex, name=name or path.name, sha256=digest, path=str(path), parsed=parsed)
    s.add(d); s.flush()
    for field, value in parsed.get('facts', {}).items():
        s.add(ExtractedFact(document_id=d.id, field=field, value={'normalized':value},
            evidence={'document_id':d.id, 'page':1, 'provider':parsed['provider'],
                      'confidence_bps':parsed['confidence_bps']}))
    return d

def citation(d, page=1, clause=None):
    return {'document_id': d.id, 'name':d.name,'page':page,'clause':clause,
            'quote':d.parsed['pages'][page-1], 'sha256':d.sha256}

def propose(s):
    r = s.scalar(select(Refund).where(Refund.id == 1).with_for_update())
    if not r: raise ValueError('Import a refund first')
    if r.revision: raise ValueError('Already processed; reprocessing cannot replace reviewed decisions')
    docs = list(s.scalars(select(Document)))
    def of(kind): return [d for d in docs if d.parsed.get('kind') == kind]
    by_id = {d.id:d for d in docs}
    shipment_index = index_documents(docs, 'shipment', 'entry')
    advices = of('refund_advice')
    initial = s.get(Allocation, 'unallocated')
    if len(advices) != 1:
        initial.reason = 'Exactly one verified refund advice is required; no entries inferred.'
        initial.issues = ['missing_or_conflicting_refund_advice']
        r.revision += 1
        return snapshot(s)
    advice = advices[0]
    f = advice.parsed['facts']
    entries = f.get('entries', [])
    valid = (f.get('importer') == r.importer and f.get('date') == r.date and
             f.get('amount') == r.amount and all(type(e.get('amount')) is int and e['amount'] > 0 for e in entries) and
             len({e['entry'] for e in entries}) == len(entries) and sum(e['amount'] for e in entries) <= r.amount)
    if not valid:
        initial.reason = 'Refund advice conflicts with refund record or contains invalid amounts.'
        initial.issues = ['conflicting_refund_advice']; r.revision += 1
        return snapshot(s)
    s.delete(initial)
    for e in entries:
        evidence = [citation(advice, e['page'])]
        issues = []; chain = {'entry':e['entry']}; obligation = {}
        shipments = [by_id[key] for key in shipment_index.get(e['entry'], [])]
        if len(shipments) != 1:
            issues.append('missing_or_conflicting_shipment')
        else:
            shipment = shipments[0]; sf = shipment.parsed['facts']
            evidence.append(citation(shipment)); chain.update(sf)
            if len(sf['pos']) != 1: issues.append('split_shipment_requires_review')
            for po in sf['pos']:
                matches = [d for d in of('po') if d.parsed['facts']['po'] == po]
                evidence.extend(citation(d) for d in matches)
                if len(matches) != 1: issues.append('missing_or_conflicting_po')
                elif len(sf['pos']) == 1 and matches[0].parsed['facts']['quantity'] != sf['quantity']:
                    issues.append('quantity_mismatch')
            invoices = [d for d in of('invoice') if d.parsed['facts']['shipment'] == sf['shipment']]
            evidence.extend(citation(d) for d in invoices)
            if len(invoices) != 1: issues.append('missing_or_conflicting_invoice')
            else:
                inv = invoices[0].parsed['facts']; chain.update({'invoice':inv['invoice'],'customer':inv['customer'],'sale':inv['invoice']})
                if inv['quantity'] != sf['quantity']: issues.append('invoice_quantity_mismatch')
                contracts = [d for d in of('contract') if d.parsed['facts']['customer'] == inv['customer']]
                evidence.extend(citation(d, clause=d.parsed['facts']['clause']) for d in contracts)
                if len(contracts) != 1: issues.append('missing_or_conflicting_contract')
                else:
                    obligation = LocalContractReader().extract(contracts[0].parsed)
                    obligation.update({'draft_amount':e['amount'], 'evidence':citation(contracts[0], clause=obligation['clause'])})
                    issues.append('contract_pending_review')
                    if obligation['draft_rule'] == 'ambiguous': issues.append('vague_surcharge_clause')
        confidence = min([by_id[e['document_id']].parsed.get('confidence_bps', 0) for e in evidence] + [6000 if any(i != 'contract_pending_review' for i in issues) else 9900])
        if confidence < THRESHOLD and 'low_confidence' not in issues: issues.append('low_confidence')
        s.add(Allocation(id=e['entry'], amount=e['amount'], status='unallocated' if issues else 'auto-proposed',
            disposition='unallocated' if issues else 'importer_retained', confidence=confidence,
            chain=chain,evidence=evidence,issues=issues,obligation=obligation,
            reason='; '.join(issues) if issues else 'Exact identifiers and quantities agree; method exact-link-v1.'))
    remainder = r.amount - sum(e['amount'] for e in entries)
    if remainder:
        s.add(Allocation(id='unallocated',amount=remainder,status='unallocated',disposition='unallocated',
            confidence=0,chain={},evidence=[],issues=['uncovered_refund_balance'],obligation={},reason='Refund advice does not cover this balance.'))
    r.revision += 1; s.flush()
    return snapshot(s)

def decide(s, command):
    r = s.scalar(select(Refund).where(Refund.id == 1).with_for_update())
    if not r: raise ValueError('No refund')
    previous = s.get(Event, command['key'])
    if previous: raise ValueError('Duplicate decision key; reload the current ledger')
    if command['revision'] != r.revision: raise ValueError('Stale revision; reload before reviewing')
    a = s.get(Allocation, command['allocation_id'])
    if not a: raise ValueError('Allocation not found')
    actor = command['actor'].strip(); reason = command['reason'].strip()
    if not actor or not reason: raise ValueError('Reviewer name and reason are required')
    before = record(a); action = command['action']
    if action == 'hold':
        if a.obligation.get('status') in ('pending_review', 'confirmed'):
            raise ValueError('Resolve the candidate obligation explicitly before retaining an unallocated hold')
        a.status = 'unallocated'; a.disposition = 'unallocated'; a.reviewed_hold = True
    elif action in ('confirm','override'):
        parts = command.get('parts') or []
        if not parts or sum(p['amount'] for p in parts) != a.amount or any(type(p['amount']) is not int or p['amount'] <= 0 for p in parts):
            raise ValueError('Positive integer-cent parts must sum exactly to the original amount')
        if action == 'confirm' and (any(issue != 'contract_pending_review' for issue in a.issues) or len(parts) != 1):
            raise ValueError('Flagged cases require an explicit override')
        if not a.evidence: raise ValueError('Cannot allocate money without source evidence')
        if not all(k in a.chain for k in ('entry','shipment','pos','invoice','customer')):
            raise ValueError('Evidence chain is incomplete; retain this balance unallocated')
        obligation_decision = command.get('obligation_decision')
        if a.obligation and obligation_decision not in ('confirmed','rejected'):
            raise ValueError('Explicitly confirm or reject the candidate obligation')
        customer_total = sum(p['amount'] for p in parts if p['disposition'] == 'customer_payable')
        if a.obligation and ((obligation_decision == 'rejected' and customer_total) or (obligation_decision == 'confirmed' and not customer_total)):
            raise ValueError('Customer payable must agree with the obligation decision')
        for p in parts:
            if p['disposition'] not in ('customer_payable','importer_retained'): raise ValueError('Invalid disposition')
            if p.get('po') not in a.chain['pos']: raise ValueError('Choose a PO cited in the source chain')
        a.obligation = {**a.obligation,'status':obligation_decision,'confirmed_amount':customer_total} if a.obligation else {}
        original_id = a.id
        for index, p in enumerate(parts):
            target = a if index == 0 else Allocation(id=f'{original_id}-{uuid.uuid4().hex[:8]}', confidence=a.confidence,
                evidence=a.evidence,reason=reason,issues=[],obligation=a.obligation,reviewed_hold=False)
            target.amount=p['amount']; target.chain={**a.chain,'selected_po':p['po']}
            if target.obligation:
                target.obligation={**target.obligation,'confirmed_amount':p['amount'] if p['disposition']=='customer_payable' else 0}
            target.status='human-overridden' if action == 'override' else 'human-confirmed'
            target.disposition=p['disposition']; target.issues=[]; target.reason=reason
            if index: s.add(target)
    elif action == 'reject_obligation_hold':
        if not a.obligation: raise ValueError('No obligation to reject')
        a.obligation={**a.obligation,'status':'rejected','confirmed_amount':0}
        a.status='unallocated'; a.disposition='unallocated'; a.reviewed_hold=True
    else: raise ValueError('Unknown decision')
    a.reason=reason; r.revision += 1; s.flush()
    after = snapshot(s)
    s.add(Event(id=command['key'],allocation_id=a.id,actor=actor,at=datetime.now(timezone.utc).isoformat(),
        reason=reason,before=before,after={'rows':[x for x in after['rows'] if x['id']==a.id or x['id'].startswith(a.id+'-')]},revision=r.revision))
    s.flush(); return snapshot(s)
