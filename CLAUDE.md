# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`docs/SPEC.md` is the source of truth and overrides anything here that conflicts with it. `AGENTS.md` is a
mirror of this file for other tools; keep them identical.

## What Sherlock is

One lump-sum tariff refund comes in. Sherlock matches it through customs entries, shipments, POs, invoices and
customers into an allocation ledger where every line has evidence, a confidence, and a review status. Uncertain
lines go to a human queue. Outputs are an audit memo (markdown), a labeled journal-entry CSV (the close entry)
and a labeled payables CSV (human-confirmed customer obligations). There is no auth, no live ERP/Ramp write,
and no external key is required to run the demo. `docs/PITCH.md` is the video script; `docs/DEMO_PATH.md` is
the click sequence the demo follows.

## Commands

```
make install                       # python3 -m venv .venv && pip install -e ".[dev]"   (Python >= 3.11)
make demo                          # DB (docker Postgres if present, else SQLite) + seed + API :8000 + UI :8501
make demo-lite                     # same, forcing SQLite
make seed DATASET=synthetic_v1     # the dataset swap: reset DB and run the full pipeline on data/<name>/
make synthetic                     # regenerate data/synthetic_v1 (deterministic, seed 42; includes the scanned invoice)
make llm-cache                     # read every contract and scan with the real model; needs ANTHROPIC_API_KEY; commit llm_cache/
make api / make ui                 # run the pieces separately
make test                          # pytest (SQLite, no network, no key)
.venv/bin/pytest tests/test_review.py -k override        # one test
```

Config comes from `.env` (copy `.env.example`). `DATABASE_URL` defaults to `sqlite:///./sherlock.db`;
docker-compose exposes Postgres on 5432. `ANTHROPIC_API_KEY` is optional at run time: without it the LLM client
serves `llm_cache/` and falls back to the rule-based stub only for documents with no cached output. The demo
must never hit the stub for synthetic_v1, so after any prompt-version bump or new document run `make llm-cache`
with a key and commit `llm_cache/`; `tests/test_ai_coverage.py` enforces this once the cache exists.
`SHERLOCK_DEMO_ACTOR` pre-fills the reviewer name so decision buttons are live during a demo.

## Architecture

The pipeline (`sherlock/pipeline.py`) is reset -> ingest -> parse -> normalize -> scans -> match -> obligations.
Each stage is a function `(session, dataset_dir) -> summary dict` registered in `STAGES`.

- **Dataset seam.** `sherlock/ingest.py` is the only code that reads files. The layout and column types are in
  `docs/DATA_CONTRACT.md`. Swapping datasets is `make seed DATASET=<folder>`; nothing else moves.
- **Matching rules** live in `sherlock/matching/rules.py` (one named function per hop) with tolerances and
  thresholds in `sherlock/matching/config.py`. `engine.py` walks the hops and writes `AllocationRecord`s.
- **Queue semantics.** A line below `auto_threshold`, or with ambiguous evidence, is written as `unallocated`
  with a reason, a `proposal` (what the engine would do), and `needs_review=True`. The queue is simply the live
  records with `needs_review`. Nothing below threshold is ever counted as allocated.
- **Conservation.** `assert_conservation` runs after matching and after every review decision: live records sum
  to the refund, every unallocated line has a reason, every allocated line has a customer.
- **Review** (`sherlock/review.py`) never edits money in place. The reviewed record gets
  `superseded_by_decision_id`; replacement lines get `created_by_decision_id`. `live_records` filters on
  `superseded_by_decision_id IS NULL`. Partial overrides leave an `override_remainder` line.
- **Contracts.** `parsing/` (DocumentParser: pypdf stub, optional Document AI) -> `normalize.py` (one LLM call
  per contract via `llm/client.py`, cached by content hash) -> `obligations.py` (CandidateObligation, always
  `pending_review`, draft amount recomputed from the live ledger after every decision).
- **LLM.** `llm/client.py` is the only caller (text and vision; images are part of the cache key). Output is
  validated against the Pydantic schemas in `llm/schemas.py`. Only real API output is cached; the stub
  (`llm/stub.py`) is never cached, so changing the stub cannot be shadowed by stale files. `ParsedDocument`
  records `extract_source` and `extract_model` so the memo can say what read each document.
- **Scans** (`scans.py`). Image-only PDFs under `data/<dataset>/scans/` are read by the model into
  ExtractedFields. A scanned invoice naming a PO with no invoice becomes a proposal (`invoice_from_scan`) on
  that PO's queued `missing_invoice` line. `review._materialize_scanned_invoice` creates the Invoice row only
  when a human approves or overrides; the decision's `after.created_invoices` records it.
- **Why AI.** Two contracts in synthetic_v1 are off-template (manifest `off_template: true`); the rule-based
  stub misreads them and `tests/test_ai_coverage.py` pins both that failure and the model's correct reading.
- **Outputs.** `memo.py` and `export.py` (journal and payables CSVs) are pure reads of the ledger and regenerate
  on every call.
- **API** (`sherlock/api/app.py`) is unprefixed because one refund is loaded at a time. The Streamlit UI
  (`ui/app.py`) talks only to the API. Its look comes from `.streamlit/config.toml` (theme, fonts, zero radius)
  plus the CSS block at the top of `ui/app.py`; pages deep-link as `?page=Ledger`. Streamlit's DOM is
  version-specific, so after a Streamlit upgrade re-check the nav radio and expander selectors there.

## Conventions

- Money is integer cents everywhere (`BigInteger`); confidence is a float and is not money. `money.split_cents`
  does exact largest-remainder splits. Dollars exist only in `ui/app.py` (`dollars`/`to_cents`), which reject
  anything that does not convert to cents exactly.
- Branches `adi/<feature>`, merge into `main`, never commit to `main` directly. Small commits, a test per commit,
  run `make test` before committing.
- Tests must keep covering: conservation, each planted hard case in the queue and not auto-allocated, a human
  override flowing into ledger + memo + export with the decision logged, and memo/CSV regeneration.
- Never commit keys. Keep `.env.example` current.
- End each session with a three-line status: done, blocked, next.
