# Sherlock

An evidence-backed tariff refund review demo for the BBS × Ramp Hackathon. One importer, one refund, 200 synthetic shipments, eight contracts, and a traceable ledger. Nothing is written to an ERP, Ramp, customs, or a bank.

## Run the complete demo

Prerequisite: Git and Docker with Compose v2, running. The first build downloads public images and Python packages; after that the default workflow uses no external services or keys.

```sh
git clone https://github.com/adiparekh8/sherlock.git
cd sherlock
docker compose -f compose.demo.yaml up --build
```

Open http://localhost:8000. From a cloned checkout, **`docker compose -f compose.demo.yaml up --build` is the one-command run**: PostgreSQL starts, the schema is created, documents are generated and parsed, and the refund is matched. Restarting preserves human decisions. Use a separate Compose project (`docker compose -f compose.demo.yaml -p sherlock-rehearsal up --build`) for fresh volumes after stopping the previous instance.

## What to demonstrate

1. Show the $27,363.00 refund and the exact reconciliation. Initially every row is unallocated because contract candidates require human review.
2. Open **Split shipment → two POs** (`E000`). Compare the bill of lading, both POs, invoice, and contract. Each PO contains 50 of the shipment's 100 units.
3. Enter your reviewer name and reason. Choose **Override**, confirm the customer obligation, and allocate **5000 cents to PO000** and **5000 cents to PO000B**, both customer payable. Record the decision.
4. Show $100 allocated, $27,263 unallocated, and the audit event. The vague clause (`E001`) and missing invoice (`E002`) are still held.
5. For a short export demonstration, explicitly review remaining rows as unallocated. The bulk action requires a name, reason, and an explicit rejection of pending candidate claims. This keeps all remaining money in suspense; it is a human decision, not an automated legal conclusion. Alternatively, review rows individually.
6. Generate the memo and journal CSV. Both use the same immutable ledger revision. Show the override, source citations, reconciliation, and balanced debit/credit totals.

The submitted demo should disclose **stub parsing mode**. Hash-bound fixtures stand in for Document AI, including eight scanned bills of lading. Unknown PDFs extract text but stay unresolved. The program does not pretend to understand arbitrary scans without OCR.

## Optional AI

The review screen can analyze the selected source document using an optional OpenAI Responses adapter. Set `OPENAI_API_KEY` and `OPENAI_MODEL` in your shell before starting Compose. Choose a model available to your account that supports structured outputs. No key is required for the default demo, and no paid call happens automatically.

The adapter extracts normalized field suggestions and candidate tariff/refund clauses. It validates quotes against the cited page, shows interpretations as pending review, and never changes the monetary ledger. Provider failure or missing credentials produces a visible error. The live API has not been exercised without credentials; citation validation is covered by offline tests.

Implementation reference: [Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## Data and guarantees

- Money is stored and computed as integer cents. USD only.
- A synthetic refund advice identifies covered entries and refund cents. Amount/date/importer alone never establish eligibility.
- PostgreSQL stores documents, extracted fields, allocation chains, candidate obligations, review events, and immutable exported snapshots. For this small demo, business records and evidence are JSON fields rather than a separate table for each document type.
- pandas indexes candidate shipment links; Python integer arithmetic and SQL transactions enforce conservation.
- Every allocated row has a source chain. Missing/conflicting records and confidence below 9500 basis points are queued. Confidence is a heuristic, not a probability.
- Contract candidates remain pending until explicitly confirmed or rejected by a human. Draft amounts are provisional maximum amounts for review, not calculated legal liability.
- Overrides require a reason, self-declared reviewer, cited PO, exact cent sum, expected ledger revision, and unique decision key. PostgreSQL locks the refund during mutation. There is no login or authenticated identity.
- Exports require every row to be reviewed, including explicit holds; pending obligations and unreviewed proposals block export.
- The CSV debits refund clearing and credits tariff recovery, customer refund payable, or unallocated suspense. It assumes the cash receipt is already booked. Account labels require mapping for a particular ERP.
- Memo and CSV evidence URLs point to the running local app; preserve its data volumes for those links to work.

## Tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -e ".[dev]"
.venv/bin/python -m pytest tests/local_demo -q
```

Tests default to an isolated SQLite database as a fast developer fallback. The production demo uses PostgreSQL. To run against a **disposable** PostgreSQL database, set `TEST_DATABASE_URL`; the test fixture recreates its tables. GitHub Actions provisions PostgreSQL, runs the suite, and smoke-tests Compose startup.

For local development without Docker:

```sh
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

This fallback uses SQLite and is not a PostgreSQL concurrency test. Set `SHERLOCK_LOCAL_DATABASE_URL=postgresql+psycopg://...` for PostgreSQL outside Docker.

## Import a different local folder

Use fresh volumes and `SEED_DEMO=0 docker compose -f compose.demo.yaml up --build`. The intake screen accepts the refund record and a folder of PDFs, including scans packaged as PDFs (20 MB/file). Unknown documents remain unallocated with a reason. Real OCR/structured extraction is intentionally behind `DocumentParser`; `GoogleDocumentAIAdapter` is a configuration placeholder, not a working Google integration.

## Layout

- `app/db.py`: schema and storage
- `app/parsing.py`, `app/ai.py`: parser and optional AI interfaces
- `app/engine.py`, `app/matching.py`: matching, ledger, transactional review
- `app/main.py`, `app/templates/`: thin API and review UI
- `app/outputs.py`: snapshot-based memo and balanced journal export
- `app/seed.py`: deterministic synthetic documents and planted exceptions
- `tests/`: acceptance and rejection-path tests
- `architecture.md`: interface contracts and deliberate scope boundaries

## Author notes

<!-- Sid / Adi: add your explanation, demo link, and hackathon submission notes here. -->
