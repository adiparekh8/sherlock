import pytest
from app.ai import validate_analysis, ResponsesAdapter

def test_ai_citations_are_verified():
    data={'fields':[{'name':'date','raw':'2026-01-01','normalized':'2026-01-01','page':1,'quote':'Date 2026-01-01'}], 'clauses':[], 'summary':'Date found.'}
    assert validate_analysis(data,['Date 2026-01-01'])['fields'][0]['page']==1
    with pytest.raises(ValueError): validate_analysis(data,['Different text'])
    data['fields'][0]['page']=2
    with pytest.raises(ValueError): validate_analysis(data,['Date 2026-01-01'])

def test_no_credentials_fails_explicitly(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='Optional AI'): ResponsesAdapter().extract({'pages':['hello']})
