# GRAS forest dataset comparison dashboard

Compares two global 2020 forest maps, **JRC GFC2020 v4** and **Forest Typology (ForTy) 2020 v1.0**,
inside 198 hand-drawn deforestation polygons (clearings after 2020 in Uganda and south-east Brazil).
The question: did each 2020 map show the trees that were later cleared, where do the maps disagree,
and what can each one safely be used for?

Stack: PostgreSQL 16 + PostGIS · Google Earth Engine · Streamlit with Google Material 3 styling ·
MapLibre GL + OpenStreetMap · Plotly · Docker Compose.

| Document | What is in it |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, code layout, every module, data flows, database objects |
| [docs/design-decisions.md](docs/design-decisions.md) | Each design choice with its reason and trade-off |
| [docs/analysis.md](docs/analysis.md) | Full findings with tables, by region, year, size and ForTy class |

## Quick start

```bash
cp .env.example .env              # set EE_PROJECT and POSTGRES_PASSWORD (GEMINI_API_KEY optional)
mkdir -p secrets
cp /path/to/key.json secrets/ee-service-account.json
docker compose up -d --build
# open http://localhost:8501
```

On first start the app creates the schema, imports the reference polygons, fits the location
clusters and runs the Earth Engine extraction (a few seconds). Without Earth Engine access the
dashboard still starts and shows the polygons.

### Earth Engine access

People using the dashboard do not need an Earth Engine account. Every request (start-up, uploads,
recalculation) runs on the dashboard's own service account. To set it up:

1. Use a Google Cloud project registered for Earth Engine, with the Earth Engine API enabled.
2. Create a service account and a JSON key.
3. Grant it **Earth Engine Resource Viewer** and **Service Usage Consumer**. That is enough to read
   public datasets and compute; nothing is written to Earth Engine.
4. Save the key as `secrets/ee-service-account.json` (or paste it into `EE_CREDENTIALS_JSON`) and set
   `EE_PROJECT` in `.env`.

`.env` and `secrets/` are git-ignored and kept out of the image.

### Assistant (optional)

The Ask Gemini page needs a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey):
set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`, default `gemini-3.8-flash`) in `.env`. Without a key
the page explains how to enable it and everything else works. Free-tier prompts may be used by Google to
improve its products, which is acceptable for these public polygons but not for private data.

When every Gemini model is busy, the question goes to Groq instead if `GROQ_API_KEY` is set (free key from
[console.groq.com](https://console.groq.com/keys); model `GROQ_MODEL`, default `openai/gpt-oss-120b`), with the same tools.

### Updating and backups

The code is built into the image, so a running dashboard only changes when you rebuild it:
`git pull && docker compose up -d --build`. `ops/backup.sh` writes a compressed database dump to
`backups/` and keeps 14 days; its header shows the cron line and the restore command.

### Tests

```bash
pip install -r app/requirements-dev.txt
ruff check app tests
pytest                                    # unit tests
TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/gras_test pytest   # plus database tests
```

The database tests wipe the database they are given, so they refuse one whose name lacks "test".
GitHub Actions runs lint, all tests against a throwaway PostGIS, and an image build on every push.

## Pages

| Page | What it is for |
|---|---|
| **Choose data** (start) | Pick a polygon set or upload a GeoJSON; see whether results exist; recalculate |
| **Map** | Open-source map. One card holds the dataset, cluster, year and size checkboxes; the map zooms to the matching polygons. Colour polygons by GFC2020 forest share, ForTy type or agreement; optionally show a dataset itself (GFC2020 forest, ForTy class, or where they differ) as 10 m Earth Engine tiles. Click a polygon for its breakdown |
| Insights | Eleven named SQL queries, each with its answer, chart, SQL and rows |
| Ask Gemini | Questions in plain language, answered by Google Gemini from the insight queries and metrics only; every answer shows the tools, filters, SQL and rows behind it, and checks its numbers against them |
| My dashboards | Charts saved from Ask Gemini, redrawn for the selected polygon set |
| Overview | Headline numbers per region with 95% bootstrap intervals; ForTy class mix |
| Compare datasets | Pixel cross-tab, per-polygon scatter, size effects, confidence, year of clearing |
| Polygon table | Every number per polygon; sort, download CSV, open on the map |
| Findings | Findings and recommendations, recomputed for the chosen set, with how far each result goes (description, plausibility, validation, fitness for purpose) |
| Datasets & method | Definitions, class handling and how each number is computed |

Uploads: a GeoJSON FeatureCollection of polygons in WGS84, up to 2,000 features and 10 MB. A `year`
property is used when present. The same file uploaded twice reuses the cached set; at most five uploads
are kept and the least recently used one is dropped.

## How it works

```
GeoJSON ─► pipeline.polygon_sets ─► PostGIS (polygon_sets, labels)
                │                         ▲
                ├─► pipeline.clusters ────┤ cluster_models, clusters   (k-means, k by silhouette)
                └─► pipeline.extraction ──┤ extraction_runs, polygon_results
                        │                 │
                Earth Engine              └─► views v_polygon, v_set_summary, q_* insight queries
              (GFC2020, ForTy)                      │
                                    analytics (metrics, insights) ─► ui + views (Streamlit, MapLibre)
```

- **GFC2020** is unmasked to 0 so non-forest is counted. **ForTy**'s class is the argmax of its five
  scores plus "other land" (250 − sum); the winning score / 250 is its confidence.
- Each pixel gets one code, `gfc × 10 + forty_class`; one area-weighted histogram per polygon at 10 m
  gives both maps and their cross-tab in a single Earth Engine call per 400 polygons.
- Results are stored per run with their assets, scale and method; pages read only the database.
- Polygons smaller than one 10 m pixel (26 of 198) are left out of statistics by default, since
  their value comes mostly from land outside the clearing. They stay on the map and in the table.
- K-means on polygon centroids (in 3-D Earth coordinates) gives three location clusters: Uganda,
  Brazil west and Brazil east.

Code layout:

```
app/
  main.py, entrypoint.sh
  core/        settings, all SQL, colours
  pipeline/    Earth Engine, extraction runs, uploads and cache, k-means, start-up
  analytics/   metrics for the analysis pages, the insight query library
  assistant/   Gemini tools over the insight queries, chart specs, the question loop
  ui/          Material theme, page state and filters, map component
  views/       one script per page
db/init.sql    the whole schema (tables, views, insight queries, read-only role), safe to rerun
data/          reference GeoJSON
docs/          architecture, design decisions, analysis
tests/         unit tests, and database tests for a throwaway PostGIS
ops/backup.sh  nightly database dump
.github/       CI: lint, tests, image build
```

Details for each module are in [docs/architecture.md](docs/architecture.md).

## Main findings

On the 172 polygons of at least one pixel (reference set). Full tables in [docs/analysis.md](docs/analysis.md).

1. **ForTy captures far more of the cleared tree cover.** It puts 90% of the cleared area in a tree
   class (80% in its forest classes 1-4); GFC2020 maps 38% as forest. In Uganda GFC2020 sees 19%.
2. **The gap is mostly about natural forest.** Where GFC2020 says non-forest, ForTy calls 68% of it
   natural forest, 16% tree crops or plantation and 16% other land.
3. **The relationship is one-way.** In only 2 polygons does GFC2020 see forest where ForTy does not;
   99 are forest in ForTy only.
4. **ForTy is confident where they disagree** (median 0.97), so the gap is not ForTy guessing.
5. **What was cleared:** 70.8 ha in total, 57% naturally regenerating forest and 24% plantation (mostly
   western Brazil). None of it is primary forest according to ForTy.
6. **Region drives most apparent trends.** GFC2020 looks better on large polygons and on earlier years,
   but both mostly reflect more Brazilian polygons in those groups.

For EUDR-style checks with ForTy, use classes 1-4 rather than all tree classes.

What these polygons cannot show: how often either map calls forest where there is none (there are no
treeless reference points), and whether agreement is correct, since both maps use overlapping imagery.
A stratified sample of reference points, including non-forest, per cluster would answer both.

## Limitations

- Region comes from location; the source file has no country field.
- One polygon is dated 2026, outside the 2021-2024 range of the rest.
- Both maps are sampled on a 10 m grid in EPSG:4326; ForTy's native grid is UTM.
- The ForTy score is a model output, not a calibrated probability.
- The 50% threshold for polygon categories is a presentation choice; all shares are stored unrounded.
- The assistant explains results but can still word things loosely; its number check flags figures not
  found in the tool results, and every answer shows its rows, but it is a guide, not a source.
- Served over plain HTTP; put it behind HTTPS (for example a Cloudflare Tunnel or Caddy) before wider use.

## Open questions and next steps

Questions we could not settle from the data:

- **The 2026 polygon.** One polygon is dated 2026 while the rest are 2021-2024. A typo, or a newer label?
- **How the polygons were drawn.** Which imagery, which minimum size, and whether "Verified" means
  field-checked or checked on imagery. 26 polygons are smaller than one 10 m pixel.
- **Which forest definition the product needs.** Tree cover, EUDR forest (ForTy 1-4) or natural forest
  (ForTy 1-2) lead to different answers; the choice comes before the choice of dataset.
- **No treeless reference points.** The polygons only show where trees were. Measuring how often a map
  calls forest where there is none needs reference points in stable non-forest.

Trade-offs we made are listed with their reasons in [docs/design-decisions.md](docs/design-decisions.md).

Next steps:

1. A stratified sample of reference points per cluster, inside the disagreement zone and in stable forest
   and non-forest, labelled on high-resolution imagery. This turns the comparison into a validation.
2. The same comparison on a second region with known forest loss, to see whether the Uganda pattern repeats.
3. A check against the dataset publishers' own accuracy reports for these regions.

## Data sources

- JRC GFC2020 v4: <https://developers.google.com/earth-engine/datasets/catalog/JRC_GFC2020_V4>
- ForTy 2020 v1.0: <https://developers.google.com/earth-engine/datasets/catalog/projects_nature-trace_assets_forest_typology_forest_typology_2020_v1_0_collection>
