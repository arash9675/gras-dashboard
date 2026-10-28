"""Overview: the answer in one screen."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import ui
from analytics import metrics as an

ui.page_header("Overview")
st.markdown("### Do the 2020 forest maps see the trees that were later cleared?")
st.markdown(
    "Every polygon below was **tree-covered before 2020 and cleared afterwards**. "
    "A good 2020 baseline for deforestation mapping should show trees there. "
    "This page compares what each dataset says inside those polygons."
)

all_df = ui.polygons()
if all_df.empty or an.valid(all_df).empty:
    ui.callout("No Earth Engine results yet. Calculate this polygon set on "
               "<b>Choose data</b> (a few seconds), or check the Earth Engine connection.", "info")
    st.stop()

df, df_all_sizes = ui.filter_bar(all_df, split=True)
v = an.valid(df)
n_small = len(df_all_sizes) - len(df)
if v.empty:
    st.warning("No polygons match the filters.")
    st.stop()
h = an.headline(df)

c = st.columns(5)
n_reg = v["region_name"].value_counts()
ui.kpi(c[0], "Polygons in statistics", f"{len(v)}", " · ".join(f"{k} {n}" for k, n in n_reg.items())
       + (f"<br>{n_small} too small, left out" if n_small else ""))
ui.kpi(c[1], "GFC2020 says forest", ui.pct(h["gfc_forest"]), "mean share of polygon area")
ui.kpi(c[2], "ForTy says trees", ui.pct(h["forty_tree"]), "classes 1-5, mean share")
ui.kpi(c[3], "Pixel agreement", ui.pct(h["agreement"]), "forest vs non-forest, same pixel")
ui.kpi(c[4], "Tree crops / agroforestry", ui.pct(h["treecrops"]), "ForTy class 5, mean share")

st.write("")
left, right = st.columns([1.15, 1])

with left:
    st.subheader("How much of each polygon is forest in 2020?")
    st.caption("Mean share of polygon area per region. Bars show 95% bootstrap intervals over polygons.")
    mt = an.metric_table(df, by="region_name")
    fig = go.Figure()
    for metric, color in ui.METRIC_COLORS.items():
        d = mt[mt["metric"] == metric]
        fig.add_bar(name=metric, y=d["region_name"], x=d["mean"], orientation="h",
                    marker_color=color,
                    error_x=dict(type="data", symmetric=False, array=d["hi"] - d["mean"],
                                 arrayminus=d["mean"] - d["lo"], thickness=1.2, width=3),
                    hovertemplate="%{y}: %{x:.0%}<extra>" + metric + "</extra>")
    fig.update_layout(barmode="group", height=360, margin=dict(l=0, r=10, t=10, b=0),
                      xaxis=dict(tickformat=".0%", range=[0, 1], title=None),
                      yaxis=dict(title=None, autorange="reversed"),
                      legend=dict(orientation="h", y=-0.15, x=0))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("What ForTy thinks the trees were")
    st.caption("Mean ForTy class composition inside the polygons.")
    comp = an.forty_composition(df, by="region_name")
    fig = go.Figure()
    for cls, color in ui.FORTY_CLASS_COLORS.items():
        d = comp[comp["class"] == cls]
        fig.add_bar(name=cls, y=d["region_name"], x=d["share"], orientation="h", marker_color=color,
                    marker_line=dict(color="rgba(0,0,0,.25)", width=0.5),
                    hovertemplate="%{y}: %{x:.0%}<extra>" + cls + "</extra>")
    fig.update_layout(barmode="stack", height=360, margin=dict(l=0, r=10, t=10, b=0),
                      xaxis=dict(tickformat=".0%", range=[0, 1], title=None),
                      yaxis=dict(title=None, autorange="reversed"),
                      legend=dict(orientation="h", y=-0.15, x=0))
    st.plotly_chart(fig, use_container_width=True)

st.subheader("What this means")
lines = []
for reg, name in an.REGIONS.items():
    r = h.get(reg)
    if not r or not r["n"]:
        continue
    gap = r["forty_tree"] - r["gfc_forest"]
    lines.append(
        f"- **{name}** ({r['n']} polygons): ForTy sees trees on **{ui.pct(r['forty_tree'])}** of the area, "
        f"GFC2020 sees forest on **{ui.pct(r['gfc_forest'])}**, a gap of {gap * 100:.0f} points. "
        f"ForTy's most common class is *{r['dominant']}*; tree crops make up {ui.pct(r['forty_treecrops'])} "
        f"and plantations {ui.pct(r['forty_plantation'])}."
    )
st.markdown("\n".join(lines))
ui.callout(
    "<b>How far these numbers go.</b> The polygons show where trees were cleared, so they can reveal tree cover a "
    "map misses. They cannot show where a map invents forest, and two maps giving the same answer could share the "
    "same mistake. <b>Findings</b> explains what we conclude and what we would check next."
)
