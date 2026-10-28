"""Google Earth Engine access for the two datasets.

  * JRC GFC2020 v4  -> ee.Image('JRC/GFC2020/V4'), band 'Map'.
    One class, 1 = forest. Everything else is *masked*, not 0, so we unmask
    to 0 - otherwise non-forest pixels silently drop out of every count and
    GFC2020 looks 100% forest wherever it says anything at all.

  * ForTy 2020 v1.0 -> ImageCollection of tiles, mosaicked.
    Five uint8 score bands (0-250) for classes 1-5. Class 6 (other land) is
    250 minus their sum, and the class of a pixel is the argmax of the six -
    the same recipe as the catalog example. The winning score / 250 is kept
    as a rough per-pixel confidence.

The extraction encodes both maps in one band (gfc * 10 + forty_class) so a
single histogram per polygon gives both compositions *and* their pixel-level
cross-tab on exactly the same pixels.

Catalog pages:
  https://developers.google.com/earth-engine/datasets/catalog/JRC_GFC2020_V4
  https://developers.google.com/earth-engine/datasets/catalog/projects_nature-trace_assets_forest_typology_forest_typology_2020_v1_0_collection
"""
from __future__ import annotations

import json
import logging
import time

import ee

from core.config import load_ee_credentials, settings

log = logging.getLogger("earth_engine")

SCALE_M = 10

# ------------------------------------------------------------------
# Dataset catalog
# ------------------------------------------------------------------

GFC = {
    "name": "JRC GFC2020 v4",
    "asset": "JRC/GFC2020/V4",
    "band": "Map",
    "definition": (
        "Forest presence/absence for 2020 at 10 m (EUDR definition): >0.5 ha, trees >5 m, "
        ">10% canopy, excluding land predominantly under agricultural or urban use. "
        "Agricultural plantations and agroforestry (coffee, cocoa, oil palm, rubber...) are NOT forest."
    ),
    "representation": "Single band, value 1 = forest; non-forest is masked (no data).",
    "citation": "Bourgoin et al. (2026), JRC, doi:10.2905/JRC.3KATEH8",
    "catalog": "https://developers.google.com/earth-engine/datasets/catalog/JRC_GFC2020_V4",
}

FORTY = {
    "name": "ForTy 2020 v1.0",
    "asset": "projects/nature-trace/assets/forest_typology/forest_typology_2020_v1_0_collection",
    "bands": ["PrimaryForest", "NaturallyRegeneratingForest", "PlantedForest",
              "PlantationForest", "TreeCropsAndAgroforestry"],
    "definition": (
        "Global 10 m forest typology for 2020 with six classes aligned with FAO and EUDR: "
        "primary, naturally regenerating, planted, plantation forest, tree crops and agroforestry, other land."
    ),
    "representation": "Five uint8 score bands (0-250); other land = 250 - sum; class = argmax.",
    "citation": "Neumann et al. (2026), Sci Data 13, 1434, doi:10.1038/s41597-026-08299-5",
    "catalog": "https://developers.google.com/earth-engine/datasets/catalog/"
               "projects_nature-trace_assets_forest_typology_forest_typology_2020_v1_0_collection",
}

# ForTy classes with the catalog's own colours, so our charts match its maps.
FORTY_CLASSES = {
    1: ("Primary forest", "#1B7837"),
    2: ("Naturally regenerating", "#7FBF7B"),
    3: ("Planted forest", "#1D91C0"),
    4: ("Plantation forest", "#E65FA9"),
    5: ("Tree crops / agroforestry", "#E6AB02"),
    6: ("Other land", "#FDE278"),
}
GFC_FOREST_COLOR = "#4D9221"

# Stored on every extraction run so a result can be traced back to its recipe.
METHOD = ("gfc=unmask(Map,0); forty=argmax(5 bands + 250-sum); "
          "area-weighted frequencyHistogram of gfc*10+forty at 10 m")


# ------------------------------------------------------------------
# Connection
# ------------------------------------------------------------------

_state = {"ok": False, "error": None, "tried": 0.0}


def init_ee() -> bool:
    """Connect once. After a failure we retry at most once a minute, so a page
    view never waits on a dead connection more than that."""
    if _state["ok"]:
        return True
    if _state["error"] and time.time() - _state["tried"] < 60:
        return False
    _state["tried"] = time.time()
    try:
        email, creds = load_ee_credentials()
        if creds is not None:
            if not settings.ee_project:
                raise RuntimeError("EE_PROJECT is required for service-account auth")
            credentials = ee.ServiceAccountCredentials(email, key_data=json.dumps(creds))
            ee.Initialize(credentials, project=settings.ee_project)
        else:
            ee.Initialize(project=settings.ee_project)
        _state.update(ok=True, error=None)
        log.info("Earth Engine initialised (project=%s)", settings.ee_project)
    except Exception as e:  # noqa: BLE001 - any auth problem is shown in the UI instead
        _state.update(ok=False, error=str(e))
        log.warning("Earth Engine init failed: %s", e)
    return _state["ok"]


def status() -> dict:
    return {"ok": _state["ok"], "error": _state["error"], "project": settings.ee_project}


# ------------------------------------------------------------------
# Images
# ------------------------------------------------------------------

def gfc_forest() -> ee.Image:
    """1 = forest, 0 = not forest."""
    return ee.Image(GFC["asset"]).select(GFC["band"]).unmask(0).rename("gfc")


def forty_scores() -> ee.Image:
    """The five published score bands plus the derived 'other land' band."""
    m = ee.ImageCollection(FORTY["asset"]).mosaic().select(FORTY["bands"])
    other = ee.Image(250).subtract(m.reduce(ee.Reducer.sum())).rename("OtherLand")
    return m.addBands(other)


def forty_class() -> ee.Image:
    return forty_scores().toArray().arrayArgmax().arrayGet([0]).add(1).rename("forty").toInt()


def forty_confidence() -> ee.Image:
    return forty_scores().reduce(ee.Reducer.max()).divide(250).rename("conf")


# ------------------------------------------------------------------
# Map tiles
# ------------------------------------------------------------------

# Colours of the "where they differ" layer: GFC2020 forest without ForTy trees,
# and ForTy trees without GFC2020 forest. Pixels where they agree stay clear.
DIFFER_COLORS = {"GFC2020 forest only": "#1A73E8", "ForTy trees only": "#E8710A"}


def tile_urls() -> dict[str, str]:
    """XYZ tile URL templates for the optional dataset layers on the map.

    Earth Engine renders these on request; the URLs carry a token that expires
    after a few hours, so callers should cache them for less than that.
    """
    if not init_ee():
        raise RuntimeError(_state["error"])
    gfc = gfc_forest()
    cls = forty_class()
    trees = cls.lt(6)
    differ = gfc.And(trees.Not()).add(gfc.Not().And(trees).multiply(2)).selfMask()
    layers = {
        "gfc": gfc.selfMask().getMapId({"palette": [GFC_FOREST_COLOR]}),
        "forty": cls.getMapId({"min": 1, "max": 6, "palette": [c for _, c in FORTY_CLASSES.values()]}),
        "differ": differ.getMapId({"min": 1, "max": 2, "palette": list(DIFFER_COLORS.values())}),
    }
    return {k: v["tile_fetcher"].url_format for k, v in layers.items()}


# ------------------------------------------------------------------
# Extraction
# ------------------------------------------------------------------

def extract(polygons: list[dict]) -> list[dict]:
    """Composition of every polygon, in two batched requests.

    polygons: [{"id": int, "geometry": GeoJSON}]. Returns one dict per polygon
    with shares of its area (see summarise). The histogram is area-weighted,
    so a pixel half inside the polygon counts as half a pixel.
    """
    if not init_ee():
        raise RuntimeError(_state["error"])

    fc = ee.FeatureCollection([ee.Feature(ee.Geometry(p["geometry"]), {"label_id": p["id"]}) for p in polygons])
    joint = gfc_forest().multiply(10).add(forty_class()).rename("joint")
    hist_reducer = ee.Reducer.frequencyHistogram().combine(ee.Reducer.count().unweighted(), sharedInputs=True)
    hist = joint.reduceRegions(fc, hist_reducer, SCALE_M).getInfo()["features"]
    conf = forty_confidence().reduceRegions(fc, ee.Reducer.mean(), SCALE_M).getInfo()["features"]
    conf_by_id = {f["properties"]["label_id"]: f["properties"].get("mean") for f in conf}

    out = []
    for f in hist:
        p = f["properties"]
        h = {int(float(k)): float(v) for k, v in (p.get("histogram") or {}).items()}
        out.append(summarise(p["label_id"], h, int(p.get("count") or 0), conf_by_id.get(p["label_id"])))
    return out


def summarise(label_id: int, joint_hist: dict[int, float], px_count: int, conf_mean: float | None) -> dict:
    """Turn a {gfc*10 + forty_class: area} histogram into shares of the polygon.

    x_ff / x_fn / x_nf / x_nn are the 2x2 cross-tab: GFC forest or not (first
    letter) against ForTy tree class or other land (second letter).
    """
    total = sum(joint_hist.values())
    row = {"label_id": label_id, "px_count": px_count, "px_area": total,
           "joint_hist": {str(k): v for k, v in joint_hist.items()}, "forty_conf_mean": conf_mean}
    if total <= 0:
        return row

    def share(pred) -> float:
        return sum(v for k, v in joint_hist.items() if pred(k // 10, k % 10)) / total

    keys = ["forty_primary", "forty_natreg", "forty_planted", "forty_plantation", "forty_treecrops", "forty_other"]
    row["gfc_forest"] = share(lambda g, c: g == 1)
    for i, key in enumerate(keys, start=1):
        row[key] = share(lambda g, c, i=i: c == i)
    row["x_ff"] = share(lambda g, c: g == 1 and c < 6)
    row["x_fn"] = share(lambda g, c: g == 1 and c == 6)
    row["x_nf"] = share(lambda g, c: g == 0 and c < 6)
    row["x_nn"] = share(lambda g, c: g == 0 and c == 6)
    return row
