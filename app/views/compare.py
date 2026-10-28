"""Compare datasets: agreement, distributions, scale, confidence, time, flags."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui
from analytics import metrics as an

ui.page_header("Compare datasets")

all_df = ui.polygons()
if an.valid(all_df).empty:
    st.info("No results yet. Calculate this polygon set on Choose data.")
    st.stop()
df, df_all_sizes = ui.filter_bar(all_df, split=True)
v = an.valid(df)
if v.empty:
    st.warning("No polygons match the filters.")
    st.stop()

tabs = st.tabs(["Agreement", "Per polygon", "Polygon size", "ForTy confidence", "By year", "Odd labels"])

# ------------------------------------------------------------------
# Agreement
# ------------------------------------------------------------------
with tabs[0]:
    st.markdown("Where the two maps put the **same pixels**. Rows are GFC2020, columns are ForTy classes; "
                "cells are shares of all pixel area in the selected polygons.")
    scope = st.radio("Scope", ["All selected", *sorted(v["region_name"].unique())], horizontal=True)
    sub = v if scope == "All selected" else v[v["region_name"] == scope]
    mat = an.agreement_matrix(sub)
    c1, c2 = st.columns([1.6, 1])
    with c1:
        short = ["Primary", "Natural regen.", "Planted", "Plantation", "Tree crops", "Other land"]
        fig = px.imshow(mat.values, x=short, y=list(mat.index), text_auto=".1%",
                        color_continuous_scale="YlGn", zmin=0, zmax=max(0.01, mat.values.max()), aspect="auto")
        fig.update_traces(hovertemplate="%{y} × %{x}: %{z:.1%}<extra></extra>")
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False,
                          xaxis=dict(side="top", title=None, tickangle=0), yaxis=dict(title=None),
                          font=dict(size=13))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        nf = mat.loc["GFC non-forest"]
        natural = nf["Primary forest"] + nf["Naturally regenerating"]
        managed = nf["Planted forest"] + nf["Plantation forest"]
        crops = nf["Tree crops / agroforestry"]
        total_nf = nf.sum()
        st.markdown(f"**Where GFC2020 says non-forest ({ui.pct(total_nf, 1)} of all pixels), ForTy says…**")
        for label, val, color in [("natural forest: true conflict", natural, "#DC2626"),
                                  ("planted / plantation: partly definitional", managed, "#E65FA9"),
                                  ("tree crops: definitional (EUDR excludes)", crops, "#E6AB02"),
                                  ("other land: both see no forest", nf["Other land"], "#9CA3AF")]:
            share = val / total_nf if total_nf else 0
            st.markdown(f'<span class="pill" style="background:{color}">{ui.pct(share)}</span> {label} '
                        f'<span style="opacity:.65">({ui.pct(val, 1)} of all pixels)</span>',
                        unsafe_allow_html=True)
        st.caption("The badges are shares of the GFC2020 non-forest area, so they add up to 100%; the grey "
                   "figure is the same cell as a share of all pixels, as in the table.")
    ui.callout("High agreement would not prove either map right: both are built from overlapping satellite "
               "inputs and could share errors. Use this to see <i>where and why</i> they differ.", "info")

    st.markdown("##### Polygon-level agreement categories")
    cc = an.category_counts(v, by="region_name")
    fig = px.bar(cc, y="region_name", x="n", color="category", orientation="h",
                 category_orders={"category": an.CATEGORY_ORDER}, color_discrete_map=ui.CATEGORY_COLORS,
                 text=cc["n"].astype(str), custom_data=["share"])
    fig.update_traces(hovertemplate="%{y}: %{x} polygons (%{customdata[0]:.0%})<extra>%{fullData.name}</extra>")
    fig.update_layout(height=200, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis=dict(title="Polygons", tickformat=",d"),
                      yaxis=dict(title=None), legend=dict(orientation="h", y=-0.45, title=None))
    st.plotly_chart(fig, use_container_width=True)
    totals = "; ".join(
        f"{reg}: {int((v['region_name'] == reg).sum())} of {int((df_all_sizes['region_name'] == reg).sum())}"
        for reg in sorted(v["region_name"].unique()))
    st.caption(f"Counts of polygons ({totals}; the rest are left out by the size filter). 'Forest' = at least "
               "half the polygon's area; ForTy counts classes 1-5 (any tree class). The table above is "
               "pixel area instead, so a polygon count and a pixel share of the same group differ.")

# ------------------------------------------------------------------
# Per polygon
# ------------------------------------------------------------------
with tabs[1]:
    st.markdown("Each dot is one polygon. Points on the diagonal mean both maps agree on the forest share.")
    yopt = {"ForTy: any tree class (1-5)": "forty_tree", "ForTy: forest classes (1-4)": "forty_forest_eudr",
            "ForTy: natural forest (1-2)": "forty_natural"}
    ylab = st.radio("ForTy measure", list(yopt), horizontal=True)
    fig = px.scatter(v, x="gfc_forest", y=yopt[ylab], color="region_name", size="area_m2", size_max=28,
                     color_discrete_map=ui.REGION_COLORS, opacity=0.75,
                     hover_data={"id": True, "source_year": True, "area_m2": ":,.0f", "region_name": False,
                                 "gfc_forest": ":.0%", yopt[ylab]: ":.0%"},
                     labels={"gfc_forest": "GFC2020 forest share", yopt[ylab]: ylab, "region_name": "Region"})
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1, line=dict(dash="dot", color="gray"))
    fig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis=dict(tickformat=".0%", range=[-0.03, 1.03]),
                      yaxis=dict(tickformat=".0%", range=[-0.03, 1.03]))
    st.plotly_chart(fig, use_container_width=True)

    long = v.melt(id_vars=["id", "region_name"], value_vars=list(an.METRICS), var_name="m", value_name="share")
    long["metric"] = long["m"].map(an.METRICS)
    fig = px.box(long, x="share", y="metric", color="region_name", points="all", orientation="h",
                 color_discrete_map=ui.REGION_COLORS, labels={"share": "Share of polygon area", "metric": ""})
    fig.update_traces(jitter=0.4, pointpos=0, marker=dict(size=4, opacity=0.5))
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(tickformat=".0%"),
                      legend=dict(orientation="h", y=-0.15, title=None), boxmode="group")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Most values sit at 0% or 100%: polygons are small, so a few pixels decide the share.")

# ------------------------------------------------------------------
# Size
# ------------------------------------------------------------------
with tabs[2]:
    va = an.valid(df_all_sizes)
    sub = va[va["area_m2"] < an.PIXEL_M2]
    st.markdown("Both maps have 10 m pixels, so one pixel covers 100 m². Polygon size decides how much "
                "a result can be trusted. This tab ignores the minimum-size filter so you can see the effect.")
    if len(sub):
        ex = sub.sort_values("area_m2").iloc[0]
        ui.callout(
            f"<b>What happens to polygons smaller than a pixel ({len(sub)} of {len(va)}).</b> Earth Engine "
            f"still gives them the value of the whole 10 m pixel they touch. Polygon #{ex['id']} covers "
            f"{ex['area_m2']:.0f} m², but it is judged by a 100 m² pixel, so about "
            f"{(1 - ex['area_m2'] / an.PIXEL_M2) * 100:.0f}% of that evidence lies outside the cleared area. "
            f"One or two pixels decide the result: {ui.pct(an.all_or_nothing_share(sub))} of them come out "
            f"as exactly 0% or 100% for both maps. They are left out of statistics by default and kept on the "
            f"map with a flag. Change this with <i>Minimum polygon size</i> in the sidebar.")

    st.markdown("##### How the headline numbers change as small polygons are dropped")
    sens = an.sensitivity(df_all_sizes)
    fig = go.Figure()
    fig.add_bar(x=sens["min_area_m2"].astype(str), y=sens["n"], name="Polygons kept", yaxis="y2",
                marker_color="rgba(156,163,175,.35)", hovertemplate="%{y} polygons<extra></extra>")
    for col, name, color in [("gfc_forest", "GFC2020 forest", ui.GFC_COLOR),
                             ("forty_tree", "ForTy trees", ui.FORTY_COLOR),
                             ("agreement", "Pixel agreement", "#111827")]:
        fig.add_scatter(x=sens["min_area_m2"].astype(str), y=sens[col], name=name, mode="lines+markers",
                        line=dict(color=color, width=2.5), hovertemplate="%{y:.0%}<extra>" + name + "</extra>")
    fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis=dict(title="Minimum polygon area (m²)", type="category"),
                      yaxis=dict(tickformat=".0%", range=[0, 1.05], title="Mean share"),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Polygons kept",
                                  range=[0, max(1, sens["n"].max()) * 1.1]),
                      legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, use_container_width=True)
    s0, s100 = sens.iloc[0], sens[sens["min_area_m2"] == 100].iloc[0]
    s5k = sens[sens["min_area_m2"] == 5000].iloc[0]
    st.caption(
        f"All polygons: GFC {ui.pct(s0['gfc_forest'])}, ForTy {ui.pct(s0['forty_tree'])}. "
        f"Without sub-pixel ones: GFC {ui.pct(s100['gfc_forest'])}, ForTy {ui.pct(s100['forty_tree'])}. "
        f"Only polygons of 0.5 ha or more ({int(s5k['n'])}): GFC {ui.pct(s5k['gfc_forest'])}, "
        f"ForTy {ui.pct(s5k['forty_tree'])}. " + an.size_effect_note(df_all_sizes))

    st.markdown("##### Results by size class")
    bs = an.by_size(va)
    bs["size"] = bs["size_class"].str.split(": ").str[1]
    st.caption("Split by region, because the large polygons are mostly in Brazil.")
    br = (va.groupby(["region_name", "size_class"])
            .agg(n=("id", "size"), gfc_forest=("gfc_forest", "mean"), forty_tree=("forty_tree", "mean"))
            .reset_index())
    br["size"] = br["size_class"].str.split(": ").str[1]
    long = br.melt(id_vars=["region_name", "size", "n"], value_vars=["gfc_forest", "forty_tree"],
                   var_name="m", value_name="share")
    long["dataset"] = long["m"].map({"gfc_forest": "GFC2020 forest", "forty_tree": "ForTy trees"})
    c1, c2 = st.columns([1.3, 1])
    with c1:
        fig = px.bar(long, x="size", y="share", color="dataset", barmode="group", facet_col="region_name",
                     text="n", color_discrete_map={"GFC2020 forest": ui.GFC_COLOR, "ForTy trees": ui.FORTY_COLOR},
                     labels={"size": "Polygon size", "share": "Mean share", "region_name": "Region", "n": "Polygons"})
        fig.update_traces(texttemplate="n=%{text}", textposition="outside", textfont_size=10)
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=30, b=0), yaxis=dict(tickformat=".0%", range=[0, 1.15]),
                          legend=dict(orientation="h", y=-0.3, title=None))
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.dataframe(bs[["size", "n", "gfc_forest", "forty_tree", "agreement", "agreement_sd"]],
                     hide_index=True, use_container_width=True,
                     column_config={
                         "size": "Size", "n": "Polygons",
                         "gfc_forest": st.column_config.NumberColumn("GFC forest", format="%.2f"),
                         "forty_tree": st.column_config.NumberColumn("ForTy trees", format="%.2f"),
                         "agreement": st.column_config.NumberColumn("Agreement", format="%.2f"),
                         "agreement_sd": st.column_config.NumberColumn("Agreement SD", format="%.2f")})
        st.caption("Values are mean shares (0-1). A high SD means the result flips between 0 and 1.")
    st.markdown("##### Per polygon or per square metre?")
    st.markdown("A per-polygon mean counts every clearing once, so tiny polygons weigh as much as large ones. "
                "An area-weighted mean counts every square metre once, so a few large polygons dominate. "
                "A big difference between the two means size is driving the result.")
    wt = an.weighting_table(df)
    st.dataframe(wt, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(c, format="%.2f")
                                for c in wt.columns if c not in ("Region", "Polygons")})
    st.caption("Uses the polygons selected in the sidebar (including the minimum-size filter).")

    fig = px.scatter(va, x="area_m2", y="pixel_agreement", color="region_name", log_x=True, opacity=0.7,
                     color_discrete_map=ui.REGION_COLORS,
                     labels={"area_m2": "Polygon area (m², log scale)", "pixel_agreement": "Pixel agreement",
                             "region_name": "Region"}, hover_data=["id", "source_year"])
    fig.add_vline(x=100, line_dash="dot", annotation_text="1 pixel", line_color="gray")
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(tickformat=".0%"))
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# Confidence
# ------------------------------------------------------------------
with tabs[3]:
    st.markdown("ForTy publishes a score per class. The winning score (0-1) is a rough per-pixel confidence. "
                "If disagreements sit in low-confidence pixels, ForTy itself is signalling doubt there.")
    fig = px.box(v, x="category", y="forty_conf_mean", color="category", points="all",
                 category_orders={"category": an.CATEGORY_ORDER}, color_discrete_map=ui.CATEGORY_COLORS,
                 labels={"category": "", "forty_conf_mean": "Mean ForTy confidence in polygon"})
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                      yaxis=dict(tickformat=".0%"))
    st.plotly_chart(fig, use_container_width=True)
    t = v.groupby("category")["forty_conf_mean"].agg(["count", "mean", "median"]).reindex(an.CATEGORY_ORDER).dropna()
    st.dataframe(t.rename(columns={"count": "Polygons", "mean": "Mean confidence", "median": "Median"}),
                 use_container_width=True,
                 column_config={"Mean confidence": st.column_config.NumberColumn(format="%.2f"),
                                "Median": st.column_config.NumberColumn(format="%.2f")})
    st.caption("The score is a relative model output, not a calibrated probability.")

# ------------------------------------------------------------------
# By year
# ------------------------------------------------------------------
with tabs[4]:
    st.markdown("Both maps describe 2020. The year of clearing should not matter, unless clearing started "
                "before the 2020 imagery (more likely for early events) or the land changed type before clearing.")
    yr = v.groupby(["region_name", "source_year"]).agg(
        n=("id", "size"), gfc_forest=("gfc_forest", "mean"), forty_tree=("forty_tree", "mean")).reset_index()
    long = yr.melt(id_vars=["region_name", "source_year", "n"], value_vars=["gfc_forest", "forty_tree"],
                   var_name="m", value_name="share")
    long["dataset"] = long["m"].map({"gfc_forest": "GFC2020 forest", "forty_tree": "ForTy trees"})
    fig = px.line(long, x="source_year", y="share", color="dataset", facet_col="region_name", markers=True,
                  color_discrete_map={"GFC2020 forest": ui.GFC_COLOR, "ForTy trees": ui.FORTY_COLOR},
                  hover_data=["n"], labels={"source_year": "Year cleared", "share": "Mean share",
                                            "region_name": "Region"})
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=30, b=0), yaxis=dict(tickformat=".0%", range=[0, 1.05]),
                      legend=dict(orientation="h", y=-0.25, title=None))
    fig.update_xaxes(dtick=1)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(yr.pivot(index="source_year", columns="region_name", values="n").fillna(0).astype(int),
                 use_container_width=True)
    st.caption("Polygons per year. The single 2026 polygon is an outlier and is flagged.")

# ------------------------------------------------------------------
# Odd labels
# ------------------------------------------------------------------
with tabs[5]:
    fl = an.flags(df_all_sizes)
    st.markdown(f"**{len(fl)}** of {len(df_all_sizes)} polygons (ignoring the size filter) need a second look "
                "before their numbers are used.")
    if not fl.empty:
        st.dataframe(fl, hide_index=True, use_container_width=True,
                     column_config={"area_m2": st.column_config.NumberColumn("Area (m²)", format="%.0f"),
                                    "reasons": st.column_config.TextColumn("Why", width="large")})
