"""What the app does on boot, before the dashboard starts. Safe to run again.

  1. Import the reference GeoJSON as the pinned polygon set (first boot only).
  2. Fit the k-means location model on it (first boot only) and make sure
     every polygon has a cluster.

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


def main(refit: bool = False, k: int | None = None) -> None:
    sid = ensure_reference_set()
    if refit or db.active_cluster_model() is None:
        clusters.fit(sid, k)
    elif db.query("SELECT COUNT(*) AS n FROM labels WHERE cluster_model_id IS NULL")[0]["n"]:
        clusters.classify_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--k", type=int)
    args = ap.parse_args()
    main(args.refit, args.k)
