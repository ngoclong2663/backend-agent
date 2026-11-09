"""UX checks per archetype (Epic 32, Story 32.1): how a planned app behaves for each area's people, measured before
the product patterns change the planner. Synthetic specs pass and fail each check; the recorded real drafts and the
golden apps are held to the committed baseline."""

import copy
import json
from pathlib import Path

from scripts.app_design_report import APPS, GOLDEN, RECORDED_APPS, golden_app, ux_baseline, ux_report
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.drafting.access import secure_access
from src.orchestrator.frontend.app.patterns import child_shapes
from src.orchestrator.frontend.app.ux_checks import ux_checks
from src.orchestrator.integration.contract import build_contract
from tests.test_access_rules import _feed_spec


def _feed() -> tuple[dict, dict]:
    raw = _feed_spec(comment_policy=True)
    secure_access(raw)
    backend = validate_spec_data(raw).normalized
    return backend, build_contract(backend, build_plan(backend))


def _app(sections_home: list[dict], pages: list[dict] | None = None, archetype: str = "feed") -> dict:
    """A FrontendSpec of one area, written by hand: the home's sections and any other pages."""
    return {
        "app": {"design": {"archetype": archetype, "mainEntity": "Video"}},
        "pages": [{"id": "home", "route": "/", "sections": sections_home}, *(pages or [])],
        "forms": [{"id": "comment_create", "operationId": "comment.create", "fields": []}],
        "layout": {"header": {"navigation": [{"label": "Videos", "page": "home"}]}},
    }


LIKE = {"id": "add-likes", "label": "Like", "kind": "mutation", "operationId": "like.create"}
FEED = {"id": "feed", "component": "AppList", "content": {"entity": "Video", "style": "feed", "actions": [LIKE]}}


def _failed(spec: dict, backend: dict, contract: dict) -> set[str]:
    return {f["check"] for f in ux_checks(spec, backend, contract)[0]["failed"]}


def test_the_shapes_of_a_records_children():
    """A like has nothing to fill in (an interaction), a comment is a person's text (a contribution); both are the
    signed-in person's own; a shop's order item is a part, a cart item an interaction owned by the shopper."""
    backend, contract = _feed()
    shapes = child_shapes(contract)
    assert (shapes["Like"]["shape"], shapes["Like"]["owned"]) == ("interaction", True)
    assert (shapes["Comment"]["shape"], shapes["Comment"]["parents"][0]["entity"]) == ("contribution", "Video")
    _, _, shop_contract = golden_app("plant-shop")
    shop_shapes = child_shapes(shop_contract)
    assert shop_shapes["OrderItem"]["shape"] == "part"
    assert (shop_shapes["CartItem"]["shape"], shop_shapes["CartItem"]["owned"]) == ("interaction", True)


def test_a_feed_that_behaves_like_one_passes():
    backend, contract = _feed()
    area = ux_checks(_app([FEED]), backend, contract)[0]
    assert {"home-is-feed", "no-table", "no-dashboard", "interaction-on-record", "contribution-on-record"} <= set(
        area["passed"]
    ), area["failed"]
    assert area["task"] == {"operationId": "like.create", "clicks": 1}


def test_each_back_office_habit_fails_its_feed_check():
    backend, contract = _feed()
    table = copy.deepcopy(FEED)
    table["content"] |= {"style": "table", "actions": []}
    assert {"no-table", "interaction-on-record"} <= _failed(_app([table]), backend, contract)
    figures = {"id": "figures", "component": "AppDashboard", "content": {"label": "Clips"}}
    assert {"no-dashboard", "home-is-feed"} <= _failed(_app([figures]), backend, contract)
    comment_page = {
        "id": "new",
        "route": "/videos/[id]/comments/new",
        "sections": [{"id": "f", "form": "comment_create"}],
    }
    assert "contribution-on-record" in _failed(_app([FEED], [comment_page]), backend, contract)


def test_the_click_count_of_the_main_task():
    """On the home's cards one click; on another page two; through a form page three; no screen, None."""
    backend, contract = _feed()
    detail = {"id": "d", "component": "AppDetail", "content": {"entity": "Video", "actions": [LIKE]}}
    record = {"id": "video-id", "route": "/videos/[id]", "sections": [detail]}
    bare = copy.deepcopy(FEED)
    bare["content"]["actions"] = []
    assert ux_checks(_app([bare], [record]), backend, contract)[0]["task"]["clicks"] == 2
    assert ux_checks(_app([bare]), backend, contract)[0]["task"]["clicks"] is None


def test_back_office_areas_pass_and_the_recorded_viewers_met_what_the_user_reported():
    """Before the patterns (`ux-before.json`, Story 32.1), the checks found what the user met on 2026-11-09 in the
    recorded TikTok-like drafts (a dashboard, an edit route for other people's videos, a table of their own likes,
    comments on a page of their own and readable by their author alone) and nothing in any back-office area. With
    the feed pattern ready (Story 32.5) those viewers pass; one draft was secured before 32.4, so its comments are
    still private in the recorded spec."""
    before = json.loads((GOLDEN / "ux-before.json").read_text())["areas"]
    assert set(before["tiktok-viewer-ids/viewers"]["failed"]) >= {
        "no-dashboard",
        "no-edit-others",
        "no-own-interaction-menu",
        "contribution-on-record",
        "contributions-readable",
    }
    results = ux_report(APPS, RECORDED_APPS)["areas"]
    for key, area in results.items():
        if area["kind"] == "back-office":
            assert area["failed"] == [], (key, area["failed"])
    assert results["tiktok-likes/viewers"]["failed"] == []
    assert results["tiktok-feed-sessions/viewer-area"]["failed"] == []
    assert {f["check"] for f in results["tiktok-viewer-ids/viewers"]["failed"]} == {"contributions-readable"}
    assert results["plant-shop/storefront"]["task"] == {"operationId": "cartItem.create", "clicks": 3}, "a draft"


def test_the_committed_baseline_is_the_reports_output():
    """Epic 32 measures its patterns against this file: a planner change that changes how an area behaves updates it
    on purpose (`make app-design-report ARGS="--ux-only --baseline"`)."""
    expected = json.loads((GOLDEN / "ux-baseline.json").read_text())
    found = ux_baseline(ux_report(APPS, RECORDED_APPS))
    expected.pop("date"), found.pop("date")
    assert found == expected


def test_recorded_drafts_are_on_disk():
    folder = Path(__file__).parent / "fixtures" / "drafts"
    for name in RECORDED_APPS:
        assert (folder / name / "backend-spec.json").is_file() and (folder / name / "app-outline.json").is_file()
