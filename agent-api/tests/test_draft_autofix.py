"""Story 18.3: Route-parameter links hint, autofix, excerpt builder and interrupted repair re-check."""

import json
from pathlib import Path

from src.engines.fake_engine import FakeEngine, FakeStep
from src.modules.shared.domain.frontend_spec import autofix_frontend_spec, validate_frontend_spec_data
from src.orchestrator.drafting import build_excerpt

REPO = Path(__file__).parents[2]
EXAMPLES = REPO / "examples"


def _spec_with_cta(target_page_id: str, extra_pages: list[dict]) -> dict:
    return {
        "specVersion": "1.0",
        "project": {"name": "Test", "mode": "dynamic"},
        "layout": {"header": {"navigation": []}, "footer": {"links": []}},
        "theme": {"style": "minimal"},
        "pages": [
            {
                "id": "home",
                "route": "/",
                "title": "Home",
                "sections": [
                    {
                        "id": "hero",
                        "component": "Hero",
                        "content": {
                            "heading": "Welcome",
                            "cta": {"label": "Start", "page": target_page_id},
                        },
                    }
                ],
            },
            *extra_pages,
        ],
    }


def test_autofix_case_a_cta_to_prefix_page():
    """Case (a): CTA to /study/[id] with /study present -> points to study."""
    spec = _spec_with_cta(
        "study_detail",
        [
            {"id": "study", "route": "/study", "title": "Study", "sections": []},
            {"id": "study_detail", "route": "/study/[id]", "title": "Study Detail", "sections": []},
            {"id": "decks", "route": "/decks", "title": "Decks", "sections": []},
        ],
    )
    fixed, notes = autofix_frontend_spec(spec)
    hero_cta = fixed["pages"][0]["sections"][0]["content"]["cta"]
    assert hero_cta["page"] == "study"
    assert len(notes) == 1
    assert notes[0]["spec"] == "frontend"
    assert notes[0]["path"] == "/pages/0/sections/0/content/cta/page"
    assert (
        notes[0]["message"]
        == "Link to 'study_detail' (/study/[id]) now points to 'study' (/study): a link cannot fill [id]"
    )


def test_autofix_case_b_no_prefix_but_list_page_for_same_entity():
    """Case (b): CTA to /study/[id] without /study, but /decks binds to deck.list -> points to decks."""
    spec = _spec_with_cta(
        "study_detail",
        [
            {
                "id": "decks",
                "route": "/decks",
                "title": "Decks",
                "sections": [
                    {
                        "id": "deck-list",
                        "component": "CardGrid",
                        "data": {"operationId": "deck.list", "action": "list"},
                    }
                ],
            },
            {
                "id": "study_detail",
                "route": "/study/[id]",
                "title": "Study Detail",
                "sections": [
                    {
                        "id": "study-card",
                        "component": "FlashcardStudy",
                        "data": {"operationId": "deck.get", "action": "get", "params": {"id": "$route.id"}},
                    }
                ],
            },
        ],
    )
    fixed, notes = autofix_frontend_spec(spec)
    hero_cta = fixed["pages"][0]["sections"][0]["content"]["cta"]
    assert hero_cta["page"] == "decks"
    assert len(notes) == 1
    assert (
        notes[0]["message"]
        == "Link to 'study_detail' (/study/[id]) now points to 'decks' (/decks): a link cannot fill [id]"
    )


def test_autofix_case_c_neither_removes_link_when_optional():
    """Case (c): Neither prefix nor list page for entity -> removes optional CTA."""
    spec = _spec_with_cta(
        "study_detail",
        [
            {
                "id": "unrelated",
                "route": "/about",
                "title": "About",
                "sections": [
                    {
                        "id": "about-sec",
                        "component": "RichText",
                        "data": {"operationId": "other.list", "action": "list"},
                    }
                ],
            },
            {
                "id": "study_detail",
                "route": "/study/[id]",
                "title": "Study Detail",
                "sections": [
                    {
                        "id": "study-card",
                        "component": "FlashcardStudy",
                        "data": {"operationId": "deck.get", "action": "get", "params": {"id": "$route.id"}},
                    }
                ],
            },
        ],
    )
    fixed, notes = autofix_frontend_spec(spec)
    hero_content = fixed["pages"][0]["sections"][0]["content"]
    assert "cta" not in hero_content
    assert len(notes) == 1
    assert notes[0]["message"] == "Link to 'study_detail' (/study/[id]) was removed: a link cannot fill [id]"


def test_validator_hint_text_for_route_param_unbound():
    spec = _spec_with_cta(
        "study-detail",
        [
            {
                "id": "study",
                "route": "/study",
                "title": "Study",
                "sections": [{"id": "sec-1", "component": "RichText", "content": {"body": "text"}}],
            },
            {
                "id": "study-detail",
                "route": "/study/[id]",
                "title": "Study Detail",
                "sections": [{"id": "sec-2", "component": "RichText", "content": {"body": "text"}}],
            },
        ],
    )
    result = validate_frontend_spec_data(spec)
    assert not result.report.valid
    [issue] = [e for e in result.report.errors if e.code == "FE_ROUTE_PARAM_UNBOUND"]
    assert issue.hint == (
        "Link to a page without route parameters ('study'), "
        "or let a data section link each record to it (binding 'link')"
    )


def test_excerpt_builder():
    doc = {
        "project": {"name": "Test"},
        "pages": [
            {
                "id": "home",
                "sections": [{"id": "hero", "content": {"cta": {"page": "study"}}}],
            }
        ],
    }

    # 1. Path at root
    root_excerpt = build_excerpt(doc, "/")
    assert "target (/)" in root_excerpt
    assert "Test" in root_excerpt

    # 2. Nested path
    nested_excerpt = build_excerpt(doc, "/pages/0/sections/0/content/cta/page")
    assert "parent (/pages/0/sections/0/content/cta)" in nested_excerpt
    assert "target (/pages/0/sections/0/content/cta/page)" in nested_excerpt
    assert '"study"' in nested_excerpt

    # 3. Missing path
    missing_excerpt = build_excerpt(doc, "/pages/99/sections/0/missing")
    assert "parent (/pages)" in missing_excerpt


def test_interrupted_repair_recheck_succeeds_if_spec_is_valid(client, user_headers, tmp_path):
    """When a repair step ends with CLI error (stream dropped) but wrote a valid spec, re-check succeeds."""
    from tests.test_drafting import _create, _run

    req_text = "A simple store that sells coffee and tea online"
    draft_id = _create(client, user_headers, "dynamic", req_text)

    bad_frontend = _spec_with_cta(
        "non-existent-page",
        [
            {
                "id": "study",
                "route": "/study",
                "title": "Study",
                "sections": [{"id": "sec-1", "component": "RichText", "content": {"body": "text"}}],
            },
        ],
    )

    scenario = {
        "draft_frontend_spec": [FakeStep(write={"frontend-spec.json": json.dumps(bad_frontend)})],
        "repair_spec": [FakeStep(draft_fixture=True, status="cli_error", error_reason="crash")],
    }
    engine = FakeEngine(tmp_path, scenario)
    draft = _run(tmp_path, draft_id, engine=engine)
    print("VALIDATION:", draft["validation"])
    assert draft["status"] == "SUCCEEDED"
    assert draft["attempts"] == 1


def test_draft_with_bad_cta_autofixes_and_succeeds_with_zero_attempts(client, user_headers, tmp_path):
    """With the bad CTA, autofix runs before check_draft so the draft succeeds with attempts = 0."""
    from tests.test_drafting import _create, _run

    req_text = "A flashcard app to study decks online"
    draft_id = _create(client, user_headers, "dynamic", req_text)

    bad_frontend = _spec_with_cta(
        "study-detail",
        [
            {
                "id": "study",
                "route": "/study",
                "title": "Study",
                "sections": [{"id": "sec-1", "component": "RichText", "content": {"body": "text"}}],
            },
            {
                "id": "study-detail",
                "route": "/study/[id]",
                "title": "Study Detail",
                "sections": [{"id": "sec-2", "component": "RichText", "content": {"body": "text"}}],
            },
        ],
    )
    valid_backend = (EXAMPLES / "specs" / "two-entity.json").read_text()

    scenario = {
        "draft_frontend_spec": [
            FakeStep(
                write={
                    "frontend-spec.json": json.dumps(bad_frontend),
                    "backend-spec.json": valid_backend,
                    "notes.json": json.dumps({"assumptions": [], "unresolved": []}),
                }
            )
        ],
    }
    engine = FakeEngine(tmp_path, scenario)
    draft = _run(tmp_path, draft_id, engine=engine)

    assert draft["status"] == "SUCCEEDED"
    assert draft["attempts"] == 0
    cta_page = draft["frontend_spec"]["pages"][0]["sections"][0]["content"]["cta"]["page"]
    assert cta_page == "study"
    assert any("a link cannot fill [id]" in a["message"] for a in draft["assumptions"])
