"""Drafting a dynamic app (Story 22.2): one `draft_app@v2` call for the BackendSpec and the app outline; code
completes the outline from the BackendSpec, fixes what it can without a call, and writes the FrontendSpec."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, delete

from src.engines import EngineRegistry, PromptLibrary
from src.engines.fake_engine import FakeEngine, FakeStep, demo_scenario
from src.libs.database import db_session_manager
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.modules.shared.infrastructure.models import SpecDraftModel
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.checks.consistency import check_spec_pair
from src.orchestrator.drafting.app import OUTLINE_FILE, app_inputs, outline_notes
from src.orchestrator.drafting.drafts import DraftRunner
from src.orchestrator.frontend.app.outline import complete_outline, humanize, plural
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.integration.contract import build_contract
from src.orchestrator.store import JobStore

REPO = Path(__file__).parents[2]
EXAMPLES = REPO / "examples"
SNAPSHOTS = Path(__file__).parent / "fixtures" / "prompts"
PAIRS = {"flashcards": "flashcards", "two-entity": "project-tracker"}

pytestmark = pytest.mark.usefixtures("clean_redis")


@pytest.fixture
def cleanup_drafts():
    yield
    with Session(db_session_manager.engine) as session:
        session.exec(delete(SpecDraftModel))
        session.commit()


def _backend(name: str) -> dict:
    return validate_spec_data(json.loads((EXAMPLES / "specs" / f"{name}.json").read_text())).normalized


def _contract(backend: dict) -> dict:
    return build_contract(backend, build_plan(backend))


def _draft(client, headers, root: Path, text: str, scenario: dict | None = None) -> dict:
    response = client.post(
        "/api/v1/spec-drafts", json={"engine": "fake", "mode": "dynamic", "requirementText": text}, headers=headers
    )
    assert response.status_code == 202, response.text
    draft_id = response.json()["draftId"]
    engine = FakeEngine(root, scenario or demo_scenario(delay_s=0))
    runner = DraftRunner(EngineRegistry([engine], default="fake"), PromptLibrary(), JobStore(), root, "w-app", EXAMPLES)
    asyncio.run(runner.run(draft_id))
    return JobStore().draft(uuid.UUID(draft_id)).model_dump(mode="json")


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert text == path.read_text(), f"{name} changed: review, then rerun with UPDATE_SNAPSHOTS=1"


def _prompt(inline: bool) -> str:
    context = {
        "requirement_text": "A reading log: books I read, with a rating and notes.",
        "requirement_format": "text",
        "backend_schema_path": ".bga/backend-spec.schema.json",
        "backend_schema_digest_path": ".bga/backend-spec.schema.md",
        "backend_example_path": ".bga/examples/backend-spec.json",
        "output_backend_path": "backend-spec.json",
        "notes_path": "notes.json",
        "inline": inline,
        **app_inputs(EXAMPLES),
    }
    if inline:
        context |= {"backend_schema_digest": "<BackendSpec digest>", "backend_example": "{}"}
    return PromptLibrary().render("draft_app", "v2", **context).text


def _prompt_v3(inline: bool, requirement: str, version: str = "v3", **extra: object) -> str:
    from src.orchestrator.drafting.app import product_rows
    from src.orchestrator.frontend.app.design import archetype_candidates
    from src.orchestrator.frontend.app.recipes import recommended_looks, style_words

    rows = product_rows(requirement)
    context = {
        "requirement_text": requirement,
        "requirement_format": "text",
        "backend_schema_path": ".bga/backend-spec.schema.json",
        "backend_schema_digest_path": ".bga/backend-spec.schema.md",
        "backend_example_path": ".bga/examples/backend-spec.json",
        "output_backend_path": "backend-spec.json",
        "notes_path": "notes.json",
        "inline": inline,
        "archetype_candidates": ", ".join(archetype_candidates(requirement, [r["Product Type"] for r in rows])),
        "recommended_looks": recommended_looks(rows),
        "style_words": style_words(requirement),
        **app_inputs(EXAMPLES, design=True),
        **extra,
    }
    if inline:
        context |= {"backend_schema_digest": "<BackendSpec digest>", "backend_example": "{}"}
    return PromptLibrary().render("draft_app", version, **context).text


def test_draft_app_v9_prompt_says_where_records_are_made_only_when_the_requirement_does():
    """Epic 32 (Story 32.7): v8 plus one rule: code places where each record is made by the app's kind; the outline's
    `entities.<Entity>.create` (`onRecord`, `onOpen`, `page`) only where the requirement says otherwise."""
    from src.orchestrator.frontend.app.design import design_choices

    requirement = "A recipe community: cooks post recipes, others save them and leave reviews after cooking."
    choices = design_choices(["feed", "catalogue"])
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v9", design_choices=choices)
        _snapshot(f"draft_app.v9{'.inline' if inline else ''}.md", text)
        assert "write `create` only when the requirement says otherwise" in text
        v8 = _prompt_v3(inline, requirement, version="v8", design_choices=choices)
        assert 0 < len(text) - len(v8) < 600


def test_draft_app_v8_prompt_keeps_what_people_do_out_of_a_status():
    """A real draft (2026-11-09, a TikTok-like feed) made "viewed" a video status moved by the viewer's own action,
    next to a visibility policy "viewers see only published videos": a video any viewer opened left every viewer's
    feed. v8 is v7 plus one rule: a status is the record's state; what people do with a record is an interaction
    entity or a counter, never a status value or a transition."""
    from src.orchestrator.frontend.app.design import design_choices

    requirement = "A short video app: creators post clips, viewers watch, like and comment on them."
    choices = design_choices(["feed", "catalogue"])
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v8", design_choices=choices)
        _snapshot(f"draft_app.v8{'.inline' if inline else ''}.md", text)
        assert "What a person does with a" in text and "never a status value or a transition" in text
        assert "named after that person's role" in text
        v7 = _prompt_v3(inline, requirement, version="v7", design_choices=choices)
        assert 0 < len(text) - len(v7) < 800


def test_draft_app_v7_prompt_lists_the_registry_choices():
    """Epic 30 (Story 30.2): the design brief's choice lists come from the design plugin registry, only the candidates
    for the ranked archetypes; a new plugin folder is offered without a prompt change."""
    from src.modules.shared.domain.frontend_spec.design_registry import registry
    from src.orchestrator.frontend.app.design import design_choices

    requirement = "A plant shop: customers browse plants by collection and order them; the owner manages stock."
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v7", design_choices=design_choices(["storefront", "catalogue"]))
        _snapshot(f"draft_app.v7{'.inline' if inline else ''}.md", text)
        for kind in ("shell", "list-view", "detail-view", "filters", "home", "recipe"):
            for plugin in registry().candidates(kind, "storefront"):
                assert f"`{plugin.name}` (" in text, (kind, plugin.name)
        assert "`rail`" not in text, "a workspace-only shell is not offered to a storefront"
        v6 = _prompt_v3(inline, requirement, version="v6")
        assert len(text) <= len(v6) * 1.10, "Story 30.7: the prompt stays within 10% of v6 whatever the registry's size"


def test_draft_app_v6_prompt_names_the_media_fields():
    """Epic 29 (Story 29.5): v5 plus the media field types and how subtitles in several languages are written."""
    requirement = "A lesson library: video lessons with captions in two languages and a podcast of audio episodes."
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v6")
        _snapshot(f"draft_app.v6{'.inline' if inline else ''}.md", text)
        assert "`video`" in text and "`subtitles` field and a `language` field" in text
        v5 = _prompt_v3(inline, requirement, version="v5")
        assert 0 < len(text) - len(v5) < 1200


def test_draft_app_v5_prompt_asks_for_the_requirements_own_look():
    """2026-11-07: v4 plus one bullet: what the requirement says about the look, as values code applies."""
    requirement = "A pet adoption app. Look and feel: photo-first, a bright orange accent on white."
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v5")
        _snapshot(f"draft_app.v5{'.inline' if inline else ''}.md", text)
        assert "the requirement comes before\n  the design data" in text
        v4 = _prompt_v3(inline, requirement, version="v4")
        assert 0 < len(text) - len(v4) < 1000


def test_draft_app_v4_prompt_adds_the_access_rules():
    """Epic 25: v3 plus one paragraph on private records, owner actions, status through actions, staff creating for
    a person; the rest of the prompt is v3's."""
    requirement = "A video library for our training videos, in channels."
    for inline in (False, True):
        text = _prompt_v3(inline, requirement, version="v4")
        _snapshot(f"draft_app.v4{'.inline' if inline else ''}.md", text)
        assert "are private\n  to that person unless the requirement says otherwise" in text
        assert "ownership **without** `bypassRoles`" in text
        v3 = _prompt_v3(inline, requirement)
        assert len(text) - len(v3) < 1200


def test_draft_app_v3_prompt_asks_for_the_brief():
    """Story 23.6: the design brief, areas, code's candidates, the data's looks and the requirement's own words."""
    requirement = "A video library for our training videos, in channels. Make it feel like liquid glass."
    for inline in (False, True):
        text = _prompt_v3(inline, requirement)
        _snapshot(f"draft_app.v3{'.inline' if inline else ''}.md", text)
        assert "type AppDesign = {" in text and "type AppArea = {" in text
        assert "## The design brief" in text and "## Areas" in text
        assert "Code ranked these for this requirement: catalogue" in text
        assert "**The requirement asks for glass: the first look must be that.**" in text
        assert text.count("DevPulse, a news feed") == 1 and text.count("Gather, event ticketing") == 1
    plain = _prompt_v3(False, "A reading log: books I read, with a rating and notes.")
    assert "The requirement asks for" not in plain


def test_draft_app_prompt_snapshots():
    """The prompt carries the outline digest and both examples, and no layout, colour or font instructions."""
    for inline in (False, True):
        text = _prompt(inline)
        _snapshot(f"draft_app.v2{'.inline' if inline else ''}.md", text)
        assert "type AppOutline = {" in text and "type AppEntity = {" in text and "app-outline.json" in text
        assert text.count("Flashcards (") == 1 and text.count("Project tracker (") == 1
        assert text.count("Workshop bookings (") == 1, "an example with sign-in, roles and the plugins (22.8)"
        assert "never add an entity for the people who sign in" in text and "Do not add authentication" not in text
        assert "FrontendSpec" not in text and "direction" not in text.lower() and "Tailwind" not in text
    assert '"files"' in _prompt(True) and '"files"' not in _prompt(False)


@pytest.mark.parametrize("backend_name", sorted(PAIRS))
@pytest.mark.parametrize("kind", ["minimal", "full"])
def test_minimal_and_full_outlines_make_a_valid_pair(backend_name, kind):
    backend = _backend(backend_name)
    contract = _contract(backend)
    full = json.loads((EXAMPLES / "app-outlines" / f"{PAIRS[backend_name]}.json").read_text())
    raw = full if kind == "full" else {"name": full["name"], "nav": full["nav"][:1]}
    outline, notes = complete_outline(raw, backend, contract)
    assert notes == [], notes
    assert set(outline["entities"]) == {entity["name"] for entity in backend["entities"]}
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    spec = app_frontend_spec(backend, outline, {"colorScheme": "light-dark"}, contract).spec
    result = validate_frontend_spec_data(spec)
    assert result.report.valid, result.report.errors
    assert check_spec_pair(result.normalized, backend) == []  # Story 22.3: every operation on a screen
    assert result.normalized["app"]["entities"] == outline["entities"]
    assert len(result.normalized["app"]["dashboard"]) == len(outline["dashboard"])


def test_code_fills_the_outline_from_the_backend_spec():
    backend = _backend("flashcards")
    outline, _ = complete_outline({"name": "Words"}, backend, _contract(backend))
    card = outline["entities"]["Card"]
    assert card["label"] == "Card" and card["plural"] == "Cards" and card["displayField"] == "front"
    assert card["listFields"][:2] == ["front", "deckId"] and len(card["listFields"]) <= 5
    assert card["fieldLabels"]["deckId"] == "Deck", "a foreign key is named after its parent"
    assert "id" not in card["detailFields"] and card["listStyle"] == "table"
    assert outline["entities"]["ReviewLog"]["plural"] == "Review logs"
    assert [item["entity"] for item in outline["nav"]] == ["Deck"], "children are reached from their parent"
    assert outline["home"] == "dashboard" and outline["dashboard"] == []
    assert humanize("dueDate") == "Due date" and plural("Category") == "Categories"


def test_outline_errors_are_fixed_by_code_with_a_note():
    backend = _backend("flashcards")
    raw = {
        "name": "Words",
        "nav": [{"entity": "Deck"}, {"entity": "Nope"}, {"entity": "deck lower"}],
        "home": "Ghost",
        "entities": {
            "Card": {"listFields": ["front", "bogus", "back", "dueDate", "ease", "intervalDays"], "listStyle": "grid"},
            "Ghost": {},
        },
        "dashboard": [
            {"label": "Cards", "entity": "Card"},
            {"label": "Avg front", "entity": "Card", "fn": "avg", "field": "front"},
            {"label": "By deck", "kind": "bar", "entity": "Card"},
        ],
        "layout": "two columns",
    }
    outline, notes = complete_outline(raw, backend, _contract(backend))
    paths = {note["path"] for note in notes}
    assert {
        "/app/nav/1",
        "/app/nav/2",
        "/app/home",
        "/app/entities/Card/listFields",
        "/app/entities/Card/listStyle",
        "/app/entities/Ghost",
        "/app/dashboard/1",
        "/app/dashboard/2",
        "/app/layout",
    } <= paths
    card = outline["entities"]["Card"]
    assert card["listFields"] == ["front", "back", "dueDate", "ease"] and card["listStyle"] == "table"
    assert outline["home"] == "dashboard" and [item["label"] for item in outline["dashboard"]] == ["Cards"]
    assert "Ghost" not in outline["entities"]


def test_the_models_outline_notes_point_into_the_frontend_spec():
    notes = [
        {"spec": "frontend", "path": "/nav/0", "message": "a"},
        {"spec": "frontend", "path": "", "message": "b"},
        {"spec": "backend", "path": "/entities/0", "message": "c"},
        {"spec": "frontend", "path": "/app/home", "message": "d"},
    ]
    assert [note["path"] for note in outline_notes(notes)] == ["/app/nav/0", "/app", "/entities/0", "/app/home"]


def test_an_app_draft_is_one_call_and_bad_outlines_cost_no_repair(
    client, user_headers, tmp_path, monkeypatch, cleanup_drafts
):
    backend = (EXAMPLES / "specs" / "flashcards.json").read_text()
    bad = {"name": "Words", "nav": [{"entity": "Nope"}], "entities": {"Card": {"listStyle": "grid"}}}
    notes = {"assumptions": [{"spec": "frontend", "path": "/nav", "message": "Decks first"}], "unresolved": []}
    scenario = {
        "draft_app": [
            FakeStep(
                write={"backend-spec.json": backend, OUTLINE_FILE: json.dumps(bad), "notes.json": json.dumps(notes)}
            )
        ]
    }
    draft = _draft(client, user_headers, tmp_path, "Vocabulary decks to learn new words", scenario)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert [call["prompt"] for call in draft["usage"]["calls"]] == ["draft_app@v9"]
    messages = {note["path"]: note["message"] for note in draft["assumptions"]}
    assert messages["/app/nav"] == "Decks first", "the model's own notes point into the FrontendSpec"
    assert "names no entity" in messages["/app/nav/0"] and "/app/entities/Card/listStyle" in messages
    assert [item["entity"] for item in draft["frontend_spec"]["app"]["nav"]] == ["Deck"]


def test_an_invalid_backend_spec_gets_one_repair(client, user_headers, tmp_path, monkeypatch, cleanup_drafts):
    good = (EXAMPLES / "specs" / "two-entity.json").read_text()
    broken = {**json.loads(good), "specVersion": "9.9"}
    outline = (EXAMPLES / "app-outlines" / "project-tracker.json").read_text()
    scenario = {
        "draft_app": [FakeStep(write={"backend-spec.json": json.dumps(broken), OUTLINE_FILE: outline})],
        "repair_spec": [FakeStep(write={"backend-spec.json": good})],
    }
    draft = _draft(client, user_headers, tmp_path, "A team's projects and their tasks", scenario)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert [call["prompt"] for call in draft["usage"]["calls"]] == ["draft_app@v9", "repair_spec@v3"]
    assert draft["frontend_spec"]["app"]["tagline"] == "Projects and their tasks, in one place"


def test_a_draft_without_an_outline_still_makes_an_app(client, user_headers, tmp_path, monkeypatch, cleanup_drafts):
    scenario = {"draft_app": [FakeStep(write={"backend-spec.json": (EXAMPLES / "specs" / "shop.json").read_text()})]}
    draft = _draft(client, user_headers, tmp_path, "A small store with products by category", scenario)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert any(note["path"] == "/app" for note in draft["assumptions"])
    assert set(draft["frontend_spec"]["app"]["entities"]) >= {"Category", "Product"}


def test_the_fake_engine_drafts_the_example_outline(client, user_headers, tmp_path, monkeypatch, cleanup_drafts):
    draft = _draft(client, user_headers, tmp_path, "A flashcard app to learn vocabulary")
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    app = draft["frontend_spec"]["app"]
    assert app["name"] == "Flashcards" and app["entities"]["Deck"]["listStyle"] == "cards"
    assert [item["label"] for item in app["dashboard"]][:2] == ["Decks", "Cards"]


def test_a_real_antigravity_draft_becomes_an_app(client, user_headers, tmp_path, monkeypatch, cleanup_drafts):
    """Story 22.2's live check (Antigravity, 2026-11-05): its outline and BackendSpec, replayed. Its one slip, a date
    default of `today`, is fixed by code (the repair round did not fix it live); its own aggregates are reused."""
    recorded = Path(__file__).parent / "fixtures" / "drafts" / "plant-care-antigravity"
    files = {name: (recorded / name).read_text() for name in ("backend-spec.json", OUTLINE_FILE, "notes.json")}
    draft = _draft(
        client,
        user_headers,
        tmp_path,
        (recorded / "requirement.md").read_text(),
        {"draft_app": [FakeStep(write=files)]},
    )
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert [call["prompt"] for call in draft["usage"]["calls"]] == ["draft_app@v9"], "no repair round"
    assert any("default 'today' is written 'now'" in note["message"] for note in draft["assumptions"])
    assert draft["validation"]["pair"]["errors"] == [] and draft["validation"]["pair"]["warnings"] == []
    spec = draft["frontend_spec"]
    home = next(page for page in spec["pages"] if page["route"] == "/")
    figures = [s["data"]["operationId"] for s in home["sections"] if s["component"] == "AppDashboard"]
    assert figures[:2] == ["plant.countDueToday", "watering.countThisWeek"], "the model's aggregates, not new ones"
    navigation = spec["layout"]["header"]["navigation"]
    assert navigation[-1] == {"label": "Plants that need water today", "page": "plants-due"}
    assert draft["unresolved"] and all(note["spec"] in ("backend", "frontend", None) for note in draft["unresolved"])


def test_an_app_draft_reads_the_example_of_every_plugin(tmp_path):
    """Story 22.8 (the soccer run on Antigravity): an app draft is shown how sign-in, roles, ownership, rules, uploads,
    payments and links are written; v1 told the model to leave sign-in out, so a requirement with players and staff
    left it stuck between the two."""
    from src.modules.shared.domain.entities import SpecDraftEntity
    from src.modules.shared.domain.enums import GenerationMode, SpecSource
    from src.orchestrator.drafting.drafts import write_inputs

    draft = SpecDraftEntity(
        owner_id=uuid.uuid4(),
        source=SpecSource.REQUIREMENT,
        mode=GenerationMode.DYNAMIC,
        engine="fake",
        requirement_text="Players book a pitch and pay; staff confirm bookings.",
        requirement_format="text",
    )
    write_inputs(tmp_path, draft, EXAMPLES, app=True)
    example = json.loads((tmp_path / ".bga" / "examples" / "backend-spec.json").read_text())
    assert example["auth"]["roles"] and example["policies"] and example["rules"] and example["payments"]
    backend = SpecDraftEntity(**{**draft.model_dump(), "mode": GenerationMode.BACKEND})
    write_inputs(tmp_path / "backend", backend, EXAMPLES)
    assert "auth" not in json.loads((tmp_path / "backend/.bga/examples/backend-spec.json").read_text())


def test_a_relationship_through_a_persons_field_is_dropped():
    """Story 32.8 (Pocket Chefs, gen_01M6ZRH1XQZZHC6RXSM5BFTJ21): the draft related `Recipe` to `Recipe` through
    `cookId`; the seed filled each recipe's cook with recipe ids, no demo cook owned one, and the update's success
    scenario answered 404 on the mocks. A foreign key named after a role points at a person: the relationship is
    dropped (a note), the field becomes the person field it names and the cook's recipes are a demo cook's."""
    import copy

    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.drafting.access import secure_access
    from src.orchestrator.drafting.app import fix_person_relationships
    from src.orchestrator.integration.contract import build_contract, contract_operations

    raw = json.loads((Path(__file__).parent / "fixtures" / "specs" / "pocket-chefs-cook-relation.json").read_text())
    data = copy.deepcopy(raw)
    notes = fix_person_relationships(data)
    assert [n["message"] for n in notes] == [
        "Recipe.cookId names a cook (a person), not a Recipe: the relationship Recipe → Recipe was dropped"
    ]
    assert all(rel["to"] != rel["from"] for rel in data["relationships"]), "the parent relationships stay"
    assert len(data["relationships"]) == len(raw["relationships"]) - 1
    secure_access(data)
    spec = validate_spec_data(data).normalized
    contract = build_contract(spec, build_plan(spec))
    fixtures = contract["x-bga"]["fixtures"]
    cooks = {u["id"] for u in fixtures["User"] if u.get("role") == "cook"}
    assert all(row["cookId"] in cooks for row in fixtures["Recipe"]), "each recipe is a demo cook's"
    update = contract_operations(contract)["recipe.update"]["operation"]["x-bga"]
    success = next(s for s in update["scenarios"] if s["name"] == "success")
    runs_as = success.get("user") or contract["x-bga"]["auth"]["login"]["body"]["email"]  # else the default login
    owner = next(r["cookId"] for r in fixtures["Recipe"] if r["id"] == success["params"]["id"])
    assert next(u["id"] for u in fixtures["User"] if u["email"] == runs_as) == owner, "it edits its own recipe"
    plain = {"auth": {"roles": ["member"]}, "relationships": [{"from": "Deck", "to": "Card", "foreignKey": "deckId"}]}
    assert fix_person_relationships(plain) == [], "a parent named after no role stays"
