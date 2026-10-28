# The dashboard image: dependencies, code, schema and the reference polygons.
# Built from the repository root (see docker-compose.yml), so the code lives in
# the image and a running container never changes when files on the host do.
# Every Python dependency ships as a prebuilt wheel, so we need no compilers or
# system libraries - only curl for the health check.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY db/ /db/
COPY data/ /data/
COPY app/ /app/
RUN chmod +x /app/entrypoint.sh

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
