"""K-means location clusters: geometry helpers, fitting and naming."""
import numpy as np
import pytest

from pipeline import clusters


def test_earth_coordinates_round_trip():
    for lon, lat in [(31.5, -0.6), (-44.2, -20.1), (0.0, 0.0), (179.0, 60.0)]:
        back = clusters.to_lonlat(clusters.to_xyz([lon], [lat])[0])
        assert back == pytest.approx((lon, lat), abs=1e-9)


def test_distance_is_in_km():
    a, b = clusters.to_xyz([0.0, 1.0], [0.0, 0.0])
    # one degree of longitude at the equator is about 111 km
    assert np.linalg.norm(a - b) == pytest.approx(111.2, abs=0.5)


def test_kmeans_finds_separated_groups():
    rng = np.random.default_rng(1)
    centres = [(31.5, -0.5), (-47.0, -22.0), (-40.0, -19.0)]
    lon = np.concatenate([rng.normal(c[0], 0.05, 40) for c in centres])
    lat = np.concatenate([rng.normal(c[1], 0.05, 40) for c in centres])
    X = clusters.to_xyz(lon, lat)
    lab, _ = clusters.kmeans(X, 3)
    # every true group lands in exactly one cluster
    for g in range(3):
        assert len(set(lab[g * 40:(g + 1) * 40].tolist())) == 1
    assert len(set(lab.tolist())) == 3
    assert clusters.silhouette(X, lab) > 0.9


def test_names_split_a_region_by_direction():
    names = clusters._names([(31.5, -0.5), (-47.0, -21.0), (-41.0, -21.0)], ["uganda", "brazil", "brazil"])
    assert names == ["Uganda", "Brazil · west", "Brazil · east"]
