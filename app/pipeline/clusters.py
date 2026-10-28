"""K-means location clusters for polygons.

The model is fitted once on the reference polygon set and then used to
classify the polygons of every uploaded set, so cluster names mean the same
thing across sets. A polygon farther than `max_dist_km` from every cluster
centre is left unassigned ("Outside known clusters") instead of being forced
into a cluster on another continent.

Centroids are converted to 3-D Earth-centred coordinates (km) so distances
are true distances, not degrees.
"""
from __future__ import annotations

import logging

import numpy as np

from core import db

log = logging.getLogger("clusters")
EARTH_KM = 6371.0
K_RANGE = range(3, 9)   # k=2 just splits the two regions; we want sub-regional groups


# ------------------------------------------------------------------
# Earth coordinates
# ------------------------------------------------------------------

def to_xyz(lon, lat) -> np.ndarray:
    lon, lat = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    return np.c_[np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)] * EARTH_KM


def to_lonlat(xyz: np.ndarray) -> tuple[float, float]:
    x, y, z = xyz / np.linalg.norm(xyz)
    return float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(z)))


# ------------------------------------------------------------------
# K-means and silhouette
# ------------------------------------------------------------------
# Written with numpy on purpose: scikit-learn would add a large dependency to
# the image for two small functions, and 200-2000 points need nothing faster.

def kmeans(X: np.ndarray, k: int, seeds: int = 10, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means with k-means++ starts; best of `seeds` runs by inertia."""
    best = None
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        C = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d = np.min(((X[:, None] - np.array(C)[None]) ** 2).sum(-1), axis=1)
            C.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
        C = np.array(C)
        for _ in range(iters):
            lab = ((X[:, None] - C[None]) ** 2).sum(-1).argmin(1)
            C2 = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
            if np.allclose(C2, C):
                break
            C = C2
        inertia = ((X - C[lab]) ** 2).sum()
        if best is None or inertia < best[2]:
            best = (lab, C, inertia)
    return best[0], best[1]


def silhouette(X: np.ndarray, lab: np.ndarray) -> float:
    D = np.sqrt(((X[:, None] - X[None]) ** 2).sum(-1))
    s = []
    for i in range(len(X)):
        same = lab == lab[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, lab == j].mean() for j in set(lab.tolist()) if j != lab[i])
        s.append((b - a) / max(a, b))
    return float(np.mean(s))


# ------------------------------------------------------------------
# Fit and classify
# ------------------------------------------------------------------

def _names(centres_ll: list[tuple[float, float]], regions: list[str]) -> list[str]:
    """'Uganda' for a region with one cluster, otherwise 'Brazil · north' etc.,
    from each centre's position relative to the region's other centres."""
    names = []
    for i, (lon, lat) in enumerate(centres_ll):
        reg = regions[i]
        label = {"uganda": "Uganda", "brazil": "Brazil"}.get(reg, "Other")
        peers = [j for j, r in enumerate(regions) if r == reg]
        if len(peers) == 1:
            names.append(label)
            continue
        mlon = np.mean([centres_ll[j][0] for j in peers])
        mlat = np.mean([centres_ll[j][1] for j in peers])
        dlon, dlat = lon - mlon, lat - mlat
        ns = "north" if dlat > 0 else "south"
        ew = "east" if dlon > 0 else "west"
        direction = ns if abs(dlat) >= abs(dlon) * 0.6 else (ew if abs(dlon) >= abs(dlat) * 1.6 else f"{ns}-{ew}")
        names.append(f"{label} · {direction}")
    # make duplicates unique
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if names.count(n) == 1 else f"{n} {seen[n]}")
    return out


def fit(set_id: int, k: int | None = None) -> int:
    """Fit a model on one polygon set, make it active, and classify every polygon."""
    rows = db.label_centroids(set_id)
    X = to_xyz([r["centroid_lon"] for r in rows], [r["centroid_lat"] for r in rows])
    candidates = [k] if k else [kk for kk in K_RANGE if kk < len(X)]
    best = None
    for kk in candidates:
        lab, C = kmeans(X, kk)
        s = silhouette(X, lab)
        log.info("k=%d silhouette=%.3f", kk, s)
        if best is None or s > best[2]:
            best = (lab, C, s, kk)
    lab, C, sil, k = best

    regions = []
    radii = []
    for j in range(k):
        members = [rows[i] for i in np.where(lab == j)[0]]
        regs = [m["region"] for m in members]
        regions.append(max(set(regs), key=regs.count))
        d = np.linalg.norm(X[lab == j] - C[j], axis=1)
        radii.append(float(np.percentile(d, 90)) if len(d) else 0.0)
    centres_ll = [to_lonlat(c) for c in C]
    names = _names(centres_ll, regions)
    # Unassigned beyond 3x the largest cluster radius (at least 100 km).
    max_dist = max(100.0, 3 * max(radii))
    set_name = (db.polygon_set(set_id) or {}).get("name", f"set {set_id}")

    with db.get_conn() as conn:
        conn.execute("UPDATE cluster_models SET active = FALSE")
        mid = conn.execute(
            "INSERT INTO cluster_models (k, fitted_on, n_train, silhouette, max_dist_km) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id", (k, set_name, len(X), sil, max_dist)).fetchone()["id"]
        for j in range(k):
            conn.execute(
                "INSERT INTO clusters (model_id, cluster_id, name, centroid_lon, centroid_lat, radius_km, n_train) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (mid, j, names[j], centres_ll[j][0], centres_ll[j][1], radii[j], int((lab == j).sum())))
        conn.commit()
    log.info("cluster model %d: k=%d silhouette=%.3f names=%s", mid, k, sil, names)
    classify_all()
    return mid


def classify(set_id: int | None = None) -> None:
    """Assign the active model's nearest cluster to polygons (one set, or all)."""
    model = db.active_cluster_model()
    if not model:
        return
    rows = db.label_centroids(set_id)
    if not rows:
        return
    X = to_xyz([r["centroid_lon"] for r in rows], [r["centroid_lat"] for r in rows])
    C = to_xyz([c["centroid_lon"] for c in model["clusters"]], [c["centroid_lat"] for c in model["clusters"]])
    D = np.linalg.norm(X[:, None] - C[None], axis=2)
    nearest = D.argmin(1)
    ids = [c["cluster_id"] for c in model["clusters"]]
    data = []
    for i, r in enumerate(rows):
        cid = ids[nearest[i]] if D[i, nearest[i]] <= model["max_dist_km"] else None
        data.append((model["id"], cid, r["id"]))
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.executemany("UPDATE labels SET cluster_model_id = %s, cluster_id = %s WHERE id = %s", data)
        conn.commit()


def classify_all() -> None:
    classify(None)
