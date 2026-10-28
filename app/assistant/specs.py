"""Chart specs: how the assistant asks for a chart without writing code.

A spec names one insight query, the columns to plot and a chart type from a
short list. We check it against the query's real columns, then draw it with
the app's own colours. Saved specs go into the `dashboards` table; because a
spec names a query rather than holding data, a saved chart redraws for
whichever polygon set is chosen.

    {"title": "Hectares lost by ForTy class", "source": "loss", "chart": "stacked_bar",
     "x": "year", "y": ["naturally_regenerating", "plantation_forest"], "clusters": ["Uganda"]}
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px

from analytics import insights
from core import db
from core.palette import CATEGORY_COLORS

CHARTS = ["bar", "grouped_bar", "stacked_bar", "line", "table"]

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short title saying what the chart shows."},
        "source": {"type": "string", "enum": [i.key for i in insights.INSIGHTS],
                   "description": "The insight query whose rows are plotted."},
        "chart": {"type": "string", "enum": CHARTS},
        "x": {"type": "string", "description": "Column for the x axis (categories or years)."},
        "y": {"type": "array", "items": {"type": "string"},
              "description": "One to six numeric columns. Several columns become one series each."},
        "color": {"type": "string", "description": "Optional column that splits one y column into series."},
        "clusters": {"type": "array", "items": {"type": "string"},
                     "description": "Optional: keep rows whose 'cluster' is one of these."},
        "years": {"type": "array", "items": {"type": "integer"},
                  "description": "Optional: keep rows whose 'year' is one of these."},
    },
    "required": ["title", "source", "chart", "x", "y"],
}


def _rows(source: str, set_id: int, query) -> pd.DataFrame:
    df = insights.run(source, set_id, query=query)
    return df.drop(columns=[c for c in ("set_id",) if c in df])


def validate(spec: dict, set_id: int, query=db.query) -> tuple[dict, list[str]]:
    """Return (clean spec, problems). The spec is only used when there are no problems."""
    errors = []
    source = spec.get("source")
    if source not in insights.BY_KEY:
        return {}, [f"source must be one of {list(insights.BY_KEY)}"]
    if spec.get("chart") not in CHARTS:
        errors.append(f"chart must be one of {CHARTS}")
    df = _rows(source, set_id, query)
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    y = spec.get("y") or []
    if isinstance(y, str):
        y = [y]
    if spec.get("x") not in cols:
        errors.append(f"x must be a column of {source}: {cols}")
    if not 1 <= len(y) <= 6 or any(c not in numeric for c in y):
        errors.append(f"y must be 1 to 6 numeric columns of {source}: {numeric}")
    color = spec.get("color") or None
    # Several rows per x value and one y column, but no colour: the bars would
    # silently stack unrelated rows (e.g. all categories of a cluster in one
    # blue bar). Split by the first text column instead.
    if not color and len(y) == 1 and spec.get("x") in cols and df[spec["x"]].duplicated().any():
        text_cols = [c for c in cols if c not in numeric and c != spec["x"]]
        color = text_cols[0] if text_cols else None
    if color and color not in cols:
        errors.append(f"color must be a column of {source}: {cols}")
    if color and len(y) > 1:
        errors.append("use color with a single y column only")
    for key, col in (("clusters", "cluster"), ("years", "year")):
        if spec.get(key) and col not in cols:
            errors.append(f"{key} filter needs a '{col}' column, which {source} does not have")
    clean = {"title": str(spec.get("title") or insights.BY_KEY[source].title)[:120], "source": source,
             "chart": spec.get("chart"), "x": spec.get("x"), "y": y, "color": color,
             "clusters": spec.get("clusters") or [], "years": [int(v) for v in spec.get("years") or []]}
    return clean, errors


def data(spec: dict, set_id: int, query=db.query) -> pd.DataFrame:
    """The rows a spec plots, filtered, in long form when there are several y columns."""
    df = _rows(spec["source"], set_id, query)
    if spec.get("clusters") and "cluster" in df:
        df = df[df["cluster"].isin(spec["clusters"])]
    if spec.get("years") and "year" in df:
        df = df[df["year"].isin(spec["years"])]
    keep = [spec["x"], *spec["y"], *([spec["color"]] if spec.get("color") else [])]
    df = df[list(dict.fromkeys(keep))]
    if len(spec["y"]) > 1:
        df = df.melt(id_vars=[spec["x"]], value_vars=spec["y"], var_name="series", value_name="value")
    return df


def _label(name) -> str:
    """A readable series name: 'naturally_regenerating_ha' -> 'Naturally regenerating (ha)'."""
    s = str(name)
    unit = " (ha)" if s.endswith("_ha") else ""
    base = s.removesuffix("_ha")
    if base in insights.FORTY_CLASSES:
        return insights.FORTY_CLASSES[base][0] + unit
    return s if s in CATEGORY_COLORS else base.replace("_", " ").capitalize() + unit


def _colours(names) -> dict:
    """Our fixed colours where a series has one (ForTy classes, agreement outcomes), by label."""
    known = {**{lab: c for lab, c in insights.FORTY_CLASSES.values()}, **CATEGORY_COLORS}
    return {n: known[n.removesuffix(" (ha)")] for n in names if n.removesuffix(" (ha)") in known}


def _is_count(col: str) -> bool:
    return col.endswith("_ha") or col in ("polygons", "area_ha", "area_m2", "n") or col.startswith("polygons")


def render(spec: dict, df: pd.DataFrame):
    """A Plotly figure, or None for a table spec (the caller shows the rows)."""
    if spec["chart"] == "table" or df.empty:
        return None
    long = len(spec["y"]) > 1
    y = "value" if long else spec["y"][0]
    series = "series" if long else spec.get("color")
    values = df[y].dropna()
    is_share = bool(len(values)) and values.between(0, 1).all() and not any(_is_count(c) for c in spec["y"])
    x = spec["x"]
    if x == "year":
        df = df.assign(year=df["year"].astype("Int64").astype(str))
    if series:
        df = df.assign(**{series: df[series].map(_label)})
    kwargs = dict(x=x, y=y, color=series, title=None,
                  color_discrete_map=_colours(df[series].unique()) if series else None)
    if spec["chart"] == "line":
        fig = px.line(df, markers=True, **kwargs)
    else:
        fig = px.bar(df, barmode={"stacked_bar": "relative", "grouped_bar": "group"}.get(spec["chart"], "group"),
                     **kwargs)
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), font=dict(family="Roboto"),
                      legend=dict(orientation="h", y=-0.25, title=None), plot_bgcolor="white",
                      yaxis_title=None, xaxis_title=None)
    if is_share:
        fig.update_yaxes(tickformat=".0%")
    return fig
