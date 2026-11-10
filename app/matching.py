"""Pandas indexes candidates; all monetary arithmetic stays in Python integers."""
import pandas as pd

def index_documents(documents, kind, field):
    rows=[{'key':d.parsed['facts'].get(field),'document_id':d.id} for d in documents if d.parsed.get('kind')==kind]
    if not rows: return {}
    frame=pd.DataFrame(rows,dtype=object)
    return frame.groupby('key',dropna=True,sort=True)['document_id'].agg(list).to_dict()
