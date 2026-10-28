"""Polygon table: every number behind the charts, sortable and downloadable."""
from __future__ import annotations

import streamlit as st

import ui
from analytics import metrics as an

ui.page_header("Polygon table")
st.caption("One row per polygon of the selected set. Select a row to open it on the map.")

all_df = ui.polygons()
if all_df.empty:
    st.warning("No polygons in the database yet.")
    st.stop()
in_stats, df = ui.filter_bar(all_df, split=True)  # table lists every polygon
df = df.assign(in_stats=df["id"].isin(in_stats["id"]))

cols = ["id", "region_name", "cluster_name", "source_year", "area_m2", "size_label", "in_stats", "category", "gfc_forest",
        "forty_tree", "forty_forest_eudr", "forty_natural", "forty_treecrops", "forty_other",
        "forty_dominant", "pixel_agreement", "forty_conf_mean", "px_count", "centroid_lat", "centroid_lon"]
view = df[[c for c in cols if c in df.columns]]
def share(label, help_=None):
    return st.column_config.ProgressColumn(label, min_value=0, max_value=1, format="%.2f", help=help_)
event = st.dataframe(
    view, hide_index=True, use_container_width=True, height=560,
    on_select="rerun", selection_mode="single-row",
    column_config={
        "id": st.column_config.NumberColumn("ID", width="small"),
        "region_name": "Region", "cluster_name": "Cluster", "source_year": st.column_config.NumberColumn("Year", format="%d"),
        "area_m2": st.column_config.NumberColumn("Area (m²)", format="%.0f"),
        "size_label": "Size", "category": "Category",
        "in_stats": st.column_config.CheckboxColumn(
            "In stats", help="Included in statistics under the current minimum polygon size"),
        "gfc_forest": share("GFC forest", "Share of area GFC2020 maps as forest"),
        "forty_tree": share("ForTy trees", "ForTy classes 1-5"),
        "forty_forest_eudr": share("ForTy forest", "ForTy classes 1-4 (EUDR-style forest)"),
        "forty_natural": share("ForTy natural", "ForTy classes 1-2"),
        "forty_treecrops": share("Tree crops", "ForTy class 5"),
        "forty_other": share("Other land", "ForTy class 6"),
        "forty_dominant": "ForTy main class",
        "pixel_agreement": share("Agreement", "Share of pixels where both agree on forest vs not"),
        "forty_conf_mean": share("ForTy conf.", "Mean winning-class score"),
        "px_count": st.column_config.NumberColumn("Pixels", help="Pixel centres inside the polygon"),
        "centroid_lat": st.column_config.NumberColumn("Lat", format="%.5f"),
        "centroid_lon": st.column_config.NumberColumn("Lon", format="%.5f"),
    },
)

rows = event.selection.rows if event and event.selection else []
c1, c2, _ = st.columns([1, 1, 3])
if rows:
    pid = int(view.iloc[rows[0]]["id"])
    if c1.button(f"Open #{pid} on the map", type="primary", icon=":material/map:"):
        st.session_state["sel_polygon"] = pid
        st.switch_page("views/map.py")
c2.download_button("Download CSV", view.to_csv(index=False).encode(), "gras_polygons.csv", "text/csv",
                   icon=":material/download:")
st.caption(f"{len(an.valid(df))} of {len(df)} polygons have extraction results; {int(df['in_stats'].sum())} "
           "meet the minimum polygon size used for statistics. Shares are fractions (0-1) of the polygon's "
           "area-weighted 10 m pixels.")
