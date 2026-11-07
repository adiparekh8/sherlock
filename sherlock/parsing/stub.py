"""Local parser: pypdf text extraction for text-based PDFs, plain read for .txt. No OCR."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from sherlock.parsing.base import ParsedPage, ParseResult


class StubParser:
    name = "stub"

    def parse(self, path: Path) -> ParseResult:
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            pages = [ParsedPage(i + 1, _clean(p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        else:
            pages = [ParsedPage(1, _clean(path.read_text(errors="replace")))]
        return ParseResult(parser=self.name, pages=pages)


def _clean(text: str) -> str:
    # pypdf hard-wraps lines; keep the wrap (so spans stay stable) but normalize whitespace per line.
    return "\n".join(line.strip() for line in text.replace("\r", "").split("\n")).strip()
