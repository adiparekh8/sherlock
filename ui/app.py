"""Sherlock UI (Streamlit). Talks only to the API at SHERLOCK_API_URL."""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("SHERLOCK_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Sherlock", page_icon="S", layout="wide")


# --------------------------------------------------------------------------- helpers


def usd(cents) -> str:
    if cents is None or cents == "":
        return ""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API}{path}", timeout=120, **kw)
    except requests.ConnectionError:
        st.error(f"API not reachable at {API}. Start it with `make api` (or `make demo`).")
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


def evidence_cards(items: list[dict], empty: str = "none") -> None:
    if not items:
        st.caption(empty)
    for e in items:
        st.markdown(f"**{e.get('source', '')}** · {e.get('locator', '')}  \n`{e.get('quoted_text', '')}`")


def decision_form(key: str) -> tuple[str, str]:
    actor = st.session_state.get("actor", "")
    reason = st.text_input("Reason (required, goes in the decision log)", key=f"reason_{key}")
    return actor, reason


def act(path: str, body: dict) -> None:
    try:
        post(path, body)
        st.success("Logged.")
        st.rerun()
    except RuntimeError as e:
        st.error(str(e))


# --------------------------------------------------------------------------- sidebar

st.sidebar.title("Sherlock")
st.sidebar.caption("Tariff refund allocation with an evidence-linked ledger.")
st.session_state["actor"] = st.sidebar.text_input("Reviewer name (logged with every decision)",
                                                  value=st.session_state.get("actor", ""))
page = st.sidebar.radio("Page", ["Dataset", "Ledger", "Review queue", "Contracts", "Memo", "Export"])

try:
    loaded = get("/datasets")
except RuntimeError as e:
    st.error(str(e))
    st.stop()
st.sidebar.markdown(f"**Loaded dataset:** `{loaded['loaded'] or 'none'}`")
if loaded["loaded"]:
    summ = get("/refund")["summary"]
    st.sidebar.metric("Refund", usd(summ["refund_cents"]))
    st.sidebar.metric("Allocated", usd(summ["allocated_cents"]))
    st.sidebar.metric("Unallocated", usd(summ["unallocated_cents"]))
    st.sidebar.markdown("Conservation: " + ("**holds**" if summ["conserved"] else "**BROKEN**"))
    st.sidebar.markdown(f"Queue: **{summ['queue_count']}** allocation lines")


# --------------------------------------------------------------------------- pages


def page_dataset() -> None:
    st.header("Dataset")
    st.write("A dataset is one folder under `data/` matching `docs/DATA_CONTRACT.md`. Seeding resets the database, "
             "ingests the folder, parses the contracts, matches, and builds the ledger.")
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
    name = st.selectbox("Dataset to load", [d["name"] for d in rows])
    if st.button("Seed / reload this dataset", type="primary"):
        with st.spinner("Seeding..."):
            try:
                rep = post(f"/datasets/{name}/seed")
                st.success("Seeded.")
                st.json(rep)
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
    if loaded["loaded"]:
        m = get("/manifest")
        if m.get("hard_cases"):
            st.subheader("Planted hard cases in this dataset")
            st.caption("Each must land in the review queue and must not be auto-allocated.")
            for h in m["hard_cases"]:
                st.markdown(f"- **{h['id']}** ({h['kind']}): {h.get('description', '')} "
                            f"→ expect `{h.get('expect')}`")


def page_ledger() -> None:
    st.header("Allocation ledger")
    data = get("/ledger")
    s = data["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Refund total", usd(s["refund_cents"]))
    c2.metric("Allocated", usd(s["allocated_cents"]))
    c3.metric("Unallocated", usd(s["unallocated_cents"]))
    c4.metric("Conservation", "holds" if s["conserved"] else "BROKEN")
    st.caption(f"{usd(s['refund_cents'])} = {usd(s['allocated_cents'])} + {usd(s['unallocated_cents'])}")

    left, right = st.columns(2)
    with left:
        st.markdown("**By review status**")
        st.dataframe(pd.DataFrame([{"status": k, "lines": v["count"], "amount": usd(v["cents"])}
                                   for k, v in s["by_status"].items()]), hide_index=True, use_container_width=True)
        if s["by_reason"]:
            st.markdown("**Unallocated by reason**")
            st.dataframe(pd.DataFrame([{"reason": k, "lines": v["count"], "amount": usd(v["cents"])}
                                       for k, v in s["by_reason"].items()]), hide_index=True, use_container_width=True)
    with right:
        st.markdown("**By customer**")
        st.dataframe(pd.DataFrame([{"customer": k, "name": v["name"], "lines": v["count"], "amount": usd(v["cents"])}
                                   for k, v in s["by_customer"].items()]), hide_index=True, use_container_width=True)

    st.subheader("Lines")
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

    st.subheader("Evidence drill-down")
    ids = [r["id"] for r in rows]
    if not ids:
        return
    rid = st.selectbox("Ledger line", ids, format_func=lambda i: f"#{i}")
    d = get(f"/allocations/{rid}")
    r = d["record"]
    st.markdown(f"**#{r['id']}** · {usd(r['amount_cents'])} · `{r['review_status']}`"
                + (f" · reason `{r['unallocated_reason']}`" if r["unallocated_reason"] else "")
                + f" · confidence {r['confidence']:.2f} · method `{r['match_method']}`")
    st.markdown("**Reasoning:** " + r["reasoning"])
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Evidence chain**")
        evidence_cards(r["evidence"])
    with e2:
        st.markdown("**Related records**")
        for k, v in d["related"].items():
            if v:
                st.markdown(f"*{k}*")
                st.json(v, expanded=False)
    if d["decisions"]:
        st.markdown("**Decisions on this line**")
        st.dataframe(pd.DataFrame([{"#": x["id"], "when": x["created_at"], "who": x["actor"], "action": x["action"],
                                    "why": x["reason"]} for x in d["decisions"]]), hide_index=True, use_container_width=True)
    if d["replaced_by"]:
        st.markdown("**Replaced by lines:** " + ", ".join(f"#{x['id']} ({usd(x['amount_cents'])} {x['review_status']})"
                                                           for x in d["replaced_by"]))


def page_queue() -> None:
    st.header("Review queue")
    if not st.session_state.get("actor"):
        st.warning("Enter your name in the sidebar before deciding anything; every decision is logged with it.")
    q = get("/review/queue")
    st.caption(f"{len(q['allocations'])} allocation lines and {len(q['obligations'])} contract candidates need a human.")
    tab_a, tab_o = st.tabs([f"Allocations ({len(q['allocations'])})", f"Contract candidates ({len(q['obligations'])})"])

    with tab_a:
        if not q["allocations"]:
            st.success("Nothing waiting.")
        for r in q["allocations"]:
            with st.expander(f"#{r['id']} · {r['shipment_id'] or 'no shipment'} · {usd(r['amount_cents'])} · "
                             f"{r['unallocated_reason']} · confidence {r['confidence']:.2f}", expanded=False):
                st.markdown("**AI reasoning:** " + r["reasoning"])
                if r["proposal"]:
                    st.markdown("**Proposal:** " + "; ".join(
                        f"{usd(l['amount_cents'])} → {l.get('customer_id') or '?'} via PO {l.get('po_number') or '?'}"
                        + (f" / {l['invoice_number']}" if l.get("invoice_number") else " (no invoice)") for l in r["proposal"]))
                else:
                    st.markdown("**Proposal:** none. Approving acknowledges the line stays unallocated.")
                st.markdown("**Conflicting evidence, side by side**")
                conflicts = r["conflicts"] or r["evidence"]
                cols = st.columns(max(1, min(len(conflicts), 3)))
                for i, c in enumerate(conflicts):
                    with cols[i % len(cols)]:
                        evidence_cards([c])
                st.markdown("**Full evidence chain**")
                evidence_cards(r["evidence"])

                actor, reason = decision_form(f"a{r['id']}")
                b1, b2, b3 = st.columns(3)
                if b1.button("Approve proposal", key=f"ap{r['id']}", disabled=not (actor and reason)):
                    act(f"/review/allocations/{r['id']}/approve", {"actor": actor, "reason": reason})
                if b3.button("Reject (leave unallocated)", key=f"rj{r['id']}", disabled=not (actor and reason)):
                    act(f"/review/allocations/{r['id']}/reject", {"actor": actor, "reason": reason})
                with b2:
                    st.markdown("Override with your own lines:")
                seed_lines = r["proposal"] or [{"po_number": r["po_number"], "customer_id": r["customer_id"],
                                                "invoice_number": r["invoice_number"], "amount_cents": r["amount_cents"]}]
                edited = st.data_editor(pd.DataFrame(seed_lines, columns=["po_number", "customer_id", "invoice_number", "amount_cents"]),
                                        num_rows="dynamic", key=f"ed{r['id']}", use_container_width=True)
                st.caption(f"Lines may total at most {usd(r['amount_cents'])}; any remainder stays unallocated as "
                           f"`override_remainder`. amount_cents is integer cents.")
                if st.button("Override with these lines", key=f"ov{r['id']}", disabled=not (actor and reason)):
                    lines = []
                    for _, row in edited.iterrows():
                        if pd.isna(row.get("amount_cents")):
                            continue
                        lines.append({"po_number": _s(row.get("po_number")), "customer_id": _s(row.get("customer_id")),
                                      "invoice_number": _s(row.get("invoice_number")), "amount_cents": int(row["amount_cents"])})
                    act(f"/review/allocations/{r['id']}/override", {"actor": actor, "reason": reason, "lines": lines})

    with tab_o:
        if not q["obligations"]:
            st.success("Nothing waiting.")
        for o in q["obligations"]:
            obligation_block(o, with_actions=True)


def _s(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def obligation_block(o: dict, with_actions: bool) -> None:
    title = (f"{o['customer_id']} {o.get('customer_name', '')} · {o['clause_type']} · {o['obligation_strength']} · "
             f"refund owed: {o['refund_owed_to_customer']} · confidence {o['confidence']:.2f} · draft {usd(o['draft_amount_cents'])} · "
             f"`{o['status']}`")
    with st.expander(title, expanded=False):
        left, right = st.columns(2)
        with left:
            st.markdown("**Contract clause** (" + ", ".join(f"{e['source']} {e['locator']}" for e in o["evidence"]
                                                          if e.get("entity") == "contract") + ")")
            st.markdown("> " + " ".join(o["quoted_text"].split()))
            st.markdown("**AI reading:** " + o["reasoning"])
        with right:
            st.markdown("**What the customer was billed** (surcharge invoices behind the draft)")
            inv = [e for e in o["evidence"] if e.get("entity") == "invoice"]
            evidence_cards(inv, empty="no allocated lines to this customer carried a surcharge")
            st.caption(o["draft_basis"])
        if o.get("confirmed_amount_cents") is not None:
            st.markdown(f"**Confirmed amount:** {usd(o['confirmed_amount_cents'])} (decision #{o['decided_by_decision_id']})")
        if with_actions:
            actor, reason = decision_form(f"o{o['id']}")
            b1, b2, b3 = st.columns(3)
            if b1.button("Confirm at draft amount", key=f"oa{o['id']}", disabled=not (actor and reason)):
                act(f"/review/obligations/{o['id']}/approve", {"actor": actor, "reason": reason})
            amt = b2.number_input("Confirm at a different amount (cents)", min_value=0, step=100,
                                  value=int(o["draft_amount_cents"] or 0), key=f"oamt{o['id']}")
            if b2.button("Confirm at this amount", key=f"oo{o['id']}", disabled=not (actor and reason)):
                act(f"/review/obligations/{o['id']}/override", {"actor": actor, "reason": reason, "amount_cents": int(amt)})
            if b3.button("Reject (nothing owed)", key=f"or{o['id']}", disabled=not (actor and reason)):
                act(f"/review/obligations/{o['id']}/reject", {"actor": actor, "reason": reason})


def page_contracts() -> None:
    st.header("Contract candidates")
    st.write("Every tariff clause the reader found, with its citation. Candidates stay pending until a human decides; "
             "draft amounts are recomputed from the live ledger.")
    for o in get("/obligations")["obligations"]:
        obligation_block(o, with_actions=False)
    st.subheader("Decision log")
    ds = get("/decisions")["decisions"]
    if ds:
        st.dataframe(pd.DataFrame([{"#": d["id"], "when": d["created_at"], "who": d["actor"], "target": f"{d['target_type']} #{d['target_id']}",
                                    "action": d["action"], "why": d["reason"]} for d in ds]), hide_index=True, use_container_width=True)
    else:
        st.caption("No decisions yet.")


def page_memo() -> None:
    st.header("Audit memo")
    memo = api("GET", "/memo").text
    st.download_button("Download memo (.md)", memo, file_name="sherlock_audit_memo.md", mime="text/markdown")
    st.markdown(memo)


def page_export() -> None:
    st.header("Journal-entry export")
    st.write("A labeled CSV of the reviewed ledger for ERP import. Nothing is posted anywhere by Sherlock.")
    text = api("GET", "/export.csv").text
    st.download_button("Download journal entries (.csv)", text, file_name="sherlock_journal_export.csv", mime="text/csv",
                       type="primary")
    import io

    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    deb = df["debit_cents"].astype(int).sum()
    cre = df["credit_cents"].astype(int).sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Lines", len(df))
    c2.metric("Debits", usd(deb))
    c3.metric("Credits", usd(cre))
    st.dataframe(df, hide_index=True, use_container_width=True, height=500)


if page == "Dataset":
    page_dataset()
elif not loaded["loaded"]:
    st.info("No dataset loaded. Go to the Dataset page and seed one.")
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
