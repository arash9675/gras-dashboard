"""The tools the assistant may call, and nothing else.

Gemini never sees the database. It sees these tool descriptions, asks for one
by name with arguments, and gets back rows. Every tool:
  * runs for the polygon set the user has chosen; the model cannot pick another,
  * checks its arguments against known values and says what is allowed when not,
  * reads through the read-only gras_reader role (views only),
  * records what it ran, so the page can show the rows and SQL behind an answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from analytics import insights
from analytics import metrics as an
from assistant import specs
from core import db

MAX_ROWS = 60           # rows handed back to the model per call
DEFAULT_MIN_AREA = 100  # m2: polygons smaller than one 10 m pixel are left out, as on every page

GROUPS = {"none": None, "cluster": "cluster_name", "year": "source_year", "size": "size_class"}

SHARE_COLS = {
    "gfc_forest": "GFC2020 forest share",
    "forty_tree": "ForTy any tree class (1-5) share",
    "forty_forest_eudr": "ForTy forest classes (1-4) share",
    "forty_natural": "ForTy natural forest (1-2) share",
    "pixel_agreement": "share of pixels where both give the same forest / not-forest answer",
}


class ToolError(ValueError):
    """A bad request from the model, worded so it can correct itself."""


@dataclass
class Call:
    """One tool call as the page shows it."""
    tool: str
    args: dict
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    source: str = ""          # SQL view definition, or how the rows were computed
    error: str | None = None
    chart: dict | None = None  # a validated chart spec, from propose_chart


# ------------------------------------------------------------------
# Data, read-only
# ------------------------------------------------------------------

def _polygons(set_id: int) -> pd.DataFrame:
    df = pd.DataFrame(db.reader_query("SELECT * FROM v_polygon WHERE set_id = %s ORDER BY id", (set_id,)))
    return df.drop(columns=[c for c in ("geometry", "joint_hist") if c in df])


def _filter(df: pd.DataFrame, clusters=None, years=None, min_area_m2=None) -> tuple[pd.DataFrame, dict]:
    known_clusters = sorted(df["cluster_name"].dropna().unique().tolist())
    known_years = sorted(int(y) for y in df["source_year"].dropna().unique())
    if clusters:
        bad = [c for c in clusters if c not in known_clusters]
        if bad:
            raise ToolError(f"Unknown cluster(s) {bad}. Known clusters: {known_clusters}.")
        df = df[df["cluster_name"].isin(clusters)]
    if years:
        bad = [y for y in years if int(y) not in known_years]
        if bad:
            raise ToolError(f"No polygons for year(s) {bad}. Years present: {known_years}.")
        df = df[df["source_year"].isin([int(y) for y in years])]
    min_area = DEFAULT_MIN_AREA if min_area_m2 is None else float(min_area_m2)
    df = df[df["area_m2"] >= min_area]
    used = {"clusters": clusters or "all", "years": years or "all", "min_area_m2": min_area}
    return df, used


def _rows(df: pd.DataFrame) -> list[dict]:
    """Rows for the model: rounded, at most MAX_ROWS."""
    out = df.head(MAX_ROWS).copy()
    for c in out.select_dtypes("float").columns:
        out[c] = out[c].round(4)
    return out.astype(object).where(out.notna(), None).to_dict("records")


# ------------------------------------------------------------------
# The tools
# ------------------------------------------------------------------

def list_options(set_id: int) -> tuple[dict, Call]:
    df = _polygons(set_id)
    counts = df.groupby("cluster_name").size().to_dict()
    result = {
        "clusters": counts,
        "years": sorted(int(y) for y in df["source_year"].dropna().unique()),
        "size_classes": sorted(df["size_class"].unique().tolist()),
        "polygons": len(df),
        "polygons_smaller_than_one_pixel": int((df["area_m2"] < 100).sum()),
        "insights": {i.key: f"{i.title} {i.question}" for i in insights.INSIGHTS},
        "share_columns": SHARE_COLS,
    }
    rows = pd.DataFrame([{"cluster": k, "polygons": v} for k, v in counts.items()])
    return result, Call("list_options", {}, rows, "SELECT cluster_name, COUNT(*) FROM v_polygon GROUP BY 1")


def run_insight(set_id: int, key: str) -> tuple[dict, Call]:
    if key not in insights.BY_KEY:
        raise ToolError(f"Unknown insight '{key}'. Use one of {list(insights.BY_KEY)}.")
    ins = insights.BY_KEY[key]
    df = insights.run(key, set_id, query=db.reader_query)
    df = df.drop(columns=[c for c in ("set_id",) if c in df])
    result = {"insight": ins.title, "view": ins.view, "rows": _rows(df), "row_count": len(df),
              "note": "Statistics use polygons of at least one 10 m pixel (100 m2)."}
    return result, Call("run_insight", {"key": key}, df, insights.definition(key))


def summarise(set_id: int, group_by: str = "none", clusters=None, years=None, min_area_m2=None) -> tuple[dict, Call]:
    if group_by not in GROUPS:
        raise ToolError(f"group_by must be one of {list(GROUPS)}.")
    df, used = _filter(an.valid(_polygons(set_id)), clusters, years, min_area_m2)
    if df.empty:
        raise ToolError(f"No polygons match {used}.")
    col = GROUPS[group_by]
    groups = [("all", df)] if col is None else list(df.groupby(col))
    rows = []
    for name, g in groups:
        row = {"group": name if not isinstance(name, float) else int(name), "polygons": len(g),
               "area_ha": round(g["area_m2"].sum() / 1e4, 2)}
        for c in SHARE_COLS:
            row[c] = g[c].mean()
        for cat in an.CATEGORY_ORDER:
            row[f"polygons_{cat.lower().replace(' ', '_')}"] = int((g["category"] == cat).sum())
        row["forty_confidence_mean"] = g["forty_conf_mean"].mean()
        for c in an.FORTY_COLS:   # ForTy class composition, mean share of polygon area
            row[f"{c}_share"] = g[c].mean()
        rows.append(row)
    out = pd.DataFrame(rows)
    result = {"filters": used, "group_by": group_by, "rows": _rows(out),
              "definitions": {**SHARE_COLS, "forty_<class>_share": "mean share of polygon area in each ForTy class (primary, natreg = naturally "
                              "regenerating, planted, plantation, treecrops = tree crops / agroforestry, other = no trees)",
                              "polygons_<category>": "polygons where each map calls at least half "
                              "of the polygon forest (GFC2020) or trees (ForTy 1-5)"}}
    source = (f"SELECT * FROM v_polygon WHERE set_id = {set_id}  -- read-only role\n"
              f"-- then in pandas: keep polygons with results, area_m2 >= {used['min_area_m2']}, "
              f"clusters {used['clusters']}, years {used['years']};\n"
              f"-- group by {col or 'nothing'}; mean of each share column, count of each category")
    return result, Call("summarise", {"group_by": group_by, **used}, out, source)


def list_polygons(set_id: int, category: str | None = None, clusters=None, years=None, min_area_m2=None,
                  sort_by: str = "area_m2", limit: int = 10) -> tuple[dict, Call]:
    if category and category not in an.CATEGORY_ORDER:
        raise ToolError(f"category must be one of {an.CATEGORY_ORDER}.")
    cols = ["id", "cluster_name", "source_year", "area_m2", "gfc_forest", "forty_tree", "forty_dominant",
            "forty_conf_mean", "category"]
    if sort_by not in cols:
        raise ToolError(f"sort_by must be one of {cols}.")
    df, used = _filter(an.valid(_polygons(set_id)), clusters, years, min_area_m2)
    if category:
        df = df[df["category"] == category]
    out = df.sort_values(sort_by, ascending=sort_by == "id")[cols].head(max(1, min(int(limit), 20)))
    result = {"filters": {**used, "category": category or "all"}, "matching": len(df), "rows": _rows(out)}
    source = (f"SELECT {', '.join(cols)} FROM v_polygon WHERE set_id = {set_id}  -- read-only role\n"
              f"-- filters {used}, category {category or 'all'}; sorted by {sort_by}")
    return result, Call("list_polygons", {"category": category, "sort_by": sort_by, **used}, out, source)


def polygon_detail(set_id: int, polygon_id: int) -> tuple[dict, Call]:
    df = _polygons(set_id)
    row = df[df["id"] == int(polygon_id)]
    if row.empty:
        raise ToolError(f"Polygon {polygon_id} is not in the chosen set.")
    result = {"polygon": _rows(row)[0],
              "note": "Shares are of the polygon's area; x_ff/x_fn/x_nf/x_nn is the pixel cross-tab "
                      "(GFC forest or not x ForTy trees or not)."}
    return result, Call("polygon_detail", {"polygon_id": int(polygon_id)}, row,
                        f"SELECT * FROM v_polygon WHERE set_id = {set_id} AND id = {int(polygon_id)}")


def propose_chart(set_id: int, **spec) -> tuple[dict, Call]:
    clean, errors = specs.validate(spec, set_id, query=db.reader_query)
    if errors:
        raise ToolError("Chart spec not valid: " + "; ".join(errors))
    data = specs.data(clean, set_id, query=db.reader_query)
    result = {"ok": True, "title": clean["title"], "rows_plotted": len(data),
              "note": "The chart is shown to the user under your answer, with a button to save it."}
    call = Call("propose_chart", clean, data, insights.definition(clean["source"]))
    call.chart = clean
    return result, call


# ------------------------------------------------------------------
# Declarations for Gemini (JSON schema per tool)
# ------------------------------------------------------------------

_FILTERS = {
    "clusters": {"type": "array", "items": {"type": "string"},
                 "description": "Location cluster names to keep, exactly as list_options gives them. Omit for all."},
    "years": {"type": "array", "items": {"type": "integer"}, "description": "Years of clearing to keep. Omit for all."},
    "min_area_m2": {"type": "number",
                    "description": "Smallest polygon area kept. Default 100 (one 10 m pixel); 0 includes sub-pixel "
                                   "polygons, whose values are unreliable."},
}

DECLARATIONS = [
    {"name": "list_options",
     "description": "What can be asked about: location clusters with polygon counts, years, size classes, the named "
                    "insight queries and the meaning of each share column. Call this first when unsure.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "run_insight",
     "description": "Run one named insight query (a fixed SQL view) for the chosen polygon set and return its rows.",
     "parameters": {"type": "object", "properties": {
         "key": {"type": "string", "enum": [i.key for i in insights.INSIGHTS],
                 "description": "; ".join(f"{i.key}: {i.title}" for i in insights.INSIGHTS)}},
         "required": ["key"]}},
    {"name": "summarise",
     "description": "Mean shares (GFC2020 forest, ForTy tree / forest / natural forest, each ForTy class, pixel "
                    "agreement), polygon counts per agreement category and mean ForTy confidence, for filtered polygons, optionally "
                    "grouped by cluster, year or size class.",
     "parameters": {"type": "object", "properties": {
         "group_by": {"type": "string", "enum": list(GROUPS)}, **_FILTERS}}},
    {"name": "list_polygons",
     "description": "List individual polygons (id, cluster, year, area, shares, category), filtered and sorted.",
     "parameters": {"type": "object", "properties": {
         "category": {"type": "string", "enum": an.CATEGORY_ORDER},
         "sort_by": {"type": "string", "enum": ["id", "area_m2", "gfc_forest", "forty_tree", "forty_conf_mean"]},
         "limit": {"type": "integer", "description": "At most 20."}, **_FILTERS}}},
    {"name": "polygon_detail",
     "description": "Every stored number for one polygon of the chosen set.",
     "parameters": {"type": "object", "properties": {"polygon_id": {"type": "integer"}}, "required": ["polygon_id"]}},
    {"name": "propose_chart",
     "description": "Draw a chart from one insight query's rows, shown under the answer and savable as a dashboard "
                    "card. Run the insight first to see its column names.",
     "parameters": specs.JSON_SCHEMA},
]

FUNCTIONS = {
    "list_options": list_options,
    "run_insight": run_insight,
    "summarise": summarise,
    "list_polygons": list_polygons,
    "polygon_detail": polygon_detail,
    "propose_chart": propose_chart,
}


def call(name: str, args: dict, set_id: int) -> tuple[dict, Call]:
    """Run one tool. Bad requests come back as an error the model can read and fix."""
    if name not in FUNCTIONS:
        return {"error": f"No tool named {name}."}, Call(name, args, error="unknown tool")
    try:
        return FUNCTIONS[name](set_id, **(args or {}))
    except ToolError as e:
        return {"error": str(e)}, Call(name, args, error=str(e))
    except TypeError as e:   # an argument the tool does not take
        return {"error": f"Bad arguments: {e}"}, Call(name, args, error=str(e))
