"""Locate a quoted string inside page text, tolerant of whitespace and line-wrap differences."""

from __future__ import annotations

import re


def locate_span(page_text: str, quote: str) -> tuple[int, int] | None:
    if not quote:
        return None
    idx = page_text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    tokens = [re.escape(t) for t in quote.split()]
    if not tokens:
        return None
    m = re.search(r"\s+".join(tokens), page_text)
    if m:
        return m.start(), m.end()
    return None
