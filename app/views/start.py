"""Choose data: pick a saved polygon set or upload a new one, then open the map."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from core import db
from pipeline import earth_engine as eec
from pipeline import polygon_sets as ps
from pipeline.extraction import run_extraction

ui.page_header("Choose data", "Pick a polygon set or upload one. Results that were calculated before are "
               "cached and open instantly.", show_selection=False)

ee = eec.status()
sets = db.polygon_sets()
if sets.empty:
    ui.callout("No polygon sets yet. The reference set is imported when the app starts; check the logs.", "err")
    st.stop()

sid = ui.current_set_id()
flash = st.session_state.pop("_flash", None)
if flash:
    ui.callout(flash[1], flash[0])

left, _ = st.columns([2, 1], gap="medium")

# ------------------------------------------------------------------
# 1. polygon set
# ------------------------------------------------------------------
with left:
    c = ui.card("Polygon set")
    labels = {}
    for _, s in sets.iterrows():
        yrs = (f"{int(s['year_min'])}–{int(s['year_max'])}" if pd.notna(s["year_min"]) else "no years")
        flag = "📌 " if s["pinned"] else ""
        cached = "cached" if pd.notna(s["run_id"]) else "not calculated"
        labels[int(s["id"])] = f"{flag}{s['name']} · {int(s['n_polygons'])} polygons · {yrs} · {cached}"
    ids = list(labels)
    pick = c.selectbox("Cached polygon sets", ids, index=ids.index(sid) if sid in ids else 0,
                       format_func=labels.get, help="📌 = reference set, always kept")
    if pick != sid:
        st.session_state["set_id"] = sid = pick
        st.session_state.pop("sel_polygon", None)
        db.touch_set(pick)
        st.rerun()

    s = db.polygon_set(sid)
    df = ui.polygons()
    n_cl = df.loc[df["cluster_id"].notna(), "cluster_name"].nunique() if not df.empty else 0
    chips = [f"{s['n_polygons']} polygons", f"{s['n_subpixel']} smaller than a pixel",
             f"{n_cl} location clusters", f"file: {s['source_filename'] or '–'}"]
    c.markdown("".join(f'<span class="md-chip">{x}</span>' for x in chips), unsafe_allow_html=True)
    if not df.empty:
        cl = df["cluster_name"].value_counts()
        c.caption("Clusters: " + " · ".join(f"{k} ({v})" for k, v in cl.items()))

    run = db.latest_run(sid)
    b, _ = c.columns([1, 2])
    if run:
        if b.button("Open map", type="primary", icon=":material/map:", use_container_width=True):
            st.switch_page("views/map.py")
    elif b.button("Calculate now", type="primary", icon=":material/refresh:", use_container_width=True,
                  disabled=not ee["ok"]):
        with st.spinner("Calculating both datasets for every polygon…"):
            res = run_extraction(sid)
        st.cache_data.clear()
        st.session_state["_flash"] = ("ok" if res["status"] == "ok" else "err", f"Run #{res['run_id']}: {res['note']}")
        st.rerun()

    with c.expander("Upload a new polygon set", icon=":material/upload_file:"):
        st.caption(f"GeoJSON FeatureCollection of polygons in WGS84 longitude/latitude, up to "
                   f"{ps.MAX_FEATURES:,} polygons and {ps.MAX_BYTES // 1024 // 1024} MB. A `year` property is "
                   f"used if present. The new polygons are assigned to the existing location clusters and both "
                   f"datasets are calculated for them (a few seconds per 1,000 polygons). The "
                   f"{ps.CACHE_MAX_SETS} most recently used uploads are kept; the least recently used one is "
                   f"removed when that is exceeded. The reference set is always kept.")
        f = st.file_uploader("GeoJSON file", type=["geojson", "json"], label_visibility="collapsed")
        name = st.text_input("Name for this set", placeholder="e.g. Ghana cocoa clearings 2023")
        go = st.button("Upload and calculate", type="primary", icon=":material/cloud_upload:",
                       disabled=f is None or not ee["ok"])
        if not ee["ok"]:
            st.caption("Uploading needs Earth Engine, which is not connected right now.")
        if go and f is not None:
            raw = f.getvalue()
            try:
                with st.spinner("Checking the file, assigning clusters and calculating both datasets…"):
                    res = ps.add_upload(name.strip() or f.name, f.name, raw)
            except ps.UploadError as e:
                ui.callout(f"<b>Upload rejected.</b> {e}", "err")
            else:
                st.session_state["set_id"] = res["set_id"]
                st.session_state.pop("sel_polygon", None)
                st.cache_data.clear()
                msg = res["note"] if res["status"] == "cached" else f"Calculated: {res['note']}."
                if res["evicted"]:
                    msg += " Removed from cache (least recently used): " + ", ".join(res["evicted"]) + "."
                st.session_state["_flash"] = ("ok" if res["status"] in ("ok", "cached") else "err", msg)
                st.rerun()
