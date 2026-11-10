"""Epic 33 (Story 33.14): a comment on a generated app's screen becomes a change of its choices, or a request."""

import json
from pathlib import Path

from src.orchestrator.feedback import apply_feedback, prompt

SPEC = json.loads(
    (Path(__file__).parent / "fixtures" / "drafts" / "domain-socials-v10" / "frontend-spec.json").read_text()
)


def _labels(spec):
    return [item["label"] for item in spec["layout"]["header"]["navigation"]]


def test_the_prompt_shows_the_comment_as_data_and_the_choices_the_app_has():
    page = next(p for p in SPEC["pages"] if p["route"] == "/clips/[id]")
    text = prompt(SPEC, f"{page['id']}/{page['sections'][0]['id']}", "Put the comments in a popup")
    assert '"Put the comments in a popup"' in text and "react-like" in text and "rename-menu" in text


def test_choice_changes_apply_and_unknown_ones_are_dropped_with_why():
    label = _labels(SPEC)[0]
    answer = {
        "outcome": "choices",
        "changes": [
            {"op": "rename-menu", "from": label, "to": "Discover"},
            {"op": "comments", "value": "sheet"},
            {"op": "accent", "value": "#e8435a"},
            {"op": "remove-action", "id": "nothing-like-this"},
        ],
        "message": "Renamed and moved the comments",
    }
    result = apply_feedback(SPEC, answer)
    assert result["outcome"] == "choices" and len(result["applied"]) == 3
    assert result["dropped"] == [
        {"op": "remove-action", "id": "nothing-like-this", "why": "no action 'nothing-like-this'"}
    ]
    revised = result["frontendSpec"]
    assert _labels(revised)[0] == "Discover" and revised["theme"]["colors"]["primary"] == "#e8435a"
    threads = [s for p in revised["pages"] for s in p["sections"] if s["component"] == "CommentThread"]
    assert threads and all(s["content"]["placement"] == "sheet" for s in threads)
    assert _labels(SPEC)[0] == label  # the original is untouched


def test_removing_the_like_button_is_a_choice():
    result = apply_feedback(
        SPEC, {"outcome": "choices", "changes": [{"op": "remove-action", "id": "react-like"}], "message": ""}
    )
    actions = [
        a["id"]
        for p in result["frontendSpec"]["pages"]
        for s in p["sections"]
        for a in (s.get("content") or {}).get("actions") or []
    ]
    assert "react-like" not in actions


def test_what_no_change_can_do_is_never_silently_dropped():
    bad = apply_feedback(SPEC, {"outcome": "choices", "changes": [{"op": "accent", "value": "pink"}], "message": "x"})
    assert bad["outcome"] == "request" and bad["frontendSpec"] is None
    swipe = apply_feedback(
        SPEC, {"outcome": "request", "changes": [], "request": "Swipe cards to the next clip", "message": ""}
    )
    assert swipe["outcome"] == "request" and swipe["request"] == "Swipe cards to the next clip"


def test_the_api_needs_a_frontend_and_only_admins_read_plugin_requests(client, login, tmp_path):
    from workflow_helpers import completed_generation

    generation_id = completed_generation(client, tmp_path)  # a backend-only generation
    user = {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}
    response = client.post(f"/api/v1/generations/{generation_id}/feedback", json={"comment": "Rename it"}, headers=user)
    assert response.status_code == 404
    assert client.get("/api/v1/generations/plugin-requests", headers=user).status_code == 403
    admin = {"Authorization": f"Bearer {login('admin@test.local', 'adminpass')}"}
    listed = client.get("/api/v1/generations/plugin-requests", headers=admin)
    assert listed.status_code == 200 and isinstance(listed.json()["items"], list)
