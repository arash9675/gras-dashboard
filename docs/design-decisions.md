# Design decisions

Every choice that shapes the dashboard, why we made it, and what we gave up.
Grouped by area; each entry is *decision - why - trade-off*.

## Reading the datasets

### 1. Unmask GFC2020 to 0 before counting
GFC2020 v4 has one class (1 = forest) and leaves everything else masked. Earth
Engine reducers skip masked pixels, so without `unmask(0)` every polygon is
either 100% forest or has no pixels at all - which is exactly what the first
prototype showed (all 111 polygons with pixels at 100%, 87 empty). Unmasking
makes "not forest" a real 0 that is counted.
*Trade-off:* ocean and no-data areas also become 0; irrelevant for land polygons.

### 2. ForTy class = argmax of six scores, with "other land" derived
ForTy publishes five scores (0-250) and defines the sixth class as `250 - sum`.
We take the argmax of all six, as in the catalog's own example, so our classes
match ForTy's published maps. A fixed threshold (the prototype used 0.5 on a
0-250 scale) would have classified almost everything as forest.
*Trade-off:* argmax hides how close a call was, so we keep the winning score /
250 as a confidence and show it separately.

### 3. Three readings of ForTy
The EUDR forest definition excludes tree crops and agroforestry, and the
question "is this forest?" depends on which classes count. We report ForTy as
any tree class (1-5), forest classes (1-4, the EUDR-like reading) and natural
forest (1-2), next to GFC2020's single forest class.
*Trade-off:* three numbers instead of one; but collapsing them would hide the
main source of definitional disagreement.

### 4. One combined code per pixel
Each pixel gets `gfc * 10 + forty_class` (values 1-6 and 11-16). One
area-weighted histogram of that code per polygon gives both datasets'
composition *and* their pixel-level cross-tab, guaranteed on the same pixels.
*Trade-off:* adding a third dataset means extending the code scheme; fine for two.

### 5. Area-weighted 10 m pixels
A pixel that is half inside a polygon counts as half. With a median polygon of
about 12 pixels, edge pixels are a large share of every polygon, and
centre-in/centre-out counting would make small polygons jump between values.
*Trade-off:* both datasets are sampled on a 10 m grid in EPSG:4326 while ForTy's
native grid is UTM, so very small polygons can shift slightly.

### 6. Polygons smaller than one pixel are left out of statistics
26 of 198 polygons cover less than 100 m². Earth Engine still scores each by the
whole pixel it touches, so up to 98% of what is measured lies outside the
clearing and 24 of the 26 come out as exactly 0% or 100%. We exclude them from
statistics by default, keep them on the map and in the table (dashed), and show
how the headline numbers move with the cut-off.
*Trade-off:* fewer polygons (172), but the numbers no longer depend on noise.

### 7. A 50% threshold for polygon categories
"Both forest / ForTy only / GFC only / Neither" uses at least half of the
polygon's area. It is only for presentation; every number underneath stays a
continuous share.

## Storing results

### 8. Store per-polygon results, never rasters
Every chart needs all polygons of a set at once. Asking Earth Engine on each
page view would be slow, use quota and break whenever it is unreachable. The
results are small (one row per polygon per run) and fully reproducible.
*Trade-off:* results can go stale if a dataset changes - covered by the next point.

### 9. Extraction runs carry their recipe
Each run stores the asset IDs, scale and method string. A dataset update can be
re-run and compared run against run instead of silently replacing numbers;
failed runs are kept with their error.

### 10. Derived numbers live in SQL views
ForTy forest, natural forest, size class, agreement category and cluster name
are defined once in `v_polygon`. The app, the insight queries and anyone with a
SQL client get the same definition.
*Trade-off:* a change in a definition is a schema change - which is the point.

### 11. An idempotent schema instead of a migration tool
`db/init.sql` is safe to run on every start: tables use `IF NOT EXISTS`, views are
dropped and recreated. One file, no migration framework, and a changed view
reaches the running database on the next restart.
*Trade-off:* a change to an existing table needs a hand-written, repeatable
`ALTER` in the file's short upgrade section (used once so far, for the
constraints and the `props` column). With more table changes, numbered
migrations would be the better tool.

### 12. Batched extraction
All polygons of a set go to Earth Engine in `reduceRegions` calls of 400. The
whole reference set takes a few seconds (2.5 s in the latest run), against about 3 minutes with one
request per polygon in the first prototype.

## Polygon sets, uploads and clusters

### 13. A polygon set is the unit of caching
Each GeoJSON file becomes a set with its own polygons, clusters and runs. The
supplied file is the pinned reference set. A sha256 checksum recognises a file
that was uploaded before, and only the `CACHE_MAX_SETS` (5) most recently used
uploads are kept; choosing a set marks it as used.
*Trade-off:* an evicted upload has to be uploaded again - acceptable for a
demonstrator, and it keeps the database and Earth Engine quota bounded.

### 14. Uploads run on the dashboard's Earth Engine account
Viewers need no Earth Engine account. All requests use the service account,
which only needs *Earth Engine Resource Viewer* and *Service Usage Consumer*.
Uploads are limited to 2,000 polygons and 10 MB.
*Trade-off:* uploads use our quota; the limits and the cache cap it.

### 15. K-means location clusters
The two regions are known, but Brazil spans about 1,000 km and behaves
differently in the east and west. K-means on polygon centroids gives sub-regional
groups without hand-drawn boundaries:
- coordinates are converted to 3-D Earth-centred kilometres, so distances are
  real distances rather than degrees;
- k is chosen by silhouette between 3 and 8 (k = 2 only separates the two
  continents); the reference data gives k = 3 (silhouette 0.89): Uganda,
  Brazil west, Brazil east;
- the model is fitted once on the reference set and only *applied* to uploads,
  so a cluster name means the same thing in every set;
- a polygon farther than 3x the largest cluster radius (at least 100 km) from
  every centre is "Outside known clusters" instead of being forced into one.
*Trade-off:* new regions are not clustered among themselves until someone refits.

### 16. K-means in numpy, not scikit-learn
Two small functions (k-means++ with restarts, silhouette) for a few hundred
points. scikit-learn would add a large dependency for nothing we need.

### 17. Region from bounding boxes
The source file has no country field. The reference polygons form two clusters
far apart, so two bounding boxes name them; anything else is "other".
*Trade-off:* a country field in the source would be sturdier.

## Interface

### 18. Streamlit with a Material 3 skin
Streamlit keeps the whole app in Python, which suits a data team that has to
maintain it. On top of its default look we inject one Material 3 stylesheet
(Roboto, Google blue, cards, pill buttons, navigation drawer) and draw repeated
elements with small helpers, so pages never write CSS.
*Trade-off:* less control than a React front end, and every click reruns the page.

### 19. An open-source map as a small custom component
MapLibre GL with OpenStreetMap (Esri imagery as an option), in one HTML file
that talks to Streamlit through the component protocol - no build step. It fits
the shown polygons only when the filters change and otherwise leaves zoom and
pan alone; it sets itself up on style load so a tab opened in the background
still fits correctly.

### 20. Dataset layers only on request
The polygon colours come from stored results and load instantly, so they are
the default view. The datasets themselves (GFC2020 forest, ForTy class, and a
"where they differ" layer) are one switch away as Earth Engine tiles, off by
default and shown only from zoom 10: at continent scale a 10 m map is
resampled into misleading blocks. An earlier version showed them all the time
and was slower and harder to read; removing them entirely meant reviewers could
not see the datasets at all.
*Trade-off:* the tiles depend on Earth Engine being reachable; when it is not,
the switch says so and the map works without them.

### 21. One control per job
- Choose data: only the polygon set (pick or upload).
- Map: one card with datasets, clusters, years and sizes as checkboxes; one
  "Polygon colour" choice; one Map/Satellite switch.
- Analysis pages: the same filters in the sidebar.
Datasets are picked on the map because that is where the choice is visible.

### 22. Every number says what it is a share of
Pixel shares, shares of GFC2020's non-forest area and polygon counts are
different bases; mixing them unlabelled made numbers look inconsistent. Each
chart now names its base, and counts sit on count axes.

## Analysis and insight queries

### 23. Insights are named SQL views, not free-form queries
The Insights page runs only the eleven `q_*` views, always for one set, and
shows each answer with the SQL and rows behind it. Nothing builds SQL from user
input. The same views fed the shareable dashboard and are the natural tools for
a future assistant, which could call them by name and cite them.

### 24. Our own reading of the evidence
The polygons show where trees were removed after 2020. They can reveal tree
cover a map misses; they cannot show where a map invents forest, and two maps
built from overlapping imagery can share a mistake. The Findings page and
[analysis.md](analysis.md) are written from that position rather than reporting
any number as accuracy.

## Code and operations

### 25. Four small packages with one-way dependencies
`core` (settings, database), `pipeline` (Earth Engine, uploads, clusters,
start-up), `analytics` (metrics, insight queries), `ui` (theme, state, map).
Only `ui` and the pages import Streamlit, so the pipeline and analytics run from
the command line and can be tested without a browser.

### 26. A slim image that holds the code
Every Python dependency installs as a wheel, so the image needs no compilers or
system libraries (1.34 GB instead of 1.89 GB). The code, schema and reference
polygons are copied into the image rather than mounted from the host: a running
dashboard then changes only when it is rebuilt, never because a file on the
server changed (a mounted folder once took the live site down when it was
replaced). Only the Earth Engine key is mounted, and `.dockerignore` keeps
`.env` and `secrets/` out of the image.

### 27. Staging before live, secrets out of git
Changes are tried on a separate copy of the stack on the server (its own
database volume and a private port), then deployed by rebuilding the live
image. `.env` and `secrets/` are git-ignored. There is no admin page: recalculating a
set is on Choose data, the upload cache manages itself, and a cluster refit is
a command (`python -m pipeline.startup --refit [--k N]`), so the dashboard has
no password-protected controls that change shared data.

### 28. Constraints in the database, not only in the code
Shares must lie between 0 and 1, statuses and regions come from fixed lists,
every polygon belongs to a set and a cluster reference must exist. The code
already keeps to these rules; the constraints make a future bug fail loudly
instead of writing a wrong number. The app connects as the owner, but anything
that only reads on a user's behalf (the assistant's tools) switches to
`gras_reader`, which can read the views and nothing else.

### 29. Tests where a silent change would hurt
The tests cover the pixel maths (histogram to shares), clustering, upload
checks, the SQL views' derived columns, the constraints, the read-only role
and the assistant's tools. These are the places where a refactor could change
a published number without any page looking broken. CI runs them on every push
against a throwaway PostGIS; the database tests refuse any database whose name
lacks "test", because they wipe it.

## The assistant

### 30. The model chooses tools; the database computes
Gemini gets six tools (list the options, run a named insight, summarise with
filters, list polygons, show one polygon, propose a chart) and never SQL or
code. Each tool runs for the polygon set the user chose, checks its arguments
against the values that exist, and reads through the read-only role. This keeps
answers inside what the dashboard already computes and makes every answer
traceable: the page shows each tool call with its filters, SQL and rows.
*Trade-off:* questions outside the tools get "the data cannot answer that",
which is the intended behaviour.

### 31. A number check after every answer
Language models can still slip a number. After the answer is written, every
number in it is looked up among the rows the tools returned (allowing for
rounding and percentages); any that cannot be found is shown to the user above
the trace. It is a warning, not a filter, so a correct total the model added up
itself is flagged rather than hidden.

### 32. The evidence rules go in the system prompt
The prompt states what the polygons cannot show (accuracy, false forest, that
agreement proves anything) in the same words as the Findings page, so the
assistant and the dashboard draw the same line. A suggested question ("Which map
is more accurate?") exists to show that refusal.

### 33. Dashboards as specs, not pictures or code
When asked for a chart, the model returns a spec: an insight query, columns
from it, a chart type from a short list and optional cluster or year filters.
We validate it against the query's real columns and draw it with the app's
colours. A saved spec redraws for whichever polygon set is chosen, and nothing
the model writes is ever executed.

### 34. Gemini API key, not Vertex AI
The project's Google Cloud account has no billing, which Vertex AI requires, so
the assistant uses an AI Studio API key (free tier available), with the model
id in `.env`. Free-tier prompts may be used by Google to improve its products,
acceptable for these public polygons; private data would need a paid key or
Vertex AI with the existing service account.

### 35. Groq as the backup model
The Gemini free tier was often overloaded during testing. Groq serves open
models through an OpenAI-style API, free without a card and without training on
prompts. When every Gemini model is busy, the same question and tools go to
Groq. It is called with plain `httpx` (already installed with the Gemini SDK)
rather than another client library.
*Trade-off:* Groq's free tier allows few tokens per minute, so it suits a
fallback, not the main model; answers may differ in style between the two.

### 36. Ship one set of results with the repo
`data/reference_results.json` holds the results of one real extraction run for
the 198 reference polygons. On first start, if the reference set has no
results, they are loaded as an ordinary run (same assets and method, with a
note saying where it came from). A reviewer can then use every page without an
Earth Engine key; uploads and recalculation still need one.
*Trade-off:* 82 KB of data in the repo, and the shipped numbers reflect the
dataset versions of that run until someone recalculates.
