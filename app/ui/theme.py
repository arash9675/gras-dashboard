"""Look and feel: Google Material 3 styling and small page-building helpers.

Streamlit has no theme for Material 3, so we inject one stylesheet (Roboto,
Google blue, rounded cards and pill buttons, a navigation-drawer sidebar) and
draw the few repeated pieces - cards, number tiles, callouts, legends - with
the helpers below. Pages only call these helpers, never write CSS themselves.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.palette import CATEGORY_COLORS, FORTY_COLOR, GFC_COLOR, METRIC_COLORS, REGION_COLORS  # noqa: F401
from pipeline.earth_engine import FORTY_CLASSES

# ForTy class name -> colour, in class order (used by legends and charts).
FORTY_CLASS_COLORS = {name: color for name, color in FORTY_CLASSES.values()}

# The two datasets as the pages name them.
DATASETS = {
    "gfc": {"label": "JRC GFC2020 v4"},
    "forty": {"label": "ForTy 2020 v1.0"},
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Mono&display=swap');
:root { --md-primary:#1A73E8; --md-on-primary:#fff; --md-primary-container:#D3E3FD;
        --md-on-primary-container:#041E49; --md-surface:#FFFFFF; --md-surface-variant:#F1F3F4;
        --md-surface-container:#F8FAFD; --md-outline:#DADCE0; --md-on-surface:#1F1F1F;
        --md-on-surface-variant:#444746; }
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select, label {
  font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif !important; }
.block-container {padding-top: 1.4rem; max-width: 1500px;}
header[data-testid="stHeader"] {background: transparent; height: 2.6rem;}
h1 {font-weight: 400 !important; font-size: 2rem !important; letter-spacing: 0; color: var(--md-on-surface);}
h2, h3 {font-weight: 500 !important; letter-spacing: 0;}
[data-testid="stSidebar"] {background: var(--md-surface-container); border-right: 1px solid var(--md-outline);}
[data-testid="stSidebarNavLink"] {border-radius: 100px; padding: 6px 14px; margin: 1px 0;}
[data-testid="stSidebarNavLink"][aria-current="page"] {background: var(--md-primary-container);}
[data-testid="stSidebarNavLink"][aria-current="page"] span {color: var(--md-on-primary-container); font-weight: 500;}
[data-testid="stSidebarNavSeparator"] {display: none;}
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: 100px; padding: 0.35rem 1.2rem; font-weight: 500; letter-spacing: .01em;}
.stButton > button[kind="primary"] {box-shadow: 0 1px 2px rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);}
[data-testid="stExpander"] details {border-radius: 12px; border-color: var(--md-outline);}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > .element-container .md-card-marker) {
  background: var(--md-surface); border-radius: 16px !important;}
div[data-baseweb="select"] > div {border-radius: 8px;}
.md-appbar {display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin: 0 0 6px 0;}
.md-appbar h1 {margin: 0; padding: 0;}
.md-sub {color: var(--md-on-surface-variant); font-size: .95rem; margin: 0 0 16px 0;}
.md-chip {display:inline-flex; align-items:center; gap:6px; height: 30px; padding: 0 12px; border-radius: 8px;
          border: 1px solid var(--md-outline); font-size: .85rem; color: var(--md-on-surface-variant);
          background: var(--md-surface); margin: 2px 6px 2px 0; white-space: nowrap;}
.md-chip.on {background: var(--md-primary-container); border-color: transparent; color: var(--md-on-primary-container);}
.md-chip .dot {width: 10px; height: 10px; border-radius: 50%; display:inline-block;}
.kpi {border-radius: 16px; padding: 16px 18px; background: var(--md-surface-container);
      border: 1px solid var(--md-outline); height: 100%;}
.kpi .lbl {font-size: .8rem; color: var(--md-on-surface-variant); font-weight: 500;}
.kpi .val {font-size: clamp(1.25rem, 2vw, 2rem); font-weight: 400; line-height: 1.25; margin-top: 4px;}
.kpi .sub {font-size: .8rem; color: var(--md-on-surface-variant); margin-top: 2px;}
.pill {display:inline-block; padding: 1px 10px; border-radius: 100px; font-size: .78rem; font-weight: 500;
       color: white; margin-right: 4px;}
.callout {border-radius: 12px; padding: 12px 16px; margin: 8px 0 14px 0; background: #FEF7E0; color: #3C2A00;}
.callout.info {background: #E8F0FE; color: #0B2A5B;}
.callout.ok {background: #E6F4EA; color: #0D3B1A;}
.callout.err {background: #FCE8E6; color: #5C0E0A;}
             border: 1px solid var(--md-outline);}
.legend-row {display:flex; flex-wrap: wrap; gap: 6px 14px; font-size: .82rem; margin: 6px 0 8px 0;
             color: var(--md-on-surface-variant);}
.legend-row span.sw {display:inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px;
                     vertical-align: -1px;}
.md-section {font-size: .78rem; font-weight: 500; color: var(--md-on-surface-variant); text-transform: none;
             letter-spacing: .02em; margin: 10px 0 2px 0;}
.md-step {display:inline-flex; align-items:center; justify-content:center; width: 28px; height: 28px;
          border-radius: 50%; background: var(--md-primary); color: white; font-weight: 500; margin-right: 10px;}
.md-cardtitle {display:flex; align-items:center; font-size: 1.15rem; font-weight: 500; margin-bottom: 4px;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def card(title: str | None = None, step: int | None = None):
    """A bordered container styled as a Material card, optionally with a numbered title."""
    c = st.container(border=True)
    c.markdown('<span class="md-card-marker"></span>', unsafe_allow_html=True)
    if title:
        badge = f'<span class="md-step">{step}</span>' if step else ""
        c.markdown(f'<div class="md-cardtitle">{badge}{title}</div>', unsafe_allow_html=True)
    return c


def kpi(col, label: str, value: str, sub: str = "") -> None:
    col.markdown(f'<div class="kpi"><div class="lbl">{label}</div><div class="val">{value}</div>'
                 f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def callout(text: str, kind: str = "") -> None:
    """A tinted note. kind: '' (amber), 'info' (blue), 'ok' (green) or 'err' (red)."""
    st.markdown(f'<div class="callout {kind}">{text}</div>', unsafe_allow_html=True)


def legend(items: dict[str, str]) -> None:
    html = "".join(f'<span><span class="sw" style="background:{c}"></span>{n}</span>' for n, c in items.items())
    st.markdown(f'<div class="legend-row">{html}</div>', unsafe_allow_html=True)


def pct(x, digits: int = 0) -> str:
    return "–" if x is None or pd.isna(x) else f"{x * 100:.{digits}f}%"
