"""Adapters return source-grounded pages and facts; fixture lookup is explicit."""
import hashlib
import json
from pathlib import Path
from typing import Protocol
from pypdf import PdfReader
from .db import DATA

class DocumentParser(Protocol):
    def parse(self, path: Path) -> dict: ...
class FieldNormalizer(Protocol):
    def normalize(self, parsed: dict) -> dict: ...
class ContractReader(Protocol):
    def extract(self, parsed: dict) -> dict: ...

class LocalParser:
    def parse(self, path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path = DATA / 'fixtures.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if digest in manifest:
            return {**manifest[digest], 'provider': 'demo-stub', 'confidence_bps': 10000}
        try:
            pages = [p.extract_text() or '' for p in PdfReader(path).pages]
        except Exception:
            pages = []
        return {'kind': 'unknown', 'pages': pages, 'facts': {}, 'provider': 'local-text',
                'confidence_bps': 0, 'warnings': ['No verified structured extraction; human review required.']}

class LocalNormalizer:
    def normalize(self, parsed):
        # Stub values originate in the reproducible fixture manifest, never guessed.
        return parsed

class LocalContractReader:
    def extract(self, parsed):
        if parsed.get('kind') != 'contract': return {}
        facts = parsed['facts']
        return {'customer': facts['customer'], 'clause': facts['clause'],
                'status': 'pending_review', 'draft_rule': facts['rule']}

class GoogleDocumentAIAdapter:
    def parse(self, path):
        raise RuntimeError('Google Document AI is not configured. Select the local parser.')

# Optional model implementation is ResponsesAdapter in app.ai.
