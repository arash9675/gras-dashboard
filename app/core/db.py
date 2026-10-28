"""PostgreSQL/PostGIS data access.

Every query here is fixed SQL with bound parameters - nothing builds SQL from
user input. The shape of the data lives in db/init.sql; most reads go through
its views (v_polygon, v_set_summary, v_latest_run) so the app and the SQL
agree on how a share or a category is computed.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from core.config import settings


@contextmanager
def get_conn():
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def query(sql: str, params: tuple | list | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def execute(sql: str, params: tuple | list | None = None) -> None:
    with get_conn() as conn:
        conn.execute(sql, params or ())
        conn.commit()


def reader_query(sql: str, params: tuple | list | None = None) -> list[dict]:
    """Like query(), but as the read-only gras_reader role, which can read the
    views and nothing else. The assistant's tools read through this."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET ROLE gras_reader")
        cur.execute(sql, params or ())
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        conn.rollback()
        return rows


def apply_schema() -> None:
    """Run db/init.sql. It is idempotent, so we run it on every start."""
    with get_conn() as conn:
        conn.execute(Path(settings.schema_path).read_text())
        conn.commit()


# ------------------------------------------------------------------
# Polygon sets
# ------------------------------------------------------------------

def polygon_sets() -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM v_set_summary ORDER BY pinned DESC, last_used_at DESC"))


def polygon_set(set_id: int) -> dict | None:
    rows = query("SELECT * FROM v_set_summary WHERE id = %s", (set_id,))
    return rows[0] if rows else None


def default_set_id() -> int | None:
    rows = query("SELECT id FROM polygon_sets ORDER BY pinned DESC, last_used_at DESC LIMIT 1")
    return rows[0]["id"] if rows else None


def touch_set(set_id: int) -> None:
    # last_used_at drives the least-recently-used cache in pipeline/polygon_sets.py
    execute("UPDATE polygon_sets SET last_used_at = now() WHERE id = %s", (set_id,))


# ------------------------------------------------------------------
# Polygons
# ------------------------------------------------------------------

def polygons(set_id: int, with_geometry: bool = False) -> pd.DataFrame:
    """One row per polygon of a set, joined with its latest results (v_polygon)."""
    df = pd.DataFrame(query("SELECT * FROM v_polygon WHERE set_id = %s ORDER BY id", (set_id,)))
    if not with_geometry and "geometry" in df:
        df = df.drop(columns=["geometry"])
    return df


def label_geometries(set_id: int) -> list[dict]:
    return query("SELECT id, ST_AsGeoJSON(geom)::json AS geometry FROM labels WHERE set_id = %s ORDER BY id",
                 (set_id,))


def label_centroids(set_id: int | None = None) -> list[dict]:
    """Centroids of one set, or of every polygon when set_id is None (cluster refit)."""
    if set_id is None:
        return query("SELECT id, set_id, centroid_lon, centroid_lat, region FROM labels ORDER BY id")
    return query("SELECT id, set_id, centroid_lon, centroid_lat, region FROM labels WHERE set_id = %s ORDER BY id",
                 (set_id,))


# ------------------------------------------------------------------
# Extraction runs and results
# ------------------------------------------------------------------

def latest_run(set_id: int) -> dict | None:
    rows = query("SELECT * FROM v_latest_run WHERE set_id = %s", (set_id,))
    return rows[0] if rows else None


def start_run(set_id: int, gfc_asset: str, forty_asset: str, scale_m: float, method: str) -> int:
    with get_conn() as conn:
        rid = conn.execute(
            "INSERT INTO extraction_runs (set_id, gfc_asset, forty_asset, scale_m, method, status) "
            "VALUES (%s,%s,%s,%s,%s,'running') RETURNING id",
            (set_id, gfc_asset, forty_asset, scale_m, method),
        ).fetchone()["id"]
        conn.commit()
        return rid


def finish_run(run_id: int, status: str, n_polygons: int, note: str) -> None:
    execute("UPDATE extraction_runs SET status=%s, n_polygons=%s, note=%s, finished_at=now() WHERE id=%s",
            (status, n_polygons, note, run_id))


RESULT_COLS = [
    "px_count", "px_area", "gfc_forest",
    "forty_primary", "forty_natreg", "forty_planted", "forty_plantation",
    "forty_treecrops", "forty_other", "forty_conf_mean",
    "x_ff", "x_fn", "x_nf", "x_nn",
]


def insert_results(run_id: int, rows: list[dict]) -> None:
    cols = ["run_id", "label_id", *RESULT_COLS, "joint_hist"]
    placeholders = ",".join(["%s"] * len(cols))
    data = [
        (run_id, r["label_id"], *[r.get(c) for c in RESULT_COLS], json.dumps(r.get("joint_hist") or {}))
        for r in rows
    ]
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(f"INSERT INTO polygon_results ({','.join(cols)}) VALUES ({placeholders})", data)
        conn.commit()


# ------------------------------------------------------------------
# Location clusters
# ------------------------------------------------------------------

def active_cluster_model() -> dict | None:
    rows = query("SELECT * FROM cluster_models WHERE active ORDER BY id DESC LIMIT 1")
    if not rows:
        return None
    m = rows[0]
    m["clusters"] = query("SELECT * FROM clusters WHERE model_id = %s ORDER BY cluster_id", (m["id"],))
    return m
