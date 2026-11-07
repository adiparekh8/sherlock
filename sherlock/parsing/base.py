"""DocumentParser interface. Implementations turn a file into per-page text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sherlock.config import Settings, get_settings


@dataclass
class ParsedPage:
    page: int  # 1-based
    text: str


@dataclass
class ParseResult:
    parser: str
    pages: list[ParsedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


class DocumentParser(Protocol):
    name: str

    def parse(self, path: Path) -> ParseResult: ...


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_parser(settings: Settings | None = None) -> DocumentParser:
    """Document AI when credentials are configured, otherwise the local stub."""
    settings = settings or get_settings()
    if settings.docai_enabled:
        from sherlock.parsing.docai import DocumentAIParser

        return DocumentAIParser(settings.docai_processor_name)
    from sherlock.parsing.stub import StubParser

    return StubParser()
