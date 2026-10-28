"""One Earth Engine extraction of a polygon set, stored as a run.

Each run records the assets, scale and method it used, so results stay
traceable and a dataset update can be re-run and compared instead of quietly
replacing the numbers. A failed run is kept too, with its error.

    python -m pipeline.extraction            # every set without results (used on start-up)
    python -m pipeline.extraction --set 3    # one set, even if it has results
"""
from __future__ import annotations

import argparse
import logging
import time

from core import db
from pipeline import earth_engine as eec

log = logging.getLogger("extraction")

# Polygons per Earth Engine request. 400 keeps a request well under EE's
# payload and timeout limits while staying at a few seconds per set.
CHUNK = 400


def run_extraction(set_id: int) -> dict:
    polys = db.label_geometries(set_id)
    run_id = db.start_run(set_id, eec.GFC["asset"], eec.FORTY["asset"], eec.SCALE_M, eec.METHOD)
    t0 = time.time()
    try:
        rows = []
        for i in range(0, len(polys), CHUNK):
            rows.extend(eec.extract(polys[i:i + CHUNK]))
        db.insert_results(run_id, rows)
        valid = sum(1 for r in rows if r.get("gfc_forest") is not None)
        note = f"{valid}/{len(polys)} polygons with pixels, {time.time() - t0:.1f}s"
        db.finish_run(run_id, "ok", len(rows), note)
        return {"run_id": run_id, "status": "ok", "note": note}
    except Exception as e:  # noqa: BLE001 - we want the failure on the run, not a crashed page
        db.finish_run(run_id, "failed", 0, str(e)[:500])
        log.exception("extraction failed")
        return {"run_id": run_id, "status": "failed", "note": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=int, help="extract this set even if it has results")
    args = ap.parse_args()
    if not eec.init_ee():
        log.warning("Earth Engine unavailable; skipping extraction: %s", eec.status()["error"])
        raise SystemExit(0)
    targets = [args.set] if args.set else [
        r["id"] for r in db.query("SELECT id FROM v_set_summary WHERE run_id IS NULL AND n_polygons > 0")]
    for sid in targets:
        res = run_extraction(sid)
        log.info("set %s run %s: %s (%s)", sid, res["run_id"], res["status"], res["note"])
