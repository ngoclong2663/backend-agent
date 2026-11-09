"""The app design report (Story 23.1; Story 30.1: signed in, fingerprints, edge similarity): its pure parts. The builds
and screenshots run with `make app-design-report`."""

import json
from pathlib import Path

import pytest

from scripts.app_design_report import (
    APPS,
    GOLDEN,
    HAND_WRITTEN,
    app_failures,
    area_routes,
    areas,
    baseline,
    coverage,
    demo_login,
    draft_cost,
    fingerprint,
    fingerprint_key,
    frame,
    golden_app,
    main_list,
    markdown,
    shared_fingerprints,
    similarity,
)
from src.orchestrator.drafting.design_diversity import edge_signature, edge_similarity

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
        assert draft["calls"] >= 1 and draft["costUsd"] >= 0  # Epic 30's drafts ran on the account login ($0)
        assert json.loads((GOLDEN / name / "design-brief.json").read_text())["mainEntity"]


def _results() -> dict:
    sidebar = {
        "shell": "sidebar",
        "home": "dashboard",
        "view": "table",
        "detail": "record",
        "card": "-",
        "filters": "toolbar",
    }
    return {
        "date": "2026-11-09",
        "apps": {
            "a": {"frame": ["sidebar", "dashboard", "table"], "replaced": [], "draft": {}},
            "b": {"frame": ["sidebar", "dashboard", "table"], "replaced": ["x"], "draft": {}},
        },
        "areas": {
            "a/app": {
                "app": "a",
                "login": "demo-x@example.com:demo12345",
                "fingerprint": sidebar,
                "failures": ["home-375-light: scrolls sideways"],
            },
            "b/app": {"app": "b", "login": None, "fingerprint": sidebar, "failures": []},
        },
        "home": {"mean": 0.7, "max": 0.7, "mostAlike": "a/app / b/app"},
        "list": {"mean": None, "max": None},
        "edges": {
            screen: {"mean": 0.3, "max": 0.5, "mostAlike": "a/app / b/app"} for screen in ("home", "list", "record")
        },
        "distinctFrames": 1,
        "distinctFingerprints": 1,
        "sharedFingerprints": [["a/app", "b/app"]],
        "coverage": {
            "used": {"shell": ["sidebar"]},
            "unused": {"shell": ["rail", "topbar", "topbar-tabs"], "card": []},
        },
    }


def test_the_markdown_lists_every_area_the_shared_fingerprints_and_the_unused_plugins():
    text = markdown(_results())
    assert (
        "| a/app | sidebar, dashboard, table, record, -, toolbar | demo-x@example.com:demo12345 | 1 | 0 | — |" in text
    )
    assert "| b/app | sidebar, dashboard, table, record, -, toolbar | nobody (open app) | 0 | 1 | — |" in text
    assert "- a/app, b/app" in text and "- shell: rail, topbar, topbar-tabs" in text and "card:" not in text
    assert "- home-375-light: scrolls sideways" in text and "Distinct fingerprints: 1 of 2" in text


def test_the_baseline_keeps_the_numbers_the_next_report_is_compared_against():
    kept = baseline(_results())
    assert kept["distinctFingerprints"] == 1 and kept["edges"]["home"] == {"mean": 0.3, "max": 0.5}
    assert kept["fingerprints"]["a/app"]["shell"] == "sidebar" and kept["coverage"]["unused"]["shell"] == [
        "rail",
        "topbar",
        "topbar-tabs",
    ]
    assert "areas" not in kept and "apps" not in kept


def test_a_fingerprint_reads_the_design_then_the_dom_markers():
    area = {
        "design": {
            "shell": "topbar",
            "homeView": "catalogue",
            "mainEntity": "Plant",
            "entities": {"Plant": {"view": "media-grid"}},
        }
    }
    print_ = fingerprint(area, {"list": {"card": ["overlay"], "filters": ["chips"]}, "record": {"detail": ["media"]}})
    assert print_ == {
        "shell": "topbar",
        "home": "catalogue",
        "view": "media-grid",
        "detail": "media",
        "card": "overlay",
        "filters": "chips",
    }
    assert (
        fingerprint_key(print_) == "shell=topbar|home=catalogue|view=media-grid|detail=media|card=overlay|filters=chips"
    )
    bare = fingerprint({"design": {}})
    assert bare == {
        "shell": "sidebar",
        "home": "dashboard",
        "view": "table",
        "detail": "record",
        "card": "-",
        "filters": "toolbar",
    }
    prints = {"x": {"fingerprint": print_}, "y": {"fingerprint": print_}, "z": {"fingerprint": bare}}
    assert shared_fingerprints(prints) == [["x", "y"]]


def test_coverage_names_the_used_and_the_unused_plugins_per_kind():
    prints = {
        "a": {
            "design": {
                "shell": "topbar",
                "homeView": "catalogue",
                "looks": [{"recipe": "minimal"}],
                "entities": {"P": {"view": "media-grid", "filtersStyle": "chips"}},
            }
        },
        "b": {"design": {"shell": "sidebar", "homeView": "dashboard", "entities": {"Q": {"view": "table"}}}},
    }
    found = coverage(prints)
    assert found["used"]["shell"] == ["sidebar", "topbar"] and "rail" in found["unused"]["shell"]
    assert found["used"]["list-view"] == ["media-grid", "table"] and "board" in found["unused"]["list-view"]
    assert found["used"]["filters"] == ["chips", "toolbar"], "an entity without a filters style uses the toolbar"
    assert found["used"]["detail-view"] == ["record"] and found["used"]["recipe"] == ["minimal"]


def test_edge_similarity_tells_a_sidebar_from_a_top_bar(tmp_path):
    from PIL import Image, ImageDraw

    def shot(name: str, draw_lines) -> Path:
        image = Image.new("RGB", (1440, 900), "white")
        draw_lines(ImageDraw.Draw(image))
        path = tmp_path / f"{name}.png"
        image.save(path)
        return path

    sidebar = shot(
        "sidebar",
        lambda d: (
            d.rectangle((0, 0, 256, 900), outline="black", width=3),
            [d.rectangle((300, 100 + i * 60, 1400, 140 + i * 60), outline="black", width=2) for i in range(8)],
        ),
    )
    sidebar_too = shot(
        "sidebar2",
        lambda d: (
            d.rectangle((0, 0, 256, 900), outline="black", width=3),
            [d.rectangle((300, 100 + i * 60, 1400, 140 + i * 60), outline="black", width=2) for i in range(7)],
        ),
    )
    topbar = shot(
        "topbar",
        lambda d: (
            d.rectangle((0, 0, 1440, 64), outline="black", width=3),
            [
                d.rectangle(
                    (40 + (i % 4) * 350, 120 + (i // 4) * 300, 340 + (i % 4) * 350, 380 + (i // 4) * 300),
                    outline="black",
                    width=2,
                )
                for i in range(8)
            ],
        ),
    )
    a, b, c = edge_signature(sidebar), edge_signature(sidebar_too), edge_signature(topbar)
    assert len(a) == 96 * 60 and sum(a) > 0
    assert edge_similarity(a, a) == 1.0
    assert edge_similarity(a, b) > 0.6 > edge_similarity(a, c)


def test_areas_routes_and_demo_logins_of_a_golden_app_with_areas():
    spec, _, contract = golden_app("plant-shop")
    found = areas(spec)
    assert [area["id"] for area in found] == ["storefront", "management"] and found[1]["prefix"] == "/management"
    routes = area_routes(spec, contract, found[1])
    assert routes["home"] == "/management" and routes["list"] == "/management/plants"
    assert routes["record"].startswith("/management/plants/") and "[" not in routes["record"]
    assert demo_login(contract, found[1]) == "demo-owner@example.com:demo12345"
    assert demo_login(contract, found[0]) == "demo-shopper@example.com:demo12345"
    open_spec, _, open_contract = golden_app("media-library")
    assert demo_login(open_contract, areas(open_spec)[0]) is None
