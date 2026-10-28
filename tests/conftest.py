"""Shared test set-up.

Unit tests need nothing but the Python packages. The database tests run only
when TEST_DATABASE_URL points at a throwaway PostGIS database; they create and
drop tables freely, so never point it at a database whose data you need.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

# Settings are read once at import time, so point them at the test files first.
TEST_DB = os.environ.get("TEST_DATABASE_URL")
if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB
os.environ.setdefault("SCHEMA_PATH", str(ROOT / "db" / "init.sql"))
os.environ.setdefault("GEOJSON_PATH", str(next((ROOT / "data").glob("*.geojson"))))


@pytest.fixture(scope="session")
def reference_geojson() -> bytes:
    return Path(os.environ["GEOJSON_PATH"]).read_bytes()


needs_db = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to a throwaway PostGIS database")


# ------------------------------------------------------------------
# Database fixtures (only with TEST_DATABASE_URL)
# ------------------------------------------------------------------

@pytest.fixture(scope="session")
def db():
    import psycopg
    assert "test" in TEST_DB.rsplit("/", 1)[-1], "refusing to wipe a database whose name lacks 'test'"
    from core import db as core_db
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    core_db.apply_schema()
    core_db.apply_schema()   # a second run must be harmless
    return core_db


@pytest.fixture(scope="session")
def reference_set(db, reference_geojson):
    from pipeline import clusters, polygon_sets
    sid = polygon_sets.create_set("reference", "ref.geojson", reference_geojson, pinned=True)
    clusters.fit(sid)
    return sid


@pytest.fixture(scope="session")
def results(db, reference_set):
    """A finished run with made-up results for two polygons: one both-forest, one neither."""
    ids = [r["id"] for r in db.query("SELECT id FROM labels WHERE set_id = %s AND area_m2 >= 100 ORDER BY id LIMIT 2",
                                     (reference_set,))]
    run = db.start_run(reference_set, "gfc", "forty", 10, "test")
    both = {"label_id": ids[0], "px_count": 20, "px_area": 20.0, "gfc_forest": 1.0, "forty_natreg": 1.0,
            "forty_primary": 0, "forty_planted": 0, "forty_plantation": 0, "forty_treecrops": 0, "forty_other": 0,
            "x_ff": 1.0, "x_fn": 0, "x_nf": 0, "x_nn": 0, "forty_conf_mean": 0.9}
    neither = {**both, "label_id": ids[1], "gfc_forest": 0.0, "forty_natreg": 0, "forty_other": 1.0,
               "x_ff": 0, "x_nn": 1.0}
    db.insert_results(run, [both, neither])
    db.finish_run(run, "ok", 2, "test")
    return ids
