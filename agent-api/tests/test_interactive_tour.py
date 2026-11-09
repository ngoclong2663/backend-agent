"""Epic 28: the tour's step kinds and record needs (28.1, 28.4), the forms' examples from the contract (28.3) and
the evaluation's tour plan (28.6). Pure functions, no browser, no model."""

import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.business.binding import step_kind, tour_workflows
from src.orchestrator.evaluation.tour import merge_play, tour_plan, tour_roles
from src.orchestrator.frontend.app.files import app_data, form_example
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.integration.contract import build_contract

EXAMPLES = Path(__file__).parents[2] / "examples"

STEP = {"record": "request", "rule": "", "delivers": []}
BUSINESS = {
    "actors": [
        {"id": "requester", "name": "Requester", "description": "", "signsIn": True},
        {"id": "handler", "name": "Handler", "description": "", "signsIn": True},
    ],
    "workflows": [
        {
            "id": "handle",
            "name": "Handle a request",
            "priority": "core",
            "outcome": "The request is closed",
            "steps": [
                {**STEP, "id": "ask", "actor": "requester", "action": "submit a request", "statusAfter": "open"},
                {**STEP, "id": "triage", "actor": "handler", "action": "triage it", "statusAfter": "triaged"},
                {**STEP, "id": "read", "actor": "handler", "action": "read the request", "statusAfter": ""},
                {**STEP, "id": "notify", "actor": "handler", "action": "notify the requester", "statusAfter": ""},
                {**STEP, "id": "close", "actor": "handler", "action": "close it", "statusAfter": "closed"},
                {**STEP, "id": "audit", "actor": "auditor", "action": "audit it", "statusAfter": ""},
            ],
            "branches": [],
        }
    ],
}
FRONTEND = {
    "forms": [{"id": "request_create", "operationId": "request.create"}],
    "pages": [
        {"id": "requests-new", "route": "/requests/new", "sections": [{"id": "form", "form": "request_create"}]},
        {
            "id": "requests-id",
            "route": "/requests/[id]",
            "sections": [
                {
                    "id": "detail",
                    "data": {"operationId": "request.get"},
                    "content": {
                        "actions": [
                            {"id": "triage", "operationId": "request.triage"},
                            {"id": "close", "operationId": "request.close"},
                        ]
                    },
                }
            ],
        },
    ],
}
BINDING = {
    "actors": [{"actor": "requester", "role": "member"}, {"actor": "handler", "role": "staff"}],
    "steps": [
        {"workflow": "handle", "path": "main", "step": "ask", "operationId": "request.create", "page": "requests-new"},
        {
            "workflow": "handle",
            "path": "main",
            "step": "triage",
            "operationId": "request.triage",
            "page": "requests-id",
        },  # fmt: skip
        {"workflow": "handle", "path": "main", "step": "read", "operationId": "request.get", "page": "requests-id"},
        {"workflow": "handle", "path": "main", "step": "notify", "automatic": True},
        {"workflow": "handle", "path": "main", "step": "close", "operationId": "request.close", "page": "requests-id"},
        {"workflow": "handle", "path": "main", "step": "audit", "operationId": "request.get", "page": "requests-id"},
    ],
}


def test_every_step_has_a_kind_from_its_target():
    [tour] = tour_workflows(BUSINESS, BINDING, FRONTEND)["tours"]
    kinds = {step["id"]: step["kind"] for step in tour["steps"]}
    assert kinds == {"ask": "do", "triage": "do", "read": "look", "notify": "note", "close": "do", "audit": "note"}
    audit = tour["steps"][-1]
    assert audit["skip"] == "no app role plays this actor" and audit["role"] is None
    assert step_kind({"target": {"section": "s", "action": None}}) == "look"
    assert step_kind({"target": {"section": "s", "action": "go"}, "skip": "no screen performs this step"}) == "note"


def test_a_record_step_names_the_earlier_step_that_makes_a_record_ready():
    [tour] = tour_workflows(BUSINESS, BINDING, FRONTEND)["tours"]
    by_id = {step["id"]: step for step in tour["steps"]}
    assert "needs" not in by_id["ask"]  # a create page: no record yet
    assert by_id["triage"]["needs"] == {"step": "ask", "role": "member", "status": "open"}
    assert by_id["close"]["needs"] == {"step": "triage", "role": "staff", "status": "triaged"}
    assert "needs" not in by_id["read"]  # a look step
    assert by_id["ask"]["record"] == "request" and by_id["ask"]["statusAfter"] == "open"


def test_the_tour_version_changes_with_the_kinds():
    assert len(tour_workflows(BUSINESS, BINDING, FRONTEND)["version"]) == 12


# -- 28.3: the forms' examples ----------------------------------------------------------------------------------------


def _workshop():
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / "workshop-bookings.json").read_text())).normalized
    raw = json.loads((EXAMPLES / "app-outlines" / "workshop-bookings.json").read_text())
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    theme = {"style": "dashboard", "colorScheme": "light-dark", "density": "comfortable"}
    spec = app_frontend_spec(backend, outline, theme, contract).spec
    return spec, contract


def test_create_forms_carry_the_success_scenarios_values_for_their_visible_fields():
    spec, contract = _workshop()
    normalized = validate_frontend_spec_data(spec).normalized
    data = app_data(plan_frontend(normalized, contract), normalized, contract)
    forms = data["forms"]
    with_example = {name: form for name, form in forms.items() if form.get("example")}
    assert with_example, "no form has an example"
    for name, form in with_example.items():
        fields = {field["name"]: field for field in form["fields"]}
        for key, value in form["example"].items():
            field = fields[key]
            assert not field.get("hidden") and not field.get("reference") and not field.get("upload"), (name, key)
            if field["type"] == "enum":
                assert value in field["values"]
            if field["type"] in ("integer", "number", "decimal"):
                assert isinstance(value, int | float) and not isinstance(value, bool)
    # the auth forms (sign-in, sign-up) have no scenario body of their own fields: no example
    assert all("example" not in form for name, form in forms.items() if name.startswith("auth_"))


def test_values_a_field_would_refuse_are_left_out():
    contract = {
        "paths": {
            "/things": {
                "post": {
                    "operationId": "thing.create",
                    "x-bga": {
                        "scenarios": [
                            {
                                "name": "success",
                                "params": {},
                                "body": {
                                    "name": "A very long name that is far beyond the limit",
                                    "kind": "GREEN",
                                    "count": 3.5,
                                    "due": "2026-01-02",
                                    "startsAt": "not a date",
                                    "ownerId": "u1",
                                    "cover": "thing/cover/seed/1.png",
                                    "nested": {"a": 1},
                                },
                            }
                        ]
                    },
                }
            }
        }
    }
    form = {
        "operationId": "thing.create",
        "fields": [
            {"name": "name", "type": "string", "maxLength": 6},
            {"name": "kind", "type": "enum", "values": ["RED", "BLUE"]},
            {"name": "count", "type": "integer"},
            {"name": "due", "type": "date"},
            {"name": "startsAt", "type": "datetime"},
            {"name": "ownerId", "type": "string", "reference": {"entity": "User", "listOperation": "user.list"}},
            {"name": "cover", "type": "string", "upload": {"entity": "Thing", "field": "cover"}},
            {"name": "projectId", "type": "string", "hidden": True, "value": "$route.id"},
            {"name": "nested", "type": "object"},
        ],
    }
    assert form_example(form, contract) == {"name": "A very", "due": "2026-01-02"}
    assert form_example({"operationId": "thing.list", "fields": []}, contract) is None


# -- 28.6: the walker's plan ------------------------------------------------------------------------------------------

DEMO = [
    {"login": "demo-member@example.com", "role": "member"},
    {"login": "demo-member-2@example.com", "role": "member"},
    {"login": "demo-staff@example.com", "role": "staff"},
]
APP = {
    "auth": {"demoUsers": DEMO},
    "workflows": {
        "version": "abc",
        "tours": [
            {
                "id": "handle",
                "name": "Handle a request",
                "roles": ["member", "staff"],
                "steps": [
                    {
                        "id": "ask",
                        "role": "member",
                        "actor": "Member",
                        "title": "Ask",
                        "kind": "do",
                        "target": {"section": "f", "action": "submit"},
                    },  # fmt: skip
                    {
                        "id": "close",
                        "role": "staff",
                        "actor": "Staff",
                        "title": "Close",
                        "kind": "do",
                        "target": {"section": "d", "action": "close"},
                    },  # fmt: skip
                    {
                        "id": "notify",
                        "role": "staff",
                        "actor": "Staff",
                        "title": "Notify",
                        "kind": "note",
                        "automatic": True,
                    },  # fmt: skip
                ],
            }
        ],
    },
}


def test_one_demo_user_per_role_plays_the_tour_with_the_kinds_of_that_role():
    assert tour_roles(APP) == [
        {"role": "member", "login": "demo-member@example.com"},
        {"role": "staff", "login": "demo-staff@example.com"},
    ]
    plan = tour_plan(APP)
    member, staff = plan
    assert [step["kind"] for step in member["tours"][0]["steps"]] == ["do", "note", "note"]
    assert [step["kind"] for step in staff["tours"][0]["steps"]] == ["note", "do", "note"]
    assert tour_plan({"auth": None, "workflows": None}) == []
    assert tour_roles({}) == [{"role": None, "login": None}]


def test_the_browsers_results_land_on_the_planned_steps():
    planned = tour_plan(APP)[1]
    played = {
        "ok": True,
        "completed": False,
        "tour": "handle",
        "steps": [
            {"tour": "handle", "id": "ask", "kind": "note", "result": "completed", "ms": 300},
            {
                "tour": "handle",
                "id": "close",
                "kind": "do",
                "result": "stuck",
                "reason": "POST /requests/1/close → 409",
                "ms": 20000,
                "file": "shots/tour-02-staff-1-close.png",
            },  # fmt: skip
        ],
        "log": ["signed in"],
    }
    merged = merge_play(planned, played)
    results = {step["id"]: step["result"] for step in merged["tours"][0]["steps"]}
    assert results == {"ask": "completed", "close": "stuck", "notify": "not reached"}
    close = merged["tours"][0]["steps"][1]
    assert close["reason"].startswith("POST") and close["file"].endswith(".png") and close["ms"] == 20000
    assert merged["tours"][0]["completed"] is False and merged["log"] == ["signed in"]
    assert merge_play(planned, None)["tours"][0]["steps"][0]["result"] == "not reached"
