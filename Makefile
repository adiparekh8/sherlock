# Sherlock developer commands. See CLAUDE.md for the full workflow.
DATASET ?= synthetic_v1
VENV    ?= .venv
PY      ?= $(VENV)/bin/python
PIP     ?= $(VENV)/bin/pip

.PHONY: install synthetic seed api ui test db-up db-down demo demo-lite clean

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

# Regenerate the synthetic dataset (deterministic; safe to re-run).
synthetic:
	$(PY) scripts/make_synthetic.py --out data/$(DATASET)

# The dataset swap: point this at any folder under data/ that matches docs/DATA_CONTRACT.md.
seed:
	$(PY) scripts/seed.py --dataset $(DATASET)

api:
	$(VENV)/bin/uvicorn sherlock.api.app:app --host 127.0.0.1 --port 8000

ui:
	$(VENV)/bin/streamlit run ui/app.py --server.port 8501 --server.headless true

test:
	$(VENV)/bin/pytest

db-up:
	docker compose up -d db

db-down:
	docker compose down

# One command: DB (docker if available, else SQLite), seed, API, UI.
demo:
	bash scripts/demo.sh $(DATASET)

# Force the SQLite path even if docker is installed.
demo-lite:
	SHERLOCK_FORCE_SQLITE=1 bash scripts/demo.sh $(DATASET)

clean:
	rm -f sherlock.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
