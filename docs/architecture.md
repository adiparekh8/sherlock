# Architecture and interface contracts

## Scope

A local monolith: FastAPI + server-rendered UI, PostgreSQL, pandas candidate indexing. No background workers, live financial connections, accounts, multiple refunds, or deployment. The default demo works without external credentials. SQLite is an explicitly labeled test/development fallback only.

## Storage

`refund` is singleton ID 1 and carries the current revision. `document` retains original bytes by local path, SHA-256, page text, parser provenance and normalized document records. `extracted_fact` makes normalized fields individually queryable with source/provider metadata. `allocation` stores integer cents, chain, evidence, review state and a candidate obligation. `review_event` stores immutable-by-API before/after values, who/when/why, revision and unique request key. `artifact` stores an immutable reviewed snapshot plus its memo and CSV.

The initial proposed normalized table-per-entity model is compressed into document facts and allocation JSON for the hackathon; document, field and ledger identities remain explicit. No raw floating monetary values enter allocation arithmetic. Allocation splits retain the original source chain and record the selected PO. A candidate obligation is metadata on the affected money, never an additional amount in reconciliation. Split rows hold only their own confirmed liability cents.

## Interfaces

- `DocumentParser.parse(path) -> {kind, pages, facts, provider, confidence_bps, warnings}`. The fixture stub checks file hash before returning known fields. Unknown documents remain `kind=unknown`.
- `FieldNormalizer.normalize(parsed)` and `ContractReader.extract(parsed)` isolate extraction from monetary decisions. `ResponsesAdapter` supplies optional, cited suggestions through the source-analysis endpoint; it cannot authorize writes.
- `ingest(session, path, name)` deduplicates by file hash and persists extracted facts.
- `propose(session)` requires an unprocessed refund and one consistent refund advice. It finds shipments by entry, POs by references, invoices by shipment, contracts by customer. Missing or duplicate links and quantity conflicts are hard blockers. It preserves unmatched money.
- `decide(session, command)` locks the refund, checks the expected revision and decision key, validates amounts, evidence and explicit contract decisions, updates the ledger and appends an audit event atomically.
- `snapshot(session)` asserts reconciliation and collects the current rows and event history.
- `generate(session)` rejects unreviewed rows or pending obligations, then creates both artifacts from a single snapshot.

## Review command

```json
{
  "allocation_id": "E000",
  "revision": 1,
  "key": "unique-request-uuid",
  "actor": "Reviewer name",
  "reason": "Both POs cover 50 units; contract section 4.2 reviewed.",
  "action": "override",
  "obligation_decision": "confirmed",
  "parts": [
    {"amount": 5000, "disposition": "customer_payable", "po": "PO000"},
    {"amount": 5000, "disposition": "customer_payable", "po": "PO000B"}
  ]
}
```

Actions: `confirm`, `override`, `hold`, `reject_obligation_hold`. Confirm is for clean proposals; flagged items require an override. A hold cannot silently resolve a pending liability. Split cents must be positive integers and sum to the original row. No proportional split is performed automatically; the human supplies exact amounts.

Review statuses: `auto-proposed`, `human-confirmed`, `human-overridden`, `unallocated`. Reviewed holds remain `unallocated` with `reviewed_hold=true`. Dispositions: `importer_retained`, `customer_payable`, `unallocated`. Candidate statuses: `pending_review`, `confirmed`, `rejected`.

## HTTP API

Open `/docs` for the generated request schemas.

| Method | Path | Result |
| --- | --- | --- |
| POST | `/imports` | One refund record and multipart PDF files |
| POST | `/imports/1/process` | One-time proposed ledger |
| GET | `/ledger` | Revision, totals, rows, audit events |
| GET | `/review-items` | Open/unallocated proposals |
| POST | `/review-items/decisions` | Atomic decision |
| POST | `/review-items/hold-remaining` | Explicit human bulk rejection/hold with one event per row |
| GET | `/documents/{id}` | Original PDF, page-fragment citations |
| POST | `/documents/{id}/analyze` | Optional cited model suggestions; no ledger mutation |
| POST | `/artifacts` | Immutable memo and CSV URLs |
| GET | `/artifacts/{id}/{memo or csv}` | Download a specific reviewed revision |

## Planted cases

E000: 100 units across PO000 and PO000B, each 50. E001: customer C2's vague “may be shared equitably” clause. E002: missing invoice. E010 adds a deliberate 99-vs-100 quantity mismatch. No fixture flag forces these outcomes; matching derives them from documents.

## Limits

A complete runnable hackathon demo, not production financial infrastructure. Generated fixtures drive the deterministic parser; the Google adapter is unimplemented. Optional AI analysis validates literal source quotes but cannot establish legal correctness, and its suggestions are not automatically promoted into matched facts. Live provider calls require separately supplied credentials/model and are not needed for acceptance tests. Uploaded standalone image files are not accepted; scanned PDFs are. Journal account mapping and memo rendering beyond Markdown are deferred. Reviewer identity is self-declared, and database administrators can alter stored data outside the application.
