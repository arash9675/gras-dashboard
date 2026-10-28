"""Metrics over the polygon table (v_polygon), as plain pandas functions.

Each function takes the rows the user currently sees, so every number on the
analysis pages can be traced back to those rows.

What the polygons can and cannot tell us shapes all of it. Each one is land
that lost its trees after 2020, so in 2020 it *had* trees - but not
necessarily forest in the EUDR sense (cleared coffee agroforestry is a valid
polygon too). So we read the numbers as:
  * area ForTy puts in "other land" (no trees)  -> a plausible miss by ForTy
  * area GFC2020 calls non-forest                -> a miss, or a correct
    exclusion of tree crops / plantations; the data alone cannot tell which
  * no polygons of land that never had trees     -> no false-alarm rate, so no accuracy
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.earth_engine import FORTY_CLASSES

REGIONS = {"uganda": "Uganda", "brazil": "Brazil", "other": "Other"}

METRICS = {
    "gfc_forest": "GFC2020: forest",
    "forty_tree": "ForTy: any tree class (1-5)",
    "forty_forest_eudr": "ForTy: forest classes (1-4)",
    "forty_natural": "ForTy: natural forest (1-2)",
}

FORTY_COLS = ["forty_primary", "forty_natreg", "forty_planted",
              "forty_plantation", "forty_treecrops", "forty_other"]

CATEGORY_ORDER = ["Both forest", "ForTy only", "GFC only", "Neither"]

PIXEL_M2 = 100.0  # one 10 m pixel


# ------------------------------------------------------------------
# Basics
# ------------------------------------------------------------------

def valid(df: pd.DataFrame) -> pd.DataFrame:
    """Polygons that have results (at least part of a pixel)."""
    return df[df["gfc_forest"].notna()] if "gfc_forest" in df else df.iloc[0:0]


def bootstrap_ci(values: pd.Series, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95% percentile bootstrap interval over polygons."""
    v = values.dropna().to_numpy(dtype=float)
    if len(v) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n, len(v)), replace=True).mean(axis=1)
    return (float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


# ------------------------------------------------------------------
# Comparing the two datasets
# ------------------------------------------------------------------

def metric_table(df: pd.DataFrame, by: str = "region") -> pd.DataFrame:
    """Mean share per group for each metric, with bootstrap 95% CI."""
    rows = []
    for grp, g in valid(df).groupby(by):
        for col, label in METRICS.items():
            m, lo, hi = bootstrap_ci(g[col])
            rows.append({by: grp, "metric": label, "mean": m, "lo": lo, "hi": hi, "n": len(g)})
    return pd.DataFrame(rows)


def forty_composition(df: pd.DataFrame, by: str = "region") -> pd.DataFrame:
    """Mean ForTy class composition (share of polygon area) per group, long format."""
    v = valid(df)
    if v.empty:
        return pd.DataFrame()
    comp = v.groupby(by)[FORTY_COLS].mean().reset_index()
    long = comp.melt(id_vars=by, var_name="col", value_name="share")
    names = {c: FORTY_CLASSES[i + 1][0] for i, c in enumerate(FORTY_COLS)}
    long["class"] = long["col"].map(names)
    return long


def agreement_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Pixel-area cross-tab GFC (rows) x ForTy class (columns), as shares of
    the total pixel area of the selected polygons."""
    total = {}
    for h in valid(df)["joint_hist"]:
        for k, v in (h or {}).items():
            total[int(k)] = total.get(int(k), 0.0) + float(v)
    s = sum(total.values())
    rows = {"GFC forest": 1, "GFC non-forest": 0}
    mat = pd.DataFrame(0.0, index=list(rows), columns=[FORTY_CLASSES[c][0] for c in range(1, 7)])
    if s == 0:
        return mat
    for k, v in total.items():
        g, c = divmod(k, 10)
        if c in FORTY_CLASSES:
            mat.loc["GFC forest" if g == 1 else "GFC non-forest", FORTY_CLASSES[c][0]] += v / s
    return mat


def category_counts(df: pd.DataFrame, by: str = "region") -> pd.DataFrame:
    v = valid(df)
    if v.empty:
        return pd.DataFrame()
    out = v.groupby([by, "category"]).size().reset_index(name="n")
    out["share"] = out["n"] / out.groupby(by)["n"].transform("sum")
    return out


# ------------------------------------------------------------------
# Polygon size
# ------------------------------------------------------------------

def by_size(df: pd.DataFrame) -> pd.DataFrame:
    v = valid(df)
    if v.empty:
        return pd.DataFrame()
    return (v.groupby("size_class")
             .agg(n=("id", "size"),
                  gfc_forest=("gfc_forest", "mean"),
                  forty_tree=("forty_tree", "mean"),
                  agreement=("pixel_agreement", "mean"),
                  agreement_sd=("pixel_agreement", "std"),
                  conf=("forty_conf_mean", "mean"))
             .reset_index())





def sensitivity(df: pd.DataFrame, thresholds=(0, 25, 50, 100, 200, 500, 1000, 2000, 5000)) -> pd.DataFrame:
    """Headline means when polygons below each size threshold are dropped."""
    v = valid(df)
    rows = []
    for t in thresholds:
        s = v[v["area_m2"] >= t]
        rows.append({"min_area_m2": t, "n": len(s),
                     "gfc_forest": s["gfc_forest"].mean(), "forty_tree": s["forty_tree"].mean(),
                     "agreement": s["pixel_agreement"].mean()})
    return pd.DataFrame(rows)


def size_effect_note(df: pd.DataFrame) -> str:
    """Plain-language check of whether GFC forest share rises with polygon size
    *within* each region (pooled trends can just reflect which region has the big polygons)."""
    v = valid(df)
    v = v[v["area_m2"] >= PIXEL_M2]
    big = v["area_m2"] >= 5000
    rises = {}
    for reg, g in v.groupby("region_name"):
        b, s = g[big.loc[g.index]], g[~big.loc[g.index]]
        if len(b) >= 5 and len(s) >= 5:
            rises[reg] = b["gfc_forest"].mean() - s["gfc_forest"].mean()
    if not rises:
        return ""
    share_brazil_big = (v.loc[big, "region"] == "brazil").mean() if big.any() else 0
    parts = ", ".join(f"{r} {d * 100:+.0f} points" for r, d in rises.items())
    if all(d > 0.05 for d in rises.values()):
        return (f"Within each region, GFC2020 sees more forest in polygons of 0.5 ha or more ({parts}), "
                "consistent with its 0.5 ha minimum forest patch.")
    return (f"The pooled rise with size mostly reflects region: {share_brazil_big:.0%} of the 0.5 ha+ polygons are "
            f"in Brazil, where GFC2020 maps more forest. Within regions there is no consistent size trend "
            f"(0.5 ha+ vs smaller: {parts}).")


def all_or_nothing_share(df: pd.DataFrame) -> float:
    """Share of polygons whose GFC and ForTy values are both exactly 0 or 1."""
    v = valid(df)
    if v.empty:
        return np.nan
    def binary(s):
        return (s.round(6) == 0) | (s.round(6) == 1)
    return float((binary(v["gfc_forest"]) & binary(v["forty_tree"])).mean())


def weighting_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per-polygon mean (each event counts once) vs area-weighted (each m² counts once)."""
    rows = []
    for reg, g in valid(df).groupby("region_name"):
        w = g["px_area"]
        rows.append({"Region": reg, "Polygons": len(g),
                     "GFC forest, per polygon": g["gfc_forest"].mean(),
                     "GFC forest, area-weighted": (g["gfc_forest"] * w).sum() / w.sum(),
                     "ForTy trees, per polygon": g["forty_tree"].mean(),
                     "ForTy trees, area-weighted": (g["forty_tree"] * w).sum() / w.sum()})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Flags and headline numbers
# ------------------------------------------------------------------

def flags(df: pd.DataFrame) -> pd.DataFrame:
    """Polygons a reviewer should look at before trusting their numbers."""
    rows = []
    for _, r in df.iterrows():
        reasons = []
        if r["source_year"] == r["source_year"] and r["source_year"] is not None and r["source_year"] > 2025:
            reasons.append(f"event year {int(r['source_year'])} is outside the 2021-2024 range of the other labels")
        if r["area_m2"] < 100:
            reasons.append(f"smaller than one 10 m pixel ({r['area_m2']:.0f} m²): judged by the whole "
                           f"pixel it touches, so its share is all-or-nothing")
        if pd.isna(r.get("gfc_forest")):
            reasons.append("no pixel overlap in extraction")
        elif r.get("forty_other", 0) >= 0.5 and r.get("gfc_forest", 0) < 0.5:
            reasons.append("both datasets see mostly no forest/trees: check label or timing")
        if reasons:
            rows.append({"id": r["id"], "region": REGIONS.get(r["region"], r["region"]),
                         "year": r["source_year"], "area_m2": r["area_m2"], "reasons": "; ".join(reasons)})
    return pd.DataFrame(rows)


def headline(df: pd.DataFrame) -> dict:
    """Numbers quoted in the Overview and Findings text."""
    v = valid(df)
    out = {"n": len(v), "n_total": len(df)}
    for col in METRICS:
        out[col] = v[col].mean() if len(v) else np.nan
    out["agreement"] = v["pixel_agreement"].mean() if len(v) else np.nan
    out["treecrops"] = v["forty_treecrops"].mean() if len(v) else np.nan
    for reg in REGIONS:
        r = v[v["region"] == reg]
        out[reg] = {col: (r[col].mean() if len(r) else np.nan)
                    for col in [*METRICS, "pixel_agreement", "forty_treecrops", "forty_other", "forty_plantation"]}
        out[reg]["n"] = len(r)
        out[reg]["dominant"] = r["forty_dominant"].mode().iat[0] if len(r) else None
    return out
