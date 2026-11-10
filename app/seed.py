"""Reproducible fixture documents; rerunning never resets a reviewed demo."""
import hashlib
import json
from io import BytesIO
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from .db import DATA, Session, Refund, Allocation, init
from .engine import ingest, propose

def generate():
    folder=DATA/'seed'; folder.mkdir(exist_ok=True)
    manifest={}; paths=[]
    def document(name, kind, facts, pages, scanned=False):
        path=folder/name
        c=canvas.Canvas(str(path), invariant=1)
        for text in pages:
            if scanned:
                im=Image.new('RGB',(1200,1500),'white'); draw=ImageDraw.Draw(im)
                draw.multiline_text((45,60),text,fill='black',spacing=14,font_size=20)
                c.drawImage(ImageReader(im),25,50,width=545,height=740)
            else:
                c.setFont('Helvetica',11)
                y=790
                for line in text.splitlines():
                    c.drawString(40,y,line); y-=18
            c.showPage()
        c.save(); paths.append(path)
        manifest[hashlib.sha256(path.read_bytes()).hexdigest()]={'kind':kind,'facts':facts,'pages':pages,'warnings':[]}
    clauses=[('refund','Tariff surcharges refunded to importer shall be returned to Customer.'),
      ('retained','Prices are fixed. Importer retains subsequent duty refunds.'),
      ('ambiguous','Tariff adjustments may be shared equitably as commercially appropriate.'),
      ('refund','Customer receives refunds only to the extent of tariff charges paid.'),
      ('retained','No rebate is due for changes in duties after delivery.'),
      ('refund','Seller shall credit recovered tariff surcharges against future invoices.'),
      ('ambiguous','Parties will discuss adjustments following changes in import costs.'),
      ('refund','Documented tariff recoveries are payable to Customer within thirty days.')]
    for i,(rule,text) in enumerate(clauses):
        document(f'contract-{i}.pdf','contract',{'customer':f'C{i}','clause':'Section 4.2','rule':rule},
                 [f'SYNTHETIC CUSTOMER CONTRACT C{i}\nSection 4.2 - Tariff treatment\n{text}\nEffective 2026-01-01. Parties: Bay Supply Imports and C{i}.'])
    entries=[]; total=0
    for i in range(200):
        amount=10000+i*37; total+=amount
        entry=f'E{i:03d}'; shipment=f'S{i:03d}'; pos=[f'PO{i:03d}']
        if i==0: pos.append('PO000B')
        entries.append({'entry':entry,'amount':amount,'page':i+1})
        document(f'shipment-{i}.pdf','shipment',{'entry':entry,'shipment':shipment,'pos':pos,'quantity':100,'date':'2026-01-15','importer':'Bay Supply Imports'},
            [f'SYNTHETIC BILL OF LADING\nImporter: Bay Supply Imports\nEntry {entry}; Shipment {shipment}\nPO references: {", ".join(pos)}\nQuantity 100 units; date 2026-01-15'],scanned=i%25==0)
        for po in pos:
            quantity=50 if i==0 else (99 if i==10 else 100)
            document(f'{po}.pdf','po',{'po':po,'quantity':quantity,'amount':amount*10,'date':'2026-01-01'},
                [f'SYNTHETIC PURCHASE ORDER {po}\nSupplier: Pacific Goods; Buyer: Bay Supply Imports\nQuantity {quantity}; merchandise cents {amount*10}\nDate 2026-01-01'])
        if i!=2:
            customer=f'C{2 if i==1 else i%8}'
            document(f'invoice-{i}.pdf','invoice',{'invoice':f'INV{i:03d}','shipment':shipment,'customer':customer,'quantity':100,'amount':amount*12,'surcharge':amount,'date':'2026-02-01'},
              [f'SYNTHETIC SALES INVOICE INV{i:03d}\nShipment {shipment}; Customer {customer}\nQuantity 100; total cents {amount*12}; tariff surcharge cents {amount}\nDate 2026-02-01'])
    document('refund-advice.pdf','refund_advice',{'importer':'Bay Supply Imports','date':'2026-11-06','amount':total,'entries':entries},
      [f'SYNTHETIC REFUND ADVICE - page {e["page"]}\nImporter: Bay Supply Imports; date 2026-11-06\nTotal refund cents {total}\nCovered entry {e["entry"]}: refund cents {e["amount"]}' for e in entries])
    (DATA/'fixtures.json').write_text(json.dumps(manifest,sort_keys=True))
    return paths,total

def main():
    init()
    with Session.begin() as s:
        if s.get(Refund,1): return
        paths,total=generate()
        s.add(Refund(id=1,amount=total,importer='Bay Supply Imports',date='2026-11-06'))
        s.add(Allocation(id='unallocated',amount=total,chain={},evidence=[],reason='Awaiting processing',issues=[],obligation={}))
        s.flush()
        for path in paths: ingest(s,path)
        propose(s)
    print('Seeded 200 shipments. Demo stub mode. Open http://localhost:8000')
if __name__ == '__main__': main()
