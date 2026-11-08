# Demo path

The exact click sequence for the video and the live final. Rehearse it; do not improvise on the day.

## Before you start

```
cp .env.example .env            # once; add SHERLOCK_DEMO_ACTOR=adi so decision buttons are live immediately
make demo                       # DB + seed + console and API at http://localhost:8000
```

Open http://localhost:8000. If a previous rehearsal left decisions in the ledger, open **Overview** and press
**Reset demo**; it re-seeds the current dataset in a few seconds. Pages are hash links: `#overview`,
`#ledger`, `#review`, `#memo`, `#export`. The top bar (refund, allocated, unallocated, BALANCED pill) stays
visible on every page; point at it whenever a number changes.

## 1. Overview: the reconciliation

- **Page:** Overview (the landing page).
- **Element:** the six tiles: refund received, auto-proposed with evidence, human-confirmed or overridden,
  unallocated with a reason, conservation, waiting for a human.
- **Notice:** "Conservation: Holds" and the BALANCED pill in the top bar. Say the equation out loud: refund =
  allocated + unallocated. Point at "Human-confirmed or overridden $0.00": nothing has been touched yet.
- **Element:** "Unallocated by reason". Every unallocated dollar has a reason: low_confidence,
  ambiguous_po_split, po_not_found, missing_invoice, no_shipment_for_entry.

## 2. Ledger: one evidence chain, drilled to the row

- **Page:** Ledger. Leave the filters alone. Click line **#1** (SHP-0001).
- **Notice:** the drill-down card: the evidence chain REFUND -> ENTRY -> SHP-0001 -> PO-240001 -> INV-240001 ->
  CUST-xxx as chips; the engine's reasoning; the evidence list citing `refund.json entries[..]`,
  `shipments.csv row 2`, `purchase_orders.csv row 2`, `invoices.csv row 2`.
- **Action:** click the **PO-240001** chip; the source-document tab switches to that PO row.
- **Say:** "This is what an auditor asks for, and it is already written."

## 3. Review queue: the split PO

- **Page:** Review Queue. The reviewer name in the sidebar is prefilled from SHERLOCK_DEMO_ACTOR.
- **Element:** the item for **SHP-0057** (reason `ambiguous_po_split`).
- **Notice:** "// WHY THIS IS FLAGGED"; "Engine proposal" with two lines to two different customers; the
  "Conflicting documents" tabs: shipments.csv (po_number blank and quantity highlighted), **PO-240057A** qty
  730, **PO-240057B** qty 500. The evidence chain shows PO ?, INV ?, Customer ? as dashed chips.
- **Say:** "730 plus 500 is 1,230. Sherlock proposes the split and does nothing until a person decides."
  Do **not** decide this one.

## 4. Review queue: the scanned invoice, approved live

- **Element:** the item for **SHP-0123** (reason `missing_invoice`).
- **Notice:** the **Scan** tab: the page image (skewed, grainy, no text layer) beside the extracted fields with
  confidences and where on the page each was read: INV-240123, PO-240123, total $75,036.07, surcharge
  $12,103.87. The proposal line reads "INV-240123 (from scan)" and the reasoning ends with "Approving creates
  that invoice record; it is not created automatically." The INV chip in the chain is dashed amber: proposed.
- **Action:** press **Approve proposal**, type a reason ("Scan matches PO quantity and the AP received
  stamp"), press **Confirm**.
- **Notice:** the item leaves the queue; the top bar moves: allocated up by $12,103.87, unallocated down by
  the same, still BALANCED; the sidebar queue count drops to 9.
- **Say:** "The engine found the gap, the AI read the scan, the human confirmed, the books changed."

## 5. Review queue: the vague clause, left pending

- **Element:** under "Contract clauses", the item for **CUST-003 Harbor & Vale Supply LLC**.
- **Notice:** the contract page with the clause highlighted in amber; "unclear", strength "ambiguous",
  confidence 0.35 in red; the model's reasoning: price adjustments at Seller's discretion, only good-faith
  discussion of reductions. The "What was billed" tab lists the surcharge invoices behind the draft amount.
- **Action:** none. Leave it pending.
- **Say:** "Nothing about a customer's money is ever decided by the model."

## 6. Memo: regenerated with the decision in it

- **Page:** Memo.
- **Notice:** section 1 Reconciliation ("Conservation holds: YES", human-confirmed now non-zero); section 2
  Method names the model that read the contracts and the committed cache; section 4 Flagged items: the
  SHP-0123 line reads "APPROVE by adi ... Created invoice INV-240123 ... from the scanned document the model
  read"; section 6 Decision log has one row with who, when, what changed, why.
- **Action:** press **Download .md** so the viewer sees it is a file.

## 7. Export: the close entry

- **Page:** Export.
- **Notice:** the tiles: journal lines, debits, credits, "Balanced". The first row is the cash debit for the
  full refund. Scroll to the row for **INV-240123**: status human_confirmed, decision 1.
- **Say:** "This is the file an accounting sync consumes. Sherlock posts nothing."
- **Element:** Payables: one row per human-confirmed customer obligation. Empty in this path because CUST-003
  was left pending; to show a row, confirm CUST-001 in step 5 first.

## 8. Reset for the next rehearsal

- **Page:** Overview. Press **Reset demo**. Confirm the queue count returns to 10 in the sidebar.

## Timing

Steps 1 to 7 take about 1 minute 50 seconds at a calm pace, which fits the 0:40 to 2:30 window in
`docs/PITCH.md`.
