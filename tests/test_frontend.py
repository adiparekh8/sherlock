"""The console is served by the API and stays within the brief's limits."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sherlock.api.app import app
from tests.conftest import DATASET_DIR, REPO


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(DATASET_DIR.parent))
    from sherlock.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_root_serves_the_console_and_its_assets(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>Sherlock</title>" in r.text and "/static/app.js" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    cfg = client.get("/config").json()
    assert cfg["auto_threshold"] == 0.8 and "demo_actor" in cfg


def test_index_is_small_and_components_live_in_app_js():
    index = (REPO / "frontend" / "index.html").read_text().splitlines()
    assert len(index) < 400
    app_js = (REPO / "frontend" / "app.js").read_text()
    for fn in ("formatCents", "toCents", "pageOverview", "pageLedger", "pageReview", "pageMemo", "pageExport", "chainFor"):
        assert f"function {fn}(" in app_js or f"async function {fn}(" in app_js
    assert "parseFloat" not in app_js and "toFixed(2)" not in app_js.replace("toFixed(2)}", "")  # money never goes through floats


def test_no_streamlit_left():
    assert "streamlit" not in (REPO / "pyproject.toml").read_text()
    assert not (REPO / "ui").exists()
    for p in Path(REPO / "sherlock").rglob("*.py"):
        assert "streamlit" not in p.read_text()
