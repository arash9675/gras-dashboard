"""summarise() turns a joint pixel histogram into the shares every page shows."""
import pytest

from pipeline.earth_engine import summarise


def test_shares_and_cross_tab():
    # code = gfc * 10 + forty_class; areas in pixels (area-weighted, so fractions are fine)
    hist = {12: 3.0,    # GFC forest, ForTy naturally regenerating
            16: 1.0,    # GFC forest, ForTy other land
            2: 4.5,     # GFC not forest, ForTy naturally regenerating
            5: 0.5,     # GFC not forest, ForTy tree crops
            6: 1.0}     # neither
    r = summarise(7, hist, px_count=10, conf_mean=0.9)
    assert r["px_area"] == pytest.approx(10.0)
    assert r["gfc_forest"] == pytest.approx(0.4)
    assert r["forty_natreg"] == pytest.approx(0.75)
    assert r["forty_treecrops"] == pytest.approx(0.05)
    assert r["forty_other"] == pytest.approx(0.2)
    assert r["x_ff"] == pytest.approx(0.3)
    assert r["x_fn"] == pytest.approx(0.1)
    assert r["x_nf"] == pytest.approx(0.5)
    assert r["x_nn"] == pytest.approx(0.1)
    # the four cells of the cross-tab cover the whole polygon
    assert r["x_ff"] + r["x_fn"] + r["x_nf"] + r["x_nn"] == pytest.approx(1.0)


def test_six_forty_classes_sum_to_one():
    hist = {1: 1, 2: 1, 3: 1, 14: 1, 15: 1, 16: 1}
    r = summarise(1, hist, 6, None)
    keys = ["forty_primary", "forty_natreg", "forty_planted", "forty_plantation", "forty_treecrops", "forty_other"]
    assert sum(r[k] for k in keys) == pytest.approx(1.0)
    assert all(r[k] == pytest.approx(1 / 6) for k in keys)


def test_polygon_without_pixels_has_no_shares():
    r = summarise(3, {}, 0, None)
    assert r["px_area"] == 0
    assert "gfc_forest" not in r
