"""Dollars appear only at the UI edge, and only when they convert back to integer cents exactly."""

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_helpers():
    """Import just the two pure helpers from ui/app.py without running the Streamlit script."""
    src = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    text = src.read_text()
    start = text.index("def dollars(")
    end = text.index("def h(s)")
    ns = {}
    exec(text[start:end], ns)
    return ns["dollars"], ns["to_cents"]


def test_dollars_and_to_cents_round_trip_exactly():
    dollars, to_cents = _load_helpers()
    for cents in (0, 1, 99, 100, 528523, 217633901, -1234):
        assert to_cents(dollars(cents)) == cents
    assert to_cents("$5,285.23") == 528523
    assert to_cents("12") == 1200
    assert to_cents("12.5") == 1250
    for bad in ("12.345", "abc", "1e3.5", "", "0.001"):
        assert to_cents(bad) is None, bad
