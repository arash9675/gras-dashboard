"""Map: the polygons of the chosen set on an open-source map (MapLibre with
OpenStreetMap or satellite imagery), coloured by what the chosen dataset(s) say
inside them. The view fits the shown polygons after every filter change;
between changes the user zooms and pans freely.

Controls: the card above the map picks datasets and filters polygons; the row
below it sets the polygon colour, an optional dataset layer (Earth Engine
tiles, off by default) and the background.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import ui
from analytics import metrics as an
from pipeline import earth_engine as eec
from ui.mapview import LAYER_MINZOOM, LAYERS, dataset_layer, map_view

ui.page_header("Map")

all_df = ui.polygons(with_geometry=True)
if all_df.empty or an.valid(all_df).empty:
    ui.callout("This polygon set has no results yet. Calculate it on <b>Choose data</b>.", "info")
    st.stop()


# Datasets and filters sit in one card above the map; the map shows exactly what they select.
df = ui.filter_bar(all_df, inline=True)
datasets = ui.current_datasets()   # read after the card: it holds the dataset checkboxes
has_gfc, has_forty = "gfc" in datasets, "forty" in datasets
if df.empty:
    ui.callout("No polygons match the filters.", "info")
    st.stop()

# ------------------------------------------------------------------
# Polygon colour
# ------------------------------------------------------------------
GFC_BINS = [(0.0, "#BDC1C6", "0–20%"), (0.2, "#CEEAD6", "20–40%"), (0.4, "#81C995", "40–60%"),
            (0.6, "#34A853", "60–80%"), (0.8, "#137333", "80–100%")]
COLOUR_MODES = {}
if has_gfc:
    COLOUR_MODES["gfc"] = "GFC2020: share mapped as forest"
if has_forty:
    COLOUR_MODES["forty"] = "ForTy: main forest type"
if has_gfc and has_forty:
    COLOUR_MODES["agree"] = "Do the two agree?"
modes = list(COLOUR_MODES)
saved_mode = st.session_state.get("_colour_mode")
c_col, l_col, b_col = st.columns([2.7, 1.2, 1.1])
if len(modes) > 1:
    mode = c_col.radio("Polygon colour", modes, index=modes.index(saved_mode) if saved_mode in modes else 0,
                       format_func=COLOUR_MODES.get, horizontal=True)
else:
    mode = modes[0]
    c_col.caption(f"Polygon colour: {COLOUR_MODES[mode]}. Tick both datasets above to compare them.")
st.session_state["_colour_mode"] = mode
BASEMAPS = {"osm": "Map", "sat": "Satellite"}
basemap = b_col.radio("Background", list(BASEMAPS), format_func=BASEMAPS.get, horizontal=True,
                      index=list(BASEMAPS).index(st.session_state.get("_basemap", "osm")))
st.session_state["_basemap"] = basemap

# The dataset itself, drawn by Earth Engine under the polygons. Off by default:
# the polygon colours already summarise it, and the tiles take a moment to load.
layer_opts = [None] + [k for k in LAYERS if (k == "gfc" and has_gfc) or (k == "forty" and has_forty)
                       or (k == "differ" and has_gfc and has_forty)]
saved_layer = st.session_state.get("_layer")
layer_name = l_col.selectbox("Dataset layer", layer_opts, format_func=lambda k: LAYERS.get(k, "Off"),
                             index=layer_opts.index(saved_layer) if saved_layer in layer_opts else 0)
st.session_state["_layer"] = layer_name
layer = dataset_layer(layer_name)
if layer_name and layer is None:
    l_col.caption("Earth Engine is not reachable, so the layer is off.")


def color_of(r) -> str:
    if mode == "agree":
        return ui.CATEGORY_COLORS.get(r["category"], "#9AA0A6")
    if mode == "gfc":
        v = r["gfc_forest"]
        if v is None or v != v:
            return "#9AA0A6"
        return [c for lo, c, _ in GFC_BINS if v >= lo - 1e-9][-1]
    return ui.FORTY_CLASS_COLORS.get(r["forty_dominant"], "#9AA0A6")


if mode == "agree":
    legend = ui.CATEGORY_COLORS
    legend_title = "Polygon colour: does each dataset map at least half the polygon as forest/trees?"
elif mode == "gfc":
    legend = {lab: c for _, c, lab in GFC_BINS}
    legend_title = "Polygon colour: share of the polygon GFC2020 maps as forest"
else:
    legend = ui.FORTY_CLASS_COLORS
    legend_title = "Polygon colour: ForTy class covering most of the polygon"

features = []
for _, r in df.iterrows():
    parts = []
    if has_gfc:
        parts.append(f"GFC2020 forest {ui.pct(r['gfc_forest'])}")
    if has_forty:
        parts.append(f"ForTy: {r['forty_dominant'] or '–'}")
    tip = (f"<b>#{r['id']}</b> · {r['cluster_name']} · {r['year_label']}<br>{r['area_m2']:,.0f} m²"
           f"<br>{' · '.join(parts)}")
    tiny = bool(r["area_m2"] < an.PIXEL_M2)
    if tiny:
        tip += "<br><i>Smaller than one pixel: left out of statistics</i>"
    features.append({"type": "Feature", "geometry": r["geometry"],
                     "properties": {"id": int(r["id"]), "color": color_of(r), "tiny": tiny, "tip": tip,
                                    "c": [float(r["centroid_lon"]), float(r["centroid_lat"])]}})
fc = {"type": "FeatureCollection", "features": features}
pad = 0.002
bounds = [[float(df["centroid_lon"].min()) - pad, float(df["centroid_lat"].min()) - pad],
          [float(df["centroid_lon"].max()) + pad, float(df["centroid_lat"].max()) + pad]]

# ------------------------------------------------------------------
# Selection
# ------------------------------------------------------------------
ids = df["id"].tolist()
sel = st.session_state.get("sel_polygon")
if sel not in ids:
    sel = None
focus = None
if sel is not None:
    rsel = df.loc[df["id"] == sel].iloc[0]
    focus = [float(rsel["centroid_lon"]), float(rsel["centroid_lat"])]

left, right = st.columns([2.3, 1], gap="medium")
with left:
    out = map_view(fc, bounds, ui.fit_key(df, ui.current_set_id()), selected=sel,
                   select_key=f"{sel}-{st.session_state.get('_sel_nonce', 0)}", focus=focus, height=620,
                   basemap=basemap, layer=layer)
    st.markdown(f'<div class="md-section">{legend_title}</div>', unsafe_allow_html=True)
    ui.legend(legend)
    if layer:
        if layer_name == "gfc":
            layer_legend = {"Forest": eec.GFC_FOREST_COLOR}
        elif layer_name == "forty":
            layer_legend = {n: c for n, c in eec.FORTY_CLASSES.values()}
        else:
            layer_legend = eec.DIFFER_COLORS
        st.markdown(f'<div class="md-section">Dataset layer: {LAYERS[layer_name]} (10 m pixels, from zoom '
                    f'{LAYER_MINZOOM})</div>', unsafe_allow_html=True)
        ui.legend(layer_legend)
    st.caption("Dashed outlines and faded dots, when '<1 px' is ticked: polygons smaller than one 10 m pixel.")

if out and out.get("nonce") != st.session_state.get("_last_click") and out.get("id") in ids:
    st.session_state["_last_click"] = out["nonce"]
    if out["id"] != sel:
        st.session_state["sel_polygon"] = out["id"]
        st.rerun()

# ------------------------------------------------------------------
# Inspector
# ------------------------------------------------------------------
with right:
    c = ui.card()
    opts = [None, *ids]

    def _label(i):
        if i is None:
            return "None selected"
        r = df.loc[df["id"] == i].iloc[0]
        return f"#{i} · {r['cluster_name']} · {r['year_label']} · {r['area_m2']:,.0f} m²"

    pick = c.selectbox("Inspect a polygon", opts, index=opts.index(sel), format_func=_label)
    if pick != sel:
        st.session_state["sel_polygon"] = pick
        st.session_state["_sel_nonce"] = st.session_state.get("_sel_nonce", 0) + 1
        st.rerun()
    v = an.valid(df)
    if sel is None:
        c.markdown(f"**{len(df)} polygons** on the map · {int((df['area_m2'] < an.PIXEL_M2).sum())} smaller than one pixel")
        k = c.columns(len(datasets))
        i = 0
        if has_gfc:
            ui.kpi(k[i], "GFC2020 forest", ui.pct(v["gfc_forest"].mean()), "mean share")
            i += 1
        if has_forty:
            ui.kpi(k[i], "ForTy trees", ui.pct(v["forty_tree"].mean()), "mean share, classes 1-5")
        c.caption("Click a polygon or dot on the map, or pick one above.")
        if has_gfc and has_forty:
            cat = df["category"].value_counts()
            c.markdown("**Do the two agree?** (polygons)")
            for name, color in ui.CATEGORY_COLORS.items():
                c.markdown(f'<span class="pill" style="background:{color}">{cat.get(name, 0)}</span> {name}',
                           unsafe_allow_html=True)
        else:
            dom = df["forty_dominant"].value_counts() if has_forty else None
            if dom is not None:
                c.markdown("**ForTy main type** (polygons)")
                for name, color in ui.FORTY_CLASS_COLORS.items():
                    c.markdown(f'<span class="pill" style="background:{color}">{dom.get(name, 0)}</span> {name}',
                               unsafe_allow_html=True)
    else:
        r = rsel
        badge = ""
        if has_gfc and has_forty:
            cat_color = ui.CATEGORY_COLORS.get(r["category"], "#9AA0A6")
            badge = f'<span class="pill" style="background:{cat_color}">{r["category"] or "no result"}</span> '
        c.markdown(f'{badge}{r["cluster_name"]} · deforested {r["year_label"]}', unsafe_allow_html=True)
        c.markdown(f"**{r['area_m2']:,.0f} m²** (≈ {r['approx_pixels']:.1f} pixels)")
        k = c.columns(len(datasets))
        i = 0
        if has_gfc:
            ui.kpi(k[i], "GFC2020 forest", ui.pct(r["gfc_forest"]), "of the polygon")
            i += 1
        if has_forty:
            ui.kpi(k[i], "ForTy trees", ui.pct(r["forty_tree"]), f"confidence {ui.pct(r['forty_conf_mean'])}")
        if r["gfc_forest"] is not None and r["gfc_forest"] == r["gfc_forest"]:
            fig = go.Figure()
            if has_forty:
                for n, col in zip(ui.FORTY_CLASS_COLORS, an.FORTY_COLS, strict=False):
                    fig.add_bar(y=["ForTy"], x=[r[col]], name=n, orientation="h",
                                marker_color=ui.FORTY_CLASS_COLORS[n],
                                hovertemplate=f"{n}: %{{x:.0%}}<extra></extra>")
            if has_gfc:
                fig.add_bar(y=["GFC2020"], x=[r["gfc_forest"]], orientation="h",
                            marker_color=eec.GFC_FOREST_COLOR, hovertemplate="Forest: %{x:.0%}<extra></extra>")
                fig.add_bar(y=["GFC2020"], x=[1 - r["gfc_forest"]], orientation="h", marker_color="#DADCE0",
                            hovertemplate="Not forest: %{x:.0%}<extra></extra>")
            fig.update_layout(barmode="stack", height=60 + 55 * len(datasets), margin=dict(l=0, r=0, t=6, b=0),
                              showlegend=False, xaxis=dict(tickformat=".0%", range=[0, 1]), font=dict(family="Roboto"))
            c.markdown("**What each dataset says inside the polygon**")
            c.plotly_chart(fig, use_container_width=True, key=f"insp_{sel}")
            if has_gfc and has_forty:
                c.markdown(
                    f"| Same pixels | ForTy: trees | ForTy: no trees |\n|---|---|---|\n"
                    f"| **GFC2020: forest** | {ui.pct(r['x_ff'])} | {ui.pct(r['x_fn'])} |\n"
                    f"| **GFC2020: not forest** | {ui.pct(r['x_nf'])} | {ui.pct(r['x_nn'])} |")
        fl = an.flags(df[df["id"] == sel])
        if not fl.empty:
            ui.callout(fl.iloc[0]["reasons"])
        c.caption(f"Centroid {r['centroid_lat']:.5f}, {r['centroid_lon']:.5f}")
