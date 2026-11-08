/* Sherlock console. No framework: each page is a function that returns HTML for #main.
   Data access goes through api(); the mock below stands in until the API is wired. */

const PAGES = [
  ["overview", "Overview", "M3 3h18v18H3z M3 9h18 M9 21V9"],
  ["ledger", "Ledger", "M4 5h16 M4 12h16 M4 19h10"],
  ["review", "Review Queue", "M12 3l9 16H3z M12 10v4 M12 17h.01"],
  ["memo", "Memo", "M6 3h9l5 5v13H6z M14 3v6h6 M9 13h6 M9 17h6"],
  ["export", "Export", "M12 3v12 M7 10l5 5 5-5 M4 19h16"],
];

// --------------------------------------------------------------------------- helpers

function formatCents(cents) {
  if (cents === null || cents === undefined || cents === "") return "";
  const n = Number(cents);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const whole = Math.floor(abs / 100).toLocaleString("en-US");
  return `${sign}$${whole}.${String(abs % 100).padStart(2, "0")}`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const TONE = { auto_proposed: "auto", human_confirmed: "ok", human_overridden: "ok", unallocated: "bad", pending_review: "review", confirmed: "ok", rejected: "bad" };
function tone(s) { return TONE[s] || ""; }
function confTone(c, threshold = 0.8) { return c >= threshold ? "ok" : c >= 0.5 ? "review" : "bad"; }

function confidence(c) {
  const pct = Math.round((c || 0) * 100);
  return `<span class="conf ${confTone(c)}"><span class="bar"><i style="width:${pct}%"></i></span>${(c || 0).toFixed(2)}</span>`;
}
function status(s, cls) { return `<span class="status ${cls || tone(s)}">${esc(s)}</span>`; }
function eyebrow(text, style = "") { return `<span class="eyebrow" style="${style}">${esc(text)}</span>`; }
function card(inner, cls = "") { return `<section class="card ${cls}"><i class="br"></i>${inner}</section>`; }
function progress(on) { document.getElementById("progress").className = on ? "on" : "done"; }

// --------------------------------------------------------------------------- shell

function renderNav(active, queueCount) {
  document.getElementById("nav").innerHTML = PAGES.map(([id, label, d]) =>
    `<a href="#${id}" class="${id === active ? "active" : ""}"><svg viewBox="0 0 24 24"><path d="${d}"/></svg><span>${label}</span>` +
    (id === "review" && queueCount ? `<em class="count">${queueCount}</em>` : "") + `</a>`).join("");
}

function renderTopbar(s) {
  const off = s.refund_cents - s.allocated_cents - s.unallocated_cents;
  const pill = off === 0 ? `<span class="pill ok">Balanced</span>` : `<span class="pill bad">Off by ${formatCents(Math.abs(off))}</span>`;
  document.getElementById("topbar").innerHTML = `
    <div class="stat money"><span>Refund</span><b>${formatCents(s.refund_cents)}</b></div>
    <div class="stat"><span>Allocated</span><b>${formatCents(s.allocated_cents)}</b></div>
    <div class="stat"><span>Unallocated</span><b>${formatCents(s.unallocated_cents)}</b></div>
    <div class="stat"><span>Conservation</span>${pill}</div>
    <div class="spacer"></div>
    <div class="stat"><span>Refund id</span><b class="dim">${esc(s.refund_id)}</b></div>`;
}

// --------------------------------------------------------------------------- review queue

function chain(ev) {
  return `<div class="chain">` + ev.map((e, i) =>
    (i ? `<span class="arrow">-&gt;</span>` : "") +
    `<button class="chip ${e.missing ? "missing" : ""}" data-doc="${i}" title="${esc(e.source || "")} ${esc(e.locator || "")}">${esc(e.label)}</button>`).join("") + `</div>`;
}

function docTabs(docs, id) {
  const tabs = docs.map((d, i) => `<button class="${i === 0 ? "active" : ""}" data-tab="${id}-${i}">${esc(d.tab)}</button>`).join("");
  const panes = docs.map((d, i) => `<div class="doc" id="${id}-${i}" ${i ? 'style="display:none"' : ""}><div class="src"><span>${esc(d.source)} · ${esc(d.locator)}</span><span>${esc(d.kind)}</span></div>${d.body}</div>`).join("");
  return `<div class="tabs" data-tabs="${id}">${tabs}</div>${panes}`;
}

function rowDoc(fields, hits = []) {
  return `<div class="row">` + fields.map(([k, v]) => `<span>${esc(k)}</span><span class="${hits.includes(k) ? "hit" : ""}">${esc(v)}</span>`).join("") + `</div>`;
}

function queueItem(item) {
  const proposal = item.proposal.length
    ? `<div class="proposal">${item.proposal.map(l => `<div class="line"><span>${esc(l.customer_id)} · PO ${esc(l.po_number)}${l.invoice_number ? " · " + esc(l.invoice_number) : " · no invoice"}</span><span class="amt">${formatCents(l.amount_cents)}</span></div>`).join("")}</div>`
    : `<div class="empty">no proposal. approving records that this amount stays unallocated.</div>`;
  const lines = item.proposal.length ? item.proposal : [{ po_number: "", customer_id: "", invoice_number: "", amount_cents: item.amount_cents }];
  return card(`
    <div class="qhead">
      <span class="id">#${item.id}</span>
      <span class="title">${esc(item.title)}</span>
      ${status(item.unallocated_reason, "bad")}
      ${confidence(item.confidence)}
      <span class="amt">${formatCents(item.amount_cents)}</span>
    </div>
    <div class="split">
      <div>
        ${eyebrow("Why this is flagged")}
        <div class="why">${item.why}</div>
        ${eyebrow("Engine proposal", "margin-top:14px")}
        ${proposal}
      </div>
      <div>
        ${eyebrow("Conflicting documents")}
        ${docTabs(item.docs, "q" + item.id)}
      </div>
    </div>
    ${eyebrow("Evidence chain", "margin-top:16px")}
    ${chain(item.chain)}
    <div class="actions">
      <button class="btn primary" data-approve="${item.id}">Approve proposal</button>
      <button class="btn" data-override="${item.id}">Override</button>
      <button class="btn danger" data-reject="${item.id}">Leave unallocated</button>
      <span class="who">reviewer: <b>adi</b></span>
    </div>
    <div class="override" id="ov-${item.id}" style="display:none">
      <div class="lines">
        <span class="h">PO number</span><span class="h">Customer</span><span class="h">Invoice</span><span class="h">Amount (cents)</span><span></span>
        ${lines.map(l => `<input class="field-in" value="${esc(l.po_number)}"><input value="${esc(l.customer_id)}"><input value="${esc(l.invoice_number || "")}"><input class="mono" value="${l.amount_cents}"><button class="btn">x</button>`).join("")}
      </div>
      <div class="field"><label>Reason <span class="req">required</span></label><textarea placeholder="What did you see in the documents that the engine did not?"></textarea></div>
      <div class="btn-row"><button class="btn primary">Apply override</button><button class="btn" data-cancel="${item.id}">Cancel</button><span class="muted mono" style="font-size:11px">lines may total at most ${formatCents(item.amount_cents)}; the remainder stays unallocated as override_remainder</span></div>
    </div>`);
}

function obligationItem(o) {
  return card(`
    <div class="qhead">
      <span class="id">CLAUSE</span>
      <span class="title">${esc(o.customer_id)} ${esc(o.customer_name)}</span>
      ${status(o.status)}
      ${confidence(o.confidence)}
      <span class="amt">${formatCents(o.draft_amount_cents)} <span class="muted" style="font-size:11px">draft</span></span>
    </div>
    <div class="split">
      <div>
        ${eyebrow("Why this is flagged")}
        <div class="why"><b>${esc(o.clause_type)}</b> · ${esc(o.obligation_strength)} · refund owed: <b>${esc(o.refund_owed_to_customer)}</b>\n\n${esc(o.reasoning)}\n\n<span class="muted">${esc(o.draft_basis)}</span></div>
      </div>
      <div>
        ${eyebrow("Contract vs. what was billed")}
        ${docTabs(o.docs, "o" + o.id)}
      </div>
    </div>
    <div class="actions">
      <button class="btn primary" data-approve-ob="${o.id}">Confirm at draft</button>
      <button class="btn" data-override-ob="${o.id}">Override amount</button>
      <button class="btn danger" data-reject-ob="${o.id}">Nothing owed</button>
      <span class="who">status moves only by human decision</span>
    </div>`);
}

function pageReview(q) {
  return `
    ${eyebrow(`Review queue ${q.allocations.length + q.obligations.length} pending`)}
    <div class="page-head"><h1>Review queue</h1><div class="btn-row"><span class="pill review">${q.allocations.length} allocation lines</span><span class="pill review">${q.obligations.length} contract clauses</span></div></div>
    <p class="lede">Lines below the confidence threshold or with evidence that disagrees. Nothing here counts as allocated until a person decides; every decision is logged with who, when, what changed and why.</p>
    <div class="queue">${q.allocations.map(queueItem).join("")}${q.obligations.map(obligationItem).join("")}</div>`;
}

// --------------------------------------------------------------------------- events

document.addEventListener("click", e => {
  const t = e.target.closest("[data-tab]");
  if (t) {
    const group = t.dataset.tab.replace(/-\d+$/, "");
    document.querySelectorAll(`[data-tabs="${group}"] button`).forEach(b => b.classList.toggle("active", b === t));
    document.querySelectorAll(`[id^="${group}-"]`).forEach(p => (p.style.display = p.id === t.dataset.tab ? "" : "none"));
  }
  const ov = e.target.closest("[data-override]");
  if (ov) document.getElementById("ov-" + ov.dataset.override).style.display = "";
  const cancel = e.target.closest("[data-cancel]");
  if (cancel) document.getElementById("ov-" + cancel.dataset.cancel).style.display = "none";
  const chip = e.target.closest(".chip");
  if (chip) {
    const tabs = chip.closest(".card").querySelector(".tabs");
    const i = Math.min(Number(chip.dataset.doc), tabs.children.length - 1);
    tabs.children[i].click();
    chip.closest(".card").querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c === chip));
  }
});

// --------------------------------------------------------------------------- mock data (static mockup only)

const MOCK = {
  summary: { refund_id: "CBP-REF-2025-0917", refund_cents: 217633901, allocated_cents: 206811015, unallocated_cents: 10822886 },
  queue: {
    allocations: [{
      id: 49, title: "SHP-0057 · entry ENT-24-001117", unallocated_reason: "ambiguous_po_split", confidence: 0.55, amount_cents: 890525,
      why: `Entry <b>ENT-24-001117</b> refunded <span class="amt">$8,905.25</span>; single shipment SHP-0057.\n\nNo PO number on the shipment and no single PO matches its quantity of 1,230, but <b>PO-240057A</b> (qty 730) and <b>PO-240057B</b> (qty 500) together do. They belong to different customers, so the split is proposed, not applied.\n\nConfidence 0.55 is below the 0.80 threshold.`,
      proposal: [{ customer_id: "CUST-004", po_number: "PO-240057A", invoice_number: "INV-240057A", amount_cents: 528523 },
                 { customer_id: "CUST-005", po_number: "PO-240057B", invoice_number: "INV-240057B", amount_cents: 362002 }],
      docs: [
        { tab: "shipments.csv", source: "shipments.csv", locator: "row 58", kind: "shipment", body: rowDoc([["shipment_id", "SHP-0057"], ["entry_number", "ENT-24-001117"], ["supplier", "Shenzhen Brightway Manufacturing Co., Ltd."], ["description", "Bicycle crank sets, alloy"], ["quantity", "1,230"], ["duty_paid", "$8,905.25"], ["po_number", "(blank)"]], ["po_number", "quantity"]) },
        { tab: "PO-240057A", source: "purchase_orders.csv", locator: "row 58", kind: "purchase order", body: rowDoc([["po_number", "PO-240057A"], ["customer", "CUST-004 Meridian Building Products"], ["supplier", "Shenzhen Brightway Manufacturing Co., Ltd."], ["description", "Bicycle crank sets, alloy"], ["quantity", "730"], ["total", "$17,520.00"], ["ordered", "2024-03-02"]], ["quantity"]) },
        { tab: "PO-240057B", source: "purchase_orders.csv", locator: "row 59", kind: "purchase order", body: rowDoc([["po_number", "PO-240057B"], ["customer", "CUST-005 Summit Lighting Group"], ["supplier", "Shenzhen Brightway Manufacturing Co., Ltd."], ["description", "Bicycle crank sets, alloy"], ["quantity", "500"], ["total", "$12,000.00"], ["ordered", "2024-03-04"]], ["quantity"]) },
      ],
      chain: [{ label: "Refund", source: "refund.json", locator: "entries[46]" }, { label: "Entry ENT-24-001117", source: "refund.json", locator: "entries[46]" }, { label: "SHP-0057", source: "shipments.csv", locator: "row 58" }, { label: "PO ?", missing: true }, { label: "INV ?", missing: true }, { label: "Customer ?", missing: true }],
    }, {
      id: 111, title: "SHP-0123 · entry ENT-24-001244", unallocated_reason: "missing_invoice", confidence: 0.59, amount_cents: 1210387,
      why: `Entry <b>ENT-24-001244</b> refunded <span class="amt">$12,103.87</span>; single shipment SHP-0123.\n\nShipment carries PO number <b>PO-240123</b>; quantities match. No invoice references PO-240123. The customer (CUST-002) is known from the PO but was never billed, so it is unclear whether any tariff was passed through.`,
      proposal: [{ customer_id: "CUST-002", po_number: "PO-240123", invoice_number: null, amount_cents: 1210387 }],
      docs: [
        { tab: "shipments.csv", source: "shipments.csv", locator: "row 124", kind: "shipment", body: rowDoc([["shipment_id", "SHP-0123"], ["entry_number", "ENT-24-001244"], ["quantity", "840"], ["duty_paid", "$12,103.87"], ["po_number", "PO-240123"]], ["po_number"]) },
        { tab: "PO-240123", source: "purchase_orders.csv", locator: "row 124", kind: "purchase order", body: rowDoc([["po_number", "PO-240123"], ["customer", "CUST-002 Ridgeline Outfitters Inc."], ["quantity", "840"], ["total", "$46,872.00"]], ["po_number"]) },
        { tab: "invoices.csv", source: "invoices.csv", locator: "no row", kind: "invoice", body: `<span class="muted">no invoice references PO-240123 (199 invoices scanned)</span>` },
      ],
      chain: [{ label: "Refund" }, { label: "Entry ENT-24-001244" }, { label: "SHP-0123" }, { label: "PO-240123" }, { label: "INV ?", missing: true }, { label: "CUST-002" }],
    }],
    obligations: [{
      id: 3, customer_id: "CUST-003", customer_name: "Harbor & Vale Supply LLC", status: "pending_review", confidence: 0.35, draft_amount_cents: 29215072,
      clause_type: "surcharge_passthrough", obligation_strength: "ambiguous", refund_owed_to_customer: "unclear",
      reasoning: "Price adjustments are at Seller's discretion and the clause promises only good-faith discussion of reductions. The text does not decide whether a refund share is owed.",
      draft_basis: "Sum over 28 allocated ledger lines to this customer whose invoice carried a tariff surcharge, each capped at the surcharge billed. Recomputed from the live ledger.",
      docs: [
        { tab: "Contract p.2", source: "contracts/CUST-003_harbor.pdf", locator: "page 2", kind: "contract", body: `3. Pricing\nUnit prices are as stated in the applicable Order or in Seller's then-current price list. Prices are quoted in U.S. dollars, FOB Seller's Tacoma, Washington warehouse, exclusive of freight, insurance, and applicable sales taxes unless otherwise stated.\n\n<mark>4. Price Adjustments\nSeller may, at its reasonable discretion, adjust prices to reflect material changes in duties, tariffs, freight, or similar governmental charges affecting the products. Seller will notify Buyer of any such adjustment. The parties will cooperate in good faith with respect to any subsequent change in such charges, including any reduction, and will discuss appropriate adjustments to pricing at that time.</mark>\n\n5. Payment\nBuyer shall pay each invoice in full within thirty (30) days of the invoice date.` },
        { tab: "Surcharge invoices", source: "invoices.csv", locator: "28 rows", kind: "invoices", body: rowDoc([["INV-240015", "surcharge $4,462.50 · allocated $4,462.50 (ledger #13)"], ["INV-240021", "surcharge $8,137.50 · allocated $8,137.50 (ledger #19)"], ["INV-240030", "surcharge $1,377.00 · allocated $1,377.00 (ledger #25)"], ["INV-240038", "surcharge $23,908.75 · allocated $23,908.75 (ledger #32)"], ["…", "24 more in the memo appendix"]]) },
      ],
    }],
  },
};

// --------------------------------------------------------------------------- boot (mockup)

function boot() {
  renderNav("review", MOCK.queue.allocations.length + MOCK.queue.obligations.length);
  renderTopbar(MOCK.summary);
  document.getElementById("dataset").innerHTML = `<option>synthetic_v1</option>`;
  document.getElementById("foot").textContent = "synthetic_v1 · 180 lines · stub reader";
  document.getElementById("main").innerHTML = pageReview(MOCK.queue);
}
boot();
