"""The assistant without the model: its tools, chart specs and number check."""
import pandas as pd

from assistant import agent, tools
from assistant.tools import Call
from conftest import needs_db


def test_every_declared_tool_exists_and_builds():
    from google.genai import types
    for d in tools.DECLARATIONS:
        assert d["name"] in tools.FUNCTIONS
        types.FunctionDeclaration(name=d["name"], description=d["description"], parameters_json_schema=d["parameters"])


def test_number_check_finds_made_up_numbers():
    rows = pd.DataFrame({"cluster": ["Uganda", "Brazil"], "gfc_forest": [0.1874, 0.5512], "polygons": [81, 91]})
    calls = [Call("summarise", {}, rows)]
    good = "GFC2020 maps 19% of Uganda and 55% of Brazil as forest, over 81 and 91 polygons (classes 1-5)."
    assert agent.unmatched_numbers(good, calls) == []
    bad = "GFC2020 maps 19% of Uganda but 72% of Brazil, in 2022."
    assert agent.unmatched_numbers(bad, calls) == ["72%"]
    assert agent.unmatched_numbers("There are 2 clusters.", calls) == []   # the row count


def test_unknown_tool_and_bad_arguments_are_reported_not_raised():
    result, call = tools.call("drop_tables", {}, 1)
    assert "error" in result and call.error
    result, call = tools.call("summarise", {"colour": "red"}, 1)
    assert "error" in result


@needs_db
def test_tools_answer_from_the_views(db, reference_set, results):
    opts, _ = tools.call("list_options", {}, reference_set)
    assert set(opts["clusters"]) == {"Uganda", "Brazil · west", "Brazil · east"}
    out, call = tools.call("summarise", {"group_by": "none"}, reference_set)
    assert out["rows"][0]["polygons"] == 2
    assert out["rows"][0]["polygons_both_forest"] == 1
    assert "v_polygon" in call.source
    out, _ = tools.call("summarise", {"clusters": ["Atlantis"]}, reference_set)
    assert "Unknown cluster" in out["error"]
    out, call = tools.call("run_insight", {"key": "categories"}, reference_set)
    assert out["view"] == "q_agreement_categories" and "CREATE VIEW" in call.source


@needs_db
def test_chart_specs_are_checked(db, reference_set, results):
    good = {"title": "Outcomes", "source": "categories", "chart": "stacked_bar",
            "x": "cluster", "y": ["polygons"], "color": "category"}
    out, call = tools.call("propose_chart", good, reference_set)
    assert out["ok"] and call.chart["source"] == "categories"
    out, call = tools.call("propose_chart", {k: v for k, v in good.items() if k != "color"}, reference_set)
    assert call.chart["color"] == "category"   # filled in when several rows share an x value
    out, _ = tools.call("propose_chart", {**good, "y": ["no_such_column"]}, reference_set)
    assert "numeric columns" in out["error"]
    out, _ = tools.call("propose_chart", {**good, "source": "everything"}, reference_set)
    assert "source must be one of" in out["error"]


def test_chart_series_get_readable_labels_and_our_colours():
    from assistant import specs
    assert specs._label("naturally_regenerating_ha") == "Naturally regenerating (ha)"
    assert specs._label("ForTy only") == "ForTy only"
    colours = specs._colours(["Naturally regenerating (ha)", "Both forest", "Something else"])
    assert set(colours) == {"Naturally regenerating (ha)", "Both forest"}
