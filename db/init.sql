-- GRAS forest dashboard - database schema
--
-- Idempotent: the app runs it on every start (core/db.py apply_schema), so a
-- change to a view reaches an existing database without a migration tool. A
-- short upgrade section at the end brings older databases up to these tables.
--
-- Tables
--   polygon_sets     one row per GeoJSON file (the reference set is pinned)
--   labels           the polygons, each in one set, with its location cluster
--   cluster_models   k-means models of polygon locations (one is active)
--   clusters         the named clusters of each model
--   extraction_runs  one Earth Engine extraction of one polygon set
--   polygon_results  per-polygon numbers of a run
--   dashboards       chart specs saved from the assistant
--   assistant_log    every assistant question, tool call and answer
-- Views
--   v_latest_run     latest successful run per polygon set
--   v_polygon        polygons + latest results + derived shares and categories
--   v_set_summary    one row per polygon set, for the start page
--   v_stats, q_*     the insight query library (Insights page)

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------- polygon sets ----------
-- Uploaded sets are a cache: once there are more than CACHE_MAX_SETS of them
-- the least recently used one is deleted (app/pipeline/polygon_sets.py).
-- The checksum lets us recognise a file that was uploaded before.
CREATE TABLE IF NOT EXISTS polygon_sets (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    source_filename  TEXT,
    checksum         TEXT UNIQUE,               -- sha256 of the file
    pinned           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- location clusters ----------
CREATE TABLE IF NOT EXISTS cluster_models (
    id            SERIAL PRIMARY KEY,
    k             INT NOT NULL,
    fitted_on     TEXT NOT NULL,                 -- name of the set it was fitted on
    n_train       INT NOT NULL,
    silhouette    DOUBLE PRECISION,
    max_dist_km   DOUBLE PRECISION NOT NULL,     -- farther than this from every centre: unassigned
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    fitted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clusters (
    model_id      INT NOT NULL REFERENCES cluster_models(id) ON DELETE CASCADE,
    cluster_id    INT NOT NULL,
    name          TEXT NOT NULL,
    centroid_lon  DOUBLE PRECISION NOT NULL,
    centroid_lat  DOUBLE PRECISION NOT NULL,
    radius_km     DOUBLE PRECISION NOT NULL,     -- 90th percentile distance of its members
    n_train       INT NOT NULL,
    PRIMARY KEY (model_id, cluster_id)
);

-- ---------- polygons ----------
-- The source file has only year and Verified, so region comes from the
-- location (two well-separated clusters in the reference data) and the area is
-- computed geodesically on import.
CREATE TABLE IF NOT EXISTS labels (
    id                SERIAL PRIMARY KEY,
    set_id            INT NOT NULL REFERENCES polygon_sets(id) ON DELETE CASCADE,
    feature_index     INT,                       -- position in the source file
    source_year       INT,                       -- year of the clearing; uploads may not have one
    verified          TEXT NOT NULL DEFAULT 'Yes',
    region            TEXT NOT NULL CHECK (region IN ('uganda', 'brazil', 'other')),
    area_m2           DOUBLE PRECISION NOT NULL,
    centroid_lon      DOUBLE PRECISION NOT NULL,
    centroid_lat      DOUBLE PRECISION NOT NULL,
    cluster_model_id  INT,
    cluster_id        INT,                       -- NULL = outside every known cluster
    props             JSONB,                     -- the source feature's own properties, as they came
    geom              geometry(MultiPolygon, 4326) NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT labels_cluster_fk FOREIGN KEY (cluster_model_id, cluster_id)
        REFERENCES clusters(model_id, cluster_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_labels_set    ON labels(set_id);
CREATE INDEX IF NOT EXISTS idx_labels_region ON labels(region);
CREATE INDEX IF NOT EXISTS idx_labels_year   ON labels(source_year);
CREATE INDEX IF NOT EXISTS idx_labels_geom   ON labels USING GIST(geom);

-- ---------- extraction runs ----------
-- Why we store Earth Engine results at all:
--  * every chart needs all polygons of a set, and asking EE on each page view
--    is slow, uses quota and fails whenever EE is unreachable;
--  * the results are tiny (one row per polygon) and reproducible - each run
--    records the exact assets, scale and method, so it can be repeated and
--    compared when a dataset version changes.
-- The rasters themselves are not stored.
CREATE TABLE IF NOT EXISTS extraction_runs (
    id            SERIAL PRIMARY KEY,
    set_id        INT NOT NULL REFERENCES polygon_sets(id) ON DELETE CASCADE,
    gfc_asset     TEXT NOT NULL,
    forty_asset   TEXT NOT NULL,
    scale_m       DOUBLE PRECISION NOT NULL,
    method        TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    n_polygons    INT,
    note          TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ
);

-- ---------- per-polygon results ----------
-- Shares (0..1) of the polygon's area, from area-weighted 10 m pixels: a
-- pixel half inside the polygon counts as half. gfc_forest and the forty_*
-- columns are each map's composition; x_ff / x_fn / x_nf / x_nn are the
-- pixel cross-tab (GFC forest or not x ForTy tree class or other land).
CREATE TABLE IF NOT EXISTS polygon_results (
    run_id            INT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    label_id          INT NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    px_count          INT,                -- pixel centres inside the polygon
    px_area           DOUBLE PRECISION,   -- area-weighted pixel count
    gfc_forest        DOUBLE PRECISION,
    forty_primary     DOUBLE PRECISION,
    forty_natreg      DOUBLE PRECISION,
    forty_planted     DOUBLE PRECISION,
    forty_plantation  DOUBLE PRECISION,
    forty_treecrops   DOUBLE PRECISION,
    forty_other       DOUBLE PRECISION,
    forty_conf_mean   DOUBLE PRECISION,   -- mean winning-class score of ForTy
    x_ff              DOUBLE PRECISION,
    x_fn              DOUBLE PRECISION,
    x_nf              DOUBLE PRECISION,
    x_nn              DOUBLE PRECISION,
    joint_hist        JSONB,              -- raw {gfc*10 + forty_class: area}
    PRIMARY KEY (run_id, label_id),
    CONSTRAINT polygon_results_shares CHECK (
        greatest(gfc_forest, forty_primary, forty_natreg, forty_planted, forty_plantation, forty_treecrops,
                 forty_other, forty_conf_mean, x_ff, x_fn, x_nf, x_nn) <= 1.000001
        AND least(gfc_forest, forty_primary, forty_natreg, forty_planted, forty_plantation, forty_treecrops,
                  forty_other, forty_conf_mean, x_ff, x_fn, x_nf, x_nn) >= 0)
);

-- ---------- assistant ----------
-- Chart specs saved from the assistant. A spec names an insight query, filters
-- and a chart type - never code - so it redraws for whichever set is chosen.
CREATE TABLE IF NOT EXISTS dashboards (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    spec        JSONB NOT NULL,
    question    TEXT,                    -- what the user asked for, if it came from the assistant
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every question, the tools the model called and its answer, for review.
CREATE TABLE IF NOT EXISTS assistant_log (
    id          SERIAL PRIMARY KEY,
    set_id      INT REFERENCES polygon_sets(id) ON DELETE SET NULL,
    question    TEXT NOT NULL,
    tool_calls  JSONB NOT NULL DEFAULT '[]',
    answer      TEXT,
    flags       JSONB NOT NULL DEFAULT '[]',   -- numbers not found in tool results, errors
    model       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- upgrade older databases ----------
-- CREATE TABLE IF NOT EXISTS leaves an existing table as it was, so what was
-- added to the tables later is applied here. Each statement does nothing once
-- it has run.
ALTER TABLE labels ADD COLUMN IF NOT EXISTS props JSONB;
ALTER TABLE labels ALTER COLUMN set_id SET NOT NULL;
ALTER TABLE extraction_runs ALTER COLUMN set_id SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'labels_region_check') THEN
        ALTER TABLE labels ADD CONSTRAINT labels_region_check CHECK (region IN ('uganda', 'brazil', 'other'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'labels_cluster_fk') THEN
        ALTER TABLE labels ADD CONSTRAINT labels_cluster_fk FOREIGN KEY (cluster_model_id, cluster_id)
            REFERENCES clusters(model_id, cluster_id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extraction_runs_status_check') THEN
        ALTER TABLE extraction_runs ADD CONSTRAINT extraction_runs_status_check
            CHECK (status IN ('running', 'ok', 'failed'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'polygon_results_shares') THEN
        ALTER TABLE polygon_results ADD CONSTRAINT polygon_results_shares CHECK (
            greatest(gfc_forest, forty_primary, forty_natreg, forty_planted, forty_plantation, forty_treecrops,
                     forty_other, forty_conf_mean, x_ff, x_fn, x_nf, x_nn) <= 1.000001
            AND least(gfc_forest, forty_primary, forty_natreg, forty_planted, forty_plantation, forty_treecrops,
                      forty_other, forty_conf_mean, x_ff, x_fn, x_nf, x_nn) >= 0);
    END IF;
END $$;

-- ---------- views ----------
-- Dropped and recreated on every start so a changed view always applies.
-- CASCADE also takes the q_* insight views, which are recreated below.
DROP VIEW IF EXISTS v_set_summary;
DROP VIEW IF EXISTS v_polygon CASCADE;
DROP VIEW IF EXISTS v_latest_run CASCADE;

CREATE VIEW v_latest_run AS
SELECT DISTINCT ON (set_id) *
FROM extraction_runs
WHERE status = 'ok'
ORDER BY set_id, finished_at DESC;

CREATE VIEW v_polygon AS
SELECT
    l.id, l.set_id, l.feature_index, l.region, l.source_year, l.verified,
    l.area_m2, l.centroid_lon, l.centroid_lat,
    l.cluster_id,
    COALESCE(c.name, 'Outside known clusters')              AS cluster_name,
    l.area_m2 / 100.0                                       AS approx_pixels,
    CASE WHEN l.area_m2 < 100   THEN '1: <1 px'
         WHEN l.area_m2 < 1000  THEN '2: 1-10 px'
         WHEN l.area_m2 < 5000  THEN '3: 10-50 px'
         ELSE                        '4: 50+ px' END        AS size_class,
    r.run_id, r.px_count, r.px_area,
    r.gfc_forest,
    1 - r.forty_other                                       AS forty_tree,
    r.forty_primary + r.forty_natreg + r.forty_planted
        + r.forty_plantation                                AS forty_forest_eudr,
    r.forty_primary + r.forty_natreg                        AS forty_natural,
    r.forty_primary, r.forty_natreg, r.forty_planted,
    r.forty_plantation, r.forty_treecrops, r.forty_other,
    r.forty_conf_mean,
    r.x_ff, r.x_fn, r.x_nf, r.x_nn,
    r.x_ff + r.x_nn                                         AS pixel_agreement,
    CASE
        WHEN r.gfc_forest IS NULL THEN NULL
        WHEN r.gfc_forest >= 0.5 AND (1 - r.forty_other) >= 0.5 THEN 'Both forest'
        WHEN r.gfc_forest <  0.5 AND (1 - r.forty_other) >= 0.5 THEN 'ForTy only'
        WHEN r.gfc_forest >= 0.5 AND (1 - r.forty_other) <  0.5 THEN 'GFC only'
        ELSE 'Neither'
    END                                                     AS category,
    CASE GREATEST(r.forty_primary, r.forty_natreg, r.forty_planted,
                  r.forty_plantation, r.forty_treecrops, r.forty_other)
        WHEN r.forty_primary    THEN 'Primary forest'
        WHEN r.forty_natreg     THEN 'Naturally regenerating'
        WHEN r.forty_planted    THEN 'Planted forest'
        WHEN r.forty_plantation THEN 'Plantation forest'
        WHEN r.forty_treecrops  THEN 'Tree crops / agroforestry'
        WHEN r.forty_other      THEN 'Other land'
    END                                                     AS forty_dominant,
    r.joint_hist,
    ST_AsGeoJSON(l.geom, 6)::json                           AS geometry
FROM labels l
LEFT JOIN v_latest_run lr ON lr.set_id = l.set_id
LEFT JOIN polygon_results r ON r.run_id = lr.id AND r.label_id = l.id
LEFT JOIN clusters c ON c.model_id = l.cluster_model_id AND c.cluster_id = l.cluster_id;

CREATE VIEW v_set_summary AS
SELECT
    s.id, s.name, s.source_filename, s.pinned, s.created_at, s.last_used_at,
    COUNT(l.id)                                          AS n_polygons,
    COUNT(l.id) FILTER (WHERE l.area_m2 < 100)           AS n_subpixel,
    MIN(l.source_year)                                   AS year_min,
    MAX(l.source_year)                                   AS year_max,
    lr.id                                                AS run_id,
    lr.finished_at                                       AS extracted_at,
    lr.note                                              AS run_note
FROM polygon_sets s
LEFT JOIN labels l      ON l.set_id = s.id
LEFT JOIN v_latest_run lr ON lr.set_id = s.id
GROUP BY s.id, lr.id, lr.finished_at, lr.note;

-- ---------- insight query library ----------
-- Each q_* view answers one question for every polygon set (filter by
-- set_id). They are read-only and used by the Insights page, the shareable
-- dashboard and (later) the assistant, so every number has a named source.
-- Statistics use polygons with results that cover at least one 10 m pixel
-- (v_stats); q_size_sensitivity deliberately uses all of them.

CREATE VIEW v_stats AS
SELECT * FROM v_polygon WHERE gfc_forest IS NOT NULL AND area_m2 >= 100;

-- 1. How much forest / tree cover does each dataset see, per cluster?
CREATE VIEW q_headline AS
SELECT set_id,
       COALESCE(cluster_name, 'All clusters')        AS cluster,
       COUNT(*)                                      AS polygons,
       AVG(gfc_forest)                               AS gfc_forest,
       AVG(forty_tree)                               AS forty_trees,
       AVG(forty_forest_eudr)                        AS forty_forest_1_4,
       AVG(forty_natural)                            AS forty_natural,
       AVG(pixel_agreement)                          AS pixel_agreement
FROM v_stats
GROUP BY GROUPING SETS ((set_id, cluster_name), (set_id));

-- 2. Where GFC2020 says non-forest, what does ForTy say?
--    joint_hist keys 1..6 = GFC non-forest x ForTy class (area in pixels).
CREATE VIEW q_disagreement_reasons AS
WITH h AS (
    SELECT set_id, cluster_name,
           COALESCE((joint_hist->>'1')::float, 0) + COALESCE((joint_hist->>'2')::float, 0) AS natural_forest,
           COALESCE((joint_hist->>'3')::float, 0) + COALESCE((joint_hist->>'4')::float, 0) AS planted_plantation,
           COALESCE((joint_hist->>'5')::float, 0)                                       AS tree_crops,
           COALESCE((joint_hist->>'6')::float, 0)                                       AS other_land
    FROM v_stats
)
SELECT set_id, COALESCE(cluster_name, 'All clusters') AS cluster,
       SUM(natural_forest + planted_plantation + tree_crops + other_land) AS gfc_nonforest_pixels,
       SUM(natural_forest)     / NULLIF(SUM(natural_forest + planted_plantation + tree_crops + other_land), 0) AS natural_forest,
       SUM(planted_plantation) / NULLIF(SUM(natural_forest + planted_plantation + tree_crops + other_land), 0) AS planted_plantation,
       SUM(tree_crops)         / NULLIF(SUM(natural_forest + planted_plantation + tree_crops + other_land), 0) AS tree_crops,
       SUM(other_land)         / NULLIF(SUM(natural_forest + planted_plantation + tree_crops + other_land), 0) AS other_land
FROM h
GROUP BY GROUPING SETS ((set_id, cluster_name), (set_id));

-- 3. Which ForTy forest types were cleared, per cluster?
CREATE VIEW q_class_mix AS
SELECT set_id, cluster_name AS cluster, COUNT(*) AS polygons,
       AVG(forty_primary) AS primary_forest, AVG(forty_natreg) AS naturally_regenerating,
       AVG(forty_planted) AS planted_forest, AVG(forty_plantation) AS plantation_forest,
       AVG(forty_treecrops) AS tree_crops, AVG(forty_other) AS other_land
FROM v_stats
GROUP BY set_id, cluster_name;

-- 4. Which ForTy forest types were cleared each year, in hectares?
--     Class share of each polygon x its area; one row per year and cluster,
--     plus All clusters. Polygons without a year are left out.
CREATE VIEW q_loss_by_type_year AS
SELECT set_id, COALESCE(cluster_name, 'All clusters') AS cluster, source_year AS year,
       COUNT(*)                                  AS polygons,
       SUM(area_m2) / 10000.0                    AS area_ha,
       SUM(area_m2 * forty_primary) / 10000.0    AS primary_forest_ha,
       SUM(area_m2 * forty_natreg) / 10000.0     AS naturally_regenerating_ha,
       SUM(area_m2 * forty_planted) / 10000.0    AS planted_forest_ha,
       SUM(area_m2 * forty_plantation) / 10000.0 AS plantation_forest_ha,
       SUM(area_m2 * forty_treecrops) / 10000.0  AS tree_crops_ha,
       SUM(area_m2 * forty_other) / 10000.0      AS other_land_ha
FROM v_stats
WHERE source_year IS NOT NULL
GROUP BY GROUPING SETS ((set_id, cluster_name, source_year), (set_id, source_year));

-- 5. How many polygons do both, one, or neither dataset call forest (>= 50% of area)?
CREATE VIEW q_agreement_categories AS
SELECT set_id, cluster_name AS cluster, category, COUNT(*) AS polygons
FROM v_stats
GROUP BY set_id, cluster_name, category;

-- 6. Do the conclusions change when small polygons are dropped?
CREATE VIEW q_size_sensitivity AS
SELECT p.set_id, t.min_area_m2, COUNT(*) AS polygons,
       AVG(p.gfc_forest) AS gfc_forest, AVG(p.forty_tree) AS forty_trees, AVG(p.pixel_agreement) AS pixel_agreement
FROM v_polygon p
CROSS JOIN (VALUES (0), (50), (100), (500), (1000), (5000)) AS t(min_area_m2)
WHERE p.gfc_forest IS NOT NULL AND p.area_m2 >= t.min_area_m2
GROUP BY p.set_id, t.min_area_m2;

-- 7. Is ForTy less sure where the two datasets disagree?
CREATE VIEW q_confidence_vs_agreement AS
SELECT set_id, category, COUNT(*) AS polygons,
       AVG(forty_conf_mean) AS mean_confidence,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY forty_conf_mean) AS median_confidence
FROM v_stats
GROUP BY set_id, category;

-- 8. Does what the datasets see depend on the year of clearing?
CREATE VIEW q_year_trend AS
SELECT set_id, cluster_name AS cluster, source_year AS year, COUNT(*) AS polygons,
       AVG(gfc_forest) AS gfc_forest, AVG(forty_tree) AS forty_trees
FROM v_stats
WHERE source_year IS NOT NULL
GROUP BY set_id, cluster_name, source_year;

-- 9. Polygons where ForTy sees mostly no trees: plausible ForTy misses.
CREATE VIEW q_trees_missed AS
SELECT set_id, id AS polygon_id, cluster_name AS cluster, source_year AS year, area_m2,
       forty_other AS forty_other_land, gfc_forest, centroid_lat, centroid_lon
FROM v_stats
WHERE forty_other >= 0.5;

-- 10. Polygons where neither dataset sees forest: check the label or its timing.
CREATE VIEW q_label_check AS
SELECT set_id, id AS polygon_id, cluster_name AS cluster, source_year AS year, area_m2,
       gfc_forest, forty_tree AS forty_trees, forty_dominant, centroid_lat, centroid_lon
FROM v_stats
WHERE category = 'Neither';

-- 11. One profile per location cluster.
CREATE VIEW q_cluster_profile AS
SELECT set_id, cluster_name AS cluster, COUNT(*) AS polygons,
       SUM(area_m2) / 10000.0                                AS area_ha,
       MIN(source_year) AS first_year, MAX(source_year) AS last_year,
       AVG(gfc_forest) AS gfc_forest, AVG(forty_tree) AS forty_trees,
       AVG(pixel_agreement) AS pixel_agreement,
       MODE() WITHIN GROUP (ORDER BY forty_dominant)        AS main_forty_class,
       AVG((category = 'ForTy only')::int)                  AS share_forty_only
FROM v_stats
GROUP BY set_id, cluster_name;


-- ---------- read-only role ----------
-- gras_reader can read the views and nothing else. The assistant switches to
-- it (SET ROLE) before running a tool, so even a bug in a tool cannot write,
-- or read tables and settings behind the views. It cannot log in by itself.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gras_reader') THEN
        CREATE ROLE gras_reader NOLOGIN;
    END IF;
END $$;
GRANT gras_reader TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO gras_reader;
DO $$
DECLARE v record;
BEGIN
    -- The views are recreated on every start, so their grants are too.
    FOR v IN SELECT viewname FROM pg_views
             WHERE schemaname = 'public' AND (viewname LIKE 'v\_%' OR viewname LIKE 'q\_%') LOOP
        EXECUTE format('GRANT SELECT ON %I TO gras_reader', v.viewname);
    END LOOP;
END $$;
