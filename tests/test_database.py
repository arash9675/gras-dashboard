"""The schema and its views against a real PostGIS database.

Runs only with TEST_DATABASE_URL set, and only on a database whose name
contains "test": the fixtures wipe the public schema before they start.
"""
import psycopg
import pytest

from conftest import needs_db

pytestmark = needs_db


def test_reference_set_and_clusters(db, reference_set):
    assert db.query("SELECT COUNT(*) AS n FROM labels WHERE set_id = %s", (reference_set,))[0]["n"] == 198
    names = {r["name"] for r in db.query("SELECT name FROM clusters")}
    assert names == {"Uganda", "Brazil · west", "Brazil · east"}
    model = db.active_cluster_model()
    assert model["k"] == 3 and model["silhouette"] > 0.85


def test_source_properties_are_kept(db, reference_set):
    row = db.query("SELECT props FROM labels WHERE set_id = %s ORDER BY id LIMIT 1", (reference_set,))[0]
    assert row["props"]["Verified"] == "Yes"


def test_views_derive_categories(db, reference_set, results):
    both, neither = results
    rows = {r["id"]: r for r in db.query(
        "SELECT id, category, forty_tree, pixel_agreement FROM v_polygon WHERE id = ANY(%s)", (results,))}
    assert rows[both]["category"] == "Both forest"
    assert rows[both]["forty_tree"] == pytest.approx(1.0)
    assert rows[neither]["category"] == "Neither"
    assert rows[neither]["pixel_agreement"] == pytest.approx(1.0)
    cats = {r["category"] for r in db.query("SELECT category FROM q_agreement_categories WHERE set_id = %s",
                                            (reference_set,))}
    assert cats >= {"Both forest", "Neither"}


def test_shares_outside_0_1_are_rejected(db, reference_set):
    label = db.query("SELECT id FROM labels WHERE set_id = %s LIMIT 1", (reference_set,))[0]["id"]
    run = db.start_run(reference_set, "gfc", "forty", 10, "test")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.insert_results(run, [{"label_id": label, "gfc_forest": 1.5}])


def test_reader_role_sees_views_only(db, reference_set):
    assert db.reader_query("SELECT COUNT(*) AS n FROM v_polygon")[0]["n"] >= 198
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.reader_query("SELECT COUNT(*) FROM labels")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.reader_query("DELETE FROM dashboards")
