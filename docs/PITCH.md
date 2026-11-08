# Sherlock: 3-minute video script

Judges are Ramp engineers. Every customs term gets a one-clause gloss the first time it appears. Read at a
normal pace; the timings assume about 150 words a minute. Screen directions are in brackets and follow
`docs/DEMO_PATH.md` step numbers.

## 0:00 to 0:20. The problem

[Slide: one number, "$2,176,339.01", under the words "Tariff refund received".]

A company imports goods and pays tariffs on every shipment. Months later the government decides some of
that money has to come back, and it arrives as one lump sum: one wire, one number, no breakdown. Someone in
finance now has to work out which shipment, which purchase order, which invoice, and which customer every
dollar belongs to. Today that is a spreadsheet, a week of matching, and the errors turn into customer
disputes, because many importers passed the tariff on to customers as a surcharge, and whether a customer
is owed a share depends on what their contract says.

## 0:20 to 0:40. Why now

[Slide: timeline 2024 to 2026 with "exclusion refunds", "reliquidations", "court-ordered refunds".]

This used to be rare. In 2025 and 2026 it is not: broad tariffs were imposed, challenged in court, and in
several cases reversed, and every reversal turns into refund notices covering thousands of customs entries
at once. [Optional: one sourced figure on refund volume, cited on screen.] Finance teams that never had to
allocate a refund now have to do it correctly, with an audit trail, under deadline. That is the workflow
Sherlock automates.

## 0:40 to 2:30. The live path

[Screen recording. Follow DEMO_PATH steps 1 to 7.]

**0:40. Overview.** This is the refund, reconciled. Sherlock read the refund notice, two hundred shipments,
their purchase orders and invoices, and ten customer contracts. Every dollar is either allocated to a
customer with evidence, or sitting in an unallocated line with a reason, and the two always add back to the
total. That line at the top, "conservation holds", is a hard invariant: the system refuses to force a
match and it refuses to lose a cent.

**0:55. One evidence chain.** Pick any line. Here is the refund entry, the shipment row, the PO row and the
invoice row it came from, each cited to the file and the row number, with the engine's reasoning in plain
language and a confidence score. This is what an auditor asks for, and it is already written.

**1:10. The review queue.** Anything below the confidence threshold, or where documents disagree, is not
allocated. It waits here for a person. This shipment has no PO number on it, and two purchase orders from
the same supplier add up to its quantity exactly. They belong to different customers. Sherlock proposes a
split, shows all three documents side by side, and does nothing until a human decides.

**1:30. The scanned invoice.** This one is the point of the whole project. The shipment matched a PO, but
the invoice was never entered in the books. The engine found the gap. In the scans folder there is a paper
invoice, a skewed, grainy image with no text layer. Claude read it: invoice number, PO number, total,
tariff surcharge, each with a confidence and where on the page it came from. Sherlock did not create the
invoice. It attached the reading to the queued line as a proposal. I type why I agree and approve. Now the
invoice record exists, the allocation is confirmed, the ledger moved, and the decision is logged with my
name, the time and my reason.

**2:00. The vague clause.** Contracts are where the legal exposure lives. This customer's contract says the
seller "may, at its reasonable discretion, adjust prices" for tariff changes and will "discuss" reductions
"in good faith". Does that mean they are owed part of the refund? Claude's answer is: unclear, low
confidence, and here is why. Sherlock leaves it pending. Nothing about a customer's money is ever decided
by the model.

**2:15. Memo and export.** The audit memo regenerates from the reviewed ledger: the reconciliation, the
method, every flagged item and how it was resolved, the decision log with my approval in it, and every
line's evidence. The journal entry export is the same ledger as a balanced CSV, debits equal credits, every
line tagged with its review status and decision id.

## 2:30 to 2:45. Where it lives in Ramp's world

[Slide: three boxes. "Cash in" -> "Close entry" -> "Money owed back".]

In accounting terms the whole workflow is three things. The refund is cash in. The journal export is the
close entry: the file an accounting sync would consume, Ramp, NetSuite or QuickBooks, to book the refund
against the right customers and leave the unexplained part in a visible suspense line. The payables export
is the customer money owed back under the contracts a human confirmed: one row per obligation, with the
clause citation and the decision behind it, shaped for a bill-pay import. Sherlock writes both files and
posts nothing; the decisions stay with the people who are accountable for them.

## 2:45 to 3:00. Close

[Slide: repo URL and "make demo".]

Sherlock is one command to run, works with no API key from a committed model-output cache, keeps money as
integer cents end to end, and never lets a dollar vanish or a model decide what a customer is owed. The
engineering is boring on purpose. The AI is used where only it works: reading documents that no rule can
read. Thanks.
