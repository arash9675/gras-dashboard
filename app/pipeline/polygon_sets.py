"""Polygon sets: import a GeoJSON file, classify it, extract EE results, and
keep the cache bounded (least recently used sets are evicted).

A polygon set is the unit of caching: one file -> one set -> its polygons, their
cluster labels and one or more extraction runs. The reference set that ships
with the project is pinned and never evicted.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from pyproj import Geod
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.validation import make_valid

from core import db
from pipeline import clusters, extraction

log = logging.getLogger("polygon_sets")
GEOD = Geod(ellps="WGS84")

MAX_FEATURES = int(os.environ.get("UPLOAD_MAX_FEATURES", "2000"))
MAX_BYTES = int(os.environ.get("UPLOAD_MAX_MB", "10")) * 1024 * 1024
# How many uploaded sets we keep; the pinned reference set does not count.
CACHE_MAX_SETS = int(os.environ.get("CACHE_MAX_SETS", "5"))


class UploadError(ValueError):
    """A problem with an uploaded file, worded for the user."""


# ------------------------------------------------------------------
# Reading a file
# ------------------------------------------------------------------

def detect_region(lon: float, lat: float) -> str:
    """Name the two regions of the reference data from the location; anything else is 'other'."""
    if 30.0 <= lon <= 34.0 and -2.0 <= lat <= 1.0:
        return "uganda"
    if -50.0 <= lon <= -38.0 and -25.0 <= lat <= -15.0:
        return "brazil"
    return "other"


def parse_geojson(raw: bytes) -> list[dict]:
    """Validate a GeoJSON FeatureCollection and return polygon rows ready to insert."""
    if len(raw) > MAX_BYTES:
        raise UploadError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UploadError(f"Not valid JSON: {e}") from e
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise UploadError("Expected a GeoJSON FeatureCollection.")
    feats = data["features"]
    if not feats:
        raise UploadError("The file has no features.")
    if len(feats) > MAX_FEATURES:
        raise UploadError(f"The file has {len(feats)} features; the limit is {MAX_FEATURES}.")
    crs = (data.get("crs") or {}).get("properties", {}).get("name", "")
    if crs and "4326" not in crs and "CRS84" not in crs:
        raise UploadError(f"Coordinates must be WGS84 longitude/latitude (EPSG:4326); file says {crs}.")

    rows, skipped = [], []
    for i, feat in enumerate(feats):
        try:
            geom = shape(feat.get("geometry"))
            if not geom.is_valid:
                geom = make_valid(geom)
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
            elif geom.geom_type == "GeometryCollection":
                polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                geom = MultiPolygon([p for g in polys for p in getattr(g, "geoms", [g])])
            if geom.geom_type != "MultiPolygon" or geom.is_empty:
                raise ValueError(f"{geom.geom_type} is not a polygon")
            minx, miny, maxx, maxy = geom.bounds
            if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
                raise ValueError("coordinates are not longitude/latitude")
        except Exception as e:  # noqa: BLE001 - report and skip bad features
            skipped.append(f"feature {i}: {e}")
            continue
        props = feat.get("properties") or {}
        year = props.get("year", props.get("Year"))
        try:
            year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        c = geom.centroid
        rows.append({
            "feature_index": i, "source_year": year,
            "verified": str(props.get("Verified", props.get("verified", "Yes"))),
            "region": detect_region(c.x, c.y),
            "area_m2": abs(GEOD.geometry_area_perimeter(geom)[0]),
            "lon": c.x, "lat": c.y, "geojson": json.dumps(mapping(geom)),
            "props": json.dumps(props, default=str),   # the uploader's own attributes, kept as they came
        })
    if not rows:
        raise UploadError("No usable polygons. " + "; ".join(skipped[:3]))
    if skipped:
        log.warning("skipped %d features: %s", len(skipped), skipped[:5])
    return rows


# ------------------------------------------------------------------
# Storing a set and keeping the cache bounded
# ------------------------------------------------------------------

def find_by_checksum(raw: bytes) -> int | None:
    rows = db.query("SELECT id FROM polygon_sets WHERE checksum = %s", (hashlib.sha256(raw).hexdigest(),))
    return rows[0]["id"] if rows else None


def create_set(name: str, filename: str, raw: bytes, pinned: bool = False) -> int:
    """Store the polygons of a file as a new set. Returns the set id."""
    rows = parse_geojson(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    with db.get_conn() as conn, conn.cursor() as cur:
        set_id = cur.execute(
            "INSERT INTO polygon_sets (name, source_filename, checksum, pinned) VALUES (%s,%s,%s,%s) RETURNING id",
            (name, filename, checksum, pinned)).fetchone()["id"]
        cur.executemany(
            """INSERT INTO labels (set_id, feature_index, source_year, verified, region, area_m2,
                                   centroid_lon, centroid_lat, props, geom)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))""",
            [(set_id, r["feature_index"], r["source_year"], r["verified"], r["region"], r["area_m2"],
              r["lon"], r["lat"], r["props"], r["geojson"]) for r in rows])
        conn.commit()
    log.info("created polygon set %d '%s' with %d polygons", set_id, name, len(rows))
    return set_id


def evict_lru(keep: int | None = None) -> list[str]:
    """Delete least recently used unpinned sets beyond the cache size."""
    unpinned = db.query("SELECT id, name FROM polygon_sets WHERE NOT pinned ORDER BY last_used_at DESC")
    gone = []
    for s in unpinned[CACHE_MAX_SETS:]:
        if s["id"] == keep:
            continue
        db.execute("DELETE FROM polygon_sets WHERE id = %s", (s["id"],))
        gone.append(s["name"])
        log.info("evicted polygon set %d '%s' (least recently used)", s["id"], s["name"])
    return gone


# ------------------------------------------------------------------
# Upload, end to end
# ------------------------------------------------------------------

def add_upload(name: str, filename: str, raw: bytes) -> dict:
    """Full pipeline for an uploaded file: dedupe, store, classify, extract, evict."""
    existing = find_by_checksum(raw)
    if existing:
        db.touch_set(existing)
        return {"set_id": existing, "status": "cached", "note": "This file was already uploaded; using the cached set.",
                "evicted": []}
    set_id = create_set(name, filename, raw)
    clusters.classify(set_id)
    res = extraction.run_extraction(set_id)
    evicted = evict_lru(keep=set_id)
    return {"set_id": set_id, "status": res["status"], "note": res["note"], "evicted": evicted}
