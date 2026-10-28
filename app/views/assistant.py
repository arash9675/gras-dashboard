"""Assistant: questions in plain language, answered from the insight queries.

Each answer shows how it was worked out: every tool the model called, with its
filters, the SQL behind it and the rows it returned, plus a check that each
number in the answer appears in those rows. Charts the model proposes can be
saved to My dashboards.
"""
from __future__ import annotations

import json
import time

import streamlit as st

import ui
from assistant import agent, specs
from assistant.prompts import HELP, SUGGESTED
from core import db
from core.config import settings

ui.page_header("Ask Gemini · beta", f"Ask Google Gemini ({settings.gemini_model}) about the selected polygon set. Answers "
               "come only from the named queries and metrics; open “How this was worked out” under an answer to see the rows behind every number.")

sid = ui.current_set_id()
if sid is None or ui.polygons().empty:
    ui.callout("No polygon set with results yet. Calculate one on <b>Choose data</b>.", "info")
    st.stop()

if not agent.available():
    ui.callout("The assistant needs a Gemini API key. Create one at "
               "<a href='https://aistudio.google.com/apikey' target='_blank'>Google AI Studio</a>, add "
               "<code>GEMINI_API_KEY=...</code> to <code>.env</code> on the server and restart the app. "
               "Everything else in the dashboard works without it.", "info")
    st.stop()

# A simple per-session limit keeps a runaway tab from spending the API quota.
LIMIT_PER_HOUR = 30
recent = [t for t in st.session_state.get("_asked_at", []) if time.time() - t < 3600]
st.session_state["_asked_at"] = recent

chat = st.session_state.setdefault("_chat", {}).setdefault(sid, [])


def show_trace(a: agent.Answer, key: str) -> None:
    if a.unmatched:
        ui.callout("These numbers were not found in any tool result (they may be totals or rounding the model did "
                   f"itself): <b>{', '.join(a.unmatched)}</b>. Check them against the rows below.")
    elif a.calls:
        st.caption(f"Number check: every number in the answer appears in the tool results · model "
                   f"{a.model or settings.gemini_model}")
    for i, c in enumerate(a.calls):
        if c.chart and not c.error:
            data = specs.data(c.chart, sid)
            fig = specs.render(c.chart, data)
            st.markdown(f"**{c.chart['title']}**")
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, key=f"{key}_fig{i}")
            else:
                st.dataframe(data, hide_index=True, use_container_width=True)
            if st.button("Save to My dashboards", key=f"{key}_save{i}", icon=":material/bookmark_add:"):
                db.execute("INSERT INTO dashboards (title, spec, question) VALUES (%s, %s, %s)",
                           (c.chart["title"], json.dumps(c.chart), st.session_state.get(f"{key}_q")))
                st.toast("Saved to My dashboards")
    if a.calls:
        with st.expander(f"How this was worked out · {len(a.calls)} tool call{'s' * (len(a.calls) != 1)}",
                         icon=":material/manage_search:"):
            for i, c in enumerate(a.calls, 1):
                st.markdown(f"**{i}. `{c.tool}`** " + (f"· {json.dumps(c.args, default=str)}" if c.args else ""))
                if c.error:
                    st.caption(f"Refused: {c.error}")
                    continue
                if c.source:
                    st.code(c.source, language="sql")
                if not c.rows.empty:
                    st.dataframe(c.rows, hide_index=True, use_container_width=True,
                                 height=min(38 + 35 * len(c.rows), 280))


for n, (q, a) in enumerate(chat):
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant", avatar=":material/auto_awesome:"):
        if a.error:
            st.error(a.error)
        else:
            st.markdown(a.text)
        st.session_state[f"a{n}_q"] = q
        show_trace(a, f"a{n}")

with st.expander("What can I ask?", expanded=not chat, icon=":material/help:"):
    st.markdown(HELP)

if not chat:
    st.markdown('<div class="md-section">Try one of these</div>', unsafe_allow_html=True)
    cols = st.columns(3)
    for i, s in enumerate(SUGGESTED):
        if cols[i % 3].button(s, key=f"sugg{i}", use_container_width=True):
            st.session_state["_pending_q"] = s
            st.rerun()

question = st.chat_input("e.g. How much forest does each map see in Brazil west?  ·  Chart hectares lost per year in Uganda",
                         max_chars=500, disabled=len(recent) >= LIMIT_PER_HOUR)
question = question or st.session_state.pop("_pending_q", None)
if len(recent) >= LIMIT_PER_HOUR:
    st.caption(f"Limit of {LIMIT_PER_HOUR} questions an hour reached for this session.")
if question:
    st.session_state["_asked_at"].append(time.time())
    with st.spinner("Looking it up…"):
        answer = agent.ask(question, sid, [(q, a.text) for q, a in chat if not a.error])
    chat.append((question, answer))
    st.rerun()

if chat and st.button("Clear conversation", icon=":material/delete_sweep:"):
    chat.clear()
    st.rerun()
