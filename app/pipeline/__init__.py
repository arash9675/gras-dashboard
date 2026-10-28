"""Pipeline: getting polygons and Earth Engine results into the database.

  earth_engine  - dataset definitions and the per-polygon extraction
  extraction    - one extraction run of a polygon set, stored with its recipe
  polygon_sets  - GeoJSON upload, validation, dedupe and the LRU cache
  clusters      - k-means location clusters and classification of new polygons
  startup       - what the container does on boot (reference set, clusters)
"""
