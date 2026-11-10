/* Sherlock console. No framework, no build step. Each page is a function that returns HTML for #main.
   All data comes from the API in sherlock/api/app.py; money arrives as integer cents and is formatted
   only here, by formatCents(). Status colors come only from review_status and the confidence threshold. */

const PAGES = [
  ["documents", "Documents", "M6 3h8l4 4v14H6z M14 3v5h5 M9 13h6 M9 17h6"],
  ["overview", "Overview", "M3 3h18v18H3z M3 9h18 M9 21V9"],
  ["ledger", "Ledger", "M4 5h16 M4 12h16 M4 19h10"],
  ["memo", "Memo", "M6 3h9l5 5v13H6z M14 3v6h6 M9 13h6 M9 17h6"],
  ["export", "Export", "M12 3v12 M7 10l5 5 5-5 M4 19h16"],
];

const S = { page: "documents", datasets: [], documentSets: [], workspaceId: null, loaded: null, summary: null, refund: null, threshold: 0.8, actor: "", queueCount: 0, uploads: [], selectedUpload: null };

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
function label(s) {
  const labels = { auto_proposed: "Auto-proposed", human_confirmed: "Confirmed", human_overridden: "Adjusted", ambiguous_po_split: "Multiple purchase orders", po_not_found: "Purchase order not found" };
  return labels[s] || String(s ?? "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
}
function status(s, cls) { return `<span class="status ${cls ?? tone(s)}">${esc(label(s))}</span>`; }
function eyebrow(text, style = "") { return `<span class="eyebrow" style="${style}">${esc(text)}</span>`; }
function card(inner, cls = "", attrs = "") { return `<section class="card ${cls}" ${attrs}>${inner}</section>`; }
function progress(on) {
  document.getElementById("progress").className = on ? "on" : "done";
  document.body.classList.toggle("is-loading", on);
  document.getElementById("loading-screen").setAttribute("aria-hidden", String(!on));
}
function note(text, cls = "empty") { return `<div class="${cls}">${esc(text)}</div>`; }

let inflight = 0;
let renderVersion = 0;
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
async function upload(file) {
  inflight++; progress(true);
  try {
    const r = await fetch("/uploads", { method: "POST", headers: { "content-type": file.type || "application/octet-stream", "x-filename": file.name, "x-workspace-id": S.workspaceId || "" }, body: file });
    if (!r.ok) { const body = await r.json().catch(() => ({})); throw new Error(body.detail || `Upload failed (${r.status})`); }
    return r.json();
  } finally { if (--inflight === 0) progress(false); }
}

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
    `<a href="#${id}" aria-label="${label}" ${id === S.page ? 'aria-current="page"' : ""} class="${id === S.page ? "active" : ""}"><svg viewBox="0 0 24 24"><path d="${d}"/></svg><span>${label}</span>` +
    (id === "review" && S.queueCount ? `<em class="count">${S.queueCount}</em>` : "") + `</a>`).join("");
}

function renderTopbar() {
  const el = document.getElementById("topbar");
  if (!S.summary) {
    const w = S.workspace;
    el.innerHTML = w?.documents ? `<div class="stat"><span>Documents</span><b>${w.documents}</b></div><div class="stat"><span>Money in</span><b>${formatCents(w.moneyIn)}</b></div><div class="stat"><span>Money out</span><b>${formatCents(w.moneyOut)}</b></div><div class="stat"><span>Needs review</span><b>${w.needsReview}</b></div><div class="spacer"></div><div class="stat"><span>Workspace</span><b class="dim">Live</b></div>` : `<div class="stat"><span>Workspace</span><b class="dim">No documents</b></div>`;
    return;
  }
  const s = S.summary;
  const off = s.refund_cents - s.allocated_cents - s.unallocated_cents;
  const pill = off === 0 ? `<span class="pill ok">Balanced</span>` : `<span class="pill bad">Off by ${formatCents(Math.abs(off))}</span>`;
  el.innerHTML = `
    <div class="stat money"><span>Refund</span><b>${formatCents(s.refund_cents)}</b></div>
    <div class="stat"><span>Allocated</span><b>${formatCents(s.allocated_cents)}</b></div>
    <div class="stat"><span>Unallocated</span><b>${formatCents(s.unallocated_cents)}</b></div>
    <div class="stat"><span>Balance</span>${pill}</div>
    <div class="spacer"></div>
    <div class="stat"><span>Refund id</span><b class="dim">${esc(s.refund_id)}</b></div>`;
}

function renderSidebar() {
  const sel = document.getElementById("dataset");
  sel.innerHTML = S.datasets.map(d => `<option value="${esc(d.name)}" ${d.loaded ? "selected" : ""}>${esc(d.name)}${d.loaded ? "" : " (not loaded)"}</option>`).join("")
    || `<option>no datasets under data/</option>`;
  document.getElementById("reviewer").value = S.actor;
  const d = S.datasets.find(x => x.loaded);
  document.getElementById("foot").textContent = d ? `${d.name} · ${d.counts.shipments} shipments · ${d.counts.contracts} contracts` : (S.workspace?.documents ? `${S.workspace.documents} uploaded documents · live` : "upload documents to begin");
}

function buildWorkspace(uploads) {
  const records = uploads.flatMap(file => (file.analysis?.records || []).map((record, i) => ({ ...record, file: file.filename, key: `${file.id}-${i}` })));
  const amount = direction => records.filter(r => r.direction === direction).reduce((sum, r) => sum + (Number(r.amount_cents) || 0), 0);
  const missing = uploads.flatMap(file => (file.analysis?.missing_links || []).map(text => ({ file: file.filename, text })));
  const incompleteShipments = records.filter(r => r.record_type === "shipment" && (!r.origin || !r.destination));
  return { documents: uploads.length, records, moneyIn: amount("money_in"), moneyOut: amount("money_out"), missing, incompleteShipments, needsReview: missing.length + incompleteShipments.length };
}

async function refreshSummary() {
  const [ds, sets] = await Promise.all([get("/datasets"), get("/workspaces")]);
  S.datasets = ds.datasets; S.loaded = ds.loaded;
  S.documentSets = sets.workspaces || [];
  if (!S.documentSets.some(set => set.id === S.workspaceId)) S.workspaceId = null;
  const uploaded = S.workspaceId ? await get(`/uploads?workspace_id=${encodeURIComponent(S.workspaceId)}`) : { uploads: [] };
  S.uploads = uploaded.uploads || [];
  S.workspace = buildWorkspace(S.uploads);
  if (S.loaded) {
    const r = await get("/refund");
    S.summary = r.summary; S.refund = r.refund; S.queueCount = r.summary.queue_count;
  } else { S.summary = null; S.refund = null; S.queueCount = S.workspace.needsReview; }
  renderSidebar(); renderTopbar(); renderNav();
}

// --------------------------------------------------------------------------- shared pieces

function statusRows(by) { return Object.entries(by).map(([k, v]) => `<tr><td>${status(k)}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join(""); }
function table(head, rows, cls = "") {
  return `<div class="tablewrap ${cls}"><table><thead><tr>${head.map(h => `<th class="${h.num ? "num" : ""}">${esc(h.label)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${head.length}" class="empty">No records</td></tr>`}</tbody></table></div>`;
}

function rowDoc(obj, keys, hits = []) {
  const money = k => k.endsWith("_cents");
  return `<div class="row">` + keys.filter(k => obj[k] !== undefined && obj[k] !== null).map(k =>
    `<span>${esc(label(k.replace(/_cents$/, "")))}</span><span class="${hits.includes(k) ? "hit" : ""}">${money(k) ? formatCents(obj[k]) : esc(obj[k] === "" ? "(blank)" : obj[k])}</span>`).join("") + `</div>`;
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

// --------------------------------------------------------------------------- document tree

const GEO = [["shanghai",121.47,31.23],["shenzhen",114.06,22.54],["hong kong",114.17,22.32],["singapore",103.82,1.35],["tokyo",139.65,35.68],["busan",129.08,35.18],["los angeles",-118.24,34.05],["long beach",-118.19,33.77],["new york",-74.01,40.71],["miami",-80.19,25.76],["houston",-95.37,29.76],["seattle",-122.33,47.61],["rotterdam",4.48,51.92],["hamburg",9.99,53.55],["london",-0.13,51.51],["dubai",55.27,25.20],["mumbai",72.88,19.08],["sydney",151.21,-33.87],["china",104.20,35.86],["united states",-98.58,39.83],["usa",-98.58,39.83],["germany",10.45,51.17],["japan",138.25,36.20],["india",78.96,20.59]];
function geoPoint(place) { const q = String(place || "").toLowerCase(); return GEO.find(([name]) => q.includes(name)); }
function routeMap(records, id) {
  const routes = records.filter(r => r.record_type === "shipment" && geoPoint(r.origin) && geoPoint(r.destination)).slice(0, 6);
  const routeList = routes.map(r => `<li><span>${esc(r.origin)}</span><i></i><span>${esc(r.destination)}</span>${r.reference ? `<b>${esc(r.reference)}</b>` : ""}</li>`).join("");
  return `<section class="map-card">
    <div class="map-head"><div>${eyebrow("Shipment routes")}<h2>Global flow</h2></div><span class="map-key"><i></i> Documented locations</span></div>
    <div id="shipment-map-${esc(id)}" class="shipment-map" aria-label="Interactive world map of shipment routes"></div>
    ${routes.length ? `<ul class="route-list">${routeList}</ul>` : `<p class="map-empty">Add a bill of lading or invoice with printed origin and destination to map a route. Financial documents remain in the flow below.</p>`}
  </section>`;
}

async function mountShipmentMaps(uploads) {
  (S.maps || []).forEach(map => map.remove());
  S.maps = [];
  if (!uploads.length) return;
  if (!S.mapboxToken || !S.mapboxToken.startsWith("pk.")) {
    document.querySelectorAll(".shipment-map").forEach(el => { el.innerHTML = `<div class="map-setup"><b>Mapbox needs a public token</b><span>Add <code>MAPBOX_ACCESS_TOKEN=pk.…</code> to <code>.env</code>, then restart Sherlock.</span></div>`; });
    return;
  }
  if (!window.mapboxgl || !window.mapboxgl.supported()) {
    document.querySelectorAll(".shipment-map").forEach(el => { el.textContent = "Mapbox requires WebGL2. Enable it in this browser and reload."; });
    return;
  }
  try {
    for (const item of uploads) {
      const container = document.getElementById(`shipment-map-${item.id}`);
      if (!container) continue;
      const routes = (item.analysis.records || []).filter(r => r.record_type === "shipment" && geoPoint(r.origin) && geoPoint(r.destination)).slice(0, 6);
      const features = routes.flatMap(r => {
        const a = geoPoint(r.origin), b = geoPoint(r.destination);
        return [{ type: "Feature", properties: { kind: "route", reference: r.reference || "Shipment" }, geometry: { type: "LineString", coordinates: [[a[1], a[2]], [b[1], b[2]]] } },
          { type: "Feature", properties: { kind: "point", label: r.origin }, geometry: { type: "Point", coordinates: [a[1], a[2]] } },
          { type: "Feature", properties: { kind: "point", label: r.destination }, geometry: { type: "Point", coordinates: [b[1], b[2]] } }];
      });
      const map = new mapboxgl.Map({ accessToken: S.mapboxToken, container, style: "mapbox://styles/mapbox/dark-v11", center: [8, 25], zoom: 1.25, attributionControl: true });
      map.on("load", () => {
        map.addSource("shipments", { type: "geojson", data: { type: "FeatureCollection", features } });
        map.addLayer({ id: "shipment-route", type: "line", source: "shipments", filter: ["==", ["get", "kind"], "route"], paint: { "line-color": "#b4ff49", "line-width": 2.2, "line-opacity": .9 } });
        map.addLayer({ id: "shipment-point", type: "circle", source: "shipments", filter: ["==", ["get", "kind"], "point"], paint: { "circle-color": "#b4ff49", "circle-radius": 5, "circle-stroke-color": "#050507", "circle-stroke-width": 2 } });
        map.on("click", "shipment-point", e => new mapboxgl.Popup({ closeButton: false }).setLngLat(e.lngLat).setText(e.features[0].properties.label).addTo(map));
        const coords = features.filter(f => f.geometry.type === "Point").map(f => f.geometry.coordinates);
        if (coords.length > 1) map.fitBounds(coords.reduce((b, c) => b.extend(c), new mapboxgl.LngLatBounds(coords[0], coords[0])), { padding: 55, maxZoom: 4 });
      });
      S.maps.push(map);
    }
  } catch (_) {
    document.querySelectorAll(".shipment-map").forEach(el => { el.textContent = "Mapbox could not load. Check your token and internet connection."; });
  }
}

function moneyNode(record) {
  const direction = record.direction === "money_in" ? "in" : record.direction === "money_out" ? "out" : "unknown";
  const amount = record.amount_cents === null ? "Amount not found" : formatCents(record.amount_cents);
  const links = (record.related_references || []).filter(Boolean).map(x => `<span class="tree-link">${esc(x)}</span>`).join("");
  return `<li class="flow-node ${direction}">
    <div class="flow-line"><span class="flow-dot"></span><div><b>${esc(label(record.record_type))}${record.reference ? ` · ${esc(record.reference)}` : ""}</b><small>${esc(record.counterparty || "Counterparty not found")} · p. ${record.page}</small></div><strong>${amount}</strong></div>
    <p>${esc(record.evidence)}</p>${links ? `<div class="tree-links">${links}</div>` : ""}
  </li>`;
}

function uploadTree(item) {
  const a = item.analysis;
  const records = a.records || [];
  const missing = (a.missing_links || []).map(x => `<li>${esc(x)}</li>`).join("");
  return `<section class="packet-flow"><div class="tree-root">
      <div><span class="file-icon">PDF</span><b>${esc(item.filename)}</b><small>${a.page_count || "?"} pages · ${esc(a.source || "analysis")}</small></div>
      <span class="status ${records.length ? "review" : "bad"}">${records.length} money records</span>
    </div>
    ${routeMap(records, item.id)}<section class="flow-card"><div class="flow-card-head"><div>${eyebrow("Document flow")}<h2>Money branches</h2></div><span class="flow-caption">${records.length} extracted records</span></div>
    <p class="tree-summary">${esc(a.summary || "No summary returned.")}</p>
    <ol class="flow-tree">${records.map(moneyNode).join("") || `<li class="empty">No monetary records found.</li>`}</ol>
    ${missing ? `<div class="missing-links"><b>Still unknown</b><ul>${missing}</ul></div>` : ""}</section></section>`;
}

async function pageDocuments() {
  const folders = S.documentSets.map(set => {
    const count = set.id === S.workspaceId ? S.workspace.documents : "";
    return desktopFolder(set.name, count === "" ? "Open document set" : `${count} active documents`, `#workspace/${encodeURIComponent(set.id)}`, "parent");
  }).join("");
  return `${eyebrow("Documents")}
    <div class="page-head"><div><h1>Worker desktop</h1><p class="lede">Each folder is isolated from every other document set.</p></div><button class="btn primary" data-new-set>New document set</button></div>
    <section class="desktop" aria-label="Worker folders">
      ${folders || note("Create a document set to begin.")}
    </section>`;
}

function desktopFolder(name, detail, href, cls) {
  return `<a class="desktop-folder ${cls}" href="${href}"><span class="folder-icon"><i></i></span><b>${esc(name)}</b><small>${esc(detail)}</small></a>`;
}

async function pageWorkspace() {
  const set = S.documentSets.find(x => x.id === S.workspaceId);
  if (!set) return `${eyebrow("Documents")}<h1>Document set not found</h1><a class="btn" href="#documents">Back to desktop</a>`;
  return `${eyebrow(`Documents / ${set.name}`)}
    <div class="page-head"><div><h1>${esc(set.name)}</h1><p class="lede">Files in this set stay together while a worker processes them.</p></div><a class="btn" href="#documents">Back to desktop</a></div>
    <section class="desktop child-desktop" aria-label="Current document set folders">
      ${desktopFolder("Incoming", "Drop PDFs and ZIPs", "#intake", "in")}
      ${desktopFolder("Shipments", `${S.workspace.records.filter(r => r.record_type === "shipment").length} shipment records`, "#ledger", "ship")}
    </section>`;
}

async function pageIntake() {
  if (!S.workspaceId) return `${eyebrow("Documents / Incoming")}<h1>Choose a document set first</h1><a class="btn primary" href="#documents">Back to desktop</a>`;
  return `${eyebrow("Documents / Incoming")}
    <div class="page-head"><div><h1>Incoming files</h1><p class="lede">Drop a PDF or ZIP to create a new active workspace record.</p></div><a class="btn" href="#documents">Back to desktop</a></div>
    <section id="drop-panel" class="drop-panel" tabindex="0">
      <input id="pdf-picker" type="file" accept="application/pdf,.pdf,.zip,application/zip" multiple hidden>
      <div class="drop-mark">+</div><b>Drop PDFs or a ZIP here</b><p>or <button class="link-btn" data-choose-files>choose files</button></p>
      <small>Files are analyzed with Claude only after you select them. ZIPs may contain up to 12 PDFs.</small>
    </section>
    <div id="upload-status"></div>
    <div class="tree-list">${S.uploads.map(uploadTree).join("") || note("No active documents. New uploads appear here and across the workspace.")}</div>`;
}

async function pageHistory() {
  const result = await get("/uploads?scope=history");
  S.history = result.uploads || [];
  const rows = S.history.map(item => { const a = item.analysis || {}, records = a.records || [], short = (a.summary || "No summary").slice(0, 150); return `<tr><td class="mono">${esc(item.filename)}</td><td class="num">${a.page_count || "—"}</td><td class="num">${records.length}</td><td class="dim">${esc(short)}${short.length === 150 ? "…" : ""}</td></tr>`; }).join("");
  return `${eyebrow("Documents / History")}<div class="page-head"><div><h1>History</h1><p class="lede">Archived packets are retained here in compact form and do not affect the active workspace.</p></div></div>${table([{label:"file"},{label:"pages",num:true},{label:"records",num:true},{label:"summary"}], rows, "tight")}`;
}

async function handleFiles(files) {
  const allowed = [...files].filter(f => /pdf|zip/i.test(f.type) || /\.(pdf|zip)$/i.test(f.name));
  if (!allowed.length) throw new Error("Choose a PDF or ZIP file");
  const status = document.getElementById("upload-status");
  status.innerHTML = note(`Analyzing ${allowed.length} file${allowed.length === 1 ? "" : "s"}…`, "upload-status");
  for (const file of allowed) await upload(file);
  await render();
}

// --------------------------------------------------------------------------- overview

async function pageOverview() {
  if (!S.loaded) return workspaceOverview();
  const led = await get("/ledger");
  const s = led.summary;
  const auto = (s.by_status.auto_proposed || {}).cents || 0;
  const human = ((s.by_status.human_confirmed || {}).cents || 0) + ((s.by_status.human_overridden || {}).cents || 0);
  const tiles = [
    ["Refund received", formatCents(s.refund_cents), "money", `${S.refund.entries} customs entries · ${esc(S.refund.received_date)}`],
    ["Matched automatically", formatCents(auto), "", `${(s.by_status.auto_proposed || {}).count || 0} lines at or above ${S.threshold.toFixed(2)} confidence`],
    ["Reviewed", formatCents(human), "", `${((s.by_status.human_confirmed || {}).count || 0) + ((s.by_status.human_overridden || {}).count || 0)} lines decided by a person`],
    ["Unallocated", formatCents(s.unallocated_cents), "", `${(s.by_status.unallocated || {}).count || 0} lines`],
    ["Balance", s.conserved ? "Balanced" : "Out of balance", s.conserved ? "ok" : "bad", "refund = allocated + unallocated"],
    ["Needs review", String(s.queue_count), s.queue_count ? "warn" : "ok", "allocation lines in the review queue"],
  ].map(([l, v, cls, sub]) => card(`${eyebrow(l)}<b>${v}</b><small>${sub}</small>`, `tile ${cls}`)).join("");
  const reasons = Object.entries(s.by_reason).map(([k, v]) => `<tr><td class="mono">${esc(label(k))}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join("");
  const customers = Object.entries(s.by_customer).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${esc(v.name)}</td><td class="num">${v.count}</td><td class="num">${formatCents(v.cents)}</td></tr>`).join("");
  return `
    ${eyebrow(`Overview · ${S.loaded}`)}
    <div class="page-head"><h1>${esc(S.refund.importer)}</h1><span class="pill">${esc(S.refund.source || "refund")}</span></div>
    <p class="lede">Track allocations and review unmatched records.</p>
    <div class="grid tiles">${tiles}</div>
    <div class="summary-action"><p>${s.queue_count} allocation lines need attention.</p><a class="btn primary" href="#ledger">Open ledger</a></div>
    <div class="grid two" style="margin-top:16px">
      ${card(`${eyebrow("Unallocated by reason")}${table([{ label: "reason" }, { label: "lines", num: true }, { label: "amount", num: true }], reasons)}`)}
      ${card(`${eyebrow("Allocated by customer")}${table([{ label: "customer" }, { label: "name" }, { label: "lines", num: true }, { label: "amount", num: true }], customers)}`)}
    </div>
    <details class="dataset-details"><summary>Manage data</summary>${datasetPanel()}</details>`;
}

function workspaceOverview() {
  const w = S.workspace;
  if (!w.documents) return `${eyebrow("Overview")}<h1>No documents yet</h1>${note("Upload a PDF to start the workspace.")}`;
  const tiles = [["Documents", w.documents, "", "uploaded packets"], ["Money in", formatCents(w.moneyIn), "money", "printed amounts"], ["Money out", formatCents(w.moneyOut), "money", "printed amounts"], ["Shipment records", w.records.filter(r => r.record_type === "shipment").length, "", "documented routes"], ["Needs review", w.needsReview, w.needsReview ? "warn" : "ok", "missing links or locations"], ["Records", w.records.length, "", "extracted from documents"]].map(([l, v, cls, sub]) => card(`${eyebrow(l)}<b>${v}</b><small>${sub}</small>`, `tile ${cls}`)).join("");
  return `${eyebrow("Overview · live workspace")}<div class="page-head"><h1>Document dashboard</h1></div><p class="lede">Every page reads the same uploaded-document workspace.</p><div class="grid tiles">${tiles}</div><div class="summary-action"><p>${w.needsReview} items need more evidence.</p><a class="btn primary" href="#ledger">Open ledger</a></div>`;
}

function datasetPanel() {
  const rows = S.datasets.map(d => `<tr class="${d.loaded ? "active" : ""}"><td class="mono">${esc(d.name)}${d.loaded ? ' <span class="pill ok" style="margin-left:6px">loaded</span>' : ""}</td><td>${esc(d.importer || "")}</td><td class="num">${d.counts.shipments ?? ""}</td><td class="num">${d.counts.contracts ?? ""}</td><td class="num">${formatCents(d.counts.refund_amount_cents)}</td></tr>`).join("");
  return card(`${eyebrow("Dataset")}<p class="dim" style="margin:0 0 10px">Load source records to build the ledger. Reloading replaces the current data and clears review decisions.</p>
    ${table([{ label: "folder" }, { label: "importer" }, { label: "shipments", num: true }, { label: "contracts", num: true }, { label: "refund", num: true }], rows)}
    <div class="btn-row" style="margin-top:12px">
      <button class="btn primary" data-load="${esc(document.getElementById("dataset").value)}">Load data</button>
      ${S.loaded ? `<button class="btn" data-reset="${esc(S.loaded)}">Reload data</button><span class="empty">re-seeds ${esc(S.loaded)} and clears every decision</span>` : ""}
    </div>`);
}

// --------------------------------------------------------------------------- ledger

async function pageLedger() {
  if (!S.loaded) return workspaceLedger();
  const led = await get("/ledger");
  S.ledgerRows = led.records;
  S.ledgerView = "all";
  const statuses = [...new Set(led.records.map(r => r.review_status))].sort();
  const customers = [...new Set(led.records.map(r => r.customer_id).filter(Boolean))].sort();
  return `
    ${eyebrow("Accounting")}
    <div class="page-head"><h1>Allocation ledger</h1><a class="btn primary" href="/export.csv" download>Export journal</a></div>
    <div class="ledger-tabs" aria-label="Allocation views">
      ${[["all", "All", led.records.length], ["review", "Needs review", led.records.filter(r => r.needs_review).length], ["allocated", "Allocated", led.records.filter(r => r.review_status !== "unallocated").length]].map(([id, text, count]) => `<button class="${id === "all" ? "active" : ""}" data-ledger-view="${id}" aria-pressed="${id === "all"}">${text}<span>${count}</span></button>`).join("")}
    </div>
    <div class="btn-row filters ledger-filters">
      <input type="search" id="f-search" aria-label="Search ledger" placeholder="Search shipment, PO, invoice or customer">
      <select id="f-status" class="sel" aria-label="Status"><option value="">All statuses</option>${statuses.map(s => `<option value="${esc(s)}">${esc(label(s))}</option>`).join("")}</select>
      <select id="f-customer" class="sel" aria-label="Customer"><option value="">All customers</option>${customers.map(c => `<option>${esc(c)}</option>`).join("")}</select>
      <span class="muted" id="ledger-count">${led.records.length} records</span>
    </div>
    <div id="ledger-table">${ledgerTable(led.records)}</div>
    <div id="drill" style="margin-top:16px">${note("click a line to open its evidence chain")}</div>`;
}

function workspaceLedger() {
  const w = S.workspace;
  const rows = w.records.map(r => `<tr><td class="mono">${esc(r.file)}</td><td>${esc(label(r.record_type))}</td><td class="mono">${esc(r.reference || "—")}</td><td>${esc(r.counterparty || "—")}</td><td class="mono">${esc(r.origin || "—")}</td><td class="mono">${esc(r.destination || "—")}</td><td class="num money">${r.amount_cents === null ? "—" : formatCents(r.amount_cents)}</td><td>${status(r.direction === "unknown" ? "pending_review" : r.direction, r.direction === "money_in" ? "ok" : r.direction === "money_out" ? "auto" : "review")}</td></tr>`).join("");
  return `${eyebrow("Ledger · live workspace")}<div class="page-head"><h1>Document ledger</h1></div><p class="lede">Records update as soon as a document is analyzed.</p>${table([{label:"document"},{label:"type"},{label:"reference"},{label:"counterparty"},{label:"origin"},{label:"destination"},{label:"amount",num:true},{label:"flow"}], rows)}`;
}

function ledgerTable(rows) {
  const body = rows.map(r => `<tr class="clickable" data-rec="${r.id}"><td class="num">${r.id}</td><td class="mono">${esc(r.shipment_id || "")}</td><td class="mono">${esc(r.po_number || "")}</td><td class="mono">${esc(r.invoice_number || "")}</td><td class="mono">${esc(r.customer_id || "")}</td><td class="num money ${r.review_status === "unallocated" ? "" : "accent"}">${formatCents(r.amount_cents)}</td><td>${confidence(r.confidence)}</td><td>${status(r.review_status)}</td><td class="mono dim">${esc(label(r.unallocated_reason || ""))}</td><td class="mono dim">${esc(label(r.match_method))}</td></tr>`).join("");
  return table([{ label: "#", num: true }, { label: "shipment" }, { label: "PO" }, { label: "invoice" }, { label: "customer" }, { label: "amount", num: true }, { label: "confidence" }, { label: "status" }, { label: "reason" }, { label: "method" }], body);
}

function applyLedgerFilters() {
  const st = document.getElementById("f-status").value;
  const cu = document.getElementById("f-customer").value;
  const query = document.getElementById("f-search").value.trim().toLowerCase();
  const rows = S.ledgerRows.filter(r => (!st || r.review_status === st) && (!cu || r.customer_id === cu)
    && (S.ledgerView !== "review" || r.needs_review)
    && (S.ledgerView !== "allocated" || r.review_status !== "unallocated")
    && (!query || [r.shipment_id, r.po_number, r.invoice_number, r.customer_id, label(r.unallocated_reason), label(r.match_method)].some(v => String(v || "").toLowerCase().includes(query))));
  document.getElementById("ledger-table").innerHTML = ledgerTable(rows);
  document.getElementById("ledger-count").textContent = `${rows.length} ${rows.length === 1 ? "record" : "records"}`;
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
      <div>${eyebrow("Match details")}<div class="why">${esc(r.reasoning)}</div>${eyebrow("Evidence, in chain order", "margin-top:14px")}${evidenceList(r.evidence)}</div>
      <div>${eyebrow("Source documents")}${docTabs(docs, "d" + r.id)}</div>
    </div>
    ${decisions ? `${eyebrow("Decisions on this line", "margin-top:16px")}${table([{ label: "#", num: true }, { label: "when" }, { label: "who" }, { label: "action" }, { label: "why" }], decisions)}` : ""}
    ${d.replaced_by.length ? `<div class="empty">replaced by ${d.replaced_by.map(x => `#${x.id} (${formatCents(x.amount_cents)} ${x.review_status})`).join(", ")}</div>` : ""}`);
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --------------------------------------------------------------------------- review queue

async function pageReview() {
  if (!S.loaded) return workspaceReview();
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
    <p class="lede">Check the source documents before approving. Decisions are saved with your name and reason.</p>
    ${S.actor ? "" : note("enter a reviewer name in the sidebar to enable the decision buttons", "error")}
    <div class="queue">${items.join("") || note("no allocation lines waiting")}</div>
    ${eyebrow("Contract clauses", "margin-top:28px")}
    <div class="queue">${obItems.join("") || note("no contract clauses waiting")}</div>
    ${decided.length ? `${eyebrow("Decided clauses", "margin-top:28px")}<div class="queue">${decidedItems.join("")}</div>` : ""}`;
}

function workspaceReview() {
  const w = S.workspace;
  const links = w.missing.map(x => `<li><b>${esc(x.file)}</b><span>${esc(x.text)}</span></li>`).join("");
  const shipments = w.incompleteShipments.map(x => `<li><b>${esc(x.file)} · ${esc(x.reference || "Shipment")}</b><span>Missing ${!x.origin ? "origin" : "destination"}</span></li>`).join("");
  const items = links + shipments;
  return `${eyebrow(`Review queue · ${w.needsReview} pending`)}<div class="page-head"><h1>Evidence needed</h1></div><p class="lede">This queue is shared with the document dashboard and updates after every upload.</p>${card(items ? `<ul class="workspace-review">${items}</ul>` : note("Nothing needs review."))}`;
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
      <div>${eyebrow("Reason for review")}<div class="why">${esc(rec.reasoning)}</div>${eyebrow("Suggested allocation", "margin-top:14px")}${proposal}</div>
      <div>${eyebrow("Source documents")}${docTabs(docs, "q" + rec.id)}</div>
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
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="ovreason-${rec.id}" placeholder="Explain the correction"></textarea></div>
      <div class="btn-row"><button class="btn primary" data-apply="${rec.id}">Apply override</button><button class="btn" data-cancel="${rec.id}">Cancel</button><span class="error" id="overr-${rec.id}"></span></div>
    </div>
    <div class="override" id="rs-${rec.id}" style="display:none">
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="reason-${rec.id}" placeholder="Reason for this decision"></textarea></div>
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
      <button class="btn primary" data-ob-approve="${o.id}" ${dis}>Confirm amount</button>
      <button class="btn" data-ob-override="${o.id}" ${dis}>Change amount</button>
      <button class="btn danger" data-ob-reject="${o.id}" ${dis}>Nothing owed</button>
      <span class="who">Requires your approval</span>
    </div>
    <div class="override" id="ob-${o.id}" style="display:none">
      <div class="grid two"><div class="field"><label>Amount (USD)</label><input id="obamt-${o.id}" class="mono" value="${toDollarsInput(o.draft_amount_cents || 0)}"></div></div>
      <div class="field"><label>Reason <span class="req">required</span></label><textarea id="obreason-${o.id}" placeholder="Reason for this decision"></textarea></div>
      <div class="btn-row"><button class="btn primary" data-ob-apply="${o.id}">Confirm</button><button class="btn" data-ob-cancel="${o.id}">Cancel</button><span class="error" id="oberr-${o.id}"></span></div>
    </div>` : `<div class="actions"><span class="who">${o.confirmed_amount_cents !== null ? `confirmed at ${formatCents(o.confirmed_amount_cents)} · decision #${o.decided_by_decision_id}` : ""}</span></div>`;
  return card(`
    <div class="qhead"><span class="id">CLAUSE</span><span class="title">${esc(o.customer_id)} ${esc(o.customer_name || "")}</span>${status(o.status)}${confidence(o.confidence)}<span class="amt">${formatCents(o.draft_amount_cents)} <span class="muted" style="font-size:11px">draft</span></span></div>
    <div class="split">
      <div>${eyebrow("Reason for review")}<div class="why"><b>${esc(o.clause_type)}</b> · ${esc(o.obligation_strength)} · ${esc(owed)}\n\n${esc(o.reasoning)}\n\n<span class="muted">${esc(o.draft_basis)}</span></div></div>
      <div>${eyebrow("Contract vs. what was billed")}${docTabs(docs, "o" + o.id)}</div>
    </div>${actions}`, "", `data-ob-item="${o.id}"`);
}

// --------------------------------------------------------------------------- memo + export

async function pageMemo() {
  if (!S.loaded) return `${eyebrow("Memo")}<h1>No dataset loaded</h1>`;
  const text = await get("/memo");
  const html = window.marked ? marked.parse(text) : `<pre>${esc(text)}</pre>`;
  return `${eyebrow("Reports")}
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
  return `${eyebrow("Accounting")}
    <div class="page-head"><h1>Exports</h1></div>
    <p class="lede">Download journal entries and confirmed customer payables. Exports are not posted or sent.</p>
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

const RENDER = { documents: pageDocuments, workspace: pageWorkspace, intake: pageIntake, overview: pageOverview, ledger: pageLedger, memo: pageMemo, export: pageExport };

async function render() {
  const main = document.getElementById("main");
  const version = ++renderVersion;
  const page = S.page;
  try {
    // Refresh the shell independently of the page body. Every page function then
    // fetches its own endpoint, so Ledger/Review/Memo/Export do not depend on
    // Overview having rendered first.
    await refreshSummary();
    if (version !== renderVersion || page !== S.page) return;
    const html = await RENDER[page]();
    if (version !== renderVersion || page !== S.page) return;
    main.innerHTML = html;
    if (page === "intake") mountShipmentMaps(S.uploads);
  } catch (e) {
    if (version !== renderVersion || page !== S.page) return;
    main.innerHTML = note(e.message, "error");
  }
}

function route() {
  const id = (location.hash || "#documents").slice(1);
  if (id.startsWith("workspace/")) {
    S.workspaceId = decodeURIComponent(id.slice("workspace/".length));
    S.page = "workspace";
  } else S.page = RENDER[id] ? id : "documents";
  window.scrollTo(0, 0);
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
  try {
    const result = await fn();
    // Mutation endpoints return the fresh ledger summary. Apply it immediately
    // so the dashboard chrome and whichever page is open stay in sync together.
    if (result && result.summary) {
      S.summary = result.summary;
      S.queueCount = result.summary.queue_count;
      renderTopbar(); renderNav();
    }
    await render();
  }
  catch (e) { document.getElementById("main").insertAdjacentHTML("afterbegin", note(e.message, "error")); window.scrollTo(0, 0); }
}

function openNewSetDialog() {
  const dialog = document.getElementById("set-dialog");
  const input = document.getElementById("set-name");
  const error = document.getElementById("set-error");
  error.textContent = "";
  input.value = "";
  dialog.showModal();
  requestAnimationFrame(() => input.focus());
}

document.addEventListener("click", async e => {
  const newSet = e.target.closest("[data-new-set]");
  if (newSet) {
    openNewSetDialog();
    return;
  }
  const cancelSet = e.target.closest("[data-new-set-cancel]");
  if (cancelSet) { document.getElementById("set-dialog").close(); return; }
  const choose = e.target.closest("[data-choose-files]");
  if (choose) { document.getElementById("pdf-picker").click(); return; }
  const view = e.target.closest("[data-ledger-view]");
  if (view) {
    S.ledgerView = view.dataset.ledgerView;
    document.querySelectorAll("[data-ledger-view]").forEach(b => {
      b.classList.toggle("active", b === view);
      b.setAttribute("aria-pressed", String(b === view));
    });
    applyLedgerFilters();
    return;
  }
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

document.getElementById("set-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("set-name");
  const error = document.getElementById("set-error");
  const submit = document.getElementById("set-submit");
  const name = input.value.trim();
  if (!name) { error.textContent = "Enter a name for this document set."; input.focus(); return; }
  error.textContent = "";
  submit.disabled = true;
  try {
    const created = await post("/workspaces", { name });
    document.getElementById("set-dialog").close();
    location.hash = `#workspace/${encodeURIComponent(created.id)}`;
  } catch (err) {
    error.textContent = err.message;
    input.focus();
  } finally {
    submit.disabled = false;
  }
});

document.addEventListener("change", e => {
  if (e.target.id === "pdf-picker") { handleFiles(e.target.files).catch(err => { document.getElementById("upload-status").innerHTML = note(err.message, "error"); }); return; }
  if (["f-status", "f-customer"].includes(e.target.id)) applyLedgerFilters();
});
document.addEventListener("input", e => {
  if (e.target.id === "f-search") applyLedgerFilters();
});
document.getElementById("reviewer").addEventListener("input", e => {
  S.actor = e.target.value.trim();
  try { localStorage.setItem("sherlock.actor", S.actor); } catch (_) { /* private mode */ }
  document.querySelectorAll("[data-approve],[data-override],[data-reject],[data-ob-approve],[data-ob-override],[data-ob-reject]").forEach(b => (b.disabled = !S.actor));
  document.querySelectorAll(".who b").forEach(b => (b.textContent = S.actor || "none"));
});
window.addEventListener("hashchange", route);
window.addEventListener("pointermove", e => {
  const orbit = document.getElementById("mouse-orbit");
  if (orbit) orbit.style.transform = `translate(${e.clientX - 38}px, ${e.clientY - 38}px)`;
});
document.addEventListener("dragover", e => { if (e.target.closest && e.target.closest("#drop-panel")) e.preventDefault(); });
document.addEventListener("drop", e => {
  if (!e.target.closest || !e.target.closest("#drop-panel")) return;
  e.preventDefault();
  handleFiles(e.dataTransfer.files).catch(err => { document.getElementById("upload-status").innerHTML = note(err.message, "error"); });
});

async function boot() {
  try {
    const cfg = await get("/config");
    S.threshold = cfg.auto_threshold;
    S.mapboxToken = cfg.mapbox_access_token || "";
    let saved = "";
    try { saved = localStorage.getItem("sherlock.actor") || ""; } catch (_) { /* private mode */ }
    S.actor = saved || cfg.demo_actor || "";
  } catch (e) { document.getElementById("main").innerHTML = note(e.message, "error"); }
  route();
}
boot();
