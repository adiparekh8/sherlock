"""Sherlock UI (Streamlit). Talks only to the API at SHERLOCK_API_URL.

Visual direction: warm paper, a serif display face carrying the numbers, monospace for labels and
identifiers, hairline rules. The six pages are the workflow in order, hence the numbering.
"""

from __future__ import annotations

import html
import io
import os

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("SHERLOCK_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Sherlock", page_icon="◇", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,300;1,6..72,400&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap');

:root{
  --paper:#F4F3EF; --paper-2:#ECEAE3; --ink:#1C1B19; --ink-2:#5F5D58; --rule:#D8D5CE;
  --teal:#2F5F5A; --teal-soft:#DCE7E4; --amber:#9A6A1F; --amber-soft:#F1E6CF; --red:#9A3B2E;
  --serif:"Newsreader",Georgia,"Times New Roman",serif; --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --sans:"IBM Plex Sans",-apple-system,"Helvetica Neue",Arial,sans-serif;
}
html,body,.stApp{background:var(--paper)!important;color:var(--ink);font-family:var(--sans)}
header[data-testid="stHeader"]{background:transparent;height:0}
#MainMenu,footer,[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"],[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],.stAppDeployButton{display:none!important}
.block-container{max-width:1180px;padding:2.4rem 2rem 6rem}
h1,h2,h3{font-family:var(--serif)!important;font-weight:400!important;letter-spacing:-.01em;color:var(--ink)}
p,li{line-height:1.6}
a{color:var(--teal)}

/* top nav */
.brand{font-family:var(--serif);font-size:1.6rem;letter-spacing:-.01em;color:var(--ink);padding-top:.35rem}
.brand small{display:block;font-family:var(--mono);font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-2);margin-top:.1rem}
[data-testid="stRadio"],[data-testid="stRadio"]>div{width:100%}
[data-testid="stRadioGroup"]{display:flex;gap:0;justify-content:flex-end;flex-wrap:wrap;width:100%}
div[role="radiogroup"] label{margin:0 0 0 1.9rem;padding:.55rem 0 .45rem;border-bottom:1px solid transparent;cursor:pointer}
label[data-testid="stRadioOption"] > div > div:not([data-testid]){display:none}
div[role="radiogroup"] label p{font-family:var(--mono)!important;font-size:.72rem!important;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-2)}
div[role="radiogroup"] label:has(input:checked){border-bottom-color:var(--ink)}
div[role="radiogroup"] label:has(input:checked) p{color:var(--ink)}
div[role="radiogroup"] label:hover p{color:var(--ink)}
.navrule{border-top:1px solid var(--rule);margin:.6rem 0 3.2rem}

/* hero */
.eyebrow{font-family:var(--mono);font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;color:var(--teal);margin-bottom:1.1rem}
.display{font-family:var(--serif);font-size:clamp(3.2rem,7.4vw,6.6rem);line-height:.98;letter-spacing:-.03em;font-weight:300;color:var(--ink);margin:0 0 1.2rem}
.display.amount{font-size:clamp(2.4rem,5.3vw,4.9rem);white-space:nowrap;letter-spacing:-.035em}
.display .dim{color:var(--ink-2)}
.lede{font-family:var(--sans);font-size:1.22rem;line-height:1.65;color:var(--ink);max-width:36rem}
.lede-sm{font-size:1.02rem;line-height:1.6;color:var(--ink-2);max-width:40rem;margin:.2rem 0 1.4rem}
.hero-rule{border-top:1px solid var(--rule);margin:3.4rem 0 3rem}

/* mono stat grid, like a résumé fact list */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1.3rem 2rem;margin-top:1.9rem}
.stats b{display:block;font-family:var(--mono);font-weight:500;font-size:1.02rem;color:var(--ink);letter-spacing:.01em}
.stats span{display:block;font-family:var(--mono);font-size:.78rem;color:var(--ink-2);margin-top:.25rem}
.stats .ok b{color:var(--teal)} .stats .warn b{color:var(--amber)} .stats .bad b{color:var(--red)}

/* numbered section heads */
.sec{display:flex;align-items:baseline;gap:1.1rem;margin:2.6rem 0 .5rem}
.sec .n{font-family:var(--mono);font-size:.72rem;color:var(--teal);letter-spacing:.12em}
.sec h2{font-size:2.3rem;margin:0}
.sub{display:flex;align-items:baseline;gap:.8rem;margin:2rem 0 .6rem;border-top:1px solid var(--rule);padding-top:1rem}
.sub h3{font-size:1.45rem;margin:0}
.sub .meta{font-family:var(--mono);font-size:.74rem;color:var(--ink-2);letter-spacing:.06em}

/* evidence */
.ev{border-left:1px solid var(--rule);padding:.15rem 0 .35rem .95rem;margin:.55rem 0}
.ev .src{font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--teal)}
.ev .q{font-family:var(--mono);font-size:.8rem;color:var(--ink);margin-top:.25rem;white-space:pre-wrap;word-break:break-word}
.ev.doc{border-left-color:var(--teal)}
.quote{font-family:var(--serif);font-size:1.25rem;line-height:1.5;color:var(--ink);border-left:2px solid var(--teal);padding:.2rem 0 .2rem 1.1rem;margin:.6rem 0 .9rem;font-style:italic}
.kv{font-family:var(--mono);font-size:.78rem;color:var(--ink-2);line-height:1.8}
.kv b{color:var(--ink);font-weight:500}
.pill{display:inline-block;font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;padding:.18rem .55rem;border:1px solid var(--rule);color:var(--ink-2);margin-right:.4rem}
.pill.ok{color:var(--teal);border-color:var(--teal)} .pill.warn{color:var(--amber);border-color:var(--amber)} .pill.bad{color:var(--red);border-color:var(--red)}
.note{font-family:var(--mono);font-size:.76rem;color:var(--ink-2);line-height:1.6}
.line{border-top:1px solid var(--rule);margin:1.4rem 0}

/* widgets */
.stButton>button{font-family:var(--mono)!important;font-size:.74rem!important;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--ink)!important;background:transparent!important;color:var(--ink)!important;padding:.55rem 1rem!important}
.stButton>button:hover{background:var(--ink)!important;color:var(--paper)!important}
.stButton>button[kind="primary"]{background:var(--teal)!important;border-color:var(--teal)!important;color:#fff!important}
.stButton>button[kind="primary"]:hover{background:var(--ink)!important;border-color:var(--ink)!important}
.stButton>button:disabled{opacity:.35}
.stDownloadButton>button{font-family:var(--mono)!important;font-size:.74rem!important;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--ink)!important;background:var(--ink)!important;color:var(--paper)!important}
[data-testid="stExpander"],[data-testid="stExpander"] details{border:none!important;border-radius:0!important;background:transparent!important;box-shadow:none!important}
[data-testid="stExpander"] details{border-top:1px solid var(--rule)!important}
[data-testid="stExpander"] summary{padding:.9rem 0}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p{font-family:var(--serif)!important;font-size:1.12rem!important;color:var(--ink)}
[data-testid="stExpander"] summary:hover{color:var(--teal)}
[data-testid="stExpander"] summary code{font-family:var(--mono);font-size:.8rem;color:var(--teal);background:transparent}
.stTextInput label p,.stSelectbox label p,.stNumberInput label p,.stCheckbox p{font-family:var(--mono)!important;font-size:.72rem!important;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-2)}
.stTextInput input,.stNumberInput input{font-family:var(--sans)}
[data-testid="stMetric"]{border-top:1px solid var(--rule);padding-top:.7rem}
[data-testid="stMetricLabel"] p{font-family:var(--mono)!important;font-size:.72rem!important;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-2)}
[data-testid="stMetricValue"]{font-family:var(--serif);font-size:2rem;font-weight:300;letter-spacing:-.02em}
[data-testid="stCaptionContainer"] p{font-family:var(--mono);font-size:.74rem;color:var(--ink-2)}
.stTabs [data-baseweb="tab"] p{font-family:var(--mono)!important;font-size:.74rem!important;letter-spacing:.12em;text-transform:uppercase}
.stTabs [data-baseweb="tab-highlight"]{background:var(--ink)}
.stTabs [data-baseweb="tab-border"]{background:var(--rule)}
.stAlert{border-radius:0}
hr{border-color:var(--rule)}
@media (max-width:760px){.block-container{padding:1.4rem 1rem 4rem}.display{font-size:2.8rem}.navrule{margin-bottom:1.8rem}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- helpers


def usd(cents) -> str:
    if cents is None or cents == "":
        return ""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def h(s) -> str:
    return html.escape("" if s is None else str(s))


def md(block: str) -> None:
    st.markdown(block, unsafe_allow_html=True)


def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API}{path}", timeout=120, **kw)
    except requests.ConnectionError:
        st.error(f"The API is not running at {API}. Start it with `make demo` or `make api`.")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"{method} {path}: {r.status_code} {detail}")
    return r


def get(path: str):
    return api("GET", path).json()


def post(path: str, body: dict | None = None):
    return api("POST", path, json=body or {}).json()


def eyebrow(text: str) -> None:
    md(f'<div class="eyebrow">{h(text)}</div>')


def section(n: str, title: str, lede: str | None = None) -> None:
    md(f'<div class="sec"><span class="n">{n}</span><h2>{h(title)}</h2></div>')
    if lede:
        md(f'<p class="lede-sm">{h(lede)}</p>')


def subhead(title: str, meta: str = "") -> None:
    md(f'<div class="sub"><h3>{h(title)}</h3><span class="meta">{h(meta)}</span></div>')


def stats(items: list[tuple[str, str, str]]) -> None:
    """items: (value, label, tone) where tone is "", "ok", "warn" or "bad"."""
    cells = "".join(f'<div class="{tone}"><b>{h(v)}</b><span>{h(label)}</span></div>' for v, label, tone in items)
    md(f'<div class="stats">{cells}</div>')


def evidence_cards(items: list[dict], empty: str = "none") -> None:
    if not items:
        md(f'<div class="note">{h(empty)}</div>')
        return
    for e in items:
        cls = "ev doc" if e.get("entity") == "contract" else "ev"
        md(f'<div class="{cls}"><div class="src">{h(e.get("source", ""))} · {h(e.get("locator", ""))}</div>'
           f'<div class="q">{h(e.get("quoted_text", ""))}</div></div>')


def pill(text: str, tone: str = "") -> str:
    return f'<span class="pill {tone}">{h(text)}</span>'


def status_tone(status: str) -> str:
    return {"auto_proposed": "", "human_confirmed": "ok", "human_overridden": "ok", "unallocated": "warn"}.get(status, "")


def decision_form(key: str) -> tuple[str, str]:
    actor = st.session_state.get("actor", "")
    reason = st.text_input("Reason, logged with the decision", key=f"reason_{key}")
    return actor, reason


def act(path: str, body: dict) -> None:
    try:
        post(path, body)
        st.rerun()
    except RuntimeError as e:
        st.error(str(e))


def _s(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


# --------------------------------------------------------------------------- nav

PAGES = ["Dataset", "Ledger", "Review queue", "Contracts", "Memo", "Export"]
NUM = {p: f"{i + 1:02d}" for i, p in enumerate(PAGES)}

nav_l, nav_r = st.columns([1, 3])
with nav_l:
    md('<div class="brand">Sherlock<small>Tariff refund allocation</small></div>')
with nav_r:
    if "nav" not in st.session_state:  # first load honours the deep link ?page=Ledger
        wanted = st.query_params.get("page", "")
        st.session_state["nav"] = wanted if wanted in PAGES else PAGES[0]
    page = st.radio("Page", PAGES, key="nav", horizontal=True, label_visibility="collapsed")
    if st.query_params.get("page") != page:
        st.query_params["page"] = page
md('<div class="navrule"></div>')

try:
    loaded = get("/datasets")
except RuntimeError as e:
    st.error(str(e))
    st.stop()

summary = get("/refund")["summary"] if loaded["loaded"] else None


def conservation_items(s: dict) -> list[tuple[str, str, str]]:
    return [
        (usd(s["refund_cents"]), "Refund received", ""),
        (usd(s["allocated_cents"]), "Allocated with evidence", ""),
        (usd(s["unallocated_cents"]), "Unallocated, each with a reason", "warn" if s["unallocated_cents"] else ""),
        ("Holds" if s["conserved"] else "Broken", "Conservation: refund = allocated + unallocated", "ok" if s["conserved"] else "bad"),
        (str(s["queue_count"]), "Lines waiting for a human", "warn" if s["queue_count"] else "ok"),
    ]


# --------------------------------------------------------------------------- pages


def page_dataset() -> None:
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        eyebrow("One lump-sum refund · every dollar traced")
        md('<div class="display">Where does<br>each dollar<br><span class="dim">belong?</span></div>')
    with right:
        md('<p class="lede">A tariff refund arrives as one number. Sherlock matches it through customs entries, '
           'shipments, purchase orders and invoices to the customers who actually bore the cost, cites the '
           'evidence for every line, and sends anything uncertain to a person before it touches the books.</p>')
        if summary:
            stats(conservation_items(summary))
        else:
            md('<div class="note" style="margin-top:1.4rem">No dataset loaded yet. Pick one below.</div>')
    md('<div class="hero-rule"></div>')

    section(NUM["Dataset"], "Dataset",
            "A dataset is one folder under data/ matching docs/DATA_CONTRACT.md. Loading it resets the database, "
            "reads the folder, parses the contracts, matches everything and builds the ledger.")
    rows = loaded["datasets"]
    if not rows:
        st.warning("No datasets found under data/. Run `make synthetic`.")
        return
    df = pd.DataFrame([{"dataset": d["name"], "importer": d.get("importer"), "loaded": d["loaded"],
                        "shipments": d["counts"].get("shipments"), "POs": d["counts"].get("purchase_orders"),
                        "invoices": d["counts"].get("invoices"), "contracts": d["counts"].get("contracts"),
                        "refund": usd(d["counts"].get("refund_amount_cents")), "planted cases": d["hard_cases"]}
                       for d in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)
    c1, c2 = st.columns([2, 1])
    name = c1.selectbox("Dataset", [d["name"] for d in rows])
    c2.write("")
    c2.write("")
    if c2.button("Load dataset", type="primary", use_container_width=True):
        with st.spinner("Loading..."):
            try:
                rep = post(f"/datasets/{name}/seed")
                st.session_state["seed_report"] = rep
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
    if st.session_state.get("seed_report"):
        with st.expander("What the load did"):
            st.json(st.session_state["seed_report"])

    if loaded["loaded"]:
        m = get("/manifest")
        if m.get("hard_cases"):
            subhead("Planted hard cases", f"{len(m['hard_cases'])} in {loaded['loaded']}")
            md('<p class="lede-sm">Each one must land in the review queue and must never be allocated by the engine.</p>')
            for case in m["hard_cases"]:
                md(f'<div class="ev"><div class="src">{h(case["id"])} · expect {h(case.get("expect"))}</div>'
                   f'<div class="q">{h(case.get("description", ""))}</div></div>')


def page_ledger() -> None:
    data = get("/ledger")
    s = data["summary"]
    refund = get("/refund")["refund"]
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        eyebrow(f"{refund['refund_id']} · received {refund['received_date']}")
        whole, frac = divmod(s["refund_cents"], 100)
        md(f'<div class="display amount">${whole:,}<span class="dim">.{frac:02d}</span></div>')
        md(f'<p class="lede-sm">Received by {h(refund["importer"])} from {h(refund["source"] or "customs")}, '
           f'covering {refund["entries"]} customs entries.</p>')
    with right:
        md('<p class="lede">The refund, reconciled. Allocated lines carry a customer, a confidence and an evidence '
           'chain. Unallocated lines carry a reason. The two always add back to the refund.</p>')
        stats(conservation_items(s))
    md('<div class="hero-rule"></div>')

    section(NUM["Ledger"], "Ledger")
    a, b, c = st.columns(3, gap="large")
    with a:
        subhead("By review status")
        st.dataframe(pd.DataFrame([{"status": k, "lines": v["count"], "amount": usd(v["cents"])}
                                   for k, v in s["by_status"].items()]), hide_index=True, use_container_width=True)
    with b:
        subhead("Unallocated by reason")
        if s["by_reason"]:
            st.dataframe(pd.DataFrame([{"reason": k, "lines": v["count"], "amount": usd(v["cents"])}
                                       for k, v in s["by_reason"].items()]), hide_index=True, use_container_width=True)
        else:
            md('<div class="note">Nothing unallocated.</div>')
    with c:
        subhead("By customer")
        st.dataframe(pd.DataFrame([{"customer": k, "name": v["name"], "lines": v["count"], "amount": usd(v["cents"])}
                                   for k, v in s["by_customer"].items()]), hide_index=True, use_container_width=True)

    subhead("Lines", f"{len(data['records'])} live")
    recs = data["records"]
    f1, f2, f3 = st.columns(3)
    status = f1.selectbox("Status", ["all"] + sorted({r["review_status"] for r in recs}))
    cust = f2.selectbox("Customer", ["all"] + sorted({r["customer_id"] for r in recs if r["customer_id"]}))
    only_q = f3.checkbox("Only lines in the review queue")
    rows = [r for r in recs if (status == "all" or r["review_status"] == status)
            and (cust == "all" or r["customer_id"] == cust) and (not only_q or r["needs_review"])]
    table = pd.DataFrame([{"id": r["id"], "shipment": r["shipment_id"], "PO": r["po_number"], "invoice": r["invoice_number"],
                           "customer": r["customer_id"], "amount": usd(r["amount_cents"]), "conf": f"{r['confidence']:.2f}",
                           "status": r["review_status"], "reason": r["unallocated_reason"], "queue": r["needs_review"],
                           "method": r["match_method"]} for r in rows])
    st.dataframe(table, hide_index=True, use_container_width=True, height=360)

    subhead("Evidence chain", "pick a line")
    ids = [r["id"] for r in rows]
    if not ids:
        return
    rid = st.selectbox("Ledger line", ids, format_func=lambda i: f"#{i}")
    d = get(f"/allocations/{rid}")
    r = d["record"]
    md(pill(r["review_status"], status_tone(r["review_status"]))
       + (pill(r["unallocated_reason"], "warn") if r["unallocated_reason"] else "")
       + pill(f"confidence {r['confidence']:.2f}") + pill(r["match_method"]))
    md(f'<div class="kv" style="margin-top:.6rem"><b>Line #{r["id"]}</b> · {usd(r["amount_cents"])}'
       + (f' · {h(r["shipment_id"])}' if r["shipment_id"] else "")
       + (f' · PO {h(r["po_number"])}' if r["po_number"] else "")
       + (f' · {h(r["invoice_number"])}' if r["invoice_number"] else "")
       + (f' · {h(r["customer_id"])}' if r["customer_id"] else "") + "</div>")
    md(f'<p class="lede-sm">{h(r["reasoning"])}</p>')
    e1, e2 = st.columns(2, gap="large")
    with e1:
        md('<div class="eyebrow">Evidence, in chain order</div>')
        evidence_cards(r["evidence"])
    with e2:
        md('<div class="eyebrow">Source records</div>')
        for k, v in d["related"].items():
            if v:
                md(f'<div class="note">{h(k)}</div>')
                st.json(v, expanded=False)
    if d["decisions"]:
        subhead("Decisions on this line")
        st.dataframe(pd.DataFrame([{"#": x["id"], "when": x["created_at"], "who": x["actor"], "action": x["action"],
                                    "why": x["reason"]} for x in d["decisions"]]), hide_index=True, use_container_width=True)
    if d["replaced_by"]:
        md('<div class="note">Replaced by ' + ", ".join(
            f'#{x["id"]} ({usd(x["amount_cents"])} {x["review_status"]})' for x in d["replaced_by"]) + "</div>")


def page_queue() -> None:
    q = get("/review/queue")
    section(NUM["Review queue"], "Review queue",
            "Everything here is below the confidence threshold or has evidence that disagrees. Nothing in this list "
            "is counted as allocated until a person decides.")
    c1, c2 = st.columns([1, 2])
    st.session_state["actor"] = c1.text_input("Your name, logged with every decision",
                                              value=st.session_state.get("actor", ""))
    with c2:
        stats([(str(len(q["allocations"])), "Allocation lines waiting", "warn" if q["allocations"] else "ok"),
               (str(len(q["obligations"])), "Contract clauses waiting", "warn" if q["obligations"] else "ok")])
    if not st.session_state.get("actor"):
        md('<div class="note" style="margin-top:.6rem">Enter your name to enable the decision buttons.</div>')

    tab_a, tab_o = st.tabs([f"Allocation lines ({len(q['allocations'])})", f"Contract clauses ({len(q['obligations'])})"])

    with tab_a:
        if not q["allocations"]:
            md('<div class="note">Nothing waiting. Every line is either allocated or has a reviewed reason.</div>')
        for r in q["allocations"]:
            label = (f"#{r['id']} · {r['shipment_id'] or 'no shipment'} · {usd(r['amount_cents'])} · "
                     f"`{r['unallocated_reason']}` · confidence {r['confidence']:.2f}")
            with st.expander(label):
                md(f'<p class="lede-sm">{h(r["reasoning"])}</p>')
                if r["proposal"]:
                    md('<div class="eyebrow">What the engine proposes</div>')
                    md('<div class="kv">' + "<br>".join(
                        f'<b>{usd(l["amount_cents"])}</b> to {h(l.get("customer_id") or "?")} via PO {h(l.get("po_number") or "?")}'
                        + (f' / {h(l["invoice_number"])}' if l.get("invoice_number") else " (no invoice)")
                        for l in r["proposal"]) + "</div>")
                else:
                    md('<div class="eyebrow">No proposal</div><div class="note">Approving records that this amount stays unallocated.</div>')

                scan_ev = [e for e in r["evidence"] if e.get("entity") == "scan"]
                if scan_ev:
                    md('<div class="eyebrow" style="margin-top:1.2rem">A scanned document the model read</div>')
                    sc1, sc2 = st.columns([1, 1], gap="large")
                    doc = get(f"/documents/{scan_ev[0]['document_id']}")
                    with sc1:
                        st.image(api("GET", f"/documents/{doc['id']}/image").content,
                                 caption=f"{doc['source_path']} · page 1 · no text layer", use_container_width=True)
                    with sc2:
                        md(f'<div class="note">{h(doc["source_path"])} read by the model. Approving the proposal creates this '
                           f'invoice record; nothing is created until then.</div>')
                        fields = [f for f in doc["fields"] if f["field_name"] != "document_type"]
                        st.dataframe(pd.DataFrame([{"field": f["field_name"],
                                                    "value": usd(f["value_norm"]) if f["field_name"].endswith("_cents") and str(f["value_norm"]).lstrip("-").isdigit() else f["value_norm"],
                                                    "confidence": f"{f['confidence']:.2f}", "where on the page": f["quoted_text"]}
                                                   for f in fields]), hide_index=True, use_container_width=True)
                        notes = next((f["quoted_text"] for f in doc["fields"] if f["field_name"] == "document_type"), "")
                        if notes:
                            md(f'<div class="note">{h(notes)}</div>')
                md('<div class="eyebrow" style="margin-top:1.2rem">The documents that disagree</div>')
                conflicts = r["conflicts"] or r["evidence"]
                cols = st.columns(max(1, min(len(conflicts), 3)), gap="medium")
                for i, c in enumerate(conflicts):
                    with cols[i % len(cols)]:
                        evidence_cards([c])
                with st.expander("Full evidence chain"):
                    evidence_cards(r["evidence"])

                md('<div class="line"></div>')
                actor, reason = decision_form(f"a{r['id']}")
                ready = bool(actor and reason)
                b1, b2 = st.columns(2)
                if b1.button("Approve the proposal", key=f"ap{r['id']}", type="primary", disabled=not ready, use_container_width=True):
                    act(f"/review/allocations/{r['id']}/approve", {"actor": actor, "reason": reason})
                if b2.button("Leave unallocated", key=f"rj{r['id']}", disabled=not ready, use_container_width=True):
                    act(f"/review/allocations/{r['id']}/reject", {"actor": actor, "reason": reason})
                md('<div class="eyebrow" style="margin-top:1.2rem">Or write your own lines</div>')
                seed_lines = r["proposal"] or [{"po_number": r["po_number"], "customer_id": r["customer_id"],
                                                "invoice_number": r["invoice_number"], "amount_cents": r["amount_cents"]}]
                edited = st.data_editor(pd.DataFrame(seed_lines, columns=["po_number", "customer_id", "invoice_number", "amount_cents"]),
                                        num_rows="dynamic", key=f"ed{r['id']}", use_container_width=True)
                md(f'<div class="note">Lines may total at most {usd(r["amount_cents"])}, in integer cents. Any remainder '
                   f'stays unallocated as override_remainder. A PO with one invoice fills the invoice in for you.</div>')
                if st.button("Override with these lines", key=f"ov{r['id']}", disabled=not ready):
                    lines = []
                    for _, row in edited.iterrows():
                        if pd.isna(row.get("amount_cents")):
                            continue
                        lines.append({"po_number": _s(row.get("po_number")), "customer_id": _s(row.get("customer_id")),
                                      "invoice_number": _s(row.get("invoice_number")), "amount_cents": int(row["amount_cents"])})
                    act(f"/review/allocations/{r['id']}/override", {"actor": actor, "reason": reason, "lines": lines})

    with tab_o:
        if not q["obligations"]:
            md('<div class="note">Nothing waiting.</div>')
        for o in q["obligations"]:
            obligation_block(o, with_actions=True)


def obligation_block(o: dict, with_actions: bool) -> None:
    owed = {"yes": "refund owed", "no": "nothing owed", "unclear": "unclear"}[o["refund_owed_to_customer"]]
    label = (f"{o['customer_id']} {o.get('customer_name', '')} · {owed} · {o['obligation_strength']} · "
             f"confidence {o['confidence']:.2f} · draft {usd(o['draft_amount_cents'])} · `{o['status']}`")
    with st.expander(label):
        left, right = st.columns(2, gap="large")
        with left:
            cite = ", ".join(f'{e["source"]} {e["locator"]}' for e in o["evidence"] if e.get("entity") == "contract")
            md(f'<div class="eyebrow">The clause · {h(cite)}</div>')
            md(f'<div class="quote">{h(" ".join(o["quoted_text"].split()))}</div>')
            md(f'<p class="lede-sm">{h(o["reasoning"])}</p>')
        with right:
            md('<div class="eyebrow">What this customer was billed</div>')
            inv = [e for e in o["evidence"] if e.get("entity") == "invoice"]
            evidence_cards(inv[:6], empty="No allocated line to this customer carried a tariff surcharge.")
            if len(inv) > 6:
                md(f'<div class="note">and {len(inv) - 6} more surcharge invoices, all in the memo appendix.</div>')
            md(f'<div class="note" style="margin-top:.8rem">{h(o["draft_basis"])}</div>')
        if o.get("confirmed_amount_cents") is not None:
            md(f'<div class="kv"><b>Confirmed at {usd(o["confirmed_amount_cents"])}</b> · decision #{o["decided_by_decision_id"]}</div>')
        if with_actions:
            md('<div class="line"></div>')
            actor, reason = decision_form(f"o{o['id']}")
            ready = bool(actor and reason)
            b1, b2, b3 = st.columns(3)
            if b1.button("Confirm at the draft amount", key=f"oa{o['id']}", type="primary", disabled=not ready, use_container_width=True):
                act(f"/review/obligations/{o['id']}/approve", {"actor": actor, "reason": reason})
            amt = b2.number_input("Different amount, in cents", min_value=0, step=100,
                                  value=int(o["draft_amount_cents"] or 0), key=f"oamt{o['id']}")
            if b2.button("Confirm at this amount", key=f"oo{o['id']}", disabled=not ready, use_container_width=True):
                act(f"/review/obligations/{o['id']}/override", {"actor": actor, "reason": reason, "amount_cents": int(amt)})
            if b3.button("Nothing is owed", key=f"or{o['id']}", disabled=not ready, use_container_width=True):
                act(f"/review/obligations/{o['id']}/reject", {"actor": actor, "reason": reason})


def page_contracts() -> None:
    section(NUM["Contracts"], "Contracts",
            "Every tariff clause the reader found, with its page citation. A clause stays pending until a person "
            "decides; draft amounts are recomputed from the live ledger.")
    for o in get("/obligations")["obligations"]:
        obligation_block(o, with_actions=False)
    subhead("Decision log", "who, when, what, why")
    ds = get("/decisions")["decisions"]
    if ds:
        st.dataframe(pd.DataFrame([{"#": d["id"], "when": d["created_at"], "who": d["actor"],
                                    "target": f"{d['target_type']} #{d['target_id']}", "action": d["action"],
                                    "why": d["reason"]} for d in ds]), hide_index=True, use_container_width=True)
    else:
        md('<div class="note">No decisions yet.</div>')


def page_memo() -> None:
    section(NUM["Memo"], "Audit memo", "Regenerated from the reviewed ledger every time this page loads.")
    memo = api("GET", "/memo").text
    st.download_button("Download the memo", memo, file_name="sherlock_audit_memo.md", mime="text/markdown")
    md('<div class="line"></div>')
    st.markdown(memo)


def page_export() -> None:
    section(NUM["Export"], "Exports",
            "Two labeled CSVs regenerated from the reviewed ledger. Sherlock posts nothing anywhere.")
    subhead("Journal entries", "the close entry")
    md('<p class="lede-sm">The file an accounting sync (Ramp, NetSuite, QuickBooks) would consume: the refund as a cash '
       'debit, one credit per allocated line with its customer, PO, invoice, review status and decision id, and the '
       'unallocated remainder in a visible suspense account. Labeled NOT POSTED.</p>')
    text = api("GET", "/export.csv").text
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    deb = df["debit_cents"].astype(int).sum()
    cre = df["credit_cents"].astype(int).sum()
    stats([(str(len(df)), "Journal lines", ""), (usd(deb), "Debits", ""), (usd(cre), "Credits", ""),
           ("Balanced" if deb == cre else "Unbalanced", "Debits equal credits", "ok" if deb == cre else "bad")])
    md('<div style="height:1.2rem"></div>')
    st.download_button("Download journal entries", text, file_name="sherlock_journal_export.csv", mime="text/csv")
    md('<div class="line"></div>')
    st.dataframe(df, hide_index=True, use_container_width=True, height=420)

    subhead("Payables", "money owed back to customers")
    md('<p class="lede-sm">One row per contract obligation a person confirmed: customer, amount, clause citation, '
       'decision id and reason, shaped for a bill-pay import. Pending and rejected clauses are not in it. '
       'Labeled NOT SENT.</p>')
    ptext = api("GET", "/payables.csv").text
    pdf_ = pd.read_csv(io.StringIO(ptext), dtype=str, keep_default_na=False)
    st.download_button("Download payables", ptext, file_name="sherlock_payables_export.csv", mime="text/csv")
    if len(pdf_):
        total = pdf_["amount_cents"].astype(int).sum()
        stats([(str(len(pdf_)), "Confirmed obligations", ""), (usd(total), "Owed back to customers", "")])
        st.dataframe(pdf_, hide_index=True, use_container_width=True)
    else:
        md('<div class="note">No obligation has been confirmed yet. Confirm one under Review queue, Contract clauses, '
           'and a row appears here.</div>')


if page == "Dataset":
    page_dataset()
elif not loaded["loaded"]:
    section(NUM[page], page)
    md('<div class="note">No dataset loaded. Open Dataset and load one.</div>')
elif page == "Ledger":
    page_ledger()
elif page == "Review queue":
    page_queue()
elif page == "Contracts":
    page_contracts()
elif page == "Memo":
    page_memo()
elif page == "Export":
    page_export()
