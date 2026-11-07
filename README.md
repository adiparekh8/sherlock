# Sherlock

Where does every dollar of a tariff refund belong? Sherlock takes one lump-sum refund plus the shipping records,
purchase orders, invoices and customer contracts behind it, and produces an allocation ledger in which every
line links to its evidence (file, row or page, clause). Uncertain lines go to a human review queue. The outputs
are an audit memo and a labeled journal-entry CSV. Built for the BBS x Ramp Hackathon; see `docs/SPEC.md`.

## Run it

```
make install          # Python 3.11+
make demo             # Postgres via docker if available, else SQLite; seeds synthetic_v1; API :8000; UI :8501
```

No API keys are needed. With `ANTHROPIC_API_KEY` in `.env` the contract reader uses Claude and caches results
in `llm_cache/`; without it, cached results are served and a deterministic rule-based stub fills any gap.

## Swap the dataset

Put a folder matching `docs/DATA_CONTRACT.md` under `data/` and run `make seed DATASET=<folder>`.
Matching tolerances live in `sherlock/matching/config.py`; the rules in `sherlock/matching/rules.py`.

## Guarantees

- Conservation: refund total = allocated + unallocated, always; every unallocated line carries a reason.
- Money is integer cents. Nothing is force-matched; lines below the confidence threshold are queued, not allocated.
- Contract obligations are never auto-confirmed. Every human decision is logged with who, when, what, why.
- Memo and CSV regenerate from the reviewed ledger.

See `CLAUDE.md` for the architecture and developer workflow.
