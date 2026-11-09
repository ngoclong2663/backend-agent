"""Epic 26 (Stories 26.1–26.4): workflow discovery, frozen expectations, binding and the tour's data, on the fake
engine and the fake LLM provider (no model is called)."""

import asyncio
import json
import uuid
from pathlib import Path

import business_fakes  # noqa: F401  (registers the fake provider's business answers)
import pytest
from fake_llm import FakeLlmProvider
from sqlmodel import Session, delete

from src.engines import EngineRegistry, PromptLibrary
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.libs.database import db_session_manager
from src.modules.shared.infrastructure.models import SpecDraftModel
from src.orchestrator.business.binding import action_targets, check_binding, tour_workflows
from src.orchestrator.business.flow import BusinessFlow
from src.orchestrator.business.model import brief, expectation_texts, paths, undelivered
from src.orchestrator.drafting.drafts import DraftRunner
from src.orchestrator.store import JobStore

EXAMPLES = Path(__file__).parents[2] / "examples"
pytestmark = pytest.mark.usefixtures("clean_redis")

STEP = {"record": "request", "rule": "", "delivers": []}
BUSINESS = {
    "app": {"name": "Requests", "purpose": "Handle requests"},
    "values": [{"id": "fast", "value": "Requests handled fast", "measure": "time to close"}],
    "actors": [
        {"id": "requester", "name": "Requester", "description": "asks for things", "signsIn": True},
        {"id": "handler", "name": "Handler", "description": "handles them", "signsIn": True},
    ],
    "workflows": [
        {
            "id": "handle",
            "name": "Handle a request",
            "priority": "core",
            "values": ["fast"],
            "actor": "requester",
            "trigger": "Someone needs something",
            "steps": [
                {**STEP, "id": "ask", "actor": "requester", "action": "submit a request", "statusAfter": "open"},
                {
                    **STEP,
                    "id": "close",
                    "actor": "handler",
                    "action": "close it",
                    "statusAfter": "closed",
                    "delivers": ["fast"],
                },  # fmt: skip
            ],
            "branches": [
                {
                    "id": "refuse",
                    "after": "ask",
                    "condition": "it is out of scope",
                    "steps": [
                        {**STEP, "id": "reject", "actor": "handler", "action": "reject it", "statusAfter": "rejected"}
                    ],
                }  # fmt: skip
            ],
            "outcome": "The request is closed",
            "acceptance": {"given": [], "when": [], "then": []},
        },
        {
            "id": "later_one",
            "name": "Reports",
            "priority": "later",
            "values": [],
            "actor": "handler",
            "trigger": "",
            "steps": [{**STEP, "id": "r", "actor": "handler", "action": "read a report", "statusAfter": ""}],
            "branches": [],
            "outcome": "",
            "acceptance": {"given": [], "when": [], "then": []},
        },  # fmt: skip
    ],
    "scope": {"goldenPath": "handle", "included": [], "excluded": ["e-mail"]},
}


def test_paths_and_the_brief():
    workflow = BUSINESS["workflows"][0]
    assert [(name, [s["id"] for s in steps]) for name, steps in paths(workflow)] == [
        ("main", ["ask", "close"]),
        ("refuse", ["ask", "reject"]),
    ], "a branch is the steps up to its split plus its own"
    text = brief("We handle requests.", BUSINESS)
    assert text.startswith("We handle requests.")
    assert "### Handle a request (the most important one)" in text
    assert "1. Requester: submit a request → the request becomes **open**" in text
    assert "If it is out of scope after step 1:" in text
    assert "Later, not needed in this first version: Reports." in text
    assert "Not in this first version: e-mail." in text
    assert undelivered(BUSINESS) == []


def test_expectations_read_as_sentences():
    expected = {
        "paths": [
            {
                "workflow": "handle",
                "path": "main",
                "steps": [
                    {
                        "step": "close",
                        "allowed": ["handler"],
                        "refused": ["requester", "other:handler"],
                        "record": "request",
                        "statusAfter": "closed",
                        "visibleTo": ["requester"],
                        "hiddenFrom": ["other:requester"],
                        "effects": [],
                        "refusedBefore": [],
                    }  # fmt: skip
                ],
                "outcome": [],
            }
        ]
    }
    [line] = expectation_texts(BUSINESS, expected)
    assert line["texts"] == [
        "Handler can close it",
        "Requester cannot close it",
        "another Handler cannot close it",
        "afterwards the request is 'closed'",
        "Requester sees the request",
        "another Requester does not see the request",
    ]


def test_every_name_in_the_binding_is_checked():
    operations = [
        {"operationId": "request.create", "method": "POST", "path": "/requests"},
        {
            "operationId": "request.get",
            "method": "GET",
            "path": "/requests/{id}",
            "response": {"status": "enum OPEN|CLOSED"},
        },  # fmt: skip
    ]
    pages = [{"page": "requests", "route": "/requests", "sections": []}]
    binding = {
        "actors": [{"actor": "requester", "role": "member"}, {"actor": "handler", "role": "boss"}],
        "records": [
            {
                "record": "request",
                "getOperation": "request.get",
                "statusField": "status",
                "statuses": [{"business": "open", "value": "OPEN"}, {"business": "closed", "value": "DONE"}],
            }
        ],  # fmt: skip
        "steps": [
            {"step": "ask", "operationId": "request.create", "page": "requests", "bodyJson": "{}"},
            {"step": "close", "operationId": "request.close", "page": "nowhere", "bodyJson": "[1]"},
            {"step": "auto", "automatic": True, "operationId": ""},
        ],
        "unbound": [{"what": "reports", "reason": "no report screen"}],
    }
    problems = {(p["what"], p["reason"]) for p in check_binding(binding, operations, pages, {"member": 2})}
    assert problems == {
        ("reports", "no report screen"),
        ("steps close", "unknown operation 'request.close'"),
        ("steps close", "bodyJson is not a JSON object"),
        ("page of close", "unknown page 'nowhere'"),
        ("status 'closed' of request", "'DONE' is not one of ['OPEN', 'CLOSED']"),
        ("actor handler", "unknown role 'boss'"),
    }, "an automatic step needs no operation"


def test_every_core_step_is_bound_or_has_a_problem():
    """Story 26.3: a core step the binding left out, or bound without a page, is a problem; one the model already
    explained (`unbound`) is not repeated; steps of other priorities are not asked for."""
    operations = [{"operationId": "request.create", "method": "POST", "path": "/requests"}]
    pages = [{"page": "requests", "route": "/requests", "sections": []}]
    business = {
        "workflows": [
            {
                "id": "handle",
                "priority": "core",
                "steps": [{"id": "ask"}, {"id": "triage"}, {"id": "notify"}],
                "branches": [{"id": "refused", "after": "ask", "steps": [{"id": "refuse"}]}],
            },
            {"id": "report", "priority": "later", "steps": [{"id": "export"}]},
        ]
    }
    binding = {
        "steps": [
            {"workflow": "handle", "path": "main", "step": "ask", "operationId": "request.create", "page": "requests"},
            {"workflow": "handle", "path": "main", "step": "triage", "operationId": "request.create", "page": ""},
            {"workflow": "handle", "path": "main", "step": "notify", "automatic": True},
        ],
        "unbound": [{"what": "step refuse", "reason": "no refusal operation"}],
    }
    problems = {(p["what"], p["reason"]) for p in check_binding(binding, operations, pages, {}, business)}
    assert problems == {
        ("step refuse", "no refusal operation"),
        ("step triage of handle", "bound without a page"),
    }
    del binding["unbound"]
    problems = {(p["what"], p["reason"]) for p in check_binding(binding, operations, pages, {}, business)}
    assert ("step refuse of handle", "the binding left this step out") in problems


def test_the_tour_points_at_the_action_that_performs_each_step():
    frontend = {
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
                        "content": {"actions": [{"id": "close", "operationId": "request.close"}]},
                    }
                ],
            },  # fmt: skip
        ],
    }
    assert action_targets(frontend)["request.close"] == [
        {"page": "requests-id", "route": "/requests/[id]", "section": "detail", "action": "close"}
    ]
    binding = {
        "actors": [{"actor": "requester", "role": "member"}, {"actor": "handler", "role": "staff"}],
        "steps": [
            {
                "workflow": "handle",
                "path": "main",
                "step": "ask",
                "operationId": "request.create",
                "page": "requests-new",
            },
            {"workflow": "handle", "path": "main", "step": "close", "operationId": "request.close", "page": ""},
        ],
    }
    tour = tour_workflows(BUSINESS, binding, frontend)
    [handle] = tour["tours"]
    assert handle["roles"] == ["member", "staff"] and len(tour["version"]) == 12
    ask, close = handle["steps"]
    assert ask["target"] == {"section": "form", "action": "submit"} and ask["route"] == "/requests/new"
    assert close["target"] == {"section": "detail", "action": "close"} and close["role"] == "staff"
    assert close["title"] == "Close it (the request becomes closed)"
    binding["steps"][1]["operationId"] = "request.get"  # a step that looks: the section showing the record
    assert tour_workflows(BUSINESS, binding, frontend)["tours"][0]["steps"][1]["target"] == {
        "section": "detail",
        "action": None,
    }
    binding["steps"][1]["operationId"] = "request.missing"
    assert tour_workflows(BUSINESS, binding, frontend)["tours"][0]["steps"][1]["skip"] == "no screen performs this step"


def test_discovery_asks_again_when_a_value_has_no_step(tmp_path):
    lost = json.loads(json.dumps(BUSINESS))
    lost["workflows"][0]["steps"][1]["delivers"] = []
    asked = []

    def discover(prompt, schema):
        asked.append(prompt)
        return lost if len(asked) == 1 else BUSINESS

    provider = FakeLlmProvider({"discover_workflows": discover, "rediscover_workflows": discover})
    flow = BusinessFlow(provider, PromptLibrary(), tmp_path)
    business = asyncio.run(flow.discover("We handle requests."))
    assert business["notes"] == [] and len(asked) == 2
    assert "No step delivers these values" in asked[1] and '"fast"' in asked[1]
    assert [call["prompt"] for call in flow.calls] == ["discover_workflows@v1", "discover_workflows@v1"]
    assert [call["purpose"] for call in flow.calls] == ["discover_workflows", "rediscover_workflows"]


# -- the draft ------------------------------------------------------------------------------------------------------


@pytest.fixture
def cleanup_drafts():
    yield
    with Session(db_session_manager.engine) as session:
        session.exec(delete(SpecDraftModel))
        session.commit()


def _draft(client, headers, root: Path, text: str, business: bool | None) -> dict:
    body = {"engine": "fake", "mode": "dynamic", "requirementText": text}
    if business is not None:
        body["businessWorkflows"] = business
    response = client.post("/api/v1/spec-drafts", json=body, headers=headers)
    assert response.status_code == 202, response.text
    draft_id = response.json()["draftId"]
    engine = FakeEngine(root, demo_scenario(delay_s=0))
    runner = DraftRunner(
        EngineRegistry([engine], default="fake"),
        PromptLibrary(),
        JobStore(),
        root,
        "w-biz",
        EXAMPLES,
        llm_provider=FakeLlmProvider(),
    )
    asyncio.run(runner.run(draft_id))
    return JobStore().draft(uuid.UUID(draft_id)).model_dump(mode="json")


def test_a_draft_with_business_workflows_has_them_bound_and_a_tour(client, user_headers, tmp_path, cleanup_drafts):
    draft = _draft(client, user_headers, tmp_path, "A workshop booking site for our studio.", business=True)
    assert draft["status"] in ("SUCCEEDED", "NEEDS_REVIEW"), draft["error"]
    prompts = [call["prompt"] for call in draft["usage"]["calls"]]
    assert prompts == ["discover_workflows@v1", "expect_workflows@v1", "draft_app@v7", "bind_workflows@v1"]
    data = draft["business"]
    assert data["provider"] == "fake" and data["business"]["workflows"][0]["id"] == "main"
    assert data["expected"]["paths"][0]["steps"][0]["allowed"] == ["member"]
    assert data["texts"][0]["texts"][0] == "Member can create a record"
    binding = data["binding"]
    assert binding["steps"][0]["operationId"] and binding["roles"], binding
    tour = draft["frontend_spec"]["app"]["workflows"]
    assert tour == data["tour"] and tour["tours"][0]["steps"][0]["target"]["action"] == "submit"


def test_with_the_option_off_the_draft_is_todays(client, user_headers, tmp_path, cleanup_drafts):
    draft = _draft(client, user_headers, tmp_path, "A workshop booking site for our studio.", business=None)
    assert draft["business"] is None
    assert [call["prompt"] for call in draft["usage"]["calls"]] == ["draft_app@v7"]
    assert "workflows" not in (draft["frontend_spec"]["app"] or {})
