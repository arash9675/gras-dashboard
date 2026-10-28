"""Colours, defined once for the app pages and the insight charts.

Google Material colours, with one fixed colour per meaning: GFC2020 is always
green, ForTy always orange, and the four agreement outcomes keep their colour
on every page. The ForTy class colours live with the dataset definition in
pipeline/earth_engine.py, because they come from the ForTy catalog.
"""

GFC_COLOR = "#188038"     # Google green
FORTY_COLOR = "#E37400"   # Google orange

CATEGORY_COLORS = {
    "Both forest": "#188038",
    "ForTy only": "#F9AB00",
    "GFC only": "#1A73E8",
    "Neither": "#9AA0A6",
}

# Shades of orange for the three ways we read ForTy, from broadest to narrowest.
METRIC_COLORS = {
    "GFC2020: forest": GFC_COLOR,
    "ForTy: any tree class (1-5)": "#FDD663",
    "ForTy: forest classes (1-4)": "#F29900",
    "ForTy: natural forest (1-2)": "#B06000",
}

REGION_COLORS = {"Uganda": "#9334E6", "Brazil": "#12B5CB", "Other": "#5F6368"}
