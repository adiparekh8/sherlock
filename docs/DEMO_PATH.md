# Demo path

The exact click sequence for the video and the live final. Rehearse it; do not improvise on the day.

## Before you start

```
cp .env.example .env            # once; set SHERLOCK_DEMO_ACTOR=adi so decision buttons are live immediately
make demo                       # DB + seed + API :8000 + UI :8501
```

Open http://localhost:8501. If a previous rehearsal left decisions in the ledger, go to **Dataset** and press
**Reset demo**; it re-seeds the current dataset in a few seconds. Set the browser zoom so the Ledger hero
and its stat grid fit on one screen (about 90% on a 14-inch laptop).

Pages, in sidebar order: Ledger, Review queue, Contracts, Memo, Export, Dataset. Each is deep-linkable
(`?page=Review%20queue`).

## 1. Ledger: the reconciliation

- **Page:** Ledger (the landing page).
- **Element:** the hero. The big number is the refund. The mono grid on the right reads refund, auto-proposed,
  human-confirmed, unallocated, conservation, queue.
- **Notice:** "Conservation: Holds". Say the equation out loud: refund = allocated + unallocated. Point at
  "Human-confirmed $0.00": nothing has been touched yet, every allocated dollar is still a proposal.
- **Element:** the three small tables (by status, unallocated by reason, by customer).
- **Notice:** every unallocated dollar has a reason: low_confidence, ambiguous_po_split, po_not_found,
  missing_invoice, no_shipment_for_entry.

## 2. Ledger: one evidence chain, drilled to the row

- **Element:** scroll to "Lines". Leave the filters on "all". In "Evidence chain", pick line **#1**.
- **Notice:** the pills (auto_proposed, confidence 0.96, po_number_exact+invoice_by_po), then the engine's
  reasoning in one paragraph, then four evidence cards: `refund.json entries[..]`, `shipments.csv row 2`,
  `purchase_orders.csv row 2`, `invoices.csv row 2`. Expand one "Source records" JSON to show the raw row.
- **Say:** "This is what an auditor asks for, and it is already written."

## 3. Review queue: the split PO

- **Page:** Review queue. Confirm the reviewer name is filled (SHERLOCK_DEMO_ACTOR) or type it.
- **Element:** tab "Allocation lines". Open the item for **SHP-0057** (reason `ambiguous_po_split`).
- **Notice:** the reasoning paragraph; "What the engine proposes" with two lines to two different customers;
  "The documents that disagree" showing three cards side by side: the shipment row with po_number blank, PO
  **PO-240057A** qty 730, PO **PO-240057B** qty 500.
- **Say:** "730 plus 500 is 1,230. Sherlock proposes the split and does nothing until a person decides."
  Do **not** decide this one; collapse it.

## 4. Review queue: the scanned invoice, approved live

- **Element:** open the item for **SHP-0123** (reason `missing_invoice`).
- **Notice:** under "A scanned document the model read": the page image on the left (skewed, grainy, no
  text layer), the extracted fields on the right with confidences and where on the page each was read:
  invoice number INV-240123, PO PO-240123, total $75,036.07, surcharge $12,103.87.
- **Notice:** the proposal line now names INV-240123, and the reasoning ends with "Approving creates that
  invoice record; it is not created automatically."
- **Action:** type a reason, for example "Scan matches PO quantity and the AP received stamp." Press
  **Approve the proposal**.
- **Notice:** the item disappears from the queue; the sidebar and hero numbers move: human-confirmed is now
  $12,103.87, unallocated dropped by the same amount, conservation still holds.
- **Say:** "The engine found the gap, the AI read the scan, the human confirmed, the books changed."

## 5. Review queue: the vague clause, left pending

- **Element:** tab "Contract clauses". Open **CUST-003 Harbor & Vale Supply LLC**.
- **Notice:** the clause quoted in italics with its citation `contracts/CUST-003_harbor.pdf page 2`; "refund
  owed: unclear", strength "ambiguous", confidence 0.35; the model's reasoning: price adjustments at Seller's
  discretion, only good-faith discussion of reductions. On the right, the surcharge invoices behind the draft
  amount.
- **Action:** none. Leave it pending.
- **Say:** "Nothing about a customer's money is ever decided by the model."

## 6. Memo: regenerated with the decision in it

- **Page:** Memo.
- **Notice:** section 1 Reconciliation, "Conservation holds: YES", with human-confirmed now non-zero;
  section 2 Method names the model that read the contracts and the committed cache; section 4 Flagged items:
  the SHP-0123 line reads "APPROVE by adi ... Created invoice INV-240123 ... from the scanned document the
  model read"; section 6 Decision log has one row with who, when, what changed, why.
- **Action:** press **Download the memo** so the viewer sees it is a file.

## 7. Export: the close entry

- **Page:** Export.
- **Notice:** the stat row: lines, debits, credits, "Balanced". The first row is the cash debit for the full
  refund. Scroll to the row for **INV-240123**: review_status `human_confirmed`, decision_id `1`.
- **Say:** "This is the file an accounting sync consumes. Sherlock posts nothing."
- **Element:** Payables export: one row per human-confirmed customer obligation. Today it is empty because
  CUST-003 was left pending; if you want a row on screen, confirm CUST-001 in step 5 first.

## 8. Reset for the next rehearsal

- **Page:** Dataset. Press **Reset demo**. Confirm the queue count returns to 10 on the sidebar.

## Timing

Steps 1 to 7 take about 1 minute 50 seconds at a calm pace, which fits the 0:40 to 2:30 window in
`docs/PITCH.md`.
