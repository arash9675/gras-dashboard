"""Page state: the chosen polygon set and datasets, cached data, and the filters.

Streamlit reruns a page top to bottom on every click and forgets the widgets
of pages you are not on. So the choices that must survive moving between
pages (polygon set, datasets, filter ticks) live in our own session keys,
and every page reads them through the functions here.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from analytics.metrics import REGIONS
from core import db
from core.config import settings
from pipeline import earth_engine as eec
from ui.theme import DATASETS, card

SIZE_ORDER = ["<1 px", "1-10 px", "10-50 px", "50+ px"]


# ------------------------------------------------------------------
# Current selection
# ------------------------------------------------------------------

def current_set_id() -> int | None:
    """The chosen polygon set; falls back to the pinned one if it was evicted meanwhile."""
    sid = st.session_state.get("set_id")
    if sid is None or db.polygon_set(sid) is None:
        sid = db.default_set_id()
        st.session_state["set_id"] = sid
    return sid


def current_datasets() -> list[str]:
    """Datasets ticked on the map page; both until someone unticks one."""
    ds = [d for d in st.session_state.get("datasets", list(DATASETS)) if d in DATASETS]
    # The map page's checkboxes may have changed in this very run, before the
    # line that stores them - read them directly so the header never lags a click.
    page = st.session_state.get("_page", "")
    live = {k: st.session_state.get(f"_map_ds_{k}_{page}") for k in DATASETS}
    if any(v is not None for v in live.values()):
        ds = [k for k, v in live.items() if v] or ds
    return ds or list(DATASETS)


def page_header(title: str, subtitle: str = "", show_selection: bool = True) -> None:
    """Page title with chips for the chosen polygon set and datasets."""
    chips = ""
    if show_selection:
        s = db.polygon_set(current_set_id()) if current_set_id() else None
        if s:
            chips += f'<span class="md-chip on">▤ {s["name"]} · {s["n_polygons"]} polygons</span>'
        chips += "".join(f'<span class="md-chip on">◫ {DATASETS[d]["label"]}</span>' for d in current_datasets())
    st.markdown(f'<div class="md-appbar"><h1>{title}</h1>{chips}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="md-sub">{subtitle}</div>', unsafe_allow_html=True)


def sidebar_status() -> None:
    with st.sidebar:
        s = eec.status()
        sid = current_set_id()
        run = db.latest_run(sid) if sid else None
        dot = ":green[●]" if s["ok"] else ":red[●]"
        st.markdown(f"{dot} Earth Engine {'connected' if s['ok'] else 'not connected'}")
        if settings.gemini_api_key:
            st.markdown(f":green[●] Gemini ready · {settings.gemini_model}")
        else:
            st.markdown(":gray[●] Gemini off (no API key)")
        if settings.groq_api_key:
            st.caption(f"Backup when Gemini is busy: Groq · {settings.groq_model}")
        st.caption(f"Results: run #{run['id']}, {run['finished_at']:%Y-%m-%d %H:%M} UTC" if run
                   else "No results yet for this polygon set")


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _polygons(set_id: int, run_key, with_geometry: bool) -> pd.DataFrame:
    # run_key is only part of the cache key: a new run gives new data.
    df = db.polygons(set_id, with_geometry=with_geometry)
    if not df.empty:
        df["region_name"] = df["region"].map(REGIONS).fillna("Other")
        df["size_label"] = df["size_class"].str.split(": ").str[1]
        df["year_label"] = df["source_year"].map(lambda y: "Unknown" if pd.isna(y) else str(int(y)))
    return df


def polygons(with_geometry: bool = False) -> pd.DataFrame:
    sid = current_set_id()
    if sid is None:
        return pd.DataFrame()
    run = db.latest_run(sid)
    return _polygons(sid, run["id"] if run else None, with_geometry)


# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------

def _checkbox_group(container, title: str, options: list[str], store: str, default_off=(),
                    cols: int = 2) -> list[str]:
    """One filter as a group of checkboxes; returns the ticked options."""
    saved: dict = st.session_state.setdefault(store, {})
    container.markdown(f'<div class="md-section">{title}</div>', unsafe_allow_html=True)
    grid = container.columns(cols)
    chosen = []
    for i, opt in enumerate(options):
        val = grid[i % cols].checkbox(opt, value=saved.get(opt, opt not in default_off),
                                      key=f"{store}_{opt}_{st.session_state.get('_page', '')}")
        saved[opt] = val
        if val:
            chosen.append(opt)
    return chosen


def _dataset_checkboxes(container) -> None:
    """GFC2020 / ForTy, one or both - the last ticked box cannot be unticked."""
    container.markdown('<div class="md-section">Datasets</div>', unsafe_allow_html=True)
    current = current_datasets()
    chosen = [k for k in DATASETS
              if container.checkbox(DATASETS[k]["label"], value=k in current,
                                    key=f"_map_ds_{k}_{st.session_state.get('_page', '')}",
                                    disabled=current == [k])]
    st.session_state["datasets"] = chosen or current


def filter_bar(df: pd.DataFrame, split: bool = False, inline: bool = False):
    """Year, cluster and size checkboxes. Returns the filtered rows, or with
    split=True (filtered, filtered_without_the_size_filter) for pages that
    show what the size cut-off does.

    inline=False puts them in the sidebar (analysis pages). inline=True puts
    them in a card above the content together with the dataset checkboxes
    (map page), so they sit right next to what they change.
    """
    if df.empty:
        return (df, df) if split else df
    years = sorted(df["year_label"].unique().tolist())
    clusters = sorted(df["cluster_name"].unique().tolist())
    sizes = [s for s in SIZE_ORDER if s in set(df["size_label"])]

    if inline:
        c = card()
        ds_col, cl_col, yr_col, sz_col = c.columns([1.1, 1.1, 1.3, 1], gap="medium")
        _dataset_checkboxes(ds_col)
        sel_cl = _checkbox_group(cl_col, "Location cluster (k-means)", clusters, "_f_cluster", cols=1)
        sel_years = _checkbox_group(yr_col, "Year of deforestation", years, "_f_year", cols=3)
        sel_sizes = _checkbox_group(sz_col, "Polygon size (10 m pixels)", sizes, "_f_size",
                                    default_off=("<1 px",), cols=1)
        note = c.caption
    else:
        st.sidebar.markdown("#### Filter polygons")
        sel_years = _checkbox_group(st.sidebar, "Year of deforestation", years, "_f_year")
        sel_cl = _checkbox_group(st.sidebar, "Location cluster (k-means)", clusters, "_f_cluster", cols=1)
        sel_sizes = _checkbox_group(st.sidebar, "Polygon size (in 10 m pixels)", sizes, "_f_size",
                                    default_off=("<1 px",))
        note = st.sidebar.caption

    unsized = df[df["year_label"].isin(sel_years) & df["cluster_name"].isin(sel_cl)]
    out = unsized[unsized["size_label"].isin(sel_sizes)]
    n_small_off = int((unsized["size_label"] == "<1 px").sum()) if "<1 px" not in sel_sizes else 0
    note(f"{len(out)} of {len(df)} polygons match"
         + (f" · {n_small_off} smaller than one pixel left out" if n_small_off else "")
         + (". The map zooms to them after every change." if inline else ""))
    return (out, unsized) if split else out


def fit_key(df: pd.DataFrame, *extra) -> str:
    """Changes whenever the shown polygons change, which tells the map to refit."""
    h = hashlib.sha1((",".join(map(str, sorted(df["id"].tolist()))) + "|" + "|".join(map(str, extra))).encode())
    return h.hexdigest()[:16]
