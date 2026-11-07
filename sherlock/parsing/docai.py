"""Google Document AI parser. Activates only when GOOGLE_APPLICATION_CREDENTIALS and
DOCAI_PROCESSOR_NAME are set (see .env.example). Handles scans; the stub does not.

Untested against a live processor in this repo; the shape follows the documented
`process_document` response (document.text plus per-page layout text anchors).
"""

from __future__ import annotations

from pathlib import Path

from sherlock.parsing.base import ParsedPage, ParseResult

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".tif": "image/tiff", ".tiff": "image/tiff"}


class DocumentAIParser:
    name = "docai"

    def __init__(self, processor_name: str):
        try:
            from google.cloud import documentai  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install 'sherlock[docai]' to use the Document AI parser") from e
        self._documentai = documentai
        self._client = documentai.DocumentProcessorServiceClient()
        self._processor_name = processor_name

    def parse(self, path: Path) -> ParseResult:
        path = Path(path)
        raw = self._documentai.RawDocument(content=path.read_bytes(),
                                           mime_type=MIME.get(path.suffix.lower(), "application/pdf"))
        request = self._documentai.ProcessRequest(name=self._processor_name, raw_document=raw)
        doc = self._client.process_document(request=request).document
        pages: list[ParsedPage] = []
        for i, page in enumerate(doc.pages):
            text = "".join(
                doc.text[int(seg.start_index):int(seg.end_index)]
                for seg in page.layout.text_anchor.text_segments
            )
            pages.append(ParsedPage(i + 1, text.strip()))
        return ParseResult(parser=self.name, pages=pages)
