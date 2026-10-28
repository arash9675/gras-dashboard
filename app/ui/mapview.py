"""Python side of the MapLibre map component (components/maplibre/index.html)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from pipeline import earth_engine as eec

_component = components.declare_component(
    "maplibre_map", path=str(Path(__file__).parent / "components" / "maplibre"))

# The optional dataset layers. A 10 m map viewed at continent scale is
# resampled into a blur, so a layer only shows from zoom 10 (about 150 m a pixel).
LAYERS = {
    "gfc": "GFC2020 forest",
    "forty": "ForTy class",
    "differ": "Where they differ",
}
LAYER_MINZOOM = 10


@st.cache_data(ttl=3000, show_spinner=False)
def _tile_urls() -> dict[str, str]:
    # Earth Engine tile tokens expire after a few hours; 50 minutes is safe.
    return eec.tile_urls()


def dataset_layer(name: str | None) -> dict | None:
    """The tile layer for one of LAYERS, or None (also when Earth Engine is down)."""
    if not name:
        return None
    try:
        url = _tile_urls()[name]
    except Exception:  # noqa: BLE001 - the map still works without the layer
        return None
    return {"url": url, "minzoom": LAYER_MINZOOM, "opacity": 0.75,
            "attribution": "GFC2020: EC JRC · ForTy: Neumann et al. · via Google Earth Engine"}


def map_view(polygons: dict, bounds: list[list[float]], fit_key: str,
             selected: int | None = None, select_key: str = "", focus: list[float] | None = None,
             height: int = 640, key: str = "map", basemap: str = "osm", layer: dict | None = None) -> dict | None:
    """Render the map. Returns {"id", "nonce"} of the last clicked polygon, or None.

    polygons   FeatureCollection; properties: id, color, tiny, tip (HTML), c ([lon, lat])
    bounds     [[west, south], [east, north]] of the shown polygons
    fit_key    change it to make the map refit to `bounds` (done after each filter change)
    basemap    "osm" (OpenStreetMap) or "sat" (Esri imagery)
    layer      one dataset layer from dataset_layer(), drawn under the polygons, or None
    """
    return _component(polygons=polygons, bounds=bounds, fit_key=fit_key,
                      selected=selected, select_key=select_key, focus=focus, height=height, basemap=basemap,
                      layer=layer, key=key, default=None)
