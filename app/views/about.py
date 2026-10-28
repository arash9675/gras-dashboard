"""Datasets & method: what is compared and how each number is computed."""
from __future__ import annotations

import streamlit as st

import ui
from core import db
from pipeline import earth_engine as eec

ui.page_header("Datasets & method", show_selection=False)

c1, c2 = st.columns(2)
for col, ds in [(c1, eec.GFC), (c2, eec.FORTY)]:
    with col:
        st.subheader(ds["name"])
        st.markdown(f"**Definition.** {ds['definition']}")
        st.markdown(f"**Data representation.** {ds['representation']}")
        st.markdown(f"**Asset.** `{ds['asset']}`")
        st.markdown(f"**Citation.** {ds['citation']} · [catalog entry]({ds['catalog']})")

st.markdown("**ForTy classes** (catalog colours, used throughout):")
ui.legend({f"{i} · {n}": c for i, (n, c) in eec.FORTY_CLASSES.items()})

st.header("Key differences that shape the analysis")
st.markdown("""
| | GFC2020 v4 | ForTy 2020 v1.0 |
|---|---|---|
| Question answered | Is this forest (EUDR)? | Which of six land/forest types is this? |
| Classes | 1 (forest); everything else masked | 6, from five score bands + derived *other land* |
| Agroforestry, tree crops | **Excluded** from forest | Own class (5), a tree class but not forest |
| Uncertainty | None published per pixel | Relative class scores (0-250) per pixel |
| Native grid | 10 m | 10 m, UTM tiles |
""")

st.header("How each number is computed")
st.markdown(f"""
1. **Polygon sets.** Each GeoJSON file (the reference file or an upload) becomes a polygon set in PostGIS
   (`polygon_sets`, `labels`). Region comes from location; area is geodesic (WGS84).
2. **Location clusters.** K-means on polygon centroids (in 3-D Earth coordinates, so distances are in km) is
   fitted once on the reference set, with k chosen by silhouette. Uploaded polygons get the nearest cluster, or
   none if they are far from every cluster.
3. **Pixels.** GFC2020 is unmasked to 0 so non-forest is counted. ForTy class = argmax over the five bands
   plus *other land* = 250 − sum, as in the catalog example.
4. **One combined code per pixel**: `gfc × 10 + forty_class`. An area-weighted frequency histogram of this
   code over each polygon at {eec.SCALE_M} m gives, in a single pass, both datasets' composition and their
   pixel-level cross-tab. Partial pixels at the edges count by the share inside the polygon.
5. **Batching.** Polygons go to Earth Engine in `reduceRegions` calls of up to 400 (a few seconds per set).
6. **Storage and cache.** Each run is a row in `extraction_runs` and one row per polygon in `polygon_results`.
   Uploaded sets are a least-recently-used cache; the reference set is pinned. Views derive the shares and
   categories the dashboard shows, so every number can be traced in SQL.
""")

sid = ui.current_set_id()
run = db.latest_run(sid) if sid else None
if run:
    st.caption(f"Selected set, latest run #{run['id']} · {run['finished_at']:%Y-%m-%d %H:%M} UTC · "
               f"{run['note']} · method: {run['method']}")

st.header("Database schema")
st.code("""polygon_sets     (id, name, source_filename, checksum, pinned, created_at, last_used_at)
labels           (id, set_id, feature_index, source_year, verified, region, area_m2,
                  centroid_lon, centroid_lat, cluster_model_id, cluster_id, geom MultiPolygon 4326)
cluster_models   (id, k, fitted_on, n_train, silhouette, max_dist_km, active, fitted_at)
clusters         (model_id, cluster_id, name, centroid_lon, centroid_lat, radius_km, n_train)
extraction_runs  (id, set_id, gfc_asset, forty_asset, scale_m, method, status, n_polygons, note,
                  started_at, finished_at)
polygon_results  (run_id, label_id, px_count, px_area, gfc_forest,
                  forty_primary .. forty_other, forty_conf_mean, x_ff, x_fn, x_nf, x_nn, joint_hist)
v_latest_run     latest successful run per polygon set
v_polygon        polygons + latest results + derived shares, categories and cluster name
v_set_summary    one row per polygon set (counts, years, cache status)""", language="text")
