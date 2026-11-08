/* Sherlock console. No framework, no build step. Each page is a function that returns HTML for #main.
   All data comes from the API in sherlock/api/app.py; money arrives as integer cents and is formatted
   only here, by formatCents(). Status colors come only from review_status and the confidence threshold. */

const PAGES = [
  ["overview", "Overview", "M3 3h18v18H3z M3 9h18 M9 21V9"],
  ["ledger", "Ledger", "M4 5h16 M4 12h16 M4 19h10"],
  ["review", "Review Queue", "M12 3l9 16H3z M12 10v4 M12 17h.01"],
  ["memo", "Memo", "M6 3h9l5 5v13H6z M14 3v6h6 M9 13h6 M9 17h6"],
  ["export", "Export", "M12 3v12 M7 10l5 5 5-5 M4 19h16"],
];

const S = { page: "overview", datasets: [], loaded: null, summary: null, refund: null, threshold: 0.8, actor: "", queueCount: 0 };

// --------------------------------------------------------------------------- helpers

function formatCents(cents) {
  if (cents === null || cents === undefined || cents === "") return "";
  const n = Number(cents);
  if (!Number.isInteger(n)) return "";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}$${Math.floor(abs / 100).toLocaleString("en-US")}.${String(abs % 100).padStart(2, "0")}`;
}
function toDollarsInput(cents) { const n = Number(cents) || 0; return `${n < 0 ? "-" : ""}${Math.floor(Math.abs(n) / 100)}.${String(Math.abs(n) % 100).padStart(2, "0")}`; }
function toCents(text) {
  // "5,285.23" -> 528523. Null unless it is a dollar amount with at most two decimals. No floats anywhere.
  const t = String(text ?? "").replace(/[$,\s]/g, "");
  const m = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(t);
  if (!m) return null;
  const frac = (m[3] || "").padEnd(2, "0");
  return (m[1] ? -1 : 1) * (parseInt(m[2], 10) * 100 + parseInt(frac, 10));
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
const TONE = { auto_proposed: "auto", human_confirmed: "ok", human_overridden: "ok", unallocated: "bad", pending_review: "review", confirmed: "ok", rejected: "bad" };
function tone(s) { return TONE[s] || ""; }
function confTone(c) { return c >= S.threshold ? "ok" : c >= 0.5 ? "review" : "bad"; }
function confidence(c) { const v = Number(c) || 0; return `<span class="conf ${confTone(v)}"><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span>${v.toFixed(2)}</span>`; }
function status(s, cls) { return `<span class="status ${cls ?? tone(s)}">${esc(s)}</span>`; }
function eyebrow(text, style = "") { return `<span class="eyebrow" style="${style}">${esc(text)}</span>`; }
function card(inner, cls = "", attrs = "") { return `<section class="card ${cls}" ${attrs}><i class="br"></i>${inner}</section>`; }
function progress(on) { document.getElementById("progress").className = on ? "on" : "done"; }
function note(text, cls = "empty") { return `<div class="${cls}">${esc(text)}</div>`; }

let inflight = 0;
async function api(method, path, body) {
  inflight++; progress(true);
  try {
    const r = await fetch(path, { method, headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail ?? detail; } catch (_) { /* not json */ }
      throw new Error(`${method} ${path}: ${r.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    const ct = r.headers.get("content-type") || "";
    return ct.includes("application/json") ? r.json() : r.text();
  } finally {
    if (--inflight === 0) progress(false);
  }
}
const get = p => api("GET", p);
const post = (p, b) => api("POST", p, b || {});

function parseCsv(text) {
  const rows = []; let row = [], field = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; } else field += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  const [head, ...body] = rows;
  return body.filter(r => r.length === head.length).map(r => Object.fromEntries(head.map((h, i) => [h, r[i]])));
}

// --------------------------------------------------------------------------- shell

function renderNav() {
  document.getElementById("nav").innerHTML = PAGES.map(([id, label, d]) =>
    `<a href="#${id}" class="${id === S.page ? "active" : ""}"><svg viewBox="0 0 24 24"><path d="${d}"/></svg><span>${label}</span>` +
    (id === "review" && S.queueCount ? `<em class="count">${S.queueCount}</em>` : "") + `</a>`).join("");
}

function renderTopbar() {
  const el = document.getElementById("topbar");
  if (!S.summary) { el.innerHTML = `<div class="stat"><span>Dataset</span><b class="dim">none loaded</b></div>`; return; }
  const s = S.summary;
  const off = s.refund_cents - s.allocated_cents - s.unallocated_cents;
  const pill = off === 0 ? `<span class="pill ok">Balanced</span>` : `<span class="pill bad">Off by ${formatCents(Math.abs(off))}</span>`;
  el.innerHTML = `
    <div class="stat money"><span>Refund</span><b>${formatCents(s.refund_cents)}</b></div>
    <div class="stat"><span>Allocated</span><b>${formatCents(s.allocated_cents)}</b></div>
    <div class="stat"><span>Unallocated</span><b>${formatCents(s.unallocated_cents)}</b></div>
    <div class="stat"><span>Conservation</span>${pill}</div>
    <div class="spacer"></div>
    <div class="stat"><span>Refund id</span><b class="dim">${esc(s.refund_id)}</b></div>`;
}

function renderSidebar() {
  const sel = document.getElementById("dataset");
  sel.innerHTML = S.datasets.map(d => `<option value="${esc(d.name)}" ${d.loaded ? "selected" : ""}>${esc(d.name)}${d.loaded ? "" : " (not loaded)"}</option>`).join("")
    || `<option>no datasets under data/</option>`;
  document.getElementById("reviewer").value = S.actor;
  const d = S.datasets.find(x => x.loaded);
  document.getElementById("foot").textContent = d ? `${d.name} · ${d.counts.shipments} shipments · ${d.counts.contracts} contracts` : "load a dataset to begin";
}

async function refreshSummary() {
  const ds = await get("/datasets");
  S.datasets = ds.datasets; S.loaded = ds.loaded;
  if (S.loaded) {
    const r = await get("/refund");
    S.summary = r.summary; S.refund = r.refund; S.queueCount = r.summary.queue_count;
  } else { S.summary = null; S.refund = null; S.queueCount = 0; }
  renderSidebar(); renderTopbar(); renderNav();
}

// --------------------------------------------------------------------------- shared pieces

function statusRows(by) { return Object.entries(by).map(([k, v]) => `<tr><td>${status(k)}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join(""); }
function table(head, rows, cls = "") {
  return `<div class="tablewrap ${cls}"><table><thead><tr>${head.map(h => `<th class="${h.num ? "num" : ""}">${esc(h.label)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${head.length}" class="empty">nothing here</td></tr>`}</tbody></table></div>`;
}

function rowDoc(obj, keys, hits = []) {
  const money = k => k.endsWith("_cents");
  return `<div class="row">` + keys.filter(k => obj[k] !== undefined && obj[k] !== null).map(k =>
    `<span>${esc(k.replace(/_cents$/, ""))}</span><span class="${hits.includes(k) ? "hit" : ""}">${money(k) ? formatCents(obj[k]) : esc(obj[k] === "" ? "(blank)" : obj[k])}</span>`).join("") + `</div>`;
}
const SHIP_KEYS = ["shipment_id", "entry_number", "ship_date", "supplier", "description", "quantity", "duty_paid_cents", "po_number"];
const PO_KEYS = ["po_number", "customer_id", "supplier", "order_date", "description", "quantity", "unit_price_cents", "total_cents"];
const INV_KEYS = ["invoice_number", "po_number", "customer_id", "invoice_date", "amount_cents", "tariff_surcharge_cents"];

function docTabs(docs, id) {
  if (!docs.length) return note("no source documents");
  const tabs = docs.map((d, i) => `<button class="${i === 0 ? "active" : ""}" data-tab="${id}-${i}">${esc(d.tab)}</button>`).join("");
  const panes = docs.map((d, i) => `<div class="doc" id="${id}-${i}" ${i ? 'style="display:none"' : ""}><div class="src"><span>${esc(d.source)} · ${esc(d.locator)}</span><span>${esc(d.kind)}</span></div>${d.body}</div>`).join("");
  return `<div class="tabs" data-tabs="${id}">${tabs}</div>${panes}`;
}

async function allocationDocs(rec, detail) {
  const rel = detail.related || {};
  const hitsShip = rec.unallocated_reason === "ambiguous_po_split" || rec.match_method.includes("fuzzy") ? ["po_number", "quantity"] : ["po_number"];
  const docs = [];
  if (rel.shipment) docs.push({ tab: "shipments.csv", source: "shipments.csv", locator: `row ${rel.shipment.source_row}`, kind: "shipment", body: rowDoc(rel.shipment, SHIP_KEYS, hitsShip) });
  for (const po of rel.purchase_orders || []) docs.push({ tab: po.po_number, source: "purchase_orders.csv", locator: `row ${po.source_row}`, kind: "purchase order", body: rowDoc(po, PO_KEYS, ["quantity", "customer_id"]) });
  for (const inv of rel.invoices || []) docs.push({ tab: inv.invoice_number, source: "invoices.csv", locator: `row ${inv.source_row}`, kind: "invoice", body: rowDoc(inv, INV_KEYS, ["amount_cents", "tariff_surcharge_cents"]) });
  if (rec.unallocated_reason === "missing_invoice" && !(rel.invoices || []).length) {
    docs.push({ tab: "invoices.csv", source: "invoices.csv", locator: "no row", kind: "invoice", body: `<span class="muted">no invoice in invoices.csv references ${esc(rec.po_number)}</span>` });
  }
  const scan = (rec.evidence || []).find(e => e.entity === "scan");
  if (scan && scan.document_id) {
    const d = await get(`/documents/${scan.document_id}`);
    const fields = d.fields.filter(f => f.field_name !== "document_type");
    const notes = (d.fields.find(f => f.field_name === "document_type") || {}).quoted_text || "";
    const rows = fields.map(f => `<tr><td>${esc(f.field_name.replace(/_cents$/, ""))}</td><td class="num">${f.field_name.endsWith("_cents") && /^-?\d+$/.test(String(f.value_norm)) ? formatCents(Number(f.value_norm)) : esc(f.value_norm)}</td><td>${confidence(f.confidence)}</td><td class="dim">${esc(f.quoted_text)}</td></tr>`).join("");
    docs.push({ tab: "Scan", source: d.source_path, locator: "page 1", kind: "image-only scan, read by " + (d.extract_model || "model"), body:
      `<div class="scan"><img src="/documents/${d.id}/image" alt="scanned page"><div>${table([{ label: "field" }, { label: "value", num: true }, { label: "conf" }, { label: "where on the page" }], rows, "tight")}<div class="empty">${esc(notes)}</div><div class="empty">Approving the proposal creates this invoice record. Nothing is created until then.</div></div></div>` });
  }
  if (rel.refund_entry) docs.push({ tab: "refund.json", source: "refund.json", locator: `entries[${rel.refund_entry.row}]`, kind: "refund entry", body: rowDoc({ entry_number: rel.refund_entry.entry_number, amount_cents: rel.refund_entry.amount_cents, entry_date: rel.refund_entry.entry_date }, ["entry_number", "amount_cents", "entry_date"], ["entry_number"]) });
  return docs;
}

function chainFor(rec, detail) {
  const rel = detail.related || {};
  const prop = (rec.proposal && rec.proposal[0]) || {};
  const po = rec.po_number || prop.po_number;
  const inv = rec.invoice_number || prop.invoice_number;
  const cust = rec.customer_id || prop.customer_id;
  const hops = [
    { label: "Refund", kind: "refund.json" },
    { label: rel.refund_entry ? `Entry ${rel.refund_entry.entry_number}` : "Entry ?", kind: "refund.json", missing: !rel.refund_entry },
    { label: rec.shipment_id || "Shipment ?", kind: "shipments.csv", missing: !rec.shipment_id },
    { label: po || "PO ?", kind: po || "", missing: !po, proposed: !rec.po_number && !!prop.po_number },
    { label: inv || "INV ?", kind: inv || "", missing: !inv, proposed: !rec.invoice_number && !!prop.invoice_number },
    { label: cust || "Customer ?", kind: "", missing: !cust, proposed: !rec.customer_id && !!prop.customer_id },
  ];
  return `<div class="chain">` + hops.map((h, i) => (i ? `<span class="arrow">-&gt;</span>` : "") +
    `<button class="chip ${h.missing ? "missing" : ""} ${h.proposed ? "proposed" : ""}" data-kind="${esc(h.kind)}" title="${h.proposed ? "proposed by the engine, not yet confirmed" : h.missing ? "not found" : "open the source document"}">${esc(h.label)}</button>`).join("") + `</div>`;
}

function evidenceList(ev) {
  return (ev || []).map(e => `<div class="evrow"><span class="src">${esc(e.source)} · ${esc(e.locator)}</span><span>${esc(e.quoted_text)}</span></div>`).join("") || note("no evidence recorded");
}

// --------------------------------------------------------------------------- overview

async function pageOverview() {
  if (!S.loaded) return `${eyebrow("Overview")}<h1>No dataset loaded</h1>${datasetPanel()}`;
  const [manifest, led] = await Promise.all([get("/manifest"), get("/ledger")]);
  const s = led.summary;
  const auto = (s.by_status.auto_proposed || {}).cents || 0;
  const human = ((s.by_status.human_confirmed || {}).cents || 0) + ((s.by_status.human_overridden || {}).cents || 0);
  const tiles = [
    ["Refund received", formatCents(s.refund_cents), "money", `${S.refund.entries} customs entries · ${esc(S.refund.received_date)}`],
    ["Auto-proposed with evidence", formatCents(auto), "", `${(s.by_status.auto_proposed || {}).count || 0} lines at or above ${S.threshold.toFixed(2)} confidence`],
    ["Human-confirmed or overridden", formatCents(human), "", `${((s.by_status.human_confirmed || {}).count || 0) + ((s.by_status.human_overridden || {}).count || 0)} lines decided by a person`],
    ["Unallocated, each with a reason", formatCents(s.unallocated_cents), "", `${(s.by_status.unallocated || {}).count || 0} lines`],
    ["Conservation", s.conserved ? "Holds" : "Broken", s.conserved ? "ok" : "bad", "refund = allocated + unallocated"],
    ["Waiting for a human", String(s.queue_count), s.queue_count ? "warn" : "ok", "allocation lines in the review queue"],
  ].map(([l, v, cls, sub]) => card(`${eyebrow(l)}<b>${v}</b><small>${sub}</small>`, `tile ${cls}`)).join("");
  const reasons = Object.entries(s.by_reason).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join("");
  const customers = Object.entries(s.by_customer).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${esc(v.name)}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join("");
  const cases = (manifest.hard_cases || []).map(h => `<div class="evrow"><span class="src">${esc(h.id)} · expect ${esc(h.expect)}</span><span>${esc(h.description || "")}</span></div>`).join("");
  return `
    ${eyebrow(`Overview · ${S.loaded}`)}
    <div class="page-head"><h1>${esc(S.refund.importer)}</h1><span class="pill">${esc(S.refund.source || "refund")}</span></div>
    <p class="lede">The refund, reconciled. Allocated lines carry a customer, a confidence and an evidence chain. Unallocated lines carry a reason. The two always add back to the refund.</p>
    <div class="grid tiles">${tiles}</div>
    <div class="grid two" style="margin-top:16px">
      ${card(`${eyebrow("Unallocated by reason")}${table([{ label: "reason" }, { label: "lines", num: true }, { label: "amount", num: true }], reasons)}`)}
      ${card(`${eyebrow("Allocated by customer")}${table([{ label: "customer" }, { label: "name" }, { label: "lines", num: true }, { label: "amount", num: true }], customers)}`)}
    </div>
    <div class="grid two" style="margin-top:16px">
      ${card(`${eyebrow("Planted hard cases in this dataset")}<p class="dim" style="margin:0 0 10px">Each must land in the review queue and never be allocated by the engine.</p>${cases || note("none recorded in manifest")}`)}
      ${datasetPanel()}
    </div>`;
}

function datasetPanel() {
  const rows = S.datasets.map(d => `<tr class="${d.loaded ? "active" : ""}"><td class="mono">${esc(d.name)}${d.loaded ? ' <span class="pill ok" style="margin-left:6px">loaded</span>' : ""}</td><td>${esc(d.importer || "")}</td><td class="num">${d.counts.shipments ?? ""}</td><td class="num">${d.counts.contracts ?? ""}</td><td class="num">${formatCents(d.counts.refund_amount_cents)}</td></tr>`).join("");
  return card(`${eyebrow("Dataset")}<p class="dim" style="margin:0 0 10px">A dataset is one folder under data/ matching docs/DATA_CONTRACT.md. Loading resets the database and rebuilds the ledger.</p>
    ${table([{ label: "folder" }, { label: "importer" }, { label: "shipments", num: true }, { label: "contracts", num: true }, { label: "refund", num: true }], rows)}
    <div class="btn-row" style="margin-top:12px">
      <button class="btn primary" data-load="${esc(document.getElementById("dataset").value)}">Load selected dataset</button>
      ${S.loaded ? `<button class="btn" data-reset="${esc(S.loaded)}">Reset demo</button><span class="empty">re-seeds ${esc(S.loaded)} and clears every decision</span>` : ""}
    </div>`);
}

// --------------------------------------------------------------------------- ledger

async function pageLedger() {
  if (!S.loaded) return `${eyebrow("Ledger")}<h1>No dataset loaded</h1>${note("open Overview and load one")}`;
  const led = await get("/ledger");
  S.ledgerRows = led.records;
  const statuses = [...new Set(led.records.map(r => r.review_status))].sort();
  const customers = [...new Set(led.records.map(r => r.customer_id).filter(Boolean))].sort();
  return `
    ${eyebrow(`Allocation ledger · ${led.records.length} live lines`)}
    <div class="page-head"><h1>Ledger</h1>
      <div class="btn-row filters">
        <select id="f-status" class="sel"><option value="">all statuses</option>${statuses.map(s => `<option>${esc(s)}</option>`).join("")}</select>
        <select id="f-customer" class="sel"><option value="">all customers</option>${customers.map(c => `<option>${esc(c)}</option>`).join("")}</select>
        <label class="chk"><input type="checkbox" id="f-queue"> only review queue</label>
      </div></div>
    <div id="ledger-table">${ledgerTable(led.records)}</div>
    <div id="drill" style="margin-top:16px">${note("click a line to open its evidence chain")}</div>`;
}

function ledgerTable(rows) {
  const body = rows.map(r => `<tr class="clickable" data-rec="${r.id}"><td class="num">${r.id}</td><td class="mono">${esc(r.shipment_id || "")}</td><td class="mono">${esc(r.po_number || "")}</td><td class="mono">${esc(r.invoice_number || "")}</td><td class="mono">${esc(r.customer_id || "")}</td><td class="num money ${r.review_status === "unallocated" ? "" : "accent"}">${formatCents(r.amount_cents)}</td><td>${confidence(r.confidence)}</td><td>${status(r.review_status)}</td><td class="mono dim">${esc(r.unallocated_reason || "")}</td><td class="mono dim">${esc(r.match_method)}</td></tr>`).join("");
  return table([{ label: "#", num: true }, { label: "shipment" }, { label: "PO" }, { label: "invoice" }, { label: "customer" }, { label: "amount", num: true }, { label: "confidence" }, { label: "status" }, { label: "reason" }, { label: "method" }], body);
}

function applyLedgerFilters() {
  const st = document.getElementById("f-status").value, cu = document.getElementById("f-customer").value, q = document.getElementById("f-queue").checked;
  const rows = S.ledgerRows.filter(r => (!st || r.review_status === st) && (!cu || r.customer_id === cu) && (!q || r.needs_review));
  document.getElementById("ledger-table").innerHTML = ledgerTable(rows);
}

async function drillDown(id) {
  const el = document.getElementById("drill");
  el.innerHTML = note("loading...");
  const d = await get(`/allocations/${id}`);
  const r = d.record;
  const docs = await allocationDocs(r, d);
  const decisions = d.decisions.map(x => `<tr><td class="num">${x.id}</td><td class="mono">${esc(x.created_at)}</td><td>${esc(x.actor)}</td><td>${status(x.action, x.action === "reject" ? "bad" : "ok")}</td><td>${esc(x.reason)}</td></tr>`).join("");
  el.innerHTML = card(`
    <div class="qhead"><span class="id">#${r.id}</span><span class="title">${esc(r.shipment_id || "no shipment")}</span>${status(r.review_status)}${r.unallocated_reason ? status(r.unallocated_reason, "bad") : ""}${confidence(r.confidence)}<span class="amt">${formatCents(r.amount_cents)}</span></div>
    ${eyebrow("Evidence chain")}${chainFor(r, d)}
    <div class="split" style="margin-top:16px">
      <div>${eyebrow("Engine reasoning")}<div class="why">${esc(r.reasoning)}</div>${eyebrow("Evidence, in chain order", "margin-top:14px")}${evidenceList(r.evidence)}</div>
      <div>${eyebrow("Source documents")}${docTabs(docs, "d" + r.id)}</div>
    </div>
    ${decisions ? `${eyebrow("Decisions on this line", "margin-top:16px")}${table([{ label: "#", num: true }, { label: "when" }, { label: "who" }, { label: "action" }, { label: "why" }], decisions)}` : ""}
    ${d.replaced_by.length ? `<div class="empty">replaced by ${d.replaced_by.map(x => `#${x.id} (${formatCents(x.amount_cents)} ${x.review_status})`).join(", ")}</div>` : ""}`);
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --------------------------------------------------------------------------- review queue

async function pageReview() {
  if (!S.loaded) return `${eyebrow("Review queue")}<h1>No dataset loaded</h1>${note("open Overview and load one")}`;
  const [q, obs] = await Promise.all([get("/review/queue"), get("/obligations")]);
  const details = await Promise.all(q.allocations.map(a => get(`/allocations/${a.id}`)));
  const items = await Promise.all(q.allocations.map((a, i) => queueItem(a, details[i])));
  const pending = obs.obligations.filter(o => o.status === "pending_review");
  const decided = obs.obligations.filter(o => o.status !== "pending_review");
  const obItems = await Promise.all(pending.map(o => obligationItem(o, true)));
  const decidedItems = await Promise.all(decided.map(o => obligationItem(o, false)));
  return `
    ${eyebrow(`Review queue · ${q.allocations.length + pending.length} pending`)}
    <div class="page-head"><h1>Review queue</h1><div class="btn-row"><span class="pill review">${q.allocations.length} allocation lines</span><span class="pill review">${pending.length} contract clauses</span></div></div>
    <p class="lede">Lines below the confidence threshold or with evidence that disagrees. Nothing here counts as allocated until a person decides; every decision is logged with who, when, what changed and why.</p>
    ${S.actor ? "" : note("enter a reviewer name in the sidebar to enable the decision buttons", "error")}
    <div class="queue">${items.join("") || note("no allocation lines waiting")}</div>
    ${eyebrow("Contract clauses", "margin-top:28px")}
    <div class="queue">${obItems.join("") || note("no contract clauses waiting")}</div>
    ${decided.length ? `${eyebrow("Decided clauses", "margin-top:28px")}<div class="queue">${decidedItems.join("")}</div>` : ""}`;
}

async function queueItem(rec, detail) {
  const docs = await allocationDocs(rec, detail);
  const lines = rec.proposal.length ? rec.proposal : [{ po_number: rec.po_number || "", customer_id: rec.customer_id || "", invoice_number: rec.invoice_number || "", amount_cents: rec.amount_cents }];
  const proposal = rec.proposal.length
    ? `<div class="proposal">${rec.proposal.map(l => `<div class="line"><span>${esc(l.customer_id)} · PO ${esc(l.po_number)}${l.invoice_number ? " · " + esc(l.invoice_number) + (l.invoice_from_scan ? " (from scan)" : "") : " · no invoice"}</span><span class="amt">${formatCents(l.amount_cents)}</span></div>`).join("")}</div>`
    : note("no proposal. approving records that this amount stays unallocated.");
  const dis = S.actor ? "" : "disabled";
  return card(`
    <div class="qhead"><span class="id">#${rec.id}</span><span class="title">${esc(rec.shipment_id || "no shipment")}${detail.related.refund_entry ? ` · entry ${esc(detail.related.refund_entry.entry_number)}` : ""}</span>${status(rec.unallocated_reason, "bad")}${confidence(rec.confidence)}<span class="amt">${formatCents(rec.amount_cents)}</span></div>
    <div class="split">
      <div>${eyebrow("Why this is flagged")}<div class="why">${esc(rec.reasoning)}</div>${eyebrow("Engine proposal", "margin-top:14px")}${proposal}</div>
      <div>${eyebrow("Conflicting documents")}${docTabs(docs, "q" + rec.id)}</div>
    </div>
    ${eyebrow("Evidence chain", "margin-top:16px")}${chainFor(rec, detail)}
    <div class="actions">
      <button class="btn primary" data-approve="${rec.id}" ${dis}>Approve proposal</button>
      <button class="btn" data-override="${rec.id}" ${dis}>Override</button>
      <button class="btn danger" data-reject="${rec.id}" ${dis}>Leave unallocated</button>
      <span class="who">reviewer: <b>${esc(S.actor || "none")}</b></span>
    </div>
    <div class="override" id="ov-${rec.id}" style="display:none">
      <div class="lines" id="lines-${rec.id}">
        <span class="h">PO number</span><span class="h">Customer</span><span class="h">Invoice</span><span class="h">Amount (USD)</span><span></span>
        ${lines.map(l => overrideRow(l)).join("")}
      </div>
      <div class="btn-row"><button class="btn" data-addline="${rec.id}">Add line</button><span class="empty">lines may total at most ${formatCents(rec.amount_cents)}; the remainder stays unallocated as override_remainder; a PO with one invoice fills the invoice in</span></div>
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="ovreason-${rec.id}" placeholder="What did you see in the documents that the engine did not?"></textarea></div>
      <div class="btn-row"><button class="btn primary" data-apply="${rec.id}">Apply override</button><button class="btn" data-cancel="${rec.id}">Cancel</button><span class="error" id="overr-${rec.id}"></span></div>
    </div>
    <div class="override" id="rs-${rec.id}" style="display:none">
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="reason-${rec.id}" placeholder="Why this decision; it goes in the audit memo and the decision log."></textarea></div>
      <div class="btn-row"><button class="btn primary" data-confirm="${rec.id}">Confirm</button><button class="btn" data-cancel-rs="${rec.id}">Cancel</button><span class="error" id="rserr-${rec.id}"></span></div>
    </div>`, "", `data-queue-item="${rec.id}"`);
}

function overrideRow(l) {
  return `<input value="${esc(l.po_number || "")}" placeholder="PO-..."><input value="${esc(l.customer_id || "")}" placeholder="CUST-..."><input value="${esc(l.invoice_number || "")}" placeholder="INV-..."><input class="mono num" value="${toDollarsInput(l.amount_cents)}"><button class="btn" data-removeline title="remove line">x</button>`;
}

async function obligationItem(o, withActions) {
  const doc = await get(`/documents/${o.contract_document_id}`);
  const pg = (doc.pages || []).find(p => p.page === o.page) || doc.pages[0] || { text: "" };
  let body;
  if (o.span_start !== null && o.span_end !== null && pg.text) {
    body = esc(pg.text.slice(0, o.span_start)) + `<mark>${esc(pg.text.slice(o.span_start, o.span_end))}</mark>` + esc(pg.text.slice(o.span_end));
  } else body = esc(pg.text);
  const invs = (o.evidence || []).filter(e => e.entity === "invoice");
  const docs = [
    { tab: `Contract p.${o.page}`, source: doc.source_path, locator: `page ${o.page}`, kind: `contract · read by ${doc.extract_model || "model"}`, body },
    { tab: "What was billed", source: "invoices.csv", locator: `${invs.length} rows`, kind: "surcharge invoices behind the draft", body: invs.length ? `<div class="row">${invs.map(e => `<span>${esc(e.key)}</span><span>${esc(e.quoted_text.replace(/^[^|]*\|\s*/, ""))}</span>`).join("")}</div>` : `<span class="muted">no allocated line to this customer carried a tariff surcharge</span>` },
  ];
  const owed = { yes: "refund owed", no: "nothing owed", unclear: "unclear" }[o.refund_owed_to_customer] || o.refund_owed_to_customer;
  const dis = S.actor ? "" : "disabled";
  const actions = withActions ? `
    <div class="actions">
      <button class="btn primary" data-ob-approve="${o.id}" ${dis}>Confirm at draft</button>
      <button class="btn" data-ob-override="${o.id}" ${dis}>Confirm at another amount</button>
      <button class="btn danger" data-ob-reject="${o.id}" ${dis}>Nothing owed</button>
      <span class="who">status moves only by human decision</span>
    </div>
    <div class="override" id="ob-${o.id}" style="display:none">
      <div class="grid two"><div class="field"><label>Amount (USD)</label><input id="obamt-${o.id}" class="mono" value="${toDollarsInput(o.draft_amount_cents || 0)}"></div></div>
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="obreason-${o.id}" placeholder="Why; it goes in the decision log and the payables export."></textarea></div>
      <div class="btn-row"><button class="btn primary" data-ob-apply="${o.id}">Confirm</button><button class="btn" data-ob-cancel="${o.id}">Cancel</button><span class="error" id="oberr-${o.id}"></span></div>
    </div>` : `<div class="actions"><span class="who">${o.confirmed_amount_cents !== null ? `confirmed at ${formatCents(o.confirmed_amount_cents)} · decision #${o.decided_by_decision_id}` : ""}</span></div>`;
  return card(`
    <div class="qhead"><span class="id">CLAUSE</span><span class="title">${esc(o.customer_id)} ${esc(o.customer_name || "")}</span>${status(o.status)}${confidence(o.confidence)}<span class="amt">${formatCents(o.draft_amount_cents)} <span class="muted" style="font-size:11px">draft</span></span></div>
    <div class="split">
      <div>${eyebrow("Why this is flagged")}<div class="why"><b>${esc(o.clause_type)}</b> · ${esc(o.obligation_strength)} · ${esc(owed)}\n\n${esc(o.reasoning)}\n\n<span class="muted">${esc(o.draft_basis)}</span></div></div>
      <div>${eyebrow("Contract vs. what was billed")}${docTabs(docs, "o" + o.id)}</div>
    </div>${actions}`, "", `data-ob-item="${o.id}"`);
}

// --------------------------------------------------------------------------- memo + export

async function pageMemo() {
  if (!S.loaded) return `${eyebrow("Memo")}<h1>No dataset loaded</h1>`;
  const text = await get("/memo");
  const html = window.marked ? marked.parse(text) : `<pre>${esc(text)}</pre>`;
  return `${eyebrow("Audit memo · regenerated from the reviewed ledger")}
    <div class="page-head"><h1>Audit memo</h1><a class="btn" href="/memo" download="sherlock_audit_memo.md">Download .md</a></div>
    ${card(`<div class="memo">${html}</div>`)}`;
}

async function pageExport() {
  if (!S.loaded) return `${eyebrow("Export")}<h1>No dataset loaded</h1>`;
  const [journal, payables] = await Promise.all([get("/export.csv"), get("/payables.csv")]);
  const jr = parseCsv(journal), pr = parseCsv(payables);
  const deb = jr.reduce((a, r) => a + Number(r.debit_cents || 0), 0), cre = jr.reduce((a, r) => a + Number(r.credit_cents || 0), 0);
  const jrows = jr.slice(0, 400).map(r => `<tr><td class="num">${r.line_no}</td><td class="mono">${esc(r.account)} ${esc(r.account_name)}</td><td class="num">${r.debit_cents !== "0" ? formatCents(r.debit_cents) : ""}</td><td class="num">${r.credit_cents !== "0" ? formatCents(r.credit_cents) : ""}</td><td class="mono">${esc(r.customer_id)}</td><td class="mono">${esc(r.po_number)}</td><td class="mono">${esc(r.invoice_number)}</td><td>${r.review_status ? status(r.review_status) : ""}</td><td class="mono dim">${esc(r.decision_id)}</td><td class="dim">${esc(r.memo)}</td></tr>`).join("");
  const prows = pr.map(r => `<tr><td class="mono">${esc(r.customer_id)}</td><td>${esc(r.customer_name)}</td><td class="num money accent">${formatCents(r.amount_cents)}</td><td class="mono">${esc(r.contract_file)} p.${esc(r.contract_page)}</td><td class="mono">#${esc(r.decision_id)} ${esc(r.decided_by)}</td><td class="dim">${esc(r.reason)}</td></tr>`).join("");
  const owed = pr.reduce((a, r) => a + Number(r.amount_cents || 0), 0);
  return `${eyebrow("Exports · nothing is posted anywhere")}
    <div class="page-head"><h1>Exports</h1></div>
    <p class="lede">The refund is cash in. The journal export is the close entry: the file an accounting sync (Ramp, NetSuite, QuickBooks) would consume. The payables export is the customer money owed back under contract clauses a person confirmed, shaped for a bill-pay import. Both carry a NOT POSTED / NOT SENT label in every row.</p>
    <div class="grid tiles">
      ${card(`${eyebrow("Journal lines")}<b>${jr.length}</b><small>one cash debit, one credit per ledger line</small>`, "tile")}
      ${card(`${eyebrow("Debits")}<b>${formatCents(deb)}</b>`, "tile money")}
      ${card(`${eyebrow("Credits")}<b>${formatCents(cre)}</b>`, "tile money")}
      ${card(`${eyebrow("Balance")}<b>${deb === cre ? "Balanced" : "Off by " + formatCents(Math.abs(deb - cre))}</b>`, `tile ${deb === cre ? "ok" : "bad"}`)}
    </div>
    <div class="page-head" style="margin-top:24px"><h2>Journal entries</h2><a class="btn primary" href="/export.csv" download>Download journal CSV</a></div>
    ${table([{ label: "#", num: true }, { label: "account" }, { label: "debit", num: true }, { label: "credit", num: true }, { label: "customer" }, { label: "PO" }, { label: "invoice" }, { label: "status" }, { label: "decision" }, { label: "memo" }], jrows)}
    <div class="page-head" style="margin-top:24px"><h2>Payables · ${formatCents(owed)} owed back to customers</h2><a class="btn" href="/payables.csv" download>Download payables CSV</a></div>
    ${table([{ label: "customer" }, { label: "name" }, { label: "amount", num: true }, { label: "clause" }, { label: "decision" }, { label: "reason" }], prows || `<tr><td colspan="6" class="empty">no obligation confirmed yet; confirm one in the review queue and a row appears here</td></tr>`)}`;
}

// --------------------------------------------------------------------------- router + events

const RENDER = { overview: pageOverview, ledger: pageLedger, review: pageReview, memo: pageMemo, export: pageExport };

async function render() {
  const main = document.getElementById("main");
  try {
    await refreshSummary();
    main.innerHTML = await RENDER[S.page]();
  } catch (e) {
    main.innerHTML = note(e.message, "error");
  }
}

function route() {
  const id = (location.hash || "#overview").slice(1);
  S.page = RENDER[id] ? id : "overview";
  renderNav();
  render();
}

function reasonOf(id, errId) {
  const t = document.getElementById(id);
  const v = (t && t.value.trim()) || "";
  if (!v) { document.getElementById(errId).textContent = "a reason is required"; }
  return v;
}

async function act(fn) {
  try { await fn(); await render(); }
  catch (e) { document.getElementById("main").insertAdjacentHTML("afterbegin", note(e.message, "error")); window.scrollTo(0, 0); }
}

document.addEventListener("click", async e => {
  const t = e.target.closest("[data-tab]");
  if (t) {
    const group = t.dataset.tab.replace(/-\d+$/, "");
    document.querySelectorAll(`[data-tabs="${group}"] button`).forEach(b => b.classList.toggle("active", b === t));
    document.querySelectorAll(`[id^="${group}-"]`).forEach(p => (p.style.display = p.id === t.dataset.tab ? "" : "none"));
    return;
  }
  const chip = e.target.closest(".chip");
  if (chip) {
    const scope = chip.closest(".card");
    const tabs = scope.querySelector(".tabs");
    if (tabs) {
      const want = chip.dataset.kind;
      const btn = [...tabs.children].find(b => b.textContent === want) || [...tabs.children].find(b => want && b.textContent.includes(want));
      if (btn) btn.click();
    }
    scope.querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c === chip));
    return;
  }
  const row = e.target.closest("tr[data-rec]");
  if (row) { drillDown(row.dataset.rec); return; }

  const ov = e.target.closest("[data-override]"); if (ov) { document.getElementById("ov-" + ov.dataset.override).style.display = ""; return; }
  const cancel = e.target.closest("[data-cancel]"); if (cancel) { document.getElementById("ov-" + cancel.dataset.cancel).style.display = "none"; return; }
  const add = e.target.closest("[data-addline]"); if (add) { document.getElementById("lines-" + add.dataset.addline).insertAdjacentHTML("beforeend", overrideRow({ amount_cents: 0 })); return; }
  const rm = e.target.closest("[data-removeline]"); if (rm) { const inputs = [rm.previousElementSibling, rm.previousElementSibling.previousElementSibling, rm.previousElementSibling.previousElementSibling.previousElementSibling, rm.previousElementSibling.previousElementSibling.previousElementSibling.previousElementSibling]; inputs.forEach(i => i.remove()); rm.remove(); return; }

  const ap = e.target.closest("[data-approve]"); if (ap) { S.pendingAction = { kind: "approve", id: ap.dataset.approve }; document.getElementById("rs-" + ap.dataset.approve).style.display = ""; return; }
  const rj = e.target.closest("[data-reject]"); if (rj) { S.pendingAction = { kind: "reject", id: rj.dataset.reject }; document.getElementById("rs-" + rj.dataset.reject).style.display = ""; return; }
  const crs = e.target.closest("[data-cancel-rs]"); if (crs) { document.getElementById("rs-" + crs.dataset.cancelRs).style.display = "none"; return; }
  const confirm = e.target.closest("[data-confirm]");
  if (confirm) {
    const id = confirm.dataset.confirm; const reason = reasonOf("reason-" + id, "rserr-" + id); if (!reason) return;
    const kind = (S.pendingAction && S.pendingAction.id === id) ? S.pendingAction.kind : "approve";
    return act(() => post(`/review/allocations/${id}/${kind}`, { actor: S.actor, reason }));
  }
  const apply = e.target.closest("[data-apply]");
  if (apply) {
    const id = apply.dataset.apply; const err = document.getElementById("overr-" + id); err.textContent = "";
    const reason = reasonOf("ovreason-" + id, "overr-" + id); if (!reason) return;
    const inputs = [...document.querySelectorAll(`#lines-${id} input`)];
    const lines = [];
    for (let i = 0; i + 3 < inputs.length; i += 4) {
      const cents = toCents(inputs[i + 3].value);
      if (cents === null || cents <= 0) { err.textContent = `'${inputs[i + 3].value}' is not a positive dollar amount with at most two decimals`; return; }
      lines.push({ po_number: inputs[i].value.trim() || null, customer_id: inputs[i + 1].value.trim() || null, invoice_number: inputs[i + 2].value.trim() || null, amount_cents: cents });
    }
    if (!lines.length) { err.textContent = "add at least one line, or use Leave unallocated"; return; }
    return act(() => post(`/review/allocations/${id}/override`, { actor: S.actor, reason, lines }));
  }

  const oa = e.target.closest("[data-ob-approve]"); if (oa) { S.pendingOb = "approve"; document.getElementById("ob-" + oa.dataset.obApprove).style.display = ""; document.getElementById("obamt-" + oa.dataset.obApprove).disabled = true; return; }
  const oo = e.target.closest("[data-ob-override]"); if (oo) { S.pendingOb = "override"; document.getElementById("ob-" + oo.dataset.obOverride).style.display = ""; document.getElementById("obamt-" + oo.dataset.obOverride).disabled = false; return; }
  const orj = e.target.closest("[data-ob-reject]"); if (orj) { S.pendingOb = "reject"; document.getElementById("ob-" + orj.dataset.obReject).style.display = ""; document.getElementById("obamt-" + orj.dataset.obReject).disabled = true; return; }
  const oc = e.target.closest("[data-ob-cancel]"); if (oc) { document.getElementById("ob-" + oc.dataset.obCancel).style.display = "none"; return; }
  const oap = e.target.closest("[data-ob-apply]");
  if (oap) {
    const id = oap.dataset.obApply; const reason = reasonOf("obreason-" + id, "oberr-" + id); if (!reason) return;
    const kind = S.pendingOb || "approve";
    if (kind === "override") {
      const cents = toCents(document.getElementById("obamt-" + id).value);
      if (cents === null || cents < 0) { document.getElementById("oberr-" + id).textContent = "amount must be dollars with at most two decimals"; return; }
      return act(() => post(`/review/obligations/${id}/override`, { actor: S.actor, reason, amount_cents: cents }));
    }
    return act(() => post(`/review/obligations/${id}/${kind}`, { actor: S.actor, reason }));
  }

  const load = e.target.closest("[data-load]");
  if (load) { const name = document.getElementById("dataset").value; return act(async () => { await post(`/datasets/${encodeURIComponent(name)}/seed`); }); }
  const reset = e.target.closest("[data-reset]");
  if (reset) return act(async () => { await post(`/datasets/${encodeURIComponent(reset.dataset.reset)}/seed`); });
});

document.addEventListener("change", e => {
  if (["f-status", "f-customer", "f-queue"].includes(e.target.id)) applyLedgerFilters();
});
document.getElementById("reviewer").addEventListener("input", e => {
  S.actor = e.target.value.trim();
  try { localStorage.setItem("sherlock.actor", S.actor); } catch (_) { /* private mode */ }
  document.querySelectorAll("[data-approve],[data-override],[data-reject],[data-ob-approve],[data-ob-override],[data-ob-reject]").forEach(b => (b.disabled = !S.actor));
  document.querySelectorAll(".who b").forEach(b => (b.textContent = S.actor || "none"));
});
window.addEventListener("hashchange", route);

async function boot() {
  try {
    const cfg = await get("/config");
    S.threshold = cfg.auto_threshold;
    let saved = "";
    try { saved = localStorage.getItem("sherlock.actor") || ""; } catch (_) { /* private mode */ }
    S.actor = saved || cfg.demo_actor || "";
  } catch (e) { document.getElementById("main").innerHTML = note(e.message, "error"); }
  route();
}
boot();
