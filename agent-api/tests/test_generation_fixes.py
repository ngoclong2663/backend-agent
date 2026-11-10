"""Fixes found on Epic 33's real generations (2026-11-10), each on the real drafted spec."""

import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.codegen import module_files
from src.orchestrator.backend.planner import build_plan

DRAFTS = Path(__file__).parent / "fixtures" / "drafts"


def _files(name: str, entity: str) -> dict[str, str]:
    spec = validate_spec_data(json.loads((DRAFTS / name / "backend-spec.json").read_text())).normalized
    plan = build_plan(spec)
    return module_files(plan, spec, next(m for m in plan["modules"] if m["entity"] == entity))


def test_an_update_whose_body_has_no_status_does_not_check_its_transition():
    """The news draft's article status moves only through its actions, so the update's DTO has no `status`; the rules
    plugin still checked `dto.status`, and every update answered 500 (gen_01M7219E7W5WGVQ9D0GRSA5XWM)."""
    update = _files("domain-news-v10", "Article")["src/modules/articles/usecases/update_article_usecase.py"]
    assert "dto.status" not in update


def test_computed_fields_are_required_in_the_response_dto():
    """The contract always returns them; with defaults the app's OpenAPI marked them optional (the openapi check)."""
    dto = _files("domain-news-v10", "Article")["src/modules/articles/presenter/dtos/article_response_dto.py"]
    assert "comment_count: int\n" in dto and "my_save_id: uuid.UUID | None\n" in dto


def test_the_completion_prompt_asks_for_the_custom_handlers_error_responses():
    """The courier draft's `GET /driver/earnings/today` (an engine-written handler) left out its 401 and the API
    contract check failed (gen_01M7242HBZ9MYVKQ6MKAH2MMMR); v6 says to declare them as the generated handlers do."""
    from src.orchestrator.backend.nodes import PROMPT_VERSIONS

    version = PROMPT_VERSIONS["complete_backend"]
    text = (Path(__file__).parents[1] / "prompts" / "complete_backend" / f"{version}.md").read_text()
    assert version == "v6" and "responses={401: ERROR" in text


def _courier() -> dict:
    return json.loads((DRAFTS / "domain-drivers-v10" / "backend-spec.json").read_text())


def test_a_code_nobody_sends_is_made_by_the_server():
    """The courier draft's `trackingCode` (required, unique, not in the create's request): every create answered 500
    (gen_01M724T95SDD3H4JNDBDBXW83M); the draft now gives it a generated code."""
    from src.orchestrator.drafting.app import fix_unsent_codes

    data = _courier()
    notes = fix_unsent_codes(data)
    tracking = next(
        f for e in data["entities"] if e["name"] == "Delivery" for f in e["fields"] if f["name"] == "trackingCode"
    )
    assert tracking["default"] == "@code" and "the server makes a code" in notes[0]["message"]
    spec = validate_spec_data(data).normalized
    plan = build_plan(spec)
    from src.orchestrator.backend.codegen import model_file

    delivery = next(m for m in plan["models"] if m["entity"] == "Delivery")
    assert "default_factory=lambda: uuid.uuid4().hex[:10].upper()" in model_file(delivery, plan)


def test_the_creating_roles_own_id_comes_from_the_signed_in_user():
    """The courier draft's `shopId`, named after the `shop_owner` role that alone creates deliveries and left out of the
    request: the shop is the creator (it was never filled and the create answered 500)."""
    spec = validate_spec_data(_courier()).normalized
    plan = build_plan(spec)
    delivery = next(m for m in plan["models"] if m["entity"] == "Delivery")
    shop = next(c for c in delivery["columns"] if c["apiName"] == "shopId")
    assert shop["source"] == "currentUser"
    create = _files("domain-drivers-v10", "Delivery")["src/modules/deliveries/usecases/create_delivery_usecase.py"]
    assert "current_user.id" in create


def test_a_figure_behind_sign_in_keeps_its_sign_in_on_the_route():
    """The courier draft's earnings (aggregates under an ownership policy) were open to anyone and the API contract
    check found their 401 missing; the route keeps the caller's dependency."""
    router = _files("domain-drivers-v10", "Delivery")["src/modules/deliveries/presenter/router.py"]
    route = router[router.index('"/driver/earnings/today"') :][:400]
    assert "current_user: CurrentUserDep" in route


def test_the_tests_seed_a_creator_id_that_is_not_a_foreign_key():
    """The courier draft's `shopId` (from the signed-in user, no relationship): writing the module's tests crashed on
    the missing foreign key (gen_01M725VHD2XVQ1GHZJB8XZ7FQV)."""
    from src.orchestrator.backend.codegen import module_tests

    spec = validate_spec_data(_courier()).normalized
    plan = build_plan(spec)
    module = next(m for m in plan["modules"] if m["entity"] == "Delivery")
    text = next(iter(module_tests(plan, spec, module).values()))
    assert 'values["shop_id"] = current_user_id() or uuid.uuid4()' in text


def test_a_create_test_with_nothing_to_compare_reads_no_body():
    """The courier draft's availability is made from the caller alone; its generated create test left `body` unused and
    the generated project's lint warned (F841, gen_01M725Y40JRJ2H2FSZGY54VVKF)."""
    from src.orchestrator.backend.codegen import module_tests

    spec = validate_spec_data(_courier()).normalized
    plan = build_plan(spec)
    module = next(m for m in plan["modules"] if m["entity"] == "Availability")
    text = next(iter(module_tests(plan, spec, module).values()))
    created = text[text.index("def test_create_availability__ok") :].split("\n\n\n")[0]
    assert "body = response.json()" not in created


def test_an_operation_only_a_later_area_may_call_and_no_screen_covers_is_a_note_not_a_crash():
    """Drivers (Epic 34's final check): an earnings aggregate only drivers may call, on no screen, crashed the plan
    (`KeyError: 'delivery.driverEarningsWeek'`): the note looked it up among the first area's operations only."""
    from scripts.domain_report import FIXTURES as DOMAIN_FIXTURES
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.drafting.app import app_theme
    from src.orchestrator.frontend.app.outline import complete_outline
    from src.orchestrator.frontend.app.screens import app_frontend_spec
    from src.orchestrator.integration.contract import build_contract

    folder = DOMAIN_FIXTURES / "drafts" / "domain-drivers-v10"
    backend = json.loads((folder / "backend-spec.json").read_text())
    week = next(op for op in backend["operations"] if op["operationId"] == "delivery.driverEarningsThisWeek")
    backend["policies"].append({"name": "driversOnly", "type": "role", "roles": ["driver"]})
    backend["operations"].append(
        {**week, "operationId": "delivery.driverEarningsWeek", "path": "/driver/earnings/w", "policy": "driversOnly"}
    )
    backend = validate_spec_data(backend).normalized
    contract = build_contract(backend, build_plan(backend))
    outline, _ = complete_outline(json.loads((folder / "app-outline.json").read_text()), backend, contract)
    planned = app_frontend_spec(backend, outline, app_theme(None), contract)
    assert any("delivery.driverEarningsWeek (GET /driver/earnings/w) has no screen" in n["message"]
               for n in planned.unresolved)  # fmt: skip


def test_a_seed_foreign_key_written_as_its_parents_name_points_at_that_row():
    """IoT (Epic 34's final check): the draft seeded `zoneId: "Zone A - Tomato Benches"` (the zone's name) and the
    BackendSpec was invalid; the repair didn't fix it and the draft needed review."""
    from src.orchestrator.drafting.app import fix_seed_references

    data = json.loads((DRAFTS / "iot-seed-names" / "backend-spec.json").read_text())
    assert validate_spec_data(json.loads(json.dumps(data))).report.errors
    notes = fix_seed_references(data)
    zones = next(s for s in data["seed"] if s["entity"] == "Zone")["records"]
    devices = next(s for s in data["seed"] if s["entity"] == "Device")["records"]
    assert devices[0]["zoneId"] == zones[0]["id"] and any("Zone A - Tomato Benches" in n["message"] for n in notes)
    cameras = next(s for s in data["seed"] if s["entity"] == "PestDetection")["records"]
    assert cameras[0]["deviceId"] == next(d["id"] for d in devices if d["name"] == "Bench Cam 1")
    assert not [e for e in validate_spec_data(data).report.errors if e.code == "SEED_INVALID"]
    unknown = {**data, "seed": [{"entity": "Device", "records": [{**devices[0], "zoneId": "Zone Z"}]}]}
    assert not fix_seed_references(unknown) and unknown["seed"][0]["records"][0]["zoneId"] == "Zone Z"
