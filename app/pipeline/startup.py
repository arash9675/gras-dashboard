"""What the app does on boot, before the dashboard starts. Safe to run again.

  1. Import the reference GeoJSON as the pinned polygon set (first boot only).
  2. Fit the k-means location model on it (first boot only) and make sure
     every polygon has a cluster.
  3. Load the saved Earth Engine results for it (first boot only), so the
     dashboard works before any Earth Engine key is set up.

    python -m pipeline.startup
    python -m pipeline.startup --refit [--k 4]   # refit clusters on the reference set
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from core import db
from core.config import settings
from pipeline import clusters, polygon_sets

log = logging.getLogger("startup")
REFERENCE_NAME = "Gold deforestation labels"


def reference_set_id() -> int | None:
    rows = db.query("SELECT id FROM polygon_sets WHERE pinned ORDER BY id LIMIT 1")
    return rows[0]["id"] if rows else None


def ensure_reference_set() -> int:
    path = Path(settings.geojson_path)
    sid = reference_set_id()
    if sid is None:
        return polygon_sets.create_set(REFERENCE_NAME, path.name, path.read_bytes(), pinned=True)
    # Databases from before the props column: copy the source attributes in once.
    if db.query("SELECT 1 FROM labels WHERE set_id = %s AND props IS NULL LIMIT 1", (sid,)):
        feats = json.loads(path.read_bytes())["features"]
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.executemany("UPDATE labels SET props = %s WHERE set_id = %s AND feature_index = %s",
                            [(json.dumps(f.get("properties") or {}), sid, i) for i, f in enumerate(feats)])
            conn.commit()
        log.info("copied source attributes into the reference set")
    return sid


def load_saved_results(sid: int) -> bool:
    """Load the shipped Earth Engine results for the reference set, if it has none.

    data/reference_results.json holds the results of one real extraction run, so a
    fresh install shows the full dashboard without an Earth Engine key. The run is
    stored like any other, with the assets and method it was computed with, and a
    note saying where it came from. Recalculating replaces it with a new run.
    """
    path = Path(settings.geojson_path).with_name("reference_results.json")
    if not path.exists() or db.latest_run(sid):
        return False
    saved = json.loads(path.read_text())
    ids = {r["feature_index"]: r["id"] for r in
           db.query("SELECT id, feature_index FROM labels WHERE set_id = %s", (sid,))}
    rows = [{**r, "label_id": ids[r["feature_index"]]} for r in saved["results"] if r["feature_index"] in ids]
    if len(rows) != len(ids):
        log.warning("saved results do not match the reference polygons; skipping them")
        return False
    run = saved["run"]
    run_id = db.start_run(sid, run["gfc_asset"], run["forty_asset"], run["scale_m"], run["method"])
    db.insert_results(run_id, rows)
    db.finish_run(run_id, "ok", len(rows), f"loaded from {path.name}, computed {run['computed_at']} with Earth Engine")
    log.info("loaded saved Earth Engine results for the reference set (%d polygons)", len(rows))
    return True


def main(refit: bool = False, k: int | None = None) -> None:
    sid = ensure_reference_set()
    if refit or db.active_cluster_model() is None:
        clusters.fit(sid, k)
    elif db.query("SELECT COUNT(*) AS n FROM labels WHERE cluster_model_id IS NULL")[0]["n"]:
        clusters.classify_all()
    load_saved_results(sid)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--k", type=int)
    args = ap.parse_args()
    main(args.refit, args.k)
