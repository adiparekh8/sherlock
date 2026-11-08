#!/usr/bin/env python
"""Generate the synthetic_v1 dataset: one mid-size importer, one lump tariff refund.

Deterministic for a given --seed. Output layout matches docs/DATA_CONTRACT.md:

    <out>/refund.json
    <out>/shipments.csv
    <out>/purchase_orders.csv
    <out>/invoices.csv
    <out>/contracts/*.pdf
    <out>/manifest.json

Planted hard cases (recorded in manifest.json so tests can assert on them):
  1. split_po         one shipment whose quantity is covered by two POs, no PO number on the shipment
  2. vague_surcharge  a customer contract whose tariff clause is discretionary and ambiguous
  3. missing_invoice  a PO that was shipped and entered but never invoiced
Plus smaller deliberate mismatches (quantity drift, dangling PO numbers, an entry on the refund with
no shipment) so the review queue and the unallocated line both have content.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

IMPORTER = "Pacific Crest Imports LLC"
IMPORTER_ADDR = "4120 Harbor Way, Suite 300, Tacoma, WA 98421"
DUTY_RATE_BPS = 2500  # 25.00% Section 301 rate on every product here

CUSTOMERS = [
    ("CUST-001", "Northwind Hardware Co."),
    ("CUST-002", "Ridgeline Outfitters Inc."),
    ("CUST-003", "Harbor & Vale Supply LLC"),
    ("CUST-004", "Meridian Building Products"),
    ("CUST-005", "Summit Lighting Group"),
    ("CUST-006", "Bluegrass Distribution Partners"),
    ("CUST-007", "Cascade Electric Wholesale"),
    ("CUST-008", "Pioneer Fabrication Works"),
    ("CUST-009", "Keystone Marine Supply Co."),
    ("CUST-010", "Alder & Finch Distributors"),
]
CUSTOMER_WEIGHTS = [22, 14, 16, 10, 12, 9, 11, 6, 9, 8]

# Customers whose contracts passed the tariff through as a surcharge on invoices.
PASSES_SURCHARGE = {"CUST-001", "CUST-002", "CUST-003", "CUST-005", "CUST-006", "CUST-007", "CUST-009", "CUST-010"}

SUPPLIERS = [
    "Shenzhen Brightway Manufacturing Co., Ltd.",
    "Ningbo Hualong Metal Products Co.",
    "Guangzhou Everfine Lighting Technology",
    "Qingdao Marine Fittings Co., Ltd.",
    "Dongguan Precision Motor Works",
    "Foshan Kaiyuan Plastics Industry",
]

# (description, hts_code, supplier indexes, unit cost cents range)
PRODUCTS = [
    ("Stainless steel kitchen sinks, undermount", "7324.10.0010", [1], (4500, 9000)),
    ("LED ceiling fixtures, 4000K, 40W", "9405.11.4010", [2], (1800, 3600)),
    ("Single-phase AC electric motors, 1/2 HP", "8501.40.4040", [4], (3200, 6100)),
    ("Threaded steel pipe fittings, 1-inch", "7307.19.3085", [1, 3], (180, 420)),
    ("Polypropylene storage bins, 60L", "3924.90.5650", [5], (600, 1200)),
    ("Bicycle crank sets, alloy", "8714.96.1000", [0], (1500, 2800)),
    ("Industrial axial fans, 24-inch", "8414.59.6590", [4], (5200, 9800)),
    ("Molded case circuit breakers, 100A", "8536.20.0020", [0, 4], (2400, 4100)),
    ("Rotary vane vacuum pumps", "8414.10.0000", [4], (11000, 19000)),
    ("Adjustable wrench sets, chrome vanadium", "8205.59.5560", [0], (900, 1700)),
    ("Marine-grade stainless cleats and hinges", "7326.90.8688", [3], (700, 1500)),
    ("Commercial pendant lights, brushed nickel", "9405.10.6020", [2], (2600, 4800)),
]


@dataclass
class Shipment:
    shipment_id: str
    entry_number: str
    bill_of_lading: str
    ship_date: str
    arrival_date: str
    supplier: str
    description: str
    hts_code: str
    quantity: int
    declared_value_cents: int
    duty_paid_cents: int
    po_number: str


@dataclass
class PurchaseOrder:
    po_number: str
    customer_id: str
    customer_name: str
    supplier: str
    order_date: str
    description: str
    quantity: int
    unit_price_cents: int
    total_cents: int


@dataclass
class Invoice:
    invoice_number: str
    po_number: str
    customer_id: str
    invoice_date: str
    amount_cents: int
    tariff_surcharge_cents: int


def iso(d: date) -> str:
    return d.isoformat()


# --------------------------------------------------------------------------- contracts

COMMON_SECTIONS_BEFORE = [
    ("1. Scope", "Seller agrees to sell and Buyer agrees to purchase the products described in each purchase order "
                 "issued by Buyer and accepted by Seller (each, an \"Order\") on the terms of this Agreement. "
                 "Each Order shall identify the products, quantities, unit prices, and requested delivery dates."),
    ("2. Term", "This Agreement commences on the Effective Date and continues for an initial term of two (2) years, "
                "renewing automatically for successive one-year periods unless either party gives ninety (90) days "
                "written notice of non-renewal."),
    ("3. Pricing", "Unit prices are as stated in the applicable Order or in Seller's then-current price list. "
                   "Prices are quoted in U.S. dollars, FOB Seller's Tacoma, Washington warehouse, exclusive of "
                   "freight, insurance, and applicable sales taxes unless otherwise stated."),
]
COMMON_SECTIONS_AFTER = [
    ("5. Payment", "Buyer shall pay each invoice in full within thirty (30) days of the invoice date. Late amounts "
                   "accrue interest at one percent (1%) per month or the maximum rate permitted by law, whichever is "
                   "less. Buyer may not set off disputed amounts without Seller's written consent."),
    ("6. Delivery and Risk of Loss", "Seller shall use commercially reasonable efforts to meet requested delivery "
                                     "dates. Title and risk of loss pass to Buyer upon delivery to the carrier at "
                                     "Seller's warehouse."),
    ("7. Warranty", "Seller warrants that products will conform to their published specifications for twelve (12) "
                    "months from delivery. Seller's sole obligation under this warranty is repair, replacement, or "
                    "credit at Seller's option."),
    ("8. Limitation of Liability", "Neither party shall be liable for indirect, incidental, or consequential damages. "
                                   "Seller's aggregate liability under this Agreement shall not exceed the amounts "
                                   "paid by Buyer in the twelve months preceding the claim."),
    ("9. Governing Law", "This Agreement is governed by the laws of the State of Washington without regard to its "
                         "conflict of laws rules. The parties submit to the exclusive jurisdiction of the state and "
                         "federal courts located in Pierce County, Washington."),
    ("10. Entire Agreement", "This Agreement, together with each accepted Order, is the entire agreement between the "
                             "parties regarding its subject matter and supersedes all prior proposals and "
                             "understandings. Amendments must be in writing and signed by both parties."),
]

# Section 4 per customer: (heading, text, kind). "kind" is only used to write the manifest; the
# system never sees it.
TARIFF_CLAUSES = {
    "CUST-001": ("4. Duties, Tariffs, and Refunds",
        "Prices under this Agreement exclude customs duties and tariffs. Seller shall itemize on each invoice, as a "
        "separate line designated \"Tariff Surcharge\", the actual duties paid by Seller on the products in that "
        "shipment, and Buyer shall pay such surcharge together with the invoice. If Seller subsequently receives a "
        "refund, drawback, or other recovery of any duty that was invoiced to Buyer as a Tariff Surcharge, Seller "
        "shall pass through to Buyer the full amount of such refund attributable to Buyer's purchases, by credit "
        "memo or payment, within thirty (30) days of Seller's receipt of the refund.", "clear_refund_obligation"),
    "CUST-002": ("4. Tariff Surcharge",
        "Buyer acknowledges that the products are subject to additional duties under Section 301 of the Trade Act "
        "of 1974. Seller may add a tariff surcharge to each invoice equal to the duties actually paid on the "
        "products shipped. Buyer agrees that the surcharge is a pricing term and not a pass-through of a specific "
        "cost. Any subsequent reduction, exclusion, drawback, or refund of such duties shall be for Seller's "
        "account and retained by Seller, and Buyer waives any claim to such amounts.", "no_refund_obligation"),
    "CUST-003": ("4. Price Adjustments",
        "Seller may, at its reasonable discretion, adjust prices to reflect material changes in duties, tariffs, "
        "freight, or similar governmental charges affecting the products. Seller will notify Buyer of any such "
        "adjustment. The parties will cooperate in good faith with respect to any subsequent change in such "
        "charges, including any reduction, and will discuss appropriate adjustments to pricing at that time.",
        "vague"),
    "CUST-004": ("4. Taxes",
        "Buyer is responsible for all sales, use, and excise taxes arising from its purchases. Unit prices stated in "
        "each Order are firm for the term of the Order.", "no_tariff_language"),
    "CUST-005": ("4. Tariff Recovery Charge",
        "In addition to the unit price, Seller shall invoice a Tariff Recovery Charge equal to the duties assessed "
        "by U.S. Customs and Border Protection on the products delivered under the applicable Order. Should any "
        "portion of such duties later be refunded to Seller, whether through exclusion, reliquidation, or "
        "protest, Seller shall credit Buyer's account for the refunded portion attributable to Buyer's Orders "
        "within sixty (60) days after Seller's receipt of the refund. Credits shall be documented with reference to "
        "the affected invoices.", "clear_refund_obligation"),
    "CUST-006": ("4. Surcharges",
        "Seller reserves the right to apply a tariff surcharge to invoices for products subject to additional "
        "import duties, in an amount not to exceed the duties actually paid. The surcharge will be shown as a "
        "separate line on the invoice.", "surcharge_silent_on_refund"),
    "CUST-007": ("4. Changes in Duties",
        "If the duties, tariffs, or other governmental charges applicable to the products increase after the "
        "Effective Date, Buyer shall reimburse Seller for the increase as a separate invoice line. If such charges "
        "decrease, or if Seller receives a refund of charges previously reimbursed by Buyer, Seller shall "
        "reimburse Buyer for the decrease or refund, net of Seller's reasonable administrative costs not to exceed "
        "five percent (5%) of the amount recovered.", "refund_obligation_net_of_costs"),
    "CUST-008": ("4. Delivered Pricing",
        "All prices are delivered duty paid (DDP) to Buyer's designated facility and are inclusive of all customs "
        "duties, tariffs, brokerage, and import fees. Seller bears the risk of any change in such charges for the "
        "term of each Order.", "ddp_no_passthrough"),
}

# Two contracts that do NOT follow the master-agreement template above. They exist to show why a
# rule-based reader is not enough: the tariff language is buried or split, and the structure differs.
OFF_TEMPLATE = {
    "CUST-009": {
        "kind": "buried_refund_obligation",
        "expect": {"refund_owed_to_customer": "yes", "clause_type": "refund_obligation"},
    },
    "CUST-010": {
        "kind": "split_refund_obligation",
        "expect": {"refund_owed_to_customer": "yes", "clause_type": "refund_obligation"},
    },
}

EFFECTIVE_DATES = {
    "CUST-001": date(2023, 3, 1), "CUST-002": date(2023, 7, 15), "CUST-003": date(2022, 11, 1),
    "CUST-004": date(2023, 1, 10), "CUST-005": date(2023, 9, 1), "CUST-006": date(2022, 6, 1),
    "CUST-007": date(2023, 5, 20), "CUST-008": date(2023, 2, 14), "CUST-009": date(2023, 8, 7),
    "CUST-010": date(2024, 1, 3),
}


def write_contract_pdf(path: Path, customer_id: str, customer_name: str) -> int:
    heading, clause, _ = TARIFF_CLAUSES[customer_id]
    eff = EFFECTIVE_DATES[customer_id]
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 20, 20)

    def para(text: str, size: int = 10, bold: bool = False, gap: int = 3) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(0, 5, text)
        pdf.ln(gap)

    pdf.add_page()
    para("MASTER SUPPLY AGREEMENT", 14, True, 4)
    para(f"This Master Supply Agreement (the \"Agreement\") is entered into as of {eff.strftime('%B %d, %Y')} "
         f"(the \"Effective Date\") between {IMPORTER}, a Washington limited liability company with offices at "
         f"{IMPORTER_ADDR} (\"Seller\"), and {customer_name} (\"Buyer\").", gap=4)
    para("RECITALS", 11, True)
    para("Seller imports and distributes industrial and consumer hardware products. Buyer wishes to purchase such "
         "products from Seller from time to time. The parties agree as follows.", gap=4)
    for h, t in COMMON_SECTIONS_BEFORE:
        para(h, 11, True, 1)
        para(t)
    # Section 4 always starts page 2 so the citation is stable across customers.
    pdf.add_page()
    para(heading, 11, True, 1)
    para(clause, gap=4)
    for h, t in COMMON_SECTIONS_AFTER:
        para(h, 11, True, 1)
        para(t)
    pdf.ln(6)
    para("IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.", gap=6)
    para(f"{IMPORTER}\n\nBy: ______________________\nName: Dana Whitfield\nTitle: Chief Financial Officer", gap=4)
    para(f"{customer_name}\n\nBy: ______________________\nName: ______________________\nTitle: Authorized Signatory")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return pdf.pages_count




def write_terms_sheet_pdf(path: Path, customer_name: str) -> int:
    """CUST-009: a one-column 'Terms and Conditions of Sale' sheet with lettered sub-clauses. The refund
    obligation sits inside a general Taxes and Duties clause and uses 'remit', not 'refund'."""
    eff = EFFECTIVE_DATES["CUST-009"]
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 6, f"{IMPORTER}\nSTANDARD TERMS AND CONDITIONS OF SALE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 4.5, f"Customer: {customer_name}    Account opened: {eff.isoformat()}    Rev. 4", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    clauses = [
        ("1. ACCEPTANCE.", "These terms govern every sale by Seller to Customer. Any additional or different terms in "
         "Customer's purchase order are rejected unless expressly accepted in writing by Seller's credit department."),
        ("2. PRICES.", "Prices are those in effect on the date of shipment unless a written quotation states otherwise. "
         "Quotations expire thirty (30) days from issue. Seller may correct clerical errors in any quotation or invoice."),
        ("3. PAYMENT.", "Net 30 days from invoice. Past-due balances bear a finance charge of 1.5% per month. Seller "
         "may suspend shipments while any balance is past due."),
        ("4. SHIPMENT.", "(a) Shipments are FOB Seller's warehouse, Tacoma, Washington. (b) Risk of loss passes to Customer "
         "on tender to the carrier. (c) Delivery dates are estimates and Seller is not liable for delay."),
        ("5. RETURNS.", "No returns without a return authorization number. Restocking charge 15%. Special-order items "
         "are not returnable."),
        ("6. WARRANTY.", "Seller passes through the manufacturer's warranty and makes no other warranty, express or "
         "implied, including merchantability or fitness for a particular purpose."),
        ("7. TAXES AND DUTIES.", "(a) Customer shall bear all sales, use, excise, value-added and similar taxes arising "
         "from the sale, other than taxes on Seller's net income. (b) Customs duties and tariffs assessed on imported "
         "goods are stated separately on Customer's invoice at Seller's actual cost and are payable with the invoice. "
         "(c) Should Seller later receive from any governmental authority a rebate, drawback or return of duties that "
         "were so stated on Customer's invoices, Seller shall remit the amount so received, less the direct costs of "
         "obtaining it, to Customer within forty-five (45) days of receipt, with a statement identifying the invoices "
         "concerned. (d) Customer shall provide resale or exemption certificates on request."),
        ("8. LIMITATION.", "Seller's liability for any claim shall not exceed the price of the goods giving rise to the "
         "claim. In no event is Seller liable for consequential or incidental damages."),
        ("9. GOVERNING LAW.", "Washington law governs. Venue lies exclusively in Pierce County, Washington."),
        ("10. ENTIRE AGREEMENT.", "These terms, the quotation and the invoice are the complete agreement."),
    ]
    for head, text in clauses:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 4.5, head, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.5, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return pdf.pages_count


def write_letter_agreement_pdf(path: Path, customer_name: str) -> int:
    """CUST-010: a letter agreement. The surcharge and the refund promise are two paragraphs apart, with
    unrelated text between them, and neither uses the words 'refund' or 'shall'."""
    eff = EFFECTIVE_DATES["CUST-010"]
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(24, 22, 24)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10.5)
    paras = [
        f"{IMPORTER}\n{IMPORTER_ADDR}\n\n{eff.strftime('%B %d, %Y')}\n\n{customer_name}\nAttn: Purchasing",
        f"Re: Supply arrangement for the 2024 program year",
        "Dear Purchasing Team,",
        "This letter confirms the terms on which we will supply product to you during the program year beginning "
        "January 1, 2024. Please countersign below and return a copy to us; your first purchase order will serve "
        "as acceptance if we do not receive the countersigned copy.",
        "Pricing for the program year is set out in the attached schedule and is firm for the year, except as "
        "described in the next paragraph. Our invoices to you will show, as a separately stated line, the Section "
        "301 duties we actually pay on the goods in each shipment, and that line is due together with the goods.",
        "Lead times are typically six to eight weeks from receipt of order. We will hold two weeks of your "
        "forecasted demand in our Tacoma warehouse at no charge; inventory beyond that is subject to a storage "
        "fee of $0.40 per cubic foot per month.",
        "Should the government later return to us any portion of the duties described above, whether through an "
        "exclusion, a reliquidation or a drawback claim, the amount returned that relates to goods you purchased "
        "will be credited against your next invoice, or paid to you if no invoice is outstanding, within sixty "
        "days of our receipt of it. We will send you a statement showing how the credit was computed.",
        "All other matters are governed by our standard terms of sale, a copy of which is attached. We value the "
        "relationship and look forward to a strong year.",
        "Sincerely,\n\n\n\nDana Whitfield\nChief Financial Officer\n\n\nAgreed and accepted:\n\n"
        f"______________________\nfor {customer_name}",
    ]
    for ptxt in paras:
        pdf.multi_cell(0, 5.5, ptxt, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return pdf.pages_count



def write_scanned_invoice(path: Path, invoice_number: str, po: "PurchaseOrder", invoice_date: str,
                          surcharge_cents: int, seed: int) -> dict:
    """An image-only PDF of an invoice: rendered as a bitmap, slightly rotated, noisy, no text layer.
    Deterministic for a given seed so the model-output cache keyed on the image bytes stays valid."""
    W, H = 1275, 1650  # letter at 150 dpi
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    big = ImageFont.load_default(size=34)
    h1 = ImageFont.load_default(size=26)
    body = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=16)
    total = po.total_cents + surcharge_cents
    d.text((90, 80), IMPORTER, font=big, fill=20)
    d.text((90, 125), IMPORTER_ADDR, font=small, fill=60)
    d.text((90, 150), "Tel (253) 555-0147  ·  AR dept: ar@pacificcrestimports.example", font=small, fill=60)
    d.text((900, 80), "INVOICE", font=big, fill=20)
    d.text((900, 130), f"No. {invoice_number}", font=h1, fill=20)
    d.text((900, 165), f"Date  {invoice_date}", font=body, fill=20)
    d.text((900, 195), f"Terms Net 30", font=body, fill=20)
    d.line((90, 240, W - 90, 240), fill=120, width=2)
    d.text((90, 265), "BILL TO", font=small, fill=90)
    d.text((90, 290), po.customer_name, font=h1, fill=20)
    d.text((90, 325), f"Customer no. {po.customer_id}", font=body, fill=20)
    d.text((700, 265), "YOUR PO", font=small, fill=90)
    d.text((700, 290), po.po_number, font=h1, fill=20)
    d.text((700, 325), f"Ordered {po.order_date}", font=body, fill=20)
    y = 420
    d.rectangle((90, y, W - 90, y + 40), fill=235)
    for x, label in ((100, "DESCRIPTION"), (720, "QTY"), (860, "UNIT PRICE"), (1060, "AMOUNT")):
        d.text((x, y + 10), label, font=small, fill=40)
    y += 60
    d.text((100, y), po.description, font=body, fill=20)
    d.text((720, y), f"{po.quantity:,}", font=body, fill=20)
    d.text((860, y), fmt_usd(po.unit_price_cents), font=body, fill=20)
    d.text((1060, y), fmt_usd(po.total_cents), font=body, fill=20)
    y += 36
    d.text((100, y), f"Country of origin: CN   HTS {po_hts(po)}", font=small, fill=90)
    y += 50
    d.text((100, y), "Tariff Surcharge - Section 301 duties paid on this shipment", font=body, fill=20)
    d.text((1060, y), fmt_usd(surcharge_cents), font=body, fill=20)
    y += 70
    d.line((700, y, W - 90, y), fill=120, width=2)
    y += 15
    d.text((860, y), "Subtotal", font=body, fill=20); d.text((1060, y), fmt_usd(po.total_cents), font=body, fill=20)
    y += 32
    d.text((860, y), "Surcharge", font=body, fill=20); d.text((1060, y), fmt_usd(surcharge_cents), font=body, fill=20)
    y += 32
    d.text((860, y), "Sales tax", font=body, fill=20); d.text((1060, y), "$0.00", font=body, fill=20)
    y += 40
    d.rectangle((840, y - 6, W - 90, y + 36), outline=20, width=2)
    d.text((860, y + 2), "TOTAL DUE", font=h1, fill=20); d.text((1060, y + 2), fmt_usd(total), font=h1, fill=20)
    y += 110
    d.text((90, y), "Remit to: Pacific Crest Imports LLC, PO Box 41118, Tacoma WA 98401. Please reference the invoice", font=small, fill=60)
    d.text((90, y + 22), "number on your payment. Duties shown are passed through at actual cost per your supply agreement.", font=small, fill=60)
    d.text((90, H - 120), "RECEIVED  AP  2024", font=h1, fill=110)
    d.rectangle((80, H - 135, 420, H - 80), outline=110, width=3)

    rng = np.random.default_rng(seed)
    img = img.rotate(0.8, resample=Image.BILINEAR, fillcolor=255, expand=False)
    arr = np.asarray(img, dtype=np.int16)
    arr = arr + rng.normal(0, 9, arr.shape).astype(np.int16) - 6  # grain and a slightly grey background
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.6))
    path.parent.mkdir(parents=True, exist_ok=True)
    jpg = path.with_suffix(".jpg")
    img.save(jpg, quality=72, optimize=True)
    pdf = FPDF(unit="pt", format="letter")
    pdf.set_creation_date(datetime(2024, 9, 11, 9, 0, 0))  # fixed so the file is byte-identical across runs
    pdf.add_page()
    pdf.image(str(jpg), x=0, y=0, w=612, h=792)
    pdf.output(str(path))
    jpg.unlink()
    return {"invoice_number": invoice_number, "po_number": po.po_number, "customer_id": po.customer_id,
            "invoice_date": invoice_date, "amount_cents": total, "tariff_surcharge_cents": surcharge_cents}


def fmt_usd(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def po_hts(po: "PurchaseOrder") -> str:
    for desc, hts, _, _ in PRODUCTS:
        if desc == po.description:
            return hts
    return ""

# --------------------------------------------------------------------------- generator


def generate(out: Path, seed: int = 42, n_shipments: int = 200) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    shipments: list[Shipment] = []
    scan_truth: dict = {}
    scan_file = ""
    pos: list[PurchaseOrder] = []
    invoices: list[Invoice] = []
    mismatches: list[dict] = []
    customer_name = dict(CUSTOMERS)

    # Fixed slots for planted cases (1-based shipment index).
    SPLIT_IDX = 57
    MISSING_INVOICE_IDX = 123
    QTY_DRIFT_SMALL = {12, 34, 71, 88, 102, 140, 155, 170, 188, 199}  # within tolerance
    QTY_DRIFT_LARGE = {19, 66, 131, 177}  # beyond tolerance -> review
    BLANK_PO_FUZZY = {8, 45, 93, 118, 162, 183}  # no po_number, unique fuzzy match
    PO_TYPO_FUZZY = {27, 149}  # po_number has a typo, fuzzy match rescues it
    PO_DANGLING = {104}  # po_number refers to nothing, no fuzzy match either
    INVOICE_AMOUNT_OFF = {15, 52, 97, 134, 176}  # invoice total disagrees with PO beyond tolerance
    PLANTED = ({SPLIT_IDX, MISSING_INVOICE_IDX} | QTY_DRIFT_SMALL | QTY_DRIFT_LARGE | BLANK_PO_FUZZY | PO_TYPO_FUZZY
               | PO_DANGLING | INVOICE_AMOUNT_OFF)
    NOT_ON_REFUND = set(rng.sample(range(1, n_shipments + 1), 28)) - PLANTED
    CONSOLIDATED_PAIRS = [(3, 4), (30, 31), (60, 61), (80, 81), (110, 111), (150, 151), (190, 191)]
    second_of_pair = {b: a for a, b in CONSOLIDATED_PAIRS}

    start = date(2024, 1, 8)
    entry_counter = 1000
    entry_for_shipment: dict[int, str] = {}

    for i in range(1, n_shipments + 1):
        prod_idx = rng.randrange(len(PRODUCTS))
        desc, hts, sup_idxs, cost_range = PRODUCTS[prod_idx]
        supplier = SUPPLIERS[rng.choice(sup_idxs)]
        cust_id = rng.choices([c for c, _ in CUSTOMERS], CUSTOMER_WEIGHTS)[0]
        qty = rng.randrange(80, 2400, 10)
        unit_cost = rng.randrange(*cost_range, 5)
        declared = qty * unit_cost
        duty = declared * DUTY_RATE_BPS // 10_000
        ship_date = start + timedelta(days=int((i - 1) * 1.7) + rng.randrange(0, 3))
        arrival = ship_date + timedelta(days=rng.randrange(18, 32))
        sid = f"SHP-{i:04d}"
        bol = f"MAEU{rng.randrange(100000000, 999999999)}"

        if i in second_of_pair:
            entry = entry_for_shipment[second_of_pair[i]]
        else:
            entry_counter += rng.randrange(1, 4)
            entry = f"ENT-24-{entry_counter:06d}"
        entry_for_shipment[i] = entry

        po_number = f"PO-24{i:04d}"
        unit_price = unit_cost * rng.choice([125, 130, 135, 140]) // 100
        order_date = ship_date - timedelta(days=rng.randrange(25, 60))

        if i == SPLIT_IDX:
            # Two POs from the same customer group cover one consolidated shipment. No PO on the shipment row.
            q_a = qty * 6 // 10 // 10 * 10
            q_b = qty - q_a
            cust_b = "CUST-005" if cust_id != "CUST-005" else "CUST-001"
            pos.append(PurchaseOrder(f"{po_number}A", cust_id, customer_name[cust_id], supplier, iso(order_date),
                                     desc, q_a, unit_price, q_a * unit_price))
            pos.append(PurchaseOrder(f"{po_number}B", cust_b, customer_name[cust_b], supplier,
                                     iso(order_date + timedelta(days=2)), desc, q_b, unit_price, q_b * unit_price))
            for p in pos[-2:]:
                invoices.append(_invoice(rng, p, arrival, duty * p.quantity // qty))
            shipments.append(Shipment(sid, entry, bol, iso(ship_date), iso(arrival), supplier, desc, hts, qty,
                                      declared, duty, ""))
            continue

        po_qty = qty
        if i in QTY_DRIFT_SMALL:
            po_qty = qty + rng.choice([-1, 1]) * max(1, qty * 3 // 100)  # 3%, inside the 5% tolerance
            mismatches.append({"kind": "quantity_drift_within_tolerance", "shipment_id": sid, "po_number": po_number})
        elif i in QTY_DRIFT_LARGE:
            po_qty = qty + rng.choice([-1, 1]) * max(50, qty * 22 // 100 // 10 * 10)
            mismatches.append({"kind": "quantity_drift_beyond_tolerance", "shipment_id": sid, "po_number": po_number,
                               "expect": "review_queue"})

        if i in PO_DANGLING:
            # The shipment points at a PO that was never entered; no PO or invoice exists for it at all.
            shipments.append(Shipment(sid, entry, bol, iso(ship_date), iso(arrival), supplier, desc, hts, qty,
                                      declared, duty, "PO-23X9999"))
            mismatches.append({"kind": "dangling_po_number_no_match", "shipment_id": sid, "expect": "review_queue"})
            continue

        po = PurchaseOrder(po_number, cust_id, customer_name[cust_id], supplier, iso(order_date), desc, po_qty,
                           unit_price, po_qty * unit_price)
        pos.append(po)

        if i == MISSING_INVOICE_IDX:
            # Planted: never made it into invoices.csv. A paper copy exists as an image-only scan.
            scan_truth = write_scanned_invoice(out / "scans" / f"INV-{po_number[3:]}_scan.pdf", f"INV-{po_number[3:]}",
                                               po, iso(arrival + timedelta(days=10)), duty, seed)
            scan_file = f"scans/INV-{po_number[3:]}_scan.pdf"
        else:
            inv = _invoice(rng, po, arrival, duty)
            if i in INVOICE_AMOUNT_OFF:
                inv.amount_cents = inv.amount_cents + rng.choice([-1, 1]) * (po.total_cents * 12 // 100)
                mismatches.append({"kind": "invoice_amount_disagrees_with_po", "shipment_id": sid,
                                   "invoice_number": inv.invoice_number})
            invoices.append(inv)

        ship_po = po_number
        if i in BLANK_PO_FUZZY:
            ship_po = ""
            mismatches.append({"kind": "blank_po_number_fuzzy_match", "shipment_id": sid, "po_number": po_number})
        elif i in PO_TYPO_FUZZY:
            ship_po = po_number.replace("240", "24O", 1)  # zero keyed as letter O: PO-24O0027
            mismatches.append({"kind": "po_number_typo_fuzzy_match", "shipment_id": sid, "po_number": po_number,
                               "expect": "review_queue"})

        shipments.append(Shipment(sid, entry, bol, iso(ship_date), iso(arrival), supplier, desc, hts, qty,
                                  declared, duty, ship_po))

    # Refund: one entry line per customs entry that CBP refunded. Full duty refunded on covered entries.
    entry_amounts: dict[str, int] = {}
    entry_dates: dict[str, str] = {}
    for idx, s in enumerate(shipments, start=1):
        if idx in NOT_ON_REFUND:
            continue
        entry_amounts[s.entry_number] = entry_amounts.get(s.entry_number, 0) + s.duty_paid_cents
        entry_dates.setdefault(s.entry_number, s.arrival_date)
    phantom_entry = "ENT-24-009999"
    entry_amounts[phantom_entry] = 412_000
    entry_dates[phantom_entry] = "2024-08-19"
    mismatches.append({"kind": "refund_entry_without_shipment", "entry_number": phantom_entry,
                       "expect": "unallocated"})
    entries = [{"entry_number": e, "amount_cents": a, "entry_date": entry_dates[e]}
               for e, a in sorted(entry_amounts.items())]
    refund_total = sum(e["amount_cents"] for e in entries)
    refund = {
        "refund_id": "CBP-REF-2025-0917",
        "importer": IMPORTER,
        "importer_of_record_number": "91-4472108",
        "amount_cents": refund_total,
        "received_date": "2025-09-17",
        "currency": "USD",
        "source": "U.S. Customs and Border Protection",
        "reference": "Section 301 exclusion reliquidation refund, ACH trace 2025091700431",
        "entries": entries,
    }

    # Contracts.
    contracts = []
    for cid, cname in CUSTOMERS:
        slug = cname.split()[0].lower().replace("&", "and")
        rel = f"contracts/{cid}_{slug}.pdf"
        if cid == "CUST-009":
            pages = write_terms_sheet_pdf(out / rel, cname)
        elif cid == "CUST-010":
            pages = write_letter_agreement_pdf(out / rel, cname)
        else:
            pages = write_contract_pdf(out / rel, cid, cname)
        kind = OFF_TEMPLATE[cid]["kind"] if cid in OFF_TEMPLATE else TARIFF_CLAUSES[cid][2]
        entry = {"file": rel, "customer_id": cid, "customer_name": cname, "pages": pages, "clause_kind": kind}
        if cid in OFF_TEMPLATE:
            entry["off_template"] = True
            entry["expect"] = OFF_TEMPLATE[cid]["expect"]
        contracts.append(entry)

    _write_csv(out / "shipments.csv", shipments)
    _write_csv(out / "purchase_orders.csv", pos)
    _write_csv(out / "invoices.csv", invoices)
    (out / "refund.json").write_text(json.dumps(refund, indent=2) + "\n")

    split = shipments[SPLIT_IDX - 1]
    manifest = {
        "dataset": out.name,
        "generator": "scripts/make_synthetic.py",
        "seed": seed,
        "importer": IMPORTER,
        "files": {
            "refund": "refund.json",
            "shipments": "shipments.csv",
            "purchase_orders": "purchase_orders.csv",
            "invoices": "invoices.csv",
            "contracts_dir": "contracts",
            "scans_dir": "scans",
        },
        "contracts": contracts,
        "scans": [{"file": scan_file, "hint": "invoice", "pages": 1}] if scan_file else [],
        "hard_cases": [
            {
                "id": "split_po",
                "kind": "shipment_split_across_pos",
                "shipment_id": split.shipment_id,
                "entry_number": split.entry_number,
                "po_numbers": [f"PO-24{SPLIT_IDX:04d}A", f"PO-24{SPLIT_IDX:04d}B"],
                "expect": "review_queue",
                "description": "Shipment has no PO number; two POs from the same supplier for the same product "
                               "have quantities that sum to the shipment quantity.",
            },
            {
                "id": "vague_surcharge",
                "kind": "vague_surcharge_clause",
                "customer_id": "CUST-003",
                "contract_file": next(c["file"] for c in contracts if c["customer_id"] == "CUST-003"),
                "page": 2,
                "expect": "pending_review",
                "description": "Clause lets Seller adjust prices 'at its reasonable discretion' and promises only "
                               "good-faith discussion of reductions. Whether a refund is owed is not decidable "
                               "from the text.",
            },
            {
                "id": "missing_invoice",
                "kind": "missing_invoice",
                "shipment_id": f"SHP-{MISSING_INVOICE_IDX:04d}",
                "po_number": f"PO-24{MISSING_INVOICE_IDX:04d}",
                "expect": "review_queue",
                "description": "Shipment and PO match cleanly but no invoice exists in invoices.csv. A scanned "
                               "paper invoice for the PO sits in scans/; only the model can read it, and only a "
                               "human can turn it into an invoice record.",
                "scan_file": scan_file,
                "scan_truth": scan_truth,
            },
        ],
        "other_mismatches": mismatches,
        "counts": {
            "shipments": len(shipments),
            "purchase_orders": len(pos),
            "invoices": len(invoices),
            "refund_entries": len(entries),
            "refund_amount_cents": refund_total,
            "shipments_not_on_refund": len(NOT_ON_REFUND),
            "contracts": len(contracts),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _invoice(rng: random.Random, po: PurchaseOrder, arrival: date, duty_for_po: int) -> Invoice:
    surcharge = duty_for_po if po.customer_id in PASSES_SURCHARGE else 0
    return Invoice(
        invoice_number=f"INV-{po.po_number[3:]}",
        po_number=po.po_number,
        customer_id=po.customer_id,
        invoice_date=iso(arrival + timedelta(days=rng.randrange(4, 21))),
        amount_cents=po.total_cents + surcharge,
        tariff_surcharge_cents=surcharge,
    )


def _write_csv(path: Path, rows: list) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("data/synthetic_v1"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--shipments", type=int, default=200)
    args = ap.parse_args()
    m = generate(args.out, args.seed, args.shipments)
    c = m["counts"]
    print(f"wrote {args.out}: {c['shipments']} shipments, {c['purchase_orders']} POs, {c['invoices']} invoices, "
          f"{c['refund_entries']} refund entries, refund ${c['refund_amount_cents'] / 100:,.2f}, "
          f"{c['contracts']} contracts")


if __name__ == "__main__":
    main()
