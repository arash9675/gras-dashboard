#!/bin/sh
# Container start-up. Every step is safe to repeat, so a restart never breaks
# anything: wait for Postgres, apply the schema, import the reference polygons
# and fit clusters (first boot only), extract Earth Engine results for any set
# that has none, then start the dashboard.
set -e
cd /app

echo "[entrypoint] waiting for Postgres..."
until python -c "from core import db; db.query('SELECT 1')" 2>/dev/null; do sleep 1; done

echo "[entrypoint] applying schema"
python -c "from core import db; db.apply_schema()"

echo "[entrypoint] reference polygons and clusters"
python -m pipeline.startup

echo "[entrypoint] extracting Earth Engine results for sets without them"
python -m pipeline.extraction || echo "[entrypoint] extraction skipped"

echo "[entrypoint] starting Streamlit"
exec streamlit run main.py --server.port=8501 --server.address=0.0.0.0 --browser.gatherUsageStats=false
