"""My dashboards: the charts saved from the assistant, as a grid.

A saved chart is a spec (insight query + columns + chart type), not a picture,
so every card redraws from the selected polygon set's current results.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from analytics import insights
from assistant import specs
from core import db

ui.page_header("My dashboards", "Charts saved from Ask Gemini. Each one redraws from the selected polygon set.")

sid = ui.current_set_id()
saved = pd.DataFrame(db.query("SELECT id, title, spec, question, created_at FROM dashboards ORDER BY created_at"))
if saved.empty:
    ui.callout("Nothing saved yet. Ask Gemini (<b>Ask Gemini</b> page) for a chart, for example “chart the agreement "
               "categories per cluster”, and press <i>Save to My dashboards</i>.", "info")
    st.stop()
if sid is None or ui.polygons().empty:
    ui.callout("The selected polygon set has no results yet. Calculate it on <b>Choose data</b>.", "info")
    st.stop()

cols = st.columns(2, gap="medium")
for n, row in enumerate(saved.itertuples()):
    with cols[n % 2]:
        c = ui.card()
        c.markdown(f'<div class="md-cardtitle">{row.title}</div>', unsafe_allow_html=True)
        spec = row.spec
        clean, problems = specs.validate(spec, sid)
        if problems:
            c.caption("This chart no longer fits its query: " + "; ".join(problems))
        else:
            data = specs.data(clean, sid)
            fig = specs.render(clean, data)
            if fig is not None:
                c.plotly_chart(fig, use_container_width=True, key=f"dash_{row.id}")
            else:
                c.dataframe(data, hide_index=True, use_container_width=True)
        source = insights.BY_KEY.get(spec.get("source"))
        c.caption(f"From `{source.view if source else spec.get('source')}`"
                  + (f" · asked: “{row.question}”" if row.question else "")
                  + f" · saved {row.created_at:%Y-%m-%d %H:%M}")
        if c.button("Remove", key=f"del_{row.id}", icon=":material/delete:"):
            db.execute("DELETE FROM dashboards WHERE id = %s", (row.id,))
            st.rerun()
