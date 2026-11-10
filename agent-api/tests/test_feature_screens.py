"""Epic 33 (Story 33.5): the comments and reactions features on screen, planned from the socials reference draft."""

import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import uncovered_operations, validate_frontend_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.drafting.app import app_theme
from src.orchestrator.drafting.features import attach
from src.orchestrator.frontend.app.domain_tasks import judge
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.integration.contract import build_contract

FIXTURES = Path(__file__).parent / "fixtures"
DRAFT = FIXTURES / "drafts" / "domain-socials"
USES = [{"feature": "comments", "on": "Clip"}, {"feature": "reactions", "on": "Clip", "options": {"kinds": ["like"]}}]


def _planned(uses=USES):
    merged, _ = attach(json.loads((DRAFT / "backend-spec.json").read_text()), uses)
    backend = validate_spec_data(merged).normalized
    raw = json.loads((DRAFT / "app-outline.json").read_text())
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    return app_frontend_spec(backend, outline, app_theme(None), contract).spec, contract


def _clip_page(spec):
    return next(p for p in spec["pages"] if p["route"] == "/clips/[id]")


def test_the_clip_shows_a_like_toggle_with_its_state_and_count():
    spec, _ = _planned()
    detail = _clip_page(spec)["sections"][0]
    like = next(a for a in detail["content"]["actions"] if a["id"] == "react-like")
    assert like == {
        "id": "react-like",
        "label": "Like",
        "kind": "reaction",
        "reaction": "like",
        "operationId": "clipReaction.create",
        "undoOperationId": "clipReaction.delete",
        "state": "myLikeId",
        "count": "likeCount",
        "body": {"clipId": "$route.id", "kind": "like"},
    }


def test_the_clip_page_has_its_comment_thread():
    spec, _ = _planned()
    thread = next(s for s in _clip_page(spec)["sections"] if s["component"] == "CommentThread")
    assert thread["content"]["thread"]["target"] == "clipId" and thread["content"]["thread"]["parent"] == "parentId"
    assert set(thread["content"]["operations"]) == {
        "clipComment.list",
        "clipComment.create",
        "clipComment.update",
        "clipComment.delete",
    }


def test_feature_entities_get_no_screens_of_their_own_and_everything_is_covered():
    spec, contract = _planned()
    routes = {page["route"] for page in spec["pages"]}
    assert not [r for r in routes if "clip-comment" in r or "clip-reaction" in r]
    assert validate_frontend_spec_data(spec).report.valid
    assert "clipComment.create" not in uncovered_operations(spec, contract)
    assert "clipReaction.delete" not in uncovered_operations(spec, contract)


def test_the_socials_tasks_the_two_features_answer_now_pass():
    spec, _ = _planned()
    tasks = json.loads((FIXTURES / "domains" / "tasks" / "socials.json").read_text())["tasks"]
    results = {r["id"]: r for r in judge(spec, tasks)}
    assert results["like-shows-state"]["passed"] and results["like-in-one-click"]["passed"]
    assert results["reply-to-comment"]["passed"]
