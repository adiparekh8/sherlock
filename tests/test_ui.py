"""Drive every Streamlit page headlessly against an in-process API on a free port."""

import socket
import threading
import time

import pytest
import requests
import uvicorn
from streamlit.testing.v1 import AppTest

from sherlock.api.app import app
from sherlock.pipeline import seed
from tests.conftest import DATASET_DIR, REPO


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def api_url(engine, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(DATASET_DIR.parent))
    from sherlock.config import get_settings

    get_settings.cache_clear()
    seed(str(DATASET_DIR), engine)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(f"{url}/health", timeout=1).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.05)
    monkeypatch.setenv("SHERLOCK_API_URL", url)
    yield url
    server.should_exit = True
    thread.join(timeout=5)
    get_settings.cache_clear()


PAGES = ["Dataset", "Ledger", "Review queue", "Contracts", "Memo", "Export"]


def test_every_page_renders_without_exception(api_url):
    at = AppTest.from_file(str(REPO / "ui" / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    for page in PAGES:
        at.radio[0].set_value(page).run()
        assert not at.exception, f"{page}: {at.exception}"
    # Ledger page shows conservation and the queue page lists the planted cases.
    at.radio[0].set_value("Ledger").run()
    body = " ".join(m.value for m in at.markdown)
    assert "Conservation: refund = allocated + unallocated" in body and ">Holds<" in body
    at.radio[0].set_value("Review queue").run()
    labels = " ".join(e.label for e in at.expander)
    assert "ambiguous_po_split" in labels and "missing_invoice" in labels and "CUST-003" in labels
