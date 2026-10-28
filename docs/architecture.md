# Architecture

How the dashboard is put together: the moving parts, what each module does, and
how data flows from a GeoJSON file to a chart. Design reasons are in
[design-decisions.md](design-decisions.md); the results are in [analysis.md](analysis.md).

## The pieces

```
 docker compose
 +-------------------------------+        +----------------------------------------+
 | db: PostGIS 16                |  SQL   | app: Python 3.11 + Streamlit           |
 |   tables  polygon_sets,       |<------>|   core       config, db, palette       |
 |           labels, clusters,   |        |   pipeline   Earth Engine, uploads,    |
 |           extraction_runs,    |        |              clusters, start-up        |
 |           polygon_results,    |        |   analytics  metrics, insight queries  |
 |           dashboards,         |        |   assistant  Gemini tools, chart specs |
 |           assistant_log       |        |   ui         theme, state, map         |
 |   views   v_polygon, q_* ...  |        |   views      the eleven pages          |
 |   role    gras_reader         |        |                                        |
 +-------------------------------+        +---------+--------------------+---------+
                                                    | earthengine-api    | google-genai
                                          Google Earth Engine      Gemini API
                                          (GFC2020, ForTy)         (Assistant only)
```

Two containers. PostGIS holds the polygons and every number the app shows; the
app reads and writes it with plain SQL. Earth Engine is only called to compute
new results (start-up, uploads, recalculation) - page views never wait on it.
The map tiles come from OpenStreetMap or Esri imagery directly in the browser.

## Code layout

```
app/
  main.py                 page setup, Earth Engine connection, navigation
  entrypoint.sh           container start-up (schema, reference set, extraction, Streamlit)
  core/
    config.py             settings from environment variables, EE credentials
    db.py                 every database read and write (fixed SQL, bound parameters)
    palette.py            the colours, defined once
  pipeline/
    earth_engine.py       dataset definitions, image recipes, per-polygon extraction
    extraction.py         one extraction run of a polygon set, stored with its recipe
    polygon_sets.py       GeoJSON validation, storage, dedupe, least-recently-used cache
    clusters.py           k-means location clusters, classification of new polygons
    startup.py            first-boot work: reference set and cluster model
  analytics/
    metrics.py            pandas functions behind the analysis pages
    insights.py           the Insights query library (names, answers, charts)
  assistant/
    tools.py              the six tools Gemini may call (read-only, set-scoped, recorded)
    specs.py              chart specs: schema, validation, drawing
    agent.py              the question loop and the number check
    prompts.py            the system prompt and suggested questions
  ui/
    theme.py              Material 3 stylesheet and drawing helpers (card, kpi, legend ...)
    state.py              chosen polygon set and datasets, cached data, filters
    mapview.py            Python side of the map component
    components/maplibre/  the map itself (MapLibre GL + OpenStreetMap), one HTML file
  views/                  one script per page (start, map, insights, assistant, dashboards,
                          overview, compare, polygons, findings, about)
db/init.sql               the whole schema: tables, views, insight queries, read-only role
data/                     the reference GeoJSON and its saved Earth Engine results
tests/                    unit tests; database tests for a throwaway PostGIS
ops/backup.sh             nightly pg_dump, 14 days kept
.github/workflows/ci.yml  lint, tests, image build
```

The packages depend in one direction only:

```
views ──► ui ──────────► analytics ──► pipeline ──► core
  └────► assistant ───────┘          (views may use any layer)
```

`core` knows nothing about Earth Engine or Streamlit; `pipeline` and `analytics`
know nothing about Streamlit, so they run from the command line and in tests;
only `ui` and `views` import Streamlit. `assistant` imports Gemini lazily, so the app runs
without a key.

## Module reference

| Module | Responsibility | Main entry points |
|---|---|---|
| `core/config.py` | Read settings once from the environment | `settings`, `load_ee_credentials()` |
| `core/db.py` | All SQL. Reads go through views so the app and the database agree on every derived number | `polygons()`, `polygon_sets()`, `latest_run()`, `start_run()` / `finish_run()`, `insert_results()`, `active_cluster_model()` |
| `core/palette.py` | One colour per meaning (GFC green, ForTy orange, outcome colours) | constants |
| `pipeline/earth_engine.py` | What the two datasets are and how a pixel is read: GFC unmasked to 0/1, ForTy argmax over six scores. One batched request turns many polygons into area shares | `GFC`, `FORTY`, `extract()`, `summarise()` |
| `pipeline/extraction.py` | Run `extract()` for a whole set in chunks of 400 and store it as a run with its assets, scale and method | `run_extraction()`; CLI `python -m pipeline.extraction` |
| `pipeline/polygon_sets.py` | Turn a GeoJSON file into a polygon set: validate, measure, store; recognise a repeated file; delete the least recently used uploads | `add_upload()`, `create_set()`, `evict_lru()` |
| `pipeline/clusters.py` | Fit k-means on the reference set's centroids (k by silhouette) and assign every polygon to the nearest centre, or none if far away | `fit()`, `classify()` |
| `pipeline/startup.py` | First boot: import the reference set, fit clusters. Safe to rerun | `main()`; CLI `python -m pipeline.startup [--refit --k N]` |
| `analytics/metrics.py` | Pandas functions over the polygon table: intervals, cross-tab, size effects, flags, headline numbers | `metric_table()`, `agreement_matrix()`, `sensitivity()`, `headline()` ... |
| `analytics/insights.py` | The eleven named insight queries: run a `q_*` view for one set, write its one-line answer, draw its chart | `INSIGHTS`, `run()`, `definition()` |
| `ui/theme.py` | Material styling and small HTML helpers | `inject_css()`, `card()`, `kpi()`, `callout()`, `legend()`, `pct()` |
| `ui/state.py` | What the user has chosen, and data loading with caching; the checkbox filters | `current_set_id()`, `current_datasets()`, `polygons()`, `filter_bar()`, `page_header()` |
| `ui/mapview.py` + `components/maplibre` | The map: polygons and centroid dots, fit-to-filter, click to select, optional Earth Engine dataset layer (tile URLs cached under an hour) | `map_view()`, `dataset_layer()` |
| `assistant/tools.py` | The six tools Gemini may call. Each runs for the chosen set, checks its arguments and reads through the read-only role; each call is recorded for the trace | `DECLARATIONS`, `call()` |
| `assistant/specs.py` | Chart specs: schema, validation against the query's columns, Plotly drawing | `validate()`, `data()`, `render()` |
| `assistant/agent.py` | The question loop (at most 6 rounds of tool calls), the number check, logging to `assistant_log` | `ask()`, `unmatched_numbers()` |
| `assistant/prompts.py` | The system prompt with the evidence rules, suggested questions | `SYSTEM`, `SUGGESTED` |

## How data flows

**Container start** (`entrypoint.sh`)

1. Wait for Postgres, then run `db/init.sql`. It is idempotent, so this also
   updates views on an existing database.
2. `pipeline.startup`: if there is no pinned set, import `data/*.geojson` as the
   reference set; if there is no cluster model, fit one on it; if the reference set has
   no results, load the saved ones from `data/reference_results.json`.
3. `pipeline.extraction`: compute results for every set that has none.
4. Start Streamlit.

**Upload** (Choose data page → `polygon_sets.add_upload`)

```
file ─► parse_geojson (validate, area, centroid, region)
     ─► checksum seen before? ─yes─► reuse that set
     ─► create_set ─► clusters.classify ─► extraction.run_extraction ─► evict_lru
```

**Extraction** (`earth_engine.extract`)

```
GFC2020 Map ─unmask(0)─► 0/1 ───────────┐
ForTy 5 scores + (250 - sum) ─argmax─► 1..6 ─► code = gfc*10 + class
                                              ─► area-weighted histogram per polygon (reduceRegions)
ForTy max score / 250 ─► mean per polygon ─────────────────────────────┘
histogram ─► summarise ─► shares of polygon area + 2x2 cross-tab ─► polygon_results
```

**Page view**

```
ui.state.polygons()  ─► v_polygon for the chosen set (cached until a new run)
ui.state.filter_bar  ─► rows the user ticked
analytics.metrics    ─► numbers and tables          ─► Plotly / MapLibre
analytics.insights   ─► q_* view for the chosen set ─► answer + chart + SQL
```

**Assistant question** (`assistant.agent.ask`)

```
question + chosen set ─► Gemini (sees tool descriptions only)
   ─► tool call ─► argument check ─► v_* / q_* as gras_reader ─► rows (recorded) ─► back to Gemini
   ─► answer ─► number check against the recorded rows ─► page: answer, chart, tools, SQL, rows
```

## Database

| Object | What it holds |
|---|---|
| `polygon_sets` | One row per GeoJSON file: name, checksum, pinned flag, last used |
| `labels` | Polygons: set, year, verified flag, region, geodesic area, centroid, cluster, source properties (`props`), geometry |
| `cluster_models`, `clusters` | K-means models (k, silhouette, distance limit) and their named centres |
| `extraction_runs` | One row per extraction of a set: assets, scale, method, status, timing |
| `polygon_results` | Per polygon and run: GFC forest share, six ForTy class shares, 2x2 cross-tab, mean ForTy confidence, raw histogram |
| `v_latest_run` | Latest successful run of each set |
| `v_polygon` | Polygons + their latest results + derived shares, size class, agreement category, cluster name |
| `v_set_summary` | One row per set (counts, years, cache status) for the start page |
| `v_stats` | `v_polygon` restricted to polygons with results covering at least one pixel |
| `q_*` (11 views) | The insight query library, one view per question |
| `dashboards` | Chart specs saved from the assistant |
| `assistant_log` | Every question, the tools called, the answer and its number-check flags |
| `gras_reader` (role) | Can read the `v_*` and `q_*` views only; the assistant's tools run as it |

Every derived number (ForTy forest 1-4, natural forest, agreement category,
size class) is defined once, in `v_polygon`, and the app reads it from there.

## Running it

| Setting | Where | Notes |
|---|---|---|
| `EE_PROJECT`, `secrets/ee-service-account.json` or `EE_CREDENTIALS_JSON` | `.env`, `secrets/` | Earth Engine service account (Resource Viewer + Service Usage Consumer) |
| `CACHE_MAX_SETS`, `UPLOAD_MAX_FEATURES`, `UPLOAD_MAX_MB` | environment | Upload cache size and limits (5, 2000, 10 by default) |
| `APP_PORT` | `.env` | Host port of the dashboard (8501) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | `.env` | Optional; enables the Assistant (default model `gemini-3.8-flash`) |

`docker compose up -d --build` builds the image (code, schema and reference data inside it) and
starts both containers; the app is
ready about 30 seconds after the database. The database volume keeps polygons,
clusters and results between restarts.

## Extending it

- **Another dataset:** add its definition and an image recipe in
  `pipeline/earth_engine.py`, add its band to the combined pixel code in
  `extract()`/`summarise()`, add result columns in `db/init.sql`, then add it to
  `ui.theme.DATASETS`.
- **Another insight:** add a `q_*` view to `db/init.sql` and one `Insight(...)`
  entry (answer and chart functions) to `analytics/insights.py`. The Insights
  page picks it up automatically.
- **Another page:** add a script to `views/` and one `st.Page(...)` line in `main.py`.
