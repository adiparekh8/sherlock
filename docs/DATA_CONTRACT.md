# Data contract

A dataset is one folder under `data/`. `make seed DATASET=<folder>` loads it; that command is the
entire dataset swap. Nothing outside `sherlock/ingest.py` reads these files.

```
data/<dataset_name>/
  manifest.json          describes the folder and the planted hard cases
  refund.json            one lump-sum refund with its per-entry breakdown
  shipments.csv          customs entries / bills of lading
  purchase_orders.csv    customer POs
  invoices.csv           customer invoices against POs
  contracts/*.pdf        one PDF per customer contract
```

Conventions that apply everywhere:

- **Money is integer cents.** Any money column containing a decimal point fails ingest.
- Dates are ISO `YYYY-MM-DD`. Optional dates may be blank.
- CSV files have a header row; `source_row` in the database is the 1-based line number including the header, so row 2 is the first data row.
- Identifiers are opaque strings. Keep them unique within their file.
- Blank strings in optional columns become NULL.

## refund.json

| key | type | required | meaning |
|---|---|---|---|
| refund_id | string | yes | identifier for the refund notice |
| importer | string | yes | importer of record |
| amount_cents | int | yes | the lump sum received |
| received_date | date | yes | |
| currency | string | no | default USD |
| source | string | no | e.g. "U.S. Customs and Border Protection" |
| reference | string | no | ACH trace, notice number, etc. |
| entries | list | yes | per customs entry lines, below |

Each entry: `entry_number` (string), `amount_cents` (int), `entry_date` (date, optional).
If the entries do not sum to `amount_cents`, the difference becomes an unallocated line with reason `refund_total_not_supported_by_entries`.

## shipments.csv

| column | type | notes |
|---|---|---|
| shipment_id | string | primary key |
| entry_number | string | customs entry; joins to refund.json entries. Several shipments may share one entry. |
| bill_of_lading | string | optional |
| ship_date | date | optional |
| arrival_date | date | optional |
| supplier | string | used for fuzzy PO matching |
| description | string | used for fuzzy PO matching |
| hts_code | string | optional |
| quantity | int | used for PO matching and for splitting an entry across shipments |
| declared_value_cents | int | |
| duty_paid_cents | int | basis for sharing an entry's refund across its shipments |
| po_number | string | optional. Blank means "unknown"; a value that matches no PO is treated as a dangling reference. |

## purchase_orders.csv

| column | type | notes |
|---|---|---|
| po_number | string | primary key |
| customer_id | string | customers are derived from this column |
| customer_name | string | display name; first occurrence wins |
| supplier | string | |
| order_date | date | optional |
| description | string | |
| quantity | int | |
| unit_price_cents | int | |
| total_cents | int | |

## invoices.csv

| column | type | notes |
|---|---|---|
| invoice_number | string | primary key |
| po_number | string | must exist in purchase_orders.csv; otherwise the row is skipped with a warning |
| customer_id | string | |
| invoice_date | date | optional |
| amount_cents | int | invoice total including any surcharge |
| tariff_surcharge_cents | int | the portion of the invoice that passed tariff cost to the customer; 0 if none |

## contracts/

One PDF per customer. Text-based PDFs are read by the local stub parser; scans need the Document AI parser (optional, see `.env.example`). The manifest maps each file to a customer.

## manifest.json

```json
{
  "dataset": "synthetic_v1",
  "importer": "Pacific Crest Imports LLC",
  "files": {"refund": "refund.json", "shipments": "shipments.csv", "purchase_orders": "purchase_orders.csv",
            "invoices": "invoices.csv", "contracts_dir": "contracts"},
  "contracts": [{"file": "contracts/CUST-001_northwind.pdf", "customer_id": "CUST-001", "customer_name": "..."}],
  "hard_cases": [
    {"id": "split_po", "kind": "shipment_split_across_pos", "shipment_id": "...", "po_numbers": ["...", "..."], "expect": "review_queue"},
    {"id": "vague_surcharge", "kind": "vague_surcharge_clause", "customer_id": "...", "contract_file": "...", "expect": "pending_review"},
    {"id": "missing_invoice", "kind": "missing_invoice", "shipment_id": "...", "po_number": "...", "expect": "review_queue"}
  ]
}
```

`contracts` is required (it is how a PDF is tied to a customer). `hard_cases` is optional and only
read by tests and the UI's "planted cases" panel; a real dataset may leave it empty.
`other_mismatches` and `counts` are informational.

## What the matching engine assumes

The chain is refund entry -> shipment (by `entry_number`) -> PO (by `po_number`, else fuzzy on
supplier + description + quantity + date window) -> invoice (by `po_number`) -> customer (from the
PO). Tolerances and thresholds live in `sherlock/matching/config.py`; the rules are the named
functions in `sherlock/matching/rules.py`. Changing either does not require touching ingest.
