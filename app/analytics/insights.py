"""The Insights page's query library.

Each insight is a named, read-only SQL view (q_* in db/init.sql) plus the
question it answers, a one-line answer worked out from its rows, and a chart.
Only these views can run - there is no free-form SQL - and always for one
polygon set, so every answer on the page can be traced to its view and rows.
The same views fed the exported dashboard, and they are the natural base for
an assistant later: it could call them by name and cite them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core import db
from core.palette import CATEGORY_COLORS as CAT
from core.palette import FORTY_COLOR as FORTY
from core.palette import GFC_COLOR as GFC
from pipeline.earth_engine import FORTY_CLASSES as _CLASSES

# Column name in the q_* views -> (label, colour), in ForTy class order.
FORTY_CLASSES = dict(zip(
    ["primary_forest", "naturally_regenerating", "planted_forest", "plantation_forest", "tree_crops", "other_land"],
    _CLASSES.values(), strict=False))


def pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x * 100:.0f}%"


def _layout(fig, height=300):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=10, b=0), font=dict(family="Roboto"),
                      legend=dict(orientation="h", y=-0.3, title=None), plot_bgcolor="white")
    return fig


@dataclass
class Insight:
    key: str
    view: str
    title: str
    question: str
    order_by: str
    answer: Callable[[pd.DataFrame], str]
    chart: Callable[[pd.DataFrame], go.Figure | None]


# ------------------------------------------------------------------
# Answers
# ------------------------------------------------------------------

def _a_headline(d):
    a = d[d["cluster"] == "All clusters"]
    if a.empty:
        return "No results."
    a = a.iloc[0]
    c = d[d["cluster"] != "All clusters"].sort_values("gfc_forest")
    low = f" GFC2020 is lowest in {c.iloc[0]['cluster']} ({pct(c.iloc[0]['gfc_forest'])})." if len(c) > 1 else ""
    return (f"GFC2020 maps {pct(a['gfc_forest'])} of the polygon area as forest; ForTy sees trees on "
            f"{pct(a['forty_trees'])}. Pixel agreement is {pct(a['pixel_agreement'])}.{low}")


def _a_reasons(d):
    a = d[d["cluster"] == "All clusters"]
    if a.empty or pd.isna(a.iloc[0]["natural_forest"]):
        return "GFC2020 maps all of these polygons as forest."
    a = a.iloc[0]
    return (f"Where GFC2020 says non-forest, ForTy calls {pct(a['natural_forest'])} natural forest "
            f"(a real conflict) and {pct(a['tree_crops'] + a['planted_plantation'])} tree crops or plantations "
            f"(excluded from GFC2020 by definition).")


def _a_mix(d):
    parts = []
    for _, r in d.iterrows():
        col = max(FORTY_CLASSES, key=lambda k: r[k])
        parts.append(f"{r['cluster']}: {FORTY_CLASSES[col][0].lower()} ({pct(r[col])})")
    return "Main ForTy class per cluster: " + "; ".join(parts) + "."


LOSS_COLS = {f"{k}_ha": v for k, v in FORTY_CLASSES.items()}   # hectares per ForTy class


def _a_loss(d):
    allc = d[d["cluster"] == "All clusters"]
    if allc.empty:
        return "These polygons have no years."
    tot = allc[list(LOSS_COLS)].sum()
    top = tot.idxmax()
    parts = []
    for cl, g in d[d["cluster"] != "All clusters"].groupby("cluster"):
        s = g[list(LOSS_COLS)].sum()
        parts.append(f"{cl}: mostly {LOSS_COLS[s.idxmax()][0].lower()}")
    return (f"{allc['area_ha'].sum():,.1f} ha were cleared in {int(allc['polygons'].sum())} polygons; ForTy puts "
            f"{tot[top]:,.1f} ha ({tot[top] / tot.sum() * 100:.0f}%) in {LOSS_COLS[top][0].lower()}. "
            + "; ".join(parts) + ".")


def _a_cat(d):
    t = d.groupby("category")["polygons"].sum()
    n = int(t.sum())
    if not n:
        return "No results."
    top = t.idxmax()
    return f"{top} is the most common outcome: {int(t[top])} of {n} polygons ({pct(t[top] / n)})."


def _a_size(d):
    d = d.set_index("min_area_m2")
    if 0 not in d.index:
        return "No results."
    s0, s1 = d.loc[0], d.loc[100] if 100 in d.index else d.loc[0]
    msg = (f"Dropping polygons under one pixel moves GFC2020 from {pct(s0['gfc_forest'])} to {pct(s1['gfc_forest'])} "
           f"and ForTy from {pct(s0['forty_trees'])} to {pct(s1['forty_trees'])}.")
    if 5000 in d.index:
        s5 = d.loc[5000]
        msg += f" Only 0.5 ha+ ({int(s5['polygons'])} polygons): GFC2020 {pct(s5['gfc_forest'])}, ForTy {pct(s5['forty_trees'])}."
    return msg


def _a_conf(d):
    m = d.set_index("category")["median_confidence"]
    if "Both forest" in m and "ForTy only" in m:
        diff = m["ForTy only"] - m["Both forest"]
        word = ("lower, so ForTy itself signals doubt there" if diff < -0.03 else
                "no lower, so the disagreement is not ForTy being unsure")
        return (f"ForTy's median confidence is {pct(m['ForTy only'])} where only ForTy sees forest, versus "
                f"{pct(m['Both forest'])} where both agree: {word}.")
    return "Not enough polygons in both groups to compare."


def _a_year(d):
    if d.empty:
        return "These polygons have no years."
    g = d.groupby("year").apply(lambda x: (x["gfc_forest"] * x["polygons"]).sum() / x["polygons"].sum())
    return (f"GFC2020 forest share ranges {pct(g.min())}–{pct(g.max())} across years of clearing "
            f"({int(g.idxmin())} lowest, {int(g.idxmax())} highest).")


def _a_missed(d):
    return (f"{len(d)} polygons where ForTy sees mostly no trees, although trees were cleared there: plausible "
            f"ForTy misses, or clearing before the 2020 imagery." if len(d) else "ForTy sees trees in every polygon.")


def _a_label(d):
    return (f"{len(d)} polygons where neither dataset sees forest: check the label or whether clearing started "
            f"before 2020." if len(d) else "Every polygon is seen as forest by at least one dataset.")


def _a_profile(d):
    return f"{len(d)} location clusters; see each one's size, years, agreement and main ForTy class below."


# ------------------------------------------------------------------
# Charts
# ------------------------------------------------------------------

def _c_headline(d):
    c = d[d["cluster"] != "All clusters"]
    f = go.Figure()
    for col, name, color in [("gfc_forest", "GFC2020 forest", GFC), ("forty_trees", "ForTy trees (1-5)", "#FDD663"),
                             ("forty_forest_1_4", "ForTy forest (1-4)", "#F29900"),
                             ("forty_natural", "ForTy natural (1-2)", "#B06000")]:
        f.add_bar(x=c["cluster"], y=c[col], name=name, marker_color=color, hovertemplate="%{y:.0%}")
    f.update_layout(barmode="group", yaxis=dict(tickformat=".0%", range=[0, 1]))
    return _layout(f)


def _c_reasons(d):
    c = d[d["cluster"] != "All clusters"]
    f = go.Figure()
    for col, name, color in [("natural_forest", "Natural forest", "#D93025"),
                             ("planted_plantation", "Planted / plantation", "#E65FA9"),
                             ("tree_crops", "Tree crops", "#E6AB02"), ("other_land", "Other land", "#BDC1C6")]:
        f.add_bar(y=c["cluster"], x=c[col], name=name, orientation="h", marker_color=color, hovertemplate="%{x:.0%}")
    f.update_layout(barmode="stack", xaxis=dict(tickformat=".0%", range=[0, 1]))
    return _layout(f, 240)


def _c_mix(d):
    f = go.Figure()
    for col, (name, color) in FORTY_CLASSES.items():
        f.add_bar(y=d["cluster"], x=d[col], name=name, orientation="h", marker_color=color, hovertemplate="%{x:.0%}")
    f.update_layout(barmode="stack", xaxis=dict(tickformat=".0%", range=[0, 1]))
    return _layout(f, 260)


def _c_loss(d):
    """Stacked hectares per year and ForTy class; one panel per cluster, All clusters first;
    polygon count above each bar."""
    clusters = ["All clusters"] + sorted(c for c in d["cluster"].unique() if c != "All clusters")
    long = d.melt(id_vars=["cluster", "year", "polygons", "area_ha"], value_vars=list(LOSS_COLS),
                  var_name="col", value_name="ha")
    long["ForTy class"] = long["col"].map(lambda c: LOSS_COLS[c][0])
    long["year"] = long["year"].astype(int).astype(str)
    years = sorted(long["year"].unique())
    # The polygon count is the text of the top segment, so it prints above each stacked bar.
    top = list(LOSS_COLS)[-1]
    long["n"] = long.apply(lambda r: f"{int(r['polygons'])}" if r["col"] == top else "", axis=1)
    f = px.bar(long, x="year", y="ha", color="ForTy class", facet_col="cluster", facet_col_wrap=2,
               facet_row_spacing=0.16, facet_col_spacing=0.08, text="n",
               category_orders={"cluster": clusters, "year": years,
                                "ForTy class": [v[0] for v in LOSS_COLS.values()]},
               color_discrete_map={v[0]: v[1] for v in LOSS_COLS.values()},
               labels={"ha": "ha", "year": ""})
    f.update_traces(hovertemplate="%{x}: %{y:,.2f} ha<extra>%{fullData.name}</extra>",
                    textposition="outside", textfont=dict(size=10, color="#444746"), cliponaxis=False)
    f.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    f.update_xaxes(showticklabels=True, tickangle=0, type="category")
    f.update_yaxes(matches=None, showticklabels=True)
    f = _layout(f, 560)
    f.update_layout(margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=-0.12, title=None))
    return f


def _c_cat(d):
    f = px.bar(d, y="cluster", x="polygons", color="category", orientation="h", color_discrete_map=CAT,
               category_orders={"category": list(CAT)})
    return _layout(f, 240)


def _c_size(d):
    d = d.sort_values("min_area_m2")
    x = d["min_area_m2"].astype(str) + " m²"
    f = go.Figure()
    f.add_bar(x=x, y=d["polygons"], name="Polygons kept", yaxis="y2", marker_color="rgba(154,160,166,.35)")
    for col, name, color in [("gfc_forest", "GFC2020 forest", GFC), ("forty_trees", "ForTy trees", FORTY),
                             ("pixel_agreement", "Agreement", "#202124")]:
        f.add_scatter(x=x, y=d[col], name=name, mode="lines+markers", line=dict(color=color, width=2.5))
    f.update_layout(yaxis=dict(tickformat=".0%", range=[0, 1.05]),
                    yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return _layout(f)


def _c_conf(d):
    f = px.bar(d, x="category", y="median_confidence", color="category", color_discrete_map=CAT,
               category_orders={"category": list(CAT)}, text_auto=".0%")
    f.update_layout(showlegend=False, yaxis=dict(tickformat=".0%", range=[0, 1]))
    return _layout(f, 260)


def _c_year(d):
    long = d.melt(id_vars=["cluster", "year", "polygons"], value_vars=["gfc_forest", "forty_trees"],
                  var_name="m", value_name="share")
    long["dataset"] = long["m"].map({"gfc_forest": "GFC2020 forest", "forty_trees": "ForTy trees"})
    f = px.line(long, x="year", y="share", color="dataset", facet_col="cluster", markers=True,
                hover_data=["polygons"], color_discrete_map={"GFC2020 forest": GFC, "ForTy trees": FORTY})
    f.update_layout(yaxis=dict(tickformat=".0%", range=[0, 1.05]))
    f.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    f.update_xaxes(dtick=1, title=None)
    return _layout(f)


SHARE_HINTS = ("forest", "trees", "agreement", "land", "crops", "plantation", "regenerating", "confidence",
               "share", "natural", "primary", "planted")


def for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Readable copy: years as plain integers, areas rounded, shares as percentages."""
    out = df.drop(columns=["set_id"], errors="ignore").copy()
    for col in out.columns:
        if col in ("year", "first_year", "last_year"):
            out[col] = out[col].astype("Int64").astype(str)
        elif col.endswith("_ha") or col in ("area_m2", "area_ha", "gfc_nonforest_pixels"):
            out[col] = out[col].round(2)
        elif col in ("centroid_lat", "centroid_lon"):
            out[col] = out[col].round(5)
        elif out[col].dtype.kind == "f" and any(h in col for h in SHARE_HINTS):
            out[col] = out[col].map(lambda v: "–" if pd.isna(v) else f"{v * 100:.0f}%")
    return out


def _c_table(_d):
    return None


INSIGHTS = [
    Insight("headline", "q_headline", "How much forest does each dataset see?",
            "Mean share of each polygon mapped as forest (GFC2020) or tree classes (ForTy), per location cluster.",
            "cluster", _a_headline, _c_headline),
    Insight("reasons", "q_disagreement_reasons", "Why do the datasets disagree?",
            "Where GFC2020 says non-forest, which ForTy class covers those pixels?",
            "cluster", _a_reasons, _c_reasons),
    Insight("mix", "q_class_mix", "What kind of forest was cleared?",
            "Mean ForTy class composition of the polygons, per cluster.", "cluster", _a_mix, _c_mix),
    Insight("loss", "q_loss_by_type_year", "Which forest types were lost each year?",
            "Hectares cleared per year by ForTy class (class share of each polygon × its area); the number "
            "above each bar is the polygon count.", "cluster, year", _a_loss, _c_loss),
    Insight("categories", "q_agreement_categories", "Do both, one or neither call it forest?",
            "Polygons per outcome (forest = at least half the polygon), per cluster.",
            "cluster, category", _a_cat, _c_cat),
    Insight("size", "q_size_sensitivity", "Do small polygons change the answer?",
            "Headline numbers when polygons below each area are dropped (includes sub-pixel polygons).",
            "min_area_m2", _a_size, _c_size),
    Insight("confidence", "q_confidence_vs_agreement", "Is ForTy unsure where they disagree?",
            "ForTy's winning-class score (0-1) per agreement outcome.", "category", _a_conf, _c_conf),
    Insight("year", "q_year_trend", "Does the year of clearing matter?",
            "Mean shares by year of the deforestation event, per cluster.", "cluster, year", _a_year, _c_year),
    Insight("missed", "q_trees_missed", "Where does ForTy miss the trees?",
            "Polygons where ForTy puts at least half the area in 'other land'.", "forty_other_land DESC",
            _a_missed, _c_table),
    Insight("label", "q_label_check", "Which labels need a second look?",
            "Polygons that neither dataset maps as forest.", "area_m2 DESC", _a_label, _c_table),
    Insight("profile", "q_cluster_profile", "Cluster profiles",
            "One row per location cluster: size, years, agreement and main ForTy class.", "cluster",
            _a_profile, _c_table),
]
BY_KEY = {i.key: i for i in INSIGHTS}


def run(key: str, set_id: int, query=db.query) -> pd.DataFrame:
    """Run one named insight for one polygon set (the only way queries are executed).

    `query` lets the assistant run it through the read-only role (db.reader_query).
    """
    ins = BY_KEY[key]   # KeyError for anything not in the library
    return pd.DataFrame(query(f"SELECT * FROM {ins.view} WHERE set_id = %s ORDER BY {ins.order_by}", (set_id,)))


def definition(key: str) -> str:
    view = BY_KEY[key].view
    rows = db.query("SELECT pg_get_viewdef(%s::regclass, true) AS sql", (view,))
    return f"CREATE VIEW {view} AS\n{rows[0]['sql']}" if rows else ""
