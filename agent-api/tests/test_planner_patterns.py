"""The planner reads each area's pattern (Epic 32, Story 32.3). The draft patterns are planned with the registry's
switch for the checks (`BGA_DESIGN_INCLUDE_DRAFTS=1`, listed in docs/development/test-doubles.md); back-office areas
and mixed areas (consumers and staff in one area) plan exactly as without it."""

import json
from pathlib import Path

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


def test_a_feed_drafted_end_to_end_reads_everyones_comments(drafts):
    """Stories 32.3 and 32.4 together: the access rules keep a feed's comments readable, the planner puts the like
    and the comment on the video; the area passes every feed check, `contributions-readable` included."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.drafting.access import secure_access
    from src.orchestrator.drafting.app import public_shapes
    from tests.test_access_rules import _feed_spec
    from tests.test_app_screens import _plan

    outline = {"design": {"archetype": "feed", "mainEntity": "Video"}}
    raw = _feed_spec(comment_policy=True)
    secure_access(raw, public_shapes(outline, None))
    backend = validate_spec_data(raw).normalized
    extended, _, contract, screens = _plan(backend, outline)
    _valid(screens.spec, extended, contract)
    area = ux_checks(screens.spec, extended, contract)[0]
    assert area["kind"] == "feed" and area["failed"] == [], area["failed"]
    assert area["task"] == {"operationId": "like.create", "clicks": 1}


def test_a_view_is_counted_when_the_record_opens_not_by_a_button(drafts):
    """Story 32.5: the recorded draft's `video.view` (a record action with nothing to fill in, named like a view) runs
    once when the video opens (`onOpen`, covered); it is no button on the cards or the page."""
    spec, backend, contract = recorded_app("tiktok-likes")
    _valid(spec, backend, contract)
    record = next(page for page in spec["pages"] if page["route"] == "/viewers/videos/[id]")
    detail = next(s for s in record["sections"] if s["component"] == "AppDetail")
    assert detail["content"]["onOpen"] == {"operationId": "video.view", "params": {"id": "$route.id"}}
    every = [a.get("operationId") for page in _area(spec, "/viewers") for a in _actions(page)]
    assert "video.view" not in every


def test_a_back_office_keeps_a_view_action_as_a_button():
    """The same recorded draft with its viewers' area drafted as a back-office: `video.view` stays a button."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.frontend.app.screens import _name_words
    from tests.test_app_screens import _plan

    assert _name_words("VideoView") == {"video", "view"}
    folder = Path(__file__).parent / "fixtures" / "drafts" / "tiktok-likes"
    backend = validate_spec_data(json.loads((folder / "backend-spec.json").read_text())).normalized
    outline = json.loads((folder / "app-outline.json").read_text())
    for area in outline["areas"]:
        area.setdefault("design", {})["archetype"] = "back-office"
    _, _, _, screens = _plan(backend, outline)
    assert not [s for page in screens.spec["pages"] for s in page["sections"] if (s.get("content") or {}).get("onOpen")]
    assert any(a.get("operationId") == "video.view" for page in screens.spec["pages"] for a in _actions(page)), (
        "a button in a back-office"
    )


def _feed_with(archetype: str, creates: dict[str, str]):
    """The synthetic feed spec (videos, comments, likes) planned with the draft's `entities.<Entity>.create`."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.drafting.access import secure_access
    from src.orchestrator.drafting.app import public_shapes
    from tests.test_access_rules import _feed_spec
    from tests.test_app_screens import _plan

    outline = {
        "design": {"archetype": archetype, "mainEntity": "Video"},
        "entities": {entity: {"create": where} for entity, where in creates.items()},
    }
    raw = _feed_spec(comment_policy=True)
    secure_access(raw, public_shapes(outline, None))
    backend = validate_spec_data(raw).normalized
    extended, completed, contract, screens = _plan(backend, outline)
    _valid(screens.spec, extended, contract)
    return completed, screens


def _video(screens) -> list[dict]:
    record = next(page for page in screens.spec["pages"] if page["route"] == "/videos/[id]")
    return next(s for s in record["sections"] if s["component"] == "AppDetail")


def test_the_drafts_placement_wins_over_the_pattern():
    """Story 32.7: what the requirement says about where a record is made reaches the screens, in any area: a
    back-office's comment on the video (`onRecord`), a feed's comment on a page of its own (`page`), a like made when
    the video opens (`onOpen`, nothing to fill in); a placement for an entity without a parent is dropped."""
    _, screens = _feed_with("back-office", {"Comment": "onRecord"})
    routes = {page["route"] for page in screens.spec["pages"]}
    assert "/videos/[id]/comments/new" not in routes
    assert any(
        a.get("operationId") == "comment.create" and a.get("form") for a in _video(screens)["content"]["actions"]
    )

    _, screens = _feed_with("feed", {"Comment": "page"})
    routes = {page["route"] for page in screens.spec["pages"]}
    assert "/videos/[id]/comments/new" in routes
    assert not any(a.get("operationId") == "comment.create" for a in _video(screens)["content"]["actions"])

    _, screens = _feed_with("feed", {"Like": "onOpen"})
    detail = _video(screens)
    assert detail["content"]["onOpen"] == {"operationId": "like.create", "body": {"videoId": "$route.id"}}
    assert not any(a.get("operationId") == "like.create" for a in detail["content"]["actions"])

    completed, _ = _feed_with("feed", {"Video": "onRecord"})
    assert "create" not in completed["entities"]["Video"], "a video has no parent record to be made on"


def test_the_tour_finds_a_step_done_by_opening_the_record():
    from src.orchestrator.business.binding import action_targets

    _, screens = _feed_with("feed", {"Like": "onOpen"})
    places = action_targets(screens.spec)["like.create"]
    assert {(p["route"], p["action"]) for p in places} == {("/videos/[id]", None)}


def test_a_catalogue_area_of_members_behaves_like_one():
    """Story 32.8's first real run (Pocket Chefs, 2026-11-09): the model called the members' area a `catalogue`, for
    which no pattern was ready, so members met the cook's Edit, Publish and Delete, a "Record view" button and a
    dashboard. Under the `catalogue` pattern: Feed and Mine, like, save and comment on the recipe (the draft's
    `create: onRecord`), the view counted when the recipe opens, every check passed."""
    spec, backend, contract = recorded_app("pocket-chefs")
    _valid(spec, backend, contract)
    assert _menu(spec, "members") == ["Feed", "Mine"]
    record = next(page for page in spec["pages"] if page["route"] == "/members/recipes/[id]")
    detail = next(s for s in record["sections"] if s["component"] == "AppDetail")
    assert detail["content"]["onOpen"]["operationId"] == "recipe.recordView"
    assert not {"Edit", "Publish", "Delete", "Record view"} & {a["label"] for a in detail["content"]["actions"]}
    members = next(a for a in ux_checks(spec, backend, contract) if a["area"] == "members")
    assert members["kind"] == "catalogue" and members["failed"] == []
