"""Areas (Story 23.10): a set of screens per group of roles, from one contract. Each area plans only what its roles
may call; the first area (the one sign-up leads to) is at `/`, the others under their prefix; sign-in and payment
pages are shared; every operation is on a screen of an area whose roles may call it."""

import json
from pathlib import Path

import pytest

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import uncovered_operations, validate_frontend_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.checks.consistency import check_spec_pair
from src.orchestrator.frontend.app.files import app_access, app_data
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.integration.contract import build_contract

EXAMPLES = Path(__file__).parents[2] / "examples"
KIT = Path(__file__).parents[1] / "templates"


def _app(name: str):
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / f"{name}.json").read_text())).normalized
    raw = json.loads((EXAMPLES / "app-outlines" / f"{name}.json").read_text())
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    screens = app_frontend_spec(backend, outline, {"colorScheme": "light-dark"}, contract)
    return backend, contract, screens


@pytest.mark.parametrize("name", ["event-tickets", "clinic-bookings", "plant-shop"])
def test_each_area_gets_its_own_screens_and_everything_stays_reachable(name):
    backend, contract, screens = _app(name)
    spec = screens.spec
    areas = spec["app"]["areas"]
    assert len(areas) == 2 and areas[0]["prefix"] == "/" and areas[1]["prefix"] == f"/{areas[1]['id']}"
    assert backend["auth"]["roles"][0] in areas[0]["roles"], "sign-up lands in the first area"
    result = validate_frontend_spec_data(spec)
    assert result.report.valid, result.report.errors
    assert check_spec_pair(result.normalized, backend) == []
    assert uncovered_operations(spec, contract) == [] and screens.unresolved == []
    routes = [page["route"] for page in spec["pages"]]
    assert len(routes) == len(set(routes)), "no route twice"
    assert sum(route in ("/login", "/register") for route in routes) <= 2, "sign-in pages once, shared"
    assert any(route.startswith(areas[1]["prefix"] + "/") for route in routes)


def test_an_area_has_only_what_its_roles_may_call():
    _, contract, screens = _app("event-tickets")
    access = app_access(contract)
    organizer_only = {op for op, rule in access.items() if rule.get("roles") == ["organizer"]}
    assert organizer_only, "the draft has organizer-only operations"
    root = [p for p in screens.spec["pages"] if not p["route"].startswith("/organizers")]
    used = {s.get("data", {}).get("operationId") for p in root for s in p["sections"]}
    used |= {
        f["operationId"]
        for f in screens.spec["forms"]
        if any(s.get("form") == f["id"] for p in root for s in p["sections"])
    }
    assert not used & organizer_only, "the attendees' screens offer nothing an attendee may not call"


def test_area_links_stay_inside_their_area():
    _, contract, screens = _app("plant-shop")
    pages = {page["id"]: page for page in screens.spec["pages"]}
    for page in screens.spec["pages"]:
        if not page["route"].startswith("/management"):
            continue
        text = json.dumps(page)
        for page_id in pages:
            if f'"page": "{page_id}"' in text and pages[page_id]["route"] not in ("/login", "/register"):
                assert pages[page_id]["route"].startswith("/management") or page_id.startswith("payments"), page_id


def test_the_kit_reads_the_areas_and_sends_each_role_home():
    backend, contract, screens = _app("clinic-bookings")
    spec = validate_frontend_spec_data(screens.spec).normalized
    data = app_data(plan_frontend(spec, contract), spec, contract)
    assert [area["prefix"] for area in data["areas"]] == ["/", "/front-desk"]
    assert data["areas"][1]["design"]["shell"] == "sidebar"
    session = (
        KIT
        / "plugins"
        / "auth-jwt"
        / "frontend"
        / "files"
        / "src"
        / "components"
        / "plugins"
        / "auth-jwt"
        / "session.ts"
    ).read_text()
    assert "export async function homePath" in session and "candidate.roles.includes(role)" in session
    shell = (  # Epic 30: the shells moved into their own module, dispatched by the generated design registry
        KIT / "nextjs_overlay" / "files" / "dynamic" / "app" / "src" / "components" / "app" / "shells.tsx"
    ).read_text()
    assert "function AreaSwitch" in shell and "layout.area.prefix" in shell


def test_an_app_without_areas_is_planned_as_before():
    _, _, screens = _app("news-feed")
    assert "areas" not in screens.spec["app"] or screens.spec["app"]["areas"] == []
