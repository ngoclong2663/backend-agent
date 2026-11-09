"""The planner reads each area's pattern (Epic 32, Story 32.3). The draft patterns are planned with the registry's
switch for the checks (`BGA_DESIGN_INCLUDE_DRAFTS=1`, listed in docs/development/test-doubles.md); back-office areas
and mixed areas (consumers and staff in one area) plan exactly as without it."""

import json

import pytest

from scripts.app_design_report import golden_app, recorded_app
from src.modules.shared.domain.frontend_spec import uncovered_operations, validate_frontend_spec_data
from src.orchestrator.checks.consistency import check_spec_pair
from src.orchestrator.frontend.app.ux_checks import ux_checks


@pytest.fixture
def drafts(monkeypatch):
    monkeypatch.setenv("BGA_DESIGN_INCLUDE_DRAFTS", "1")


def _valid(spec: dict, backend: dict, contract: dict) -> None:
    checked = validate_frontend_spec_data(spec)
    assert checked.report.valid, [e.message for e in checked.report.errors]
    assert check_spec_pair(checked.normalized, backend) == []
    assert uncovered_operations(spec, contract) == []


def _area(spec: dict, prefix: str) -> list[dict]:
    return [page for page in spec["pages"] if page["route"] == prefix or page["route"].startswith(prefix + "/")]


def _menu(spec: dict, prefix_id: str) -> list[str]:
    return [item["label"] for item in spec["layout"]["header"]["navigation"] if item["page"].startswith(prefix_id)]


def _actions(page: dict) -> list[dict]:
    return [a for s in page["sections"] for a in (s.get("content") or {}).get("actions") or []]


def test_a_feed_area_lets_viewers_watch_react_and_comment_where_they_are(drafts):
    """The recorded TikTok-like draft whose viewers met tables, a dashboard, a comment page and an edit route
    (Story 28.7): under `feed` the viewers' menu is the feed and Mine; a like is one click on the video's card and
    page; a comment is written in a dialog on the video; no page or action edits a video the viewer never posts."""
    spec, backend, contract = recorded_app("tiktok-viewer-ids")
    _valid(spec, backend, contract)
    assert _menu(spec, "viewers") == ["Feed", "Mine"]
    pages = _area(spec, "/viewers")
    routes = {page["route"] for page in pages}
    assert not [r for r in routes if r.endswith("/edit") or r.endswith("/new")], routes
    assert "/viewers/dashboard" not in routes and "/viewers/mine" in routes
    home = next(page for page in pages if page["route"] == "/viewers")
    assert any(a.get("operationId") == "interaction.like" for a in _actions(home)), "a like on the feed's cards"
    record = next(page for page in pages if page["route"] == "/viewers/videos/[id]")
    video = next(s for s in record["sections"] if s["component"] == "AppDetail")  # the video's own actions
    labels = {a["label"]: a for a in video["content"]["actions"]}
    assert "Like" in labels and labels["Add comment"].get("form"), "the comment's form opens on the video"
    assert not {"Publish", "Reject", "Delete", "Edit"} & set(labels), "the creator's actions stay the creator's"
    assert not [s for s in record["sections"] if (s.get("content") or {}).get("entity") == "Interaction"]
    viewers = next(a for a in ux_checks(spec, backend, contract) if a["area"] == "viewers")
    assert {f["check"] for f in viewers["failed"]} == {"contributions-readable"}, "Story 32.4's"
    assert viewers["task"]["clicks"] == 1


def test_a_storefront_area_puts_the_cart_on_the_product_and_in_the_menu(drafts):
    spec, backend, contract = golden_app("plant-shop")
    _valid(spec, backend, contract)
    menu = [
        item["label"] for item in spec["layout"]["header"]["navigation"] if not item["page"].startswith("management")
    ]
    assert menu == ["Plants", "Cart", "My Orders"]
    shopper = next(a for a in ux_checks(spec, backend, contract) if a["area"] == "storefront")
    assert shopper["failed"] == [] and shopper["task"]["clicks"] == 2
    product = next(page for page in spec["pages"] if page["route"] == "/plants/[id]")
    assert any(a.get("operationId") == "cartItem.create" and a.get("form") for a in _actions(product))


@pytest.mark.parametrize(
    "name",
    ["agency-projects", "workshop-bookings", "news-feed", "video-library", "learning-platform"],
)
def test_back_office_and_mixed_areas_plan_as_they_always_did(name, monkeypatch):
    """A back-office app, and a mixed area (members and editors, viewers and creators in one area: its pattern would
    hide the staff's screens) plan byte for byte the same with the draft patterns on."""
    before = json.dumps(golden_app(name)[0], sort_keys=True)
    monkeypatch.setenv("BGA_DESIGN_INCLUDE_DRAFTS", "1")
    assert json.dumps(golden_app(name)[0], sort_keys=True) == before


def test_a_staff_area_next_to_a_consumer_one_is_unchanged(monkeypatch):
    spec, *_ = golden_app("plant-shop")
    before = [page for page in spec["pages"] if page["route"].startswith("/management")]
    monkeypatch.setenv("BGA_DESIGN_INCLUDE_DRAFTS", "1")
    spec, *_ = golden_app("plant-shop")
    assert [page for page in spec["pages"] if page["route"].startswith("/management")] == before
