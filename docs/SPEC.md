# Sherlock: Project Specification

Two Berkeley undergrads are building Sherlock for the BBS x Ramp Hackathon. Hackathon prompt: automate an outdated financial workflow using the newest AI tools. Submission due Tuesday Nov 10, 11:59 pm PT (GitHub repo plus demo). Today is Friday Nov 6.

## THE PROBLEM
When a company receives a tariff refund, it arrives as one lump sum. Someone must figure out where every dollar belongs across shipping records, purchase orders, accounting books, and customer contracts. Today that is manual spreadsheet work, and errors create legal exposure: many importers passed tariff costs to customers as surcharges, and whether a customer is owed a share of a refund can depend on the contract.

## WHAT SHERLOCK DOES
Ingests one lump-sum refund plus a folder of documents (bills of lading, purchase orders, invoices, customer contracts), matches them, and produces an allocation ledger where every dollar links to its evidence: document, page, and clause. Uncertain cases go to a human review queue. Outputs are an audit memo and a journal-entry export (CSV) for ERP import.

## FUNCTIONAL REQUIREMENTS
1. Ingest: one refund record (amount, date, importer) plus a local folder of PDFs and scans. No live external connections.
2. Parse: extract parties, dates, entry and PO numbers, quantities, and amounts into PostgreSQL. Document parsing sits behind an interface so a stub can stand in for Google Document AI when credentials are unavailable.
3. Match: link refund to entries, shipments, POs, sales, and customers; produce the allocation ledger. Every allocated dollar carries a confidence score and evidence links.
4. Contract reader: find candidate surcharge pass-through and refund clauses in customer contracts. Output candidate obligations (customer, clause citation, draft amount) with status pending review. Candidate liabilities from uncertain clauses are never auto-confirmed or auto-released; only a human decision moves them.
5. Review queue: anything below the confidence threshold or with conflicting evidence lands here, showing the AI's reasoning and the conflicting documents side by side. Human approvals and overrides are logged with who, when, what changed, and why.
6. Audit memo: totals, method, evidence links, flagged items and resolutions, and the reconciliation showing refund total = allocated + unallocated.
7. Export: a journal-entry CSV of the final human-reviewed allocation, labeled as an export. No live ERP or Ramp write.

## FINANCIAL INVARIANTS
- Conservation: refund total = allocated + unallocated, always. Every dollar is either allocated with evidence or sits in a visible unallocated line with a reason. Nothing is force-matched; nothing vanishes.
- Store money as integer cents or DECIMAL, never binary floats.
- Every allocation carries a review status: auto-proposed, human-confirmed, human-overridden, or unallocated. Overrides are traceable.
- Candidate customer liabilities from contract clauses stay pending until a human confirms them.

## DEMO DATA
Generate one synthetic mid-size importer: about 200 shipments, POs with deliberate mismatches, 5-10 customer contracts with varied clause language, one lump refund. Plant three hard cases: a shipment split across two POs, a vague surcharge clause, a missing invoice. A seed script makes the demo reproducible from one command.

## OUT OF SCOPE
Multiple refunds or importers, real customer data, live ERP/bank/customs connections, login or accounts, analytics dashboards.

## TEAM AND OWNERSHIP
Adi builds the full system with Claude Code, including the synthetic dataset. Sid is sourcing realistic data and will later replace the synthetic dataset with his own, and may adjust the schema and matching rules to fit it. The data layer must be designed so that swapping the dataset is a one-folder, one-command change.

## STACK
PostgreSQL, pandas, FastAPI, Streamlit, LLM APIs. Local is fine; AWS optional. Do not assume any external API keys, paid services, or deployments. Stub external services behind interfaces so everything runs locally.

## ACCEPTANCE TESTS
- The demo runs from one command on a fresh machine with seeded data.
- Conservation holds for the demo refund, verifiable on screen and in the memo.
- Every allocated dollar shows its evidence chain.
- The three planted ambiguities land in the review queue and are not auto-allocated.
- One human override on a queued item shows up in the ledger, the memo, and the export, with the override logged.
- The memo and CSV regenerate from the final reviewed ledger.
