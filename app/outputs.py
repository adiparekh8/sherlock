import csv
import io
import json
import uuid
from .db import Artifact
from .engine import snapshot

def generate(s):
    state=snapshot(s)
    if not state['refund']: raise ValueError('No refund')
    for row in state['rows']:
        if row['obligation'].get('status') == 'pending_review': raise ValueError('Pending contract obligations must receive a human decision')
        if row['status']=='auto-proposed' or (row['status']=='unallocated' and not row['reviewed_hold']):
            raise ValueError('Every row must be human reviewed, including retained unallocated balances')
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(['label','revision','allocation_id','account','debit_cents','credit_cents','currency','evidence','review_event_ids'])
    revision=state['revision']
    writer.writerow(['JOURNAL ENTRY EXPORT',revision,'REFUND','Refund clearing',state['refund']['amount'],0,'USD','',''])
    accounts={'importer_retained':'Tariff recovery','customer_payable':'Customer refund payable','unallocated':'Unallocated refund suspense'}
    for row in state['rows']:
        writer.writerow(['JOURNAL ENTRY EXPORT',revision,row['id'],accounts[row['disposition']],0,row['amount'],'USD',
            ';'.join(f"/documents/{e['document_id']}#page={e['page']}" for e in row['evidence']),
            ';'.join(e['id'] for e in state['events'] if any(r['id']==row['id'] for r in e['after']['rows']))])
    lines=['# Sherlock audit memo',f"Ledger revision: {revision}",f"Importer: {state['refund']['importer']}",
        'Synthetic demo. Parsing: hash-bound fixture stub; unknown documents use text extraction and require review.',
        'Method: exact entry/shipment/PO/invoice linkage, quantity checks, cited contract candidates, human disposition.',
        'Confidence: heuristic basis points (exact links 9900; conflicting/missing facts 6000). Not a calibrated probability.',
        f"Reconciliation (cents): {state['refund']['amount']} = {state['allocated']} allocated + {state['unallocated']} unallocated.",
        'Accounting assumption: receipt already debited cash and credited refund clearing. Export reclassifies clearing.',
        'All amounts below are integer USD cents. Reviewer names are self-declared in this local demo.', '\n## Allocation ledger']
    for row in state['rows']:
        lines.extend([f"\n### {row['id']} — {row['amount']} cents", f"{row['status']} / {row['disposition']} / confidence {row['confidence']}",
            f"Reason: {row['reason']}",f"Flags: {', '.join(row['issues']) or 'Resolved'}",f"Chain: {json.dumps(row['chain'],sort_keys=True)}",f"Obligation: {json.dumps(row['obligation'],sort_keys=True)}"])
        for e in row['evidence']:
            lines.append(f"- [{e['name']}, page {e['page']}, {e.get('clause') or 'record'}](/documents/{e['document_id']}#page={e['page']}) SHA256 {e['sha256']}\n  Quote: {e['quote']}")
    lines.append('\n## Human decisions and resolutions')
    for e in state['events']:
        lines.append(f"- {e['at']} — {e['actor']} — {e['allocation_id']} — revision {e['revision']} — {e['reason']}\n  Before: {json.dumps(e['before'],sort_keys=True)}\n  After: {json.dumps(e['after'],sort_keys=True)}")
    a=Artifact(id=uuid.uuid4().hex,revision=revision,snapshot=state,csv=output.getvalue(),memo='\n\n'.join(lines))
    s.add(a); s.flush(); return a
