"""GeoJSON validation for uploads and the reference file."""
import json

import pytest

from pipeline import polygon_sets as ps

SQUARE = {"type": "Polygon", "coordinates": [[[31.5, -0.5], [31.5005, -0.5], [31.5005, -0.5005],
                                             [31.5, -0.5005], [31.5, -0.5]]]}


def fc(*features, **extra):
    return json.dumps({"type": "FeatureCollection", "features": list(features), **extra}).encode()


def feat(geom=SQUARE, **props):
    return {"type": "Feature", "properties": props, "geometry": geom}


def test_reference_file_parses(reference_geojson):
    rows = ps.parse_geojson(reference_geojson)
    assert len(rows) == 198
    assert {r["region"] for r in rows} == {"uganda", "brazil"}
    assert all(r["area_m2"] > 0 for r in rows)


def test_year_area_region_and_properties_are_kept():
    (row,) = ps.parse_geojson(fc(feat(year="2022", Verified="Yes", note="field visit")))
    assert row["source_year"] == 2022
    assert row["region"] == "uganda"
    # about 55 m x 55 m
    assert 2900 < row["area_m2"] < 3200
    assert json.loads(row["props"])["note"] == "field visit"


def test_bad_features_are_skipped_not_fatal():
    point = {"type": "Point", "coordinates": [31.5, -0.5]}
    rows = ps.parse_geojson(fc(feat(), feat(point)))
    assert len(rows) == 1


@pytest.mark.parametrize("raw, message", [
    (b"not json", "Not valid JSON"),
    (json.dumps({"type": "Feature"}).encode(), "FeatureCollection"),
    (fc(), "no features"),
    (fc(feat(), crs={"type": "name", "properties": {"name": "EPSG:3857"}}), "WGS84"),
])
def test_unusable_files_are_rejected(raw, message):
    with pytest.raises(ps.UploadError, match=message):
        ps.parse_geojson(raw)


def test_feature_limit(monkeypatch):
    monkeypatch.setattr(ps, "MAX_FEATURES", 2)
    with pytest.raises(ps.UploadError, match="limit"):
        ps.parse_geojson(fc(feat(), feat(), feat()))


def test_region_from_location():
    assert ps.detect_region(32.0, -0.5) == "uganda"
    assert ps.detect_region(-45.0, -20.0) == "brazil"
    assert ps.detect_region(10.0, 50.0) == "other"
