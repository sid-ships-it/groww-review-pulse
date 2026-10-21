"""Groww Review Pulse: reviews -> themes -> weekly pulse + fee explainer -> approved MCP actions."""
import json

import pandas as pd
import streamlit as st

from pulse import analysis, approval, llm, mcp_client, writer

st.set_page_config(page_title="Groww Review Pulse", page_icon="📊", layout="wide")


@st.cache_data(show_spinner=False)
def load_analysis() -> dict:
    return analysis.run(force=False)


def load_outputs(a: dict) -> dict:
    if "outputs" not in st.session_state:
        st.session_state.outputs = writer.build_all(a, force=False)
    return st.session_state.outputs


a = load_analysis()
out = load_outputs(a)
fee = a["fee_issue"]

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("About this run")
    st.write(f"**Product:** Groww  \n**Source:** {a['source']}  \n"
             f"**Window:** {a['window']['start']} to {a['window']['end']} ({a['window']['weeks']} weeks)")
    st.write(f"**AI model:** {'connected' if llm.available() else 'no key (showing saved outputs)'}")
    if st.button("Regenerate pulse and explainer", disabled=not llm.available(),
                 help="Re-writes Steps 2 and 3 with the AI model from the saved analysis."):
        with st.spinner("Writing the pulse and the explainer..."):
            st.session_state.outputs = writer.build_all(a, force=True)
        st.session_state.pop("results", None)
        st.rerun()
    st.caption("Theme labels for all reviews are saved in data/review_labels.csv. "
               "To redo Step 1 from scratch run `python run_pipeline.py --reanalyse`.")

st.title("Groww Review Pulse")
st.write("Turns raw Play Store reviews into a weekly product pulse and a ready-to-use support explanation, "
         "then logs them to internal tools through MCP, **only after you approve**.")

tab1, tab2, tab3, tab4 = st.tabs(["1. Review insights", "2. Weekly pulse", "3. Fee explainer",
                                  "4. Approve and log (MCP)"])

# ---------------------------------------------------------------- step 1
with tab1:
    c = a["counts"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Reviews in CSV", f"{c['all_reviews']:,}")
    m2.metric("Detailed reviews themed", f"{c['analysed']:,}", help="6+ words, duplicates removed")
    m3.metric("Average rating", f"{c['avg_rating_all']}★")
    m4.metric("1-star share", f"{c['one_star_share'] * 100:.0f}%")

    st.subheader("Themes (max 5)")
    tdf = pd.DataFrame([{"Theme": t["name"], "Reviews": t["reviews"], "Share": f"{t['share'] * 100:.0f}%",
                         "Avg rating": t["avg_rating"], "Negative or mixed": f"{t['negative_share'] * 100:.0f}%",
                         "Last week share": f"{t['latest_week_share'] * 100:.0f}%",
                         "What belongs here": t["description"]} for t in a["themes"]])
    tdf.insert(0, "Rank", range(1, len(tdf) + 1))
    st.dataframe(tdf, hide_index=True, width="stretch")
    st.bar_chart(pd.DataFrame({"Reviews": [t["reviews"] for t in a["themes"]]},
                              index=[t["name"] for t in a["themes"]]), horizontal=True)
    st.write("**Top 3 themes:** " + ", ".join(f"**{t['name']}**" for t in a["top_themes"]))

    st.subheader("3 real user quotes")
    for q in a["quotes"]:
        st.markdown(f"> {q['text']}\n\n{q['rating']}★ · {q['date']} · *{q['theme']}*")
    st.caption("Quotes are copied word for word from data/reviews.csv "
               f"(check passed: {a.get('quotes_verified_verbatim')}).")

    st.subheader("Recurring fee confusion")
    st.error(f"**{fee.get('name')}**\n\n{fee.get('summary')}")
    f1, f2, f3 = st.columns(3)
    f1.metric("Reviews about this fee", fee["issue_reviews"])
    f2.metric("Of which confused or surprised", fee["issue_confused_reviews"])
    f3.metric("Their average rating", f"{fee['issue_avg_rating']}★")
    left, right = st.columns(2)
    with left:
        st.write("Fee mentions by type")
        st.dataframe(pd.DataFrame([{"Fee type": k.replace("_", " "), "Mentions": v["mentions"],
                                    "Confused": v["confused"]} for k, v in fee["by_topic"].items()]),
                     hide_index=True, width="stretch")
    with right:
        st.write("Reviews about this fee, per week")
        st.line_chart(pd.Series(fee["weekly_issue_reviews"], name="Reviews"))

# ---------------------------------------------------------------- step 2
with tab2:
    p = out["pulse"]
    st.caption(f"{p['words']} words (limit 250)")
    st.markdown(p["markdown"])
    st.download_button("Download pulse (.md)", p["markdown"], file_name="weekly_pulse.md")

# ---------------------------------------------------------------- step 3
with tab3:
    e = out["explainer"]
    st.caption(f"{len(e['bullets'])} bullets (limit 6) · numbers checked against verified facts"
               + (" · fallback text used" if e.get("fallback_used") else ""))
    st.markdown(e["markdown"])
    st.download_button("Download explainer (.md)", e["markdown"], file_name="fee_explainer.md")
    with st.expander("Why this fee? (link back to the reviews)"):
        st.write(f"{fee['issue_reviews']} of {a['counts']['analysed']:,} themed reviews are about charges on "
                 f"stock trades; {fee['issue_confused_reviews']} of them read as confused or surprised rather "
                 "than only saying the price is high. The explainer answers what those users ask: what is "
                 "deducted on a buy or sell beyond the ₹20 brokerage.")

# ---------------------------------------------------------------- step 4
with tab4:
    st.write("The app is an **MCP client**. It starts a local MCP server (`mcp_server.py`), discovers its tools, "
             "and proposes two actions. **Nothing is written until you approve.** The server also checks: a write "
             "tool refuses to run without a one-time approval token that matches the exact payload you approved.")
    if "tools" not in st.session_state:
        with st.spinner("Connecting to the MCP server..."):
            st.session_state.tools = mcp_client.list_tools()
    with st.expander(f"MCP server connected: {len(st.session_state.tools)} tools discovered"):
        for t in st.session_state.tools:
            st.markdown(f"- `{t['name']}`: {t['description']}")

    to = st.text_input("Email draft recipient (optional)", placeholder="team@example.com")
    actions = {
        "append_to_notes": ("Append to notes document", out["notes_payload"]),
        "create_email_draft": ("Create email draft (no auto-send)", {**out["email_payload"], "to": to}),
    }
    results = st.session_state.setdefault("results", {})
    for tool, (label, args) in actions.items():
        with st.container(border=True):
            st.markdown(f"#### {label}  \n`{tool}`")
            if tool == "create_email_draft":
                st.text_input("Subject", args["subject"], disabled=True, key=f"subj_{tool}")
                st.text_area("Body", args["body"], height=260, disabled=True, key=f"body_{tool}")
            else:
                st.json(args, expanded=False)
            if tool in results:
                r = results[tool]
                (st.success if r.get("ok") else st.warning)(json.dumps(r, ensure_ascii=False))
                continue
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("✅ Approve", key=f"ok_{tool}", type="primary"):
                token = approval.record_approval(tool, args)
                with st.spinner(f"Calling {tool} through MCP..."):
                    results[tool] = mcp_client.call_tool(tool, {**args, "approval_token": token})
                st.rerun()
            if b2.button("❌ Reject", key=f"no_{tool}"):
                approval.record_rejection(tool, args)
                results[tool] = {"ok": False, "status": "Rejected by user. Nothing was written."}
                st.rerun()

    if results.get("append_to_notes", {}).get("ok"):
        st.subheader("Notes document after the append")
        doc = (approval.RUNTIME / "Groww_Product_Notes.md").read_text(encoding="utf-8")
        st.download_button("Download notes doc (.md)", doc, file_name="Groww_Product_Notes.md")
        with st.container(border=True, height=420):
            st.markdown(doc)
    draft = results.get("create_email_draft", {})
    if draft.get("ok"):
        st.subheader("Email draft saved (not sent)")
        eml = approval.RUNTIME / "drafts" / draft["draft_file"]
        st.download_button("Download draft (.eml, opens in Mail/Outlook as a draft)", eml.read_bytes(),
                           file_name=eml.name, mime="message/rfc822")
    if results:
        with st.expander("Approval audit log"):
            st.dataframe(pd.DataFrame(approval.audit_log()), hide_index=True, width="stretch")
        if st.button("Reset this demo"):
            st.session_state.pop("results", None)
            st.rerun()

st.divider()
st.caption("Facts-only. Public reviews and official sources only. No personal data is stored: reviewer names are "
           "dropped and phone numbers, emails, PAN and account numbers in review text are redacted.")
