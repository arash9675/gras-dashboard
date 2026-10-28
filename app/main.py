"""Entry point: page setup, the Earth Engine connection and the navigation.

Run with `streamlit run main.py` (the container does this in entrypoint.sh).
Each page lives in views/ and is a plain script Streamlit reruns on every click.
"""
from __future__ import annotations

import logging

import streamlit as st

import ui
from pipeline import earth_engine as eec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

st.set_page_config(page_title="GRAS forest dataset comparison", page_icon=":material/forest:",
                   layout="wide", initial_sidebar_state="expanded")

eec.init_ee()  # no-op once connected; retried at most once a minute on failure
ui.inject_css()

pages = {
    "Data": [
        st.Page("views/start.py", title="Choose data", icon=":material/database:", default=True),
        st.Page("views/map.py", title="Map", icon=":material/map:"),
    ],
    "Analysis": [
        st.Page("views/insights.py", title="Insights", icon=":material/insights:"),
        st.Page("views/assistant.py", title="Ask Gemini · beta", icon=":material/auto_awesome:"),
        st.Page("views/dashboards.py", title="My dashboards", icon=":material/space_dashboard:"),
        st.Page("views/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("views/compare.py", title="Compare datasets", icon=":material/compare_arrows:"),
        st.Page("views/polygons.py", title="Polygon table", icon=":material/table_view:"),
        st.Page("views/findings.py", title="Findings", icon=":material/fact_check:"),
    ],
    "Reference": [
        st.Page("views/about.py", title="Datasets & method", icon=":material/menu_book:"),
    ],
}

with st.sidebar:
    st.markdown("### :material/forest: GRAS forest check")
    st.caption("JRC GFC2020 v4 vs ForTy 2020 v1.0 on confirmed post-2020 deforestation polygons")

nav = st.navigation(pages)
st.session_state["_page"] = nav.url_path
ui.sidebar_status()  # before run(): pages may st.stop()
nav.run()
