"""Screens from the contract (Story 22.3): the screen planner writes every page, form and binding of an app from the
completed outline and the contract; every operation is on a screen or an action, and the pair check passes."""

import json
import os
import sys
from pathlib import Path

import pytest

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import uncovered_operations, validate_frontend_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.checks.consistency import check_spec_pair
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.integration.contract import build_contract

sys.path.insert(0, str(Path(__file__).parent))

EXAMPLES = Path(__file__).parents[2] / "examples"
SNAPSHOTS = Path(__file__).parent / "fixtures" / "app-screens"
APPS = {  # BackendSpec example → its outline (None: what code fills from the BackendSpec alone)
    "flashcards": "flashcards",
    "two-entity": "project-tracker",
    "shop": None,
    "task-management": None,
    "workshop-bookings": "workshop-bookings",  # Story 22.7: every plugin
    # Story 23.1: the golden apps, real Gemini drafts (Story 23.0)
    **{
        name: name
        for name in (
            "news-feed",
            "video-library",
            "learning-platform",
            "agency-projects",
            "clinic-bookings",
            "plant-shop",
            "event-tickets",
        )
    },
}


def _plan(backend: dict, raw_outline: dict) -> tuple[dict, dict, dict, object]:
    outline, _ = complete_outline(raw_outline, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    assert validate_spec_data(backend).report.valid
    contract = build_contract(backend, build_plan(backend))
    return backend, outline, contract, app_frontend_spec(backend, outline, {"colorScheme": "light-dark"}, contract)


def _example(name: str) -> tuple[dict, dict]:
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / f"{name}.json").read_text())).normalized
    outline_name = APPS[name]
    raw = json.loads((EXAMPLES / "app-outlines" / f"{outline_name}.json").read_text()) if outline_name else {}
    return backend, raw


def _bindings(spec: dict) -> dict:
    """What calls what: per page, each section's component and binding; the forms; the navigation."""
    pages = {
        page["route"]: [
            {key: section[key] for key in ("id", "component", "data", "form") if key in section}
            | {"actions": [a["id"] for a in (section.get("content") or {}).get("actions") or []]}
            for section in page["sections"]
        ]
        for page in spec["pages"]
    }
    forms = {
        form["id"]: {
            "operationId": form["operationId"],
            "fields": [
                field["name"] + ("=" + field["value"] if field.get("hidden") else "") for field in form["fields"]
            ],
        }
        for form in spec.get("forms") or []
    }
    return {"pages": pages, "forms": forms, "navigation": spec["layout"]["header"]["navigation"]}


@pytest.mark.parametrize("name", sorted(APPS))
def test_every_operation_is_on_a_screen_and_the_pair_check_passes(name):
    backend, raw = _example(name)
    backend, _, contract, screens = _plan(backend, raw)
    result = validate_frontend_spec_data(screens.spec)
    assert result.report.valid, result.report.errors
    assert check_spec_pair(result.normalized, backend) == [], "no errors and no warnings (FE_FIELD_SOURCE included)"
    assert uncovered_operations(screens.spec, contract) == []
    assert screens.unresolved == [], "nothing unplaced"
    prefixes = [area["prefix"] for area in screens.spec["app"].get("areas") or [] if area["prefix"] != "/"]
    legacy = [p["route"] for p in screens.spec["pages"] if p["route"].startswith("/manage")
              and not any(p["route"].startswith(prefix) for prefix in prefixes)]  # fmt: skip
    assert not legacy, "no Manage area (an area of the brief may have its own prefix, Story 23.10)"


@pytest.mark.parametrize("name", sorted(APPS))
def test_the_planner_is_deterministic_and_snapshotted(name):
    backend, raw = _example(name)
    first = _bindings(_plan(backend, raw)[3].spec)
    assert first == _bindings(_plan(backend, raw)[3].spec)
    snapshot = SNAPSHOTS / f"{name}.json"
    text = json.dumps(first, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(text)
    assert text == snapshot.read_text(), f"{name} screens changed: review, then rerun with UPDATE_SNAPSHOTS=1"


def test_a_child_is_created_from_its_parent_with_the_parent_from_the_route():
    backend, raw = _example("flashcards")
    spec = _plan(backend, raw)[3].spec
    forms = {form["id"]: form for form in spec["forms"]}
    deck_field = next(f for f in forms["card_create_in_deck"]["fields"] if f["name"] == "deckId")
    assert deck_field == {"name": "deckId", "type": "string", "hidden": True, "value": "$route.id", "required": True}
    assert "card_create" not in forms, "no standalone create that would ask for a deck id"
    deck = next(page for page in spec["pages"] if page["route"] == "/decks/[id]")
    tabs = {s["id"]: s for s in deck["sections"] if (s.get("content") or {}).get("tab")}
    assert tabs["cards-tab"]["data"]["params"] == {"deckId": "$route.id"}
    assert tabs["cards-tab"]["content"]["create"]["page"] == "decks-id-cards-new"
    assert tabs["card-list-due-tab"]["data"]["operationId"] == "card.listDue", "a custom list filtered by its parent"
    assert "deckId" not in tabs["cards-tab"]["data"]["fields"], "the parent is the page"
    for form in spec["forms"]:  # no form asks for an id: a parent is the route's or picked by name (22.6)
        assert all(f.get("hidden") or f.get("reference") for f in form["fields"] if f["name"].endswith("Id")), form[
            "id"
        ]
    move = next(f for f in forms["card_update"]["fields"] if f["name"] == "deckId")
    assert move["reference"] == {
        "entity": "Deck",
        "listOperation": "deck.list",
        "detailOperation": "deck.get",
        "labelField": "name",
        "limitParam": "limit",
        "pageSize": 50,
    }
    assert move["label"] == "Deck" and not move["required"]


def test_custom_operations_become_actions_and_lists():
    backend, raw = _example("flashcards")
    spec = _plan(backend, raw)[3].spec
    card = next(page for page in spec["pages"] if page["route"] == "/cards/[id]")
    detail = card["sections"][0]
    review = next(a for a in detail["content"]["actions"] if a["id"] == "review")
    assert review["operationId"] == "card.review" and review["form"] == "card_review", "a body opens a dialog"
    assert review["params"] == {"id": "$route.id"}
    rows = next(page for page in spec["pages"] if page["route"] == "/cards")["sections"][0]["content"]["actions"]
    assert [a["id"] for a in rows] == ["view", "edit", "delete"], "an action with a body is not a row action"
    assert next(a for a in rows if a["id"] == "delete")["confirm"]
    deck = next(page for page in spec["pages"] if page["route"] == "/decks/[id]")
    assert any(s["data"]["operationId"] == "deck.stats" for s in deck["sections"]), "a record's summary"
    assert {"label": "Due cards", "page": "cards-due"} in spec["layout"]["header"]["navigation"]


def test_dashboard_figures_are_aggregates_added_by_code():
    backend, raw = _example("two-entity")
    extended, outline, _, screens = _plan(backend, raw)
    added = {op["operationId"]: op for op in extended["operations"] if op["type"] == "aggregate"}
    assert added["task.countWhereStatusTodo"]["aggregate"] == {"fn": "count", "filters": {"status": "TODO"}}
    assert added["task.countByStatus"]["aggregate"] == {"fn": "count", "groupBy": "status"}
    home = next(page for page in screens.spec["pages"] if page["route"] == "/")
    figures = [s for s in home["sections"] if s["component"] == "AppDashboard"]
    assert [f["data"]["operationId"] for f in figures] == [
        "project.count",
        "task.countWhereStatusTodo",
        "task.countByStatus",
    ]
    assert figures[2]["content"]["kind"] == "bar"
    assert "operationId" not in json.dumps(screens.spec["app"]), "the outline carries no bindings"


def test_period_figures_count_from_the_creation_date():
    backend, raw = _example("flashcards")
    extended = _plan(backend, raw)[0]
    week = next(op for op in extended["operations"] if op["operationId"] == "reviewLog.countThisWeek")
    assert week["aggregate"] == {"fn": "count", "period": "week", "dateField": "reviewedAt"}


def test_a_record_created_from_a_parent_that_does_not_list_it():
    """`cartItem.create` needs a product, but the cart list does not filter by product: an 'Add' link on the
    product's page opens a form that takes the product from the route."""
    backend, raw = _example("shop")
    spec = _plan(backend, raw)[3].spec
    product = next(page for page in spec["pages"] if page["route"] == "/products/[id]")
    add = product["sections"][0]["content"]["actions"][0]
    assert add == {
        "id": "add-cart-items",
        "label": "Add cart item",
        "kind": "link",
        "page": "products-id-cart-items-new",
        "params": {"id": "$route.id"},
    }
    navigation = [link["page"] for link in spec["layout"]["header"]["navigation"]]
    assert navigation == ["home", "categories", "products", "cart-items", "contact-messages-new"]


def test_a_second_parent_is_picked_by_name_and_the_pair_check_passes():
    """Story 22.6: a booking created from its room's page takes the room from the route; the guest (a second parent the
    route cannot give) is a picker on the guests' list, never an id input, so `FE_FIELD_SOURCE` (an error in apps
    now) does not fire."""
    import test_concurrency_rules

    backend = validate_spec_data(test_concurrency_rules.booking_spec(Path("/tmp"))).normalized
    backend, _, _, screens = _plan(backend, {})
    assert not screens.unresolved
    pickers = [f for form in screens.spec["forms"] for f in form["fields"] if f.get("reference")]
    assert pickers and all(f["reference"]["listOperation"].endswith(".list") for f in pickers)
    issues = check_spec_pair(validate_frontend_spec_data(screens.spec).normalized, backend)
    assert not issues


def test_a_typed_reference_is_an_error_in_an_app_and_a_warning_in_the_legacy_flow():
    backend, raw = _example("flashcards")
    backend, _, _, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec).normalized
    for form in spec["forms"]:
        for field in form["fields"]:
            field.pop("reference", None)  # a picker taken away: the user would type a deck id
    issues = [i for i in check_spec_pair(spec, backend) if i.code == "FE_FIELD_SOURCE"]
    assert issues and all(i.severity == "error" for i in issues)
    legacy = {**spec, "project": {**spec["project"], "flow": None}}
    issues = [i for i in check_spec_pair(legacy, backend) if i.code == "FE_FIELD_SOURCE"]
    assert issues and all(i.severity == "warning" for i in issues)


@pytest.mark.parametrize("name", sorted(APPS))
def test_the_app_plan_has_a_route_per_page_and_a_sidebar(name):
    backend, raw = _example(name)
    _, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec).normalized
    plan = plan_frontend(spec, contract)
    assert plan["rendering"] == "app" and plan["rendererGaps"] == []
    assert [route["route"] for route in plan["routes"]] == [page["route"] for page in screens.spec["pages"]]
    if (screens.spec["app"].get("home") or "dashboard") == "dashboard":  # the completed outline's (a brief decides)
        assert plan["app"]["nav"][0] == {"label": "Dashboard", "page": "home", "icon": "LayoutDashboard"}
    else:  # an app that opens on a list (Story 23.1): that list first; its figures on a dashboard page of their own
        assert plan["app"]["nav"][0]["label"] != "Dashboard"
        if raw.get("dashboard"):
            assert {"label": "Dashboard", "page": "dashboard", "icon": "LayoutDashboard"} in plan["app"]["nav"]


def test_a_real_antigravity_draft_plans_cleanly():
    """Story 22.3's live check (Antigravity, 2026-11-05, "Bike Shed"): one call, no repair; replayed here. Its
    BackendSpec already has the dashboard's aggregates (written by code live), so code adds none."""
    recorded = Path(__file__).parent / "fixtures" / "drafts" / "bike-shed-antigravity"
    backend = validate_spec_data(json.loads((recorded / "backend-spec.json").read_text())).normalized
    raw = json.loads((recorded / "app-outline.json").read_text())
    extended, outline, contract, screens = _plan(backend, raw)
    assert extended["operations"] == backend["operations"], "the aggregates are found, not added again"
    spec = validate_frontend_spec_data(screens.spec)
    assert spec.report.valid and check_spec_pair(spec.normalized, extended) == []
    assert uncovered_operations(screens.spec, contract) == [] and screens.unresolved == []
    spent = next(item for item in outline["dashboard"] if item["label"] == "Spent this year")
    assert spent["operationId"] == "service.sumCostThisYear" and spent["dateField"] == "date"
    routes = [page["route"] for page in screens.spec["pages"]]
    assert "/bikes/[id]/services/new" in routes and "/services/new" not in routes


KIT = Path(__file__).parents[1] / "templates" / "nextjs_overlay" / "files" / "dynamic" / "app" / "src" / "components"
KIT = KIT / "app"


def test_the_kit_renders_every_app_section():
    """Story 22.4: each app section the planner writes has its kit component, picked by `AppSection`; the plugins'
    sections (Story 22.7) through their slots, which the plugins' frontend files fill."""
    from src.modules.shared.domain.frontend_spec.app import APP_SECTIONS
    from src.orchestrator.frontend.app.files import PLUGIN_SLOTS

    switch = (KIT / "AppSection.tsx").read_text()
    slots = {name for names in PLUGIN_SLOTS.values() for name in names}
    for name in APP_SECTIONS:
        assert f'case "{name}":' in switch, name
        assert (KIT / f"{name}.tsx").is_file() or name in slots, name


def test_an_app_scaffolds_the_kit_and_its_data(tmp_path):
    from src.orchestrator.frontend.scaffold import scaffold_frontend

    backend, raw = _example("flashcards")
    _, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec).normalized
    plan = plan_frontend(spec, contract)
    assert {"table", "dropdown-menu", "alert-dialog", "dialog", "tabs", "chart", "breadcrumb", "empty"} <= set(
        plan["shadcn"]
    )
    scaffold_frontend(tmp_path, plan, spec, contract)
    for name in ("AppList", "AppDetail", "AppForm", "AppDashboard", "AppActions", "RecordActions", "FieldValue"):
        assert (tmp_path / "src" / "components" / "app" / f"{name}.tsx").is_file(), name
    data = json.loads((tmp_path / "src/content/app.json").read_text())
    card = data["entities"]["Card"]
    assert card["references"]["deckId"] == {"summary": "deck", "entity": "Deck", "href": "/decks/[id]"}
    assert card["fields"]["dueDate"] == {"type": "date"} and card["fields"]["deck"] == {"type": "summary"}
    assert card["listOperation"] == "card.list" and data["entities"]["Deck"]["listOperation"] == "deck.list"
    assert data["routes"]["decks-id-cards-new"] == "/decks/[id]/cards/new" and data["density"] == "comfortable"
    assert data["errors"]["deck.create"][0]["code"] == "VALIDATION_ERROR"
    assert data["forms"]["card_update"]["load"] == {"operationId": "card.get", "params": {"id": "$route.id"}}
    schemas = (tmp_path / "src/components/app/form-schemas.ts").read_text()
    assert '"card_create_in_deck": { schema: cardCreateInDeckSchema' in schemas


def test_custom_and_aggregate_queries_have_their_own_cache_keys():
    """Two figures of one resource with the same parameters (`task.countByStatus`, `task.countWhereStatusTodo`) and a
    custom list beside the CRUD list (`card.listDue`) must not share a React Query cache entry (seen in 22.4)."""
    from src.orchestrator.frontend.codegen import bindings_ts, queries_ts

    backend, raw = _example("two-entity")
    _, _, contract, _ = _plan(backend, raw)
    bindings = bindings_ts(contract)
    assert '"task.countByStatus": (params) => [...taskKeys.all, "task.countByStatus", params] as const' in bindings
    assert '"task.list": (params) => taskKeys.list(params)' in bindings
    backend, raw = _example("flashcards")
    _, _, contract, _ = _plan(backend, raw)
    assert 'queryKey: [...cardKeys.all, "card.listDue", params] as const' in queries_ts(contract)


@pytest.mark.parametrize("name", sorted(APPS))
def test_attaching_an_app_spec_changes_none_of_its_links(name):
    """A generation runs `autofix_frontend_spec` on the specs it attaches. It once re-checked a link without the link's
    own `params` and pointed every record link (view, edit, add a child) at the list page (live Pantry run, 22.4)."""
    import copy

    from src.modules.shared.domain.frontend_spec.autofix import autofix_frontend_spec

    backend, raw = _example(name)
    spec = _plan(backend, raw)[3].spec
    fixed, notes = autofix_frontend_spec(copy.deepcopy(spec))
    assert fixed["pages"] == spec["pages"] and notes == []


def test_the_dashboard_never_passes_its_cap_and_every_aggregate_has_a_screen():
    """Story 25.1 (F5): aggregates the draft wrote that no dashboard item names join the dashboard while there is room;
    the rest leave the BackendSpec with a note, so the FrontendSpec stays valid and coverage holds."""
    backend, raw = _example("two-entity")
    extra = [
        ("task.countDone", {"fn": "count", "filters": {"status": "DONE"}}),
        ("task.countInProgress", {"fn": "count", "filters": {"status": "IN_PROGRESS"}}),
        ("task.sumPriority", {"fn": "sum", "field": "priority"}),
        ("task.avgPriority", {"fn": "avg", "field": "priority"}),
        ("task.maxPriority", {"fn": "max", "field": "priority"}),
    ]
    spec = json.loads((EXAMPLES / "specs" / "two-entity.json").read_text())
    spec["operations"] += [
        {
            "operationId": op_id,
            "type": "aggregate",
            "entity": "Task",
            "method": "GET",
            "summary": op_id,
            "path": f"/tasks/aggregate/{op_id.split('.')[1].lower()}",
            "aggregate": aggregate,
        }
        for op_id, aggregate in extra
    ]
    result = validate_spec_data(spec)
    assert result.report.valid, result.report.errors
    extended, outline, _, screens = _plan(result.normalized, raw)
    assert len(outline["dashboard"]) == 6, "3 named + 3 of the 5 unnamed aggregates"
    aggregates = {op["operationId"] for op in extended["operations"] if op["type"] == "aggregate"}
    on_dashboard = {item["operationId"] for item in outline["dashboard"]}
    assert aggregates == on_dashboard, "an aggregate without a screen left the BackendSpec"
    assert validate_frontend_spec_data(screens.spec).report.valid
    assert uncovered_operations(screens.spec, build_contract(extended, build_plan(extended))) == []


def test_a_create_with_nothing_to_fill_in_is_a_button_on_the_list():
    """A recorded Antigravity draft (2026-11-09, a TikTok-like feed): `FeedSession` is created with no field a
    viewer fills in (the owner from the signed-in user, the status and date defaulted) and listed. The list linked
    "New feed" to a create page that was never planned (a form with no field is no form), so the FrontendSpec was
    invalid (`FE_UNKNOWN_PAGE`). Such a create is a button in the list page's actions; a create link to a page that
    does not exist is dropped in any case."""
    recorded = Path(__file__).parent / "fixtures" / "drafts" / "tiktok-feed-sessions"
    backend = validate_spec_data(json.loads((recorded / "backend-spec.json").read_text())).normalized
    raw = json.loads((recorded / "app-outline.json").read_text())
    extended, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec)
    assert spec.report.valid, [e.message for e in spec.report.errors]
    assert check_spec_pair(spec.normalized, extended) == [] and uncovered_operations(screens.spec, contract) == []
    routes = [page["route"] for page in screens.spec["pages"]]
    assert "/feed-sessions/new" not in routes and "/feed-sessions" in routes
    listing = next(page for page in screens.spec["pages"] if page["route"] == "/feed-sessions")
    buttons = next(s for s in listing["sections"] if s["component"] == "AppActions")
    assert [a["operationId"] for a in buttons["content"]["actions"]] == ["feedSession.create"]
    assert buttons["content"]["actions"][0]["kind"] == "mutation"
    table = next(s for s in listing["sections"] if s["component"] == "AppList")
    assert "create" not in table["content"]
    known = {page["id"] for page in screens.spec["pages"]}
    for page in screens.spec["pages"]:
        for section in page["sections"]:
            link = (section.get("content") or {}).get("create")
            assert not link or link["page"] in known


def test_a_child_with_nothing_to_fill_in_is_an_action_on_its_parent():
    """A recorded Antigravity draft (2026-11-09, a TikTok-like feed): a Like has the video from the route and the
    viewer from the session, nothing to fill in. The planner gave it a tab on the video with a link to a form page
    of one button, far from the video. Such a create is an action on the parent's record: on its cards and rows,
    and on its page, with the record's id in the body; no form page, no tab create link."""
    recorded = Path(__file__).parent / "fixtures" / "drafts" / "tiktok-likes"
    backend = validate_spec_data(json.loads((recorded / "backend-spec.json").read_text())).normalized
    raw = json.loads((recorded / "app-outline.json").read_text())
    extended, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec)
    assert spec.report.valid, [e.message for e in spec.report.errors]
    assert check_spec_pair(spec.normalized, extended) == [] and uncovered_operations(screens.spec, contract) == []
    routes = {page["route"]: page for page in screens.spec["pages"]}
    assert not any(route.endswith("/likes/new") for route in routes), routes.keys()
    details = [page for route, page in routes.items() if route.endswith("/videos/[id]")]  # one per area
    likes = [
        a
        for page in details
        for a in page["sections"][0]["content"]["actions"]
        if a.get("operationId") == "like.create"
    ]
    assert len(likes) == 1, "the viewers' video page has it, the creators' (who may not like) has not"
    like = likes[0]
    assert like["kind"] == "mutation" and like["body"] == {"videoId": "$route.id"} and like["label"] == "Like"
    assert "params" not in like, "it does not address the video by id: the operation's access gates it"
    cards = [
        s
        for route, page in routes.items()
        if route.endswith("/videos") and "[id]" not in route
        for s in page["sections"]
        if s["component"] == "AppList"
    ]
    assert any(
        a.get("operationId") == "like.create" and a.get("body") == {"videoId": "$record.id"}
        for s in cards
        for a in s["content"]["actions"]
    ), "the like is on the viewers' cards too"
    for page in details:  # the likes tab, if any, has no create link
        for section in page["sections"]:
            if section["component"] == "AppList" and section["content"]["entity"] == "Like":
                assert "create" not in section["content"]
