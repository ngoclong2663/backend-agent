"""The app design report (Story 23.1): its pure parts. The builds and screenshots run with `make app-design-report`."""

import json
from pathlib import Path

import pytest

from scripts.app_design_report import (
    APPS,
    GOLDEN,
    HAND_WRITTEN,
    app_failures,
    draft_cost,
    frame,
    golden_app,
    main_list,
    markdown,
    similarity,
)

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_similarity_reports_the_mean_the_max_and_the_most_alike_pair():
    dark, light, grey = [0] * 4, [255] * 4, [64] * 4
    result = similarity({"a": dark, "b": light, "c": grey})
    assert result["max"] == pytest.approx(0.749, abs=0.001) and result["mostAlike"] == "a / c"
    assert result["mean"] == pytest.approx((0 + 0.749 + 0.251) / 3, abs=0.001)
    assert similarity({"only": dark}) == {"mean": None, "max": None, "pairs": {}}


def test_app_failures_are_the_kit_rules_not_a_marketing_pages():
    clean = {
        "overflowX": False,
        "families": ['"Inter"', "ui-monospace"],
        "loadedFonts": ["Inter"],
        "typeSizes": list(range(9)),
    }
    assert app_failures("home", clean) == [], "system families need no loading; type sizes are a site rule"
    broken = {
        "overflowX": True,
        "families": ["Inter", "Lora", "Rubik"],
        "loadedFonts": ["Inter"],
        "form": {"clipped": ["save"], "unlabelled": [], "nativeDateInputs": 1},
    }
    found = app_failures("form", broken)
    assert len(found) == 5 and found[0] == "form: scrolls sideways"


def test_frames_read_the_design_and_fall_back_to_todays_kit():
    today = {"app": {"home": "dashboard", "nav": [{"entity": "Post"}], "entities": {"Post": {"listStyle": "cards"}}}}
    assert frame(today) == ("sidebar", "dashboard", "cards")
    designed = {
        "app": {
            "home": "Post",
            "nav": [{"entity": "Post"}],
            "entities": {"Post": {"listStyle": "cards"}},
            "design": {
                "shell": "topbar",
                "homeView": "feed",
                "mainEntity": "Post",
                "entities": {"Post": {"view": "feed"}},
            },
        }
    }
    assert frame(designed) == ("topbar", "feed", "feed")


@pytest.mark.parametrize("name", APPS)
def test_every_golden_app_plans_from_its_recorded_draft(name):
    spec, backend, contract = golden_app(name)
    assert spec["project"]["flow"] == "app" and backend["entities"] and contract["paths"]
    listed = main_list(spec)
    assert listed and listed != "/" and "[" not in listed
    page = next(page for page in spec["pages"] if page["route"] == listed)
    assert all((s.get("content") or {}).get("variant") != "recent" for s in page["sections"]), "not a recent list"


def test_golden_apps_have_a_requirement_a_recorded_draft_and_a_brief():
    for name in APPS:
        if name in HAND_WRITTEN:  # Epic 22's every-plugin app, Epic 29's media app: no recorded draft
            assert draft_cost(name) == {}
            continue
        assert (EXAMPLES / "requirements" / f"{name}.md").read_text().startswith("# ")
        draft = draft_cost(name)
        assert draft["calls"] >= 1 and draft["costUsd"] > 0
        assert json.loads((GOLDEN / name / "design-brief.json").read_text())["mainEntity"]


def test_the_markdown_lists_every_app():
    results = {
        "date": "2026-11-06",
        "apps": {"a": {"frame": ["sidebar", "dashboard", "table"], "failures": ["x"], "replaced": [], "draft": {}}},
        "home": {"mean": 0.7, "max": 0.7, "mostAlike": None},
        "list": {"mean": None, "max": None},
        "distinctFrames": 1,
    }
    text = markdown(results)
    assert "| a | sidebar, dashboard, table | 1 | 0 | — |" in text and "- x" in text
