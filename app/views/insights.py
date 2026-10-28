"""Insights: the query library as a gallery. Every card shows the question, the
answer computed from the data, a chart, and the exact SQL and rows behind it."""
from __future__ import annotations

import streamlit as st

import ui
from analytics import insights as lib
from core import db

ui.page_header("Insights", "Eleven named queries, each answering one question about the selected polygon set. "
               "Open “Query and data” on any card to see the SQL view and the rows behind the answer.")

sid = ui.current_set_id()
if sid is None or ui.polygons().empty:
    ui.callout("No polygon set with results yet. Calculate one on <b>Choose data</b>.", "info")
    st.stop()
st.caption("Statistics use polygons of at least one 10 m pixel; the sidebar filters do not apply to these queries.")


@st.cache_data(ttl=600, show_spinner=False)
def _run(key: str, set_id: int, run_key):
    return lib.run(key, set_id)


@st.cache_data(ttl=3600, show_spinner=False)
def _sql(key: str) -> str:
    return lib.definition(key)


run = db.latest_run(sid)
run_key = run["id"] if run else None

cols = st.columns(2, gap="medium")
for n, ins in enumerate(lib.INSIGHTS):
    with cols[n % 2]:
        c = ui.card()
        c.markdown(f'<div class="md-cardtitle"><span class="md-step">{n + 1}</span>{ins.title}</div>'
                   f'<div class="md-sub" style="margin:0 0 8px 38px">{ins.question}</div>', unsafe_allow_html=True)
        try:
            df = _run(ins.key, sid, run_key)
        except Exception as e:  # noqa: BLE001 - one broken query must not hide the others
            c.error(f"Query failed: {e}")
            continue
        c.markdown(f'<div class="callout info" style="margin:4px 0 10px 0">{ins.answer(df) if not df.empty else "No rows for this set."}</div>',
                   unsafe_allow_html=True)
        fig = ins.chart(df) if not df.empty else None
        if fig is not None:
            c.plotly_chart(fig, use_container_width=True, key=f"ins_{ins.key}")
        elif not df.empty:
            c.dataframe(lib.for_display(df).head(15), hide_index=True,
                        use_container_width=True, height=min(38 + 35 * min(len(df), 15), 420))
        with c.expander(f"Query and data · `{ins.view}`", icon=":material/code:"):
            st.code(_sql(ins.key), language="sql")
            st.dataframe(lib.for_display(df), hide_index=True, use_container_width=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode(), f"{ins.view}.csv", "text/csv",
                               key=f"dl_{ins.key}", icon=":material/download:")
