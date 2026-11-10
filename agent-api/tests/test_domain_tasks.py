"""Epic 33 (Story 33.1): the domains' UX tasks judged on planned apps."""

import json

from scripts.domain_report import BASELINE, report
from src.orchestrator.frontend.app.domain_tasks import judge


def _spec(pages, forms=(), areas=None):
    return {
        "app": {"areas": areas or [{"id": "members", "roles": ["Member"], "prefix": "/"}]},
        "pages": list(pages),
        "forms": list(forms),
    }


def _page(route, *sections):
    return {"route": route, "sections": list(sections)}


def _actions(component, *actions, **content):
    return {"component": component, "content": {"actions": list(actions), **content}}


def _task(check, role="member", budget=None):
    return {"id": "t", "role": role, "goal": "g", "check": check, **({"budget": budget} if budget else {})}


def test_an_action_counts_its_clicks_against_the_budget():
    like = {"operationId": "like.create"}
    on_home = _spec([_page("/", _actions("AppList", like))])
    deeper = _spec([_page("/"), _page("/clips/[id]", _actions("AppDetail", like))])
    check = {"kind": "action", "verbs": ["like"]}
    assert judge(on_home, [_task(check, budget=1)])[0]["passed"]
    result = judge(deeper, [_task(check, budget=1)])[0]
    assert not result["passed"] and result["why"] == "2 clicks, the budget is 1"


def test_a_reaction_needs_its_state_on_the_button():
    check = {"kind": "reaction_state", "verbs": ["like"]}
    plain = _spec([_page("/", _actions("AppList", {"operationId": "like.create"}))])
    stateful = _spec([_page("/", _actions("AppList", {"operationId": "clipReaction.like", "state": "myLikeId"}))])
    assert "shows no state" in judge(plain, [_task(check)])[0]["why"]
    assert judge(stateful, [_task(check)])[0]["passed"]


def test_a_reply_comes_from_the_comment_not_a_picker():
    picker_form = {"id": "f", "fields": [{"name": "parentCommentId"}, {"name": "text"}]}
    reply_form = {"id": "r", "fields": [{"name": "parentId", "hidden": True, "value": "$record.id"}]}
    add = _actions("AppDetail", {"operationId": "comment.create", "form": "f"})
    picker = _spec([_page("/c/[id]", add)], [picker_form])
    reply = _spec([_page("/c/[id]", _actions("AppList", {"operationId": "comment.create", "form": "r"}))], [reply_form])
    thread = _spec([_page("/c/[id]", {"component": "CommentThread"})])
    assert "picked from a list" in judge(picker, [_task({"kind": "reply"})])[0]["why"]
    assert judge(reply, [_task({"kind": "reply"})])[0]["passed"]
    assert judge(thread, [_task({"kind": "reply"})])[0]["passed"]


def test_sections_fields_filters_files_and_resume():
    spec = _spec(
        [
            _page("/", {"component": "AppChart"}, {"component": "AppList", "data": {"fields": ["progress"]}}),
            _page(
                "/devices",
                _actions("AppList", entity="Device", controls={"filters": [{"field": "status"}]}),
                _actions("AppDetail", {"operationId": "delivery.deliver", "form": "d"}),
            ),
        ],
        [{"id": "d", "fields": [{"name": "photo", "type": "image"}]}],
    )
    checks = [
        {"kind": "section", "components": ["AppChart"]},
        {"kind": "field_shown", "words": ["progress"]},
        {"kind": "filter", "entity_words": ["device"], "field_words": ["status"]},
        {"kind": "action_with_file", "verbs": ["deliver"]},
    ]
    assert all(r["passed"] for r in judge(spec, [_task(c) for c in checks]))
    assert "no way back" in judge(spec, [_task({"kind": "resume"})])[0]["why"]


def test_a_role_without_an_area_fails_with_why():
    result = judge(_spec([_page("/")]), [_task({"kind": "action", "verbs": ["x"]}, role="customer")])[0]
    assert result["why"] == "no area for the role 'customer'"


def test_the_baseline_is_todays_kit_on_the_recorded_drafts():
    """The baseline was taken before any domain plugin; the recorded drafts still judge the same."""
    baseline = json.loads(BASELINE.read_text())
    now = {name: {k: v for k, v in domain.items() if k != "draft"} for name, domain in report()["domains"].items()}
    assert now == baseline["domains"]
    assert baseline["summary"] == {"tasks": 24, "passed": 11}
