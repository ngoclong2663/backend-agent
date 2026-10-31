"""Generation modes, lanes and the FrontendSpec API (Stories 12.1, 12.2, 12.3, 12.5)."""

import json
from pathlib import Path

import pytest

from src.engines.fake_engine import FakeEngine, demo_scenario
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus
from src.modules.shared.domain.generation_modes import close_lanes, overall_status
from src.orchestrator.contract import build_contract, dump_contract
from src.orchestrator.store import JobStore
from workflow_helpers import TWO_ENTITY, cli_invocations, events, generation, node_runs, run_job

EXAMPLES = Path(__file__).parents[2] / "examples"
SHOP = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
SHOP_FRONTEND = json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text())
TRACKER_FRONTEND = json.loads((EXAMPLES / "frontend-specs" / "project-tracker-dynamic.json").read_text())
LANDING = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
OPTIONS = {"engine": "fake", "deployPreview": False, "crudFromTemplates": False}  # the backend engine path


@pytest.fixture
def headers(login):
    def _headers(email: str = "user@test.local", password: str = "userpass") -> dict:
        return {"Authorization": f"Bearer {login(email, password)}"}

    return _headers


# -- overall status ----------------------------------------------------------------------------------------------

B, S, D = GenerationMode.BACKEND, GenerationMode.STATIC, GenerationMode.DYNAMIC


@pytest.mark.parametrize(
    ("mode", "lanes", "expected"),
    [
        (B, {"backend": "COMPLETED"}, "COMPLETED"),
        (B, {"backend": "FAILED"}, "FAILED"),
        (S, {"frontend": "COMPLETED"}, "COMPLETED"),
        (S, {"frontend": "SKIPPED"}, "COMPLETED_WITH_WARNINGS"),
        (D, {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "COMPLETED"}, "COMPLETED"),
        (D, {"backend": "FAILED", "frontend": "COMPLETED", "integration": "SKIPPED"}, "COMPLETED_WITH_WARNINGS"),
        (D, {"backend": "COMPLETED", "frontend": "FAILED", "integration": "SKIPPED"}, "FAILED"),
        (D, {"backend": "COMPLETED", "frontend": "SKIPPED", "integration": "SKIPPED"}, "COMPLETED_WITH_WARNINGS"),
        (D, {"backend": "FAILED", "frontend": "SKIPPED", "integration": "SKIPPED"}, "FAILED"),
    ],
)
def test_overall_status_follows_the_lane_rules(mode, lanes, expected):
    assert overall_status(mode, lanes) == GenerationStatus(expected)


def test_close_lanes_fails_the_active_lane_and_skips_the_rest():
    lanes = {"backend": "REPAIRING", "frontend": "PENDING", "integration": "SKIPPED"}
    assert close_lanes(lanes, failed=True) == {"backend": "FAILED", "frontend": "SKIPPED", "integration": "SKIPPED"}
    assert close_lanes(lanes, failed=False)["backend"] == "SKIPPED"


# -- FrontendSpec API --------------------------------------------------------------------------------------------


def _post_json(client, url: str, body, headers: dict):
    return client.post(url, content=json.dumps(body), headers={**headers, "content-type": "application/json"})


def test_frontend_spec_routes_require_auth(client):
    assert client.get("/api/v1/frontend-specs/schema").status_code == 401
    assert client.post("/api/v1/frontend-specs/validate", content=b"{}").status_code == 401


def test_frontend_spec_schema_and_validation(client, headers):
    schema = client.get("/api/v1/frontend-specs/schema", headers=headers())
    assert schema.status_code == 200 and schema.json()["title"] == "FrontendSpec 1.0"
    assert client.get("/api/v1/frontend-specs/schema?version=2.0", headers=headers()).status_code == 404

    ok = _post_json(client, "/api/v1/frontend-specs/validate", LANDING, headers()).json()
    assert ok == {"valid": True, "specVersion": "1.0", "errors": [], "warnings": []}
    broken = {**LANDING, "layout": {"header": {"navigation": [{"label": "X", "page": "nowhere"}]}}}
    report = _post_json(client, "/api/v1/frontend-specs/validate", broken, headers()).json()
    assert not report["valid"] and report["errors"][0]["code"] == "FE_UNKNOWN_PAGE"


def test_validate_against_a_backend_spec_runs_the_consistency_check(client, headers):
    backend_id = _post_json(client, "/api/v1/specs", TWO_ENTITY, headers()).json()["specId"]
    url = f"/api/v1/frontend-specs/validate?backendSpecId={backend_id}"

    assert _post_json(client, url, TRACKER_FRONTEND, headers()).json()["valid"] is True
    report = _post_json(client, url, SHOP_FRONTEND, headers()).json()
    assert not report["valid"]
    first = report["errors"][0]
    assert first["code"] == "CONTRACT_UNKNOWN_OPERATION"
    assert first["path"] == "/pages/0/sections/1/data/operationId" and first["backendPath"] == "/operations"

    static = _post_json(client, url, LANDING, headers()).json()
    assert static["valid"] and static["warnings"][0]["code"] == "FE_UNSUPPORTED_FEATURE"
    other = _post_json(client, url, TRACKER_FRONTEND, headers("other@test.local", "otherpass"))
    assert other.status_code == 404


def test_check_pair_compares_unsaved_specs(client, headers):
    url = "/api/v1/frontend-specs/check-pair"
    assert client.post(url, json={"frontendSpec": TRACKER_FRONTEND, "backendSpec": TWO_ENTITY}).status_code == 401
    auth = headers()

    def check(frontend: dict, backend: dict) -> dict:
        response = client.post(url, json={"frontendSpec": frontend, "backendSpec": backend}, headers=auth)
        assert response.status_code == 200, response.text
        return response.json()

    tracker = check(TRACKER_FRONTEND, TWO_ENTITY)
    contract = tracker.pop("contract")
    assert tracker == {"valid": True, "specVersion": "1.0", "errors": [], "warnings": [], "checked": True}
    assert contract["openapi"].startswith("3.1") and contract["paths"], "the contract is returned for the preview"
    assert check(SHOP_FRONTEND, SHOP)["valid"] is True

    mismatch = check(SHOP_FRONTEND, TWO_ENTITY)
    assert mismatch["checked"] and not mismatch["valid"]
    first = mismatch["errors"][0]
    assert first["code"] == "CONTRACT_UNKNOWN_OPERATION"
    assert first["path"] == "/pages/0/sections/1/data/operationId" and first["backendPath"] == "/operations"

    # An invalid spec is reported by its own /validate; the pair is not compared.
    for frontend, backend in [({**TRACKER_FRONTEND, "pages": []}, TWO_ENTITY), (TRACKER_FRONTEND, {"entities": []})]:
        skipped = check(frontend, backend)
        assert skipped["checked"] is False and not skipped["valid"] and skipped["errors"] == []
        assert skipped["contract"] is None

    static = check(LANDING, TWO_ENTITY)
    assert static["checked"] is False and static["valid"] and static["warnings"][0]["code"] == "FE_UNSUPPORTED_FEATURE"

    missing = client.post(url, json={"frontendSpec": TRACKER_FRONTEND}, headers=auth)
    assert missing.status_code == 422


def test_frontend_specs_are_stored_and_owner_scoped(client, headers):
    created = _post_json(client, "/api/v1/frontend-specs", SHOP_FRONTEND, headers())
    assert created.status_code == 201, created.text
    spec_id = created.json()["specId"]
    fetched = client.get(f"/api/v1/frontend-specs/{spec_id}", headers=headers()).json()
    assert fetched["mode"] == "dynamic" and json.loads(fetched["raw"]) == SHOP_FRONTEND
    assert fetched["normalized"]["pages"][0]["id"] == "home"
    assert (
        client.get(f"/api/v1/frontend-specs/{spec_id}", headers=headers("other@test.local", "otherpass")).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/frontend-specs/{spec_id}", headers=headers("admin@test.local", "adminpass")).status_code
        == 200
    )

    invalid = _post_json(client, "/api/v1/frontend-specs", {**LANDING, "pages": []}, headers())
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "SPEC_INVALID"


# -- creating generations ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "static", "backendSpec": TWO_ENTITY},
        {"mode": "static"},
        {"mode": "dynamic", "frontendSpec": TRACKER_FRONTEND},
        {"mode": "dynamic", "backendSpec": TWO_ENTITY},
        {"mode": "backend", "backendSpec": TWO_ENTITY, "frontendSpec": TRACKER_FRONTEND},
        {"mode": "static", "frontendSpec": TRACKER_FRONTEND},  # a dynamic FrontendSpec
        {"mode": "dynamic", "frontendSpec": LANDING, "backendSpec": TWO_ENTITY},  # a static FrontendSpec
    ],
)
def test_inputs_must_match_the_mode(client, headers, body):
    response = client.post("/api/v1/generations", json={**body, "options": OPTIONS}, headers=headers())
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "MODE_INPUT_MISMATCH"


def test_a_stored_frontend_spec_must_match_the_mode(client, headers):
    spec_id = _post_json(client, "/api/v1/frontend-specs", TRACKER_FRONTEND, headers()).json()["specId"]
    body = {"mode": "static", "frontendSpecId": spec_id, "options": OPTIONS}
    response = client.post("/api/v1/generations", json=body, headers=headers())
    assert response.status_code == 422 and response.json()["error"]["code"] == "MODE_INPUT_MISMATCH"


def _submit(client, headers: dict, body: dict) -> str:
    response = client.post("/api/v1/generations", json={**body, "options": OPTIONS}, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["generationId"]


def test_generations_carry_mode_lanes_and_frontend_options(client, headers):
    generation_id = _submit(client, headers(), {"mode": "static", "frontendSpec": LANDING})
    detail = client.get(f"/api/v1/generations/{generation_id}", headers=headers()).json()
    assert detail["mode"] == "static" and detail["specId"] is None and detail["frontendSpecId"]
    assert detail["lanes"] == {"frontend": "PENDING"}
    assert detail["projectName"] == "Northwind Studio"
    assert detail["options"]["frontend"] == {"runTests": True, "generatePreview": True, "mockApi": True}
    listed = client.get("/api/v1/generations", headers=headers()).json()["items"]
    row = next(item for item in listed if item["generationId"] == generation_id)
    assert (
        row["mode"] == "static" and row["lanes"] == {"frontend": "PENDING"} and row["projectName"] == "Northwind Studio"
    )

    backend_id = _submit(client, headers(), {"backendSpec": TWO_ENTITY})
    backend = client.get(f"/api/v1/generations/{backend_id}", headers=headers()).json()
    assert backend["mode"] == "backend" and backend["lanes"] == {"backend": "PENDING"}
    assert "frontend" not in backend["options"]


def test_workflow_graph_per_mode(client, headers):
    backend = client.get("/api/v1/generations/graph", headers=headers()).json()
    dynamic = client.get("/api/v1/generations/graph?mode=dynamic", headers=headers()).json()
    static = client.get("/api/v1/generations/graph?mode=static", headers=headers()).json()
    ids = {
        name: [node["id"] for node in graph["nodes"]] for name, graph in (("b", backend), ("d", dynamic), ("s", static))
    }
    assert "validate_spec" in ids["b"] and "validate_inputs" not in ids["b"]
    assert ids["d"][:3] == ["__start__", "validate_inputs", "build_contract"] and "validate_spec" not in ids["d"]
    frontend_lane = [
        "plan_frontend", "scaffold_frontend", "generate_assets", "generate_frontend", "validate_frontend",
        "repair_frontend",
    ]  # fmt: skip
    assert ids["s"] == ["__start__", "validate_inputs", *frontend_lane, "package_artifacts", "__end__"]
    assert set(frontend_lane) <= set(ids["d"]) and not set(frontend_lane) & set(ids["b"])
    lanes = {node["id"]: node["lane"] for node in dynamic["nodes"] if not node["id"].startswith("__")}
    assert lanes["generate_backend"] == "backend" and lanes["build_contract"] is None
    assert lanes["generate_frontend"] == "frontend" and lanes["integrate"] == "integration"
    edges = {(edge["source"], edge["target"]) for edge in dynamic["edges"]}
    assert {("build_contract", "plan_architecture"), ("build_contract", "plan_frontend")} <= edges
    expected_converge = {
        ("run_validation", "integrate"),
        ("validate_frontend", "integrate"),
        ("integrate", "package_artifacts"),
    }
    assert expected_converge <= edges
    assert ("run_validation", "plan_frontend") not in edges and ("run_validation", "__end__") not in edges


# -- running them ------------------------------------------------------------------------------------------------


def _artifacts(client, headers: dict, generation_id: str) -> dict[str, dict]:
    items = client.get(f"/api/v1/generations/{generation_id}/artifacts", headers=headers).json()["items"]
    return {item["name"]: item for item in items}


def test_dynamic_generation_runs_contract_backend_and_frontend_lanes(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit(
        client, auth, {"mode": "dynamic", "frontendSpec": TRACKER_FRONTEND, "backendSpec": TWO_ENTITY}
    )
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED_WITH_WARNINGS"

    row = generation(generation_id)
    assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "SKIPPED"}
    assert "backend preview is not running" in row.error_summary
    nodes = [run.node for run in node_runs(generation_id)]
    assert nodes[:2] == ["validate_inputs", "build_contract"] and "validate_spec" not in nodes
    assert nodes[-2:] == ["integrate", "package_artifacts"]
    backend_lane_nodes = (
        "plan_architecture",
        "generate_database",
        "generate_backend",
        "generate_tests",
        "run_validation",
        "repair_code",
    )
    frontend_lane_nodes = (
        "plan_frontend",
        "scaffold_frontend",
        "generate_assets",
        "generate_frontend",
        "validate_frontend",
        "repair_frontend",
    )
    assert [n for n in nodes if n in backend_lane_nodes] == [
        "plan_architecture",
        "generate_database",
        "generate_backend",
        "generate_tests",
        "run_validation",
        "repair_code",
        "run_validation",
    ]
    # Story 17.4: every tracker section is in the library, so the frontend lane's only engine call draws the
    # empty-state illustration (Story 15.2).
    assert [n for n in nodes if n in frontend_lane_nodes] == [
        "plan_frontend", "scaffold_frontend", "generate_assets", "generate_frontend", "validate_frontend",
    ]  # fmt: skip
    assert {call.purpose for call in cli_invocations(generation_id)} == {
        "generate_database", "generate_backend", "generate_tests", "repair_code", "generate_assets",
    }  # fmt: skip
    frontend = tmp_path / generation_id / "frontend"
    assert (frontend / ".bga" / "contract.json").is_file() and (
        frontend / "src" / "lib" / "api" / "queries.ts"
    ).is_file()
    assert "useOperationQuery" in (frontend / "src/components/renderer/bindings.ts").read_text()

    artifacts = _artifacts(client, auth, generation_id)
    assert {
        "contract.json", "frontend-spec.json", "spec.json", "backend.zip", "manifest.json", "frontend.zip",
        "frontend-plan.json", "frontend-validation-1.json",
    } <= set(artifacts)  # fmt: skip
    assert artifacts["frontend.zip"]["kind"] == "frontend"
    assert artifacts["contract.json"]["kind"] == "contract"
    url = f"/api/v1/generations/{generation_id}/artifacts/{artifacts['contract.json']['artifactId']}"
    contract_text = client.get(url, headers=auth).text
    from generation_helpers import normalized

    assert contract_text == dump_contract(build_contract(normalized(EXAMPLES / "specs" / "two-entity.json")))
    project = tmp_path / generation_id / "project"
    assert (project / ".bga" / "contract.json").read_text() == contract_text
    manifest = json.loads(
        client.get(
            f"/api/v1/generations/{generation_id}/artifacts/{artifacts['manifest.json']['artifactId']}",
            headers=auth,
        ).text
    )
    assert manifest["artifacts"]["contract"] == artifacts["contract.json"]["artifactId"]
    assert manifest["artifacts"]["frontend"] == artifacts["frontend.zip"]["artifactId"]
    assert manifest["frontend"]["mode"] == "dynamic" and len(manifest["frontend"]["routes"]) == 4
    assert manifest["frontend"]["contractSha256"] and manifest["frontend"]["env"] == ["MOCK_TEST_API", "API_BASE_URL"]

    stored = events(generation_id)
    lane_changes = [(e.lane, e.status) for e in stored if e.type == "lane.changed"]
    assert ("integration", "SKIPPED") in lane_changes and ("backend", "COMPLETED") in lane_changes
    assert ("frontend", "REPAIRING") not in lane_changes and ("frontend", "COMPLETED") in lane_changes
    assert {e.lane for e in stored if e.step == "generate_backend"} == {"backend"}
    assert {e.lane for e in stored if e.step == "generate_frontend"} == {"frontend"}
    assert {e.lane for e in stored if e.step == "build_contract"} == {None}
    ready = next(e for e in stored if e.type == "contract.ready")
    assert ready.payload["operations"] == 10 and len(ready.payload["sha256"]) == 64
    assert stored[-1].type == "status.changed" and stored[-1].status == "COMPLETED_WITH_WARNINGS"
    assert stored[-1].payload["errorCode"] == "LANES_INCOMPLETE"


def test_dynamic_generation_with_inconsistent_specs_fails_before_any_engine_call(client, headers, tmp_path):
    generation_id = _submit(
        client, headers(), {"mode": "dynamic", "frontendSpec": SHOP_FRONTEND, "backendSpec": TWO_ENTITY}
    )
    assert run_job(tmp_path, generation_id) == "FAILED"
    row = generation(generation_id)
    assert row.lanes == {"backend": "SKIPPED", "frontend": "SKIPPED", "integration": "SKIPPED"}
    assert cli_invocations(generation_id) == []
    invalid = next(e for e in events(generation_id) if e.type == "spec.invalid")
    assert invalid.payload["total"] == 6
    assert {error["spec"] for error in invalid.payload["errors"]} == {"consistency"}
    assert invalid.payload["errors"][0]["backendPath"] == "/operations"
    assert row.error_summary.startswith("6 input error(s); first: consistency /pages/0/sections/1/data/operationId")


def test_static_generation_renders_the_site_without_the_engine(client, headers, tmp_path):
    """Story 17.2: every section of static-landing is in the section library, so no engine call is made."""
    deployed = []

    async def on_completed(generation_id):
        deployed.append(generation_id)

    auth = headers()
    generation_id = _submit(client, auth, {"mode": "static", "frontendSpec": LANDING})
    engine = FakeEngine(tmp_path, demo_scenario(0))
    assert run_job(tmp_path, generation_id, engine=engine, on_completed=on_completed) == "COMPLETED"
    row = generation(generation_id)
    assert row.lanes == {"frontend": "COMPLETED"} and row.error_summary is None
    assert [run.node for run in node_runs(generation_id)] == [
        "validate_inputs", "plan_frontend", "scaffold_frontend", "generate_assets", "generate_frontend",
        "validate_frontend", "package_artifacts",
    ]  # fmt: skip
    # Story 18.7: one engine call per drawing; LANDING has 2 illustrations (hero and work-1).
    assert [call.purpose for call in cli_invocations(generation_id)] == ["generate_assets", "generate_assets"]
    assert deployed == [generation_id]
    generate = next(run for run in node_runs(generation_id) if run.node == "generate_frontend")
    assert generate.summary == {"pages": 5, "sections": 11, "rendering": "renderer", "engineCalls": 0}
    rendered = next(e for e in events(generation_id) if e.type == "frontend.rendered")
    assert rendered.payload["pages"] == 5
    assert not [e for e in events(generation_id) if e.type == "validation.check" and e.status == "failed"]

    artifacts = _artifacts(client, auth, generation_id)
    expected = {"frontend-spec.json", "frontend-plan.json", "frontend.zip", "manifest.json", "report.json"}
    expected |= {"frontend-validation-1.json"}
    assert expected <= set(artifacts) and "frontend-repair-1.patch" not in artifacts
    assert "backend.zip" not in artifacts and "contract.json" not in artifacts
    report = client.get(
        f"/api/v1/generations/{generation_id}/artifacts/{artifacts['report.json']['artifactId']}", headers=auth
    ).json()
    assert report["outcome"] == "COMPLETED"
    manifest = client.get(
        f"/api/v1/generations/{generation_id}/artifacts/{artifacts['manifest.json']['artifactId']}", headers=auth
    ).json()
    assert manifest["mode"] == "static" and manifest["frontend"]["routes"][0]["route"] == "/"
    assert "contractSha256" not in manifest["frontend"]
    backend = client.post(f"/api/v1/generations/{generation_id}/preview/start", headers=auth)
    assert backend.status_code == 409
    frontend = client.post(f"/api/v1/generations/{generation_id}/preview/start?kind=frontend", headers=auth)
    assert frontend.status_code == 202 and frontend.json()["kind"] == "frontend"
    JobStore().delete_preview(generation_id, "frontend")  # no worker here; keep other tests' preview counts clean


def test_backend_generation_is_unchanged(client, headers, tmp_path):
    generation_id = _submit(client, headers(), {"backendSpec": TWO_ENTITY})
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED"
    row = generation(generation_id)
    assert row.mode == "backend" and row.lanes == {"backend": "COMPLETED"} and row.error_summary is None
    assert "contract.json" not in _artifacts(client, headers(), generation_id)
    assert node_runs(generation_id)[0].node == "validate_spec"


def test_a_dynamic_generation_gets_a_frontend_preview_the_backend_allows(client, headers, tmp_path):
    """Story 13.5: the frontend preview starts first (mock API on); the backend preview's CORS allows its origin."""
    import asyncio

    from preview_fakes import FakePreviewRuntime

    from src.libs.queue import PreviewCommandBus
    from src.libs.redaction import Redactor
    from src.modules.generations.infrastructure.adapters import EventPublisher
    from src.orchestrator.previews import PreviewService
    from workflow_helpers import redis_client

    auth = headers()
    body = {"mode": "dynamic", "frontendSpec": TRACKER_FRONTEND, "backendSpec": TWO_ENTITY}
    response = client.post("/api/v1/generations", json={**body, "options": {"engine": "fake"}}, headers=auth)
    generation_id = response.json()["generationId"]
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED_WITH_WARNINGS"
    backend, frontend = FakePreviewRuntime(), FakePreviewRuntime()
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            service = PreviewService(backend, store, events_, PreviewCommandBus(redis), frontend_runtime=frontend)
            assert service.startable(generation_id) == ["frontend", "backend"]
            for kind in service.startable(generation_id):
                await service.start(generation_id, kind)
        finally:
            await redis.aclose()

    try:
        asyncio.run(go())
        site, api = store.preview(generation_id, "frontend"), store.preview(generation_id, "backend")
        assert site.status == "RUNNING" and site.mock_api is True and api.status == "RUNNING"
        assert site.host_port != api.host_port
        assert frontend.options[generation_id] == {"mode": "dynamic", "mockApi": True, "apiBaseUrl": ""}
        assert f"http://localhost:{site.host_port}" in backend.options[generation_id]["corsOrigins"].split(",")
        detail = client.get(f"/api/v1/generations/{generation_id}", headers=auth).json()
        assert detail["frontendPreview"]["kind"] == "frontend" and detail["frontendPreview"]["mockApi"] is True
        assert detail["frontendPreview"]["openapiUrl"] is None and detail["preview"]["kind"] == "backend"
    finally:
        for kind in ("frontend", "backend"):
            store.delete_preview(generation_id, kind)
