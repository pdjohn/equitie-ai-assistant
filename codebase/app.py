"""Streamlit chat UI for the EquiTie Investor Assistant.

Run:  streamlit run app.py

A sidebar selects the "logged-in" investor (this stands in for authentication --
in production the investor_id comes from the session, never user input). The
assistant only ever sees that investor's data.
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import streamlit as st

from equitie.data import DataStore
from equitie.assistant import Assistant
from equitie import metrics

st.set_page_config(page_title="EquiTie Investor Assistant", page_icon="📈", layout="centered")


@st.cache_resource
def get_store() -> DataStore:
    return DataStore()


store = get_store()

# ------------------------------------------------------------------- sidebar
st.sidebar.title("EquiTie")
st.sidebar.caption("Investor Assistant — prototype")

investors = store.list_investors()
labels = {f"{r.investor_id} — {r.investor_name} ({r.reporting_currency})": r.investor_id
          for r in investors.itertuples(index=False)}
choice = st.sidebar.selectbox("Logged-in investor", list(labels.keys()))
investor_id = labels[choice]

prof = metrics.get_investor(store, investor_id)["data"]
st.sidebar.markdown(
    f"**{prof['name']}**  \n"
    f"{prof['investor_type']} · {prof['country']}  \n"
    f"Reporting: **{prof['reporting_currency']}** · KYC: {prof['kyc_status']}  \n"
    f"Tech-savviness: {prof['tech_savviness']} · Age: {prof['age'] if prof['age'] else 'n/a'}  \n"
    f"In **{prof['num_deals']}** deal(s)"
)
if prof["top_sectors"]:
    st.sidebar.caption("Top sectors: " + ", ".join(s["sector"] for s in prof["top_sectors"][:3]))

has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
st.sidebar.divider()
st.sidebar.caption(
    "🟢 Claude online" if has_key
    else "🟡 Offline mode — set ANTHROPIC_API_KEY in .env for personalised answers"
)

# Reset chat when the logged-in investor changes (no cross-investor leakage).
if st.session_state.get("investor_id") != investor_id:
    st.session_state.investor_id = investor_id
    st.session_state.assistant = Assistant(store, investor_id)
    st.session_state.messages = []

assistant: Assistant = st.session_state.assistant

# --------------------------------------------------------------------- main
st.title("📈 Investor Assistant")
st.caption(f"Ask about your portfolio. Report date: 2026-06-25. You are {investor_id}.")

EXAMPLES = [
    "How is my portfolio doing?",
    "What's my position in Forgecraft across all rounds?",
    "What do I owe — any upcoming or overdue fees or capital calls?",
    "What fees am I paying and did I get any discount?",
    "Have I received any distributions or exits?",
    "Summarise my account statement.",
]
with st.expander("Example questions"):
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"ex{i}"):
            st.session_state.pending = ex

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("sources"):
            st.caption("Sources: " + ", ".join(m["sources"][:15]))

prompt = st.chat_input("Ask about your portfolio…") or st.session_state.pop("pending", None)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Checking your records…"):
            out = assistant.ask(prompt)
        if out["mode"] == "offline":
            st.info("Offline mode: showing deterministic tool output (no LLM).")
            st.code(out["text"].split("\n\n", 1)[-1], language="json")
        else:
            st.markdown(out["text"])
        if out["sources"]:
            st.caption("Sources: " + ", ".join(out["sources"][:15]))
        if out.get("tool_calls"):
            with st.expander("🔧 tools called"):
                st.json(out["tool_calls"])
    st.session_state.messages.append(
        {"role": "assistant", "content": out["text"], "sources": out["sources"]}
    )
