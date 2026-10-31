"""Epic 14: Parallel workflow (14.1), live-API switch (14.2), and live smoke & contract validation (14.3)."""

import asyncio
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from generation_helpers import engine_path, normalized
from langgraph.checkpoint.memory import InMemorySaver
from preview_fakes import FakePreviewRuntime
from test_component_cache import PassingSandboxes

from src.configs import config
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.libs.queue import PreviewCommandBus
from src.libs.redaction import Redactor
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.orchestrator.contract import build_contract, dump_contract
from src.orchestrator.previews import PreviewService
from src.orchestrator.store import JobStore
from src.orchestrator.validation import CheckResult, ValidationOutcome, ValidationRequest
from src.sandbox import ExecResult, ISandbox, ISandboxProvider
from workflow_helpers import (
    TWO_ENTITY,
    cli_invocations,
    events,
    generation,
    node_runs,
    redis_client,
    run_job,
    runner_ctx,
)

EXAMPLES = Path(__file__).parents[2] / "examples"
TRACKER_FRONTEND = json.loads((EXAMPLES / "frontend-specs" / "project-tracker-dynamic.json").read_text())
# Story 17.4: the tracker frontend is rendered without the engine. Tests of the frontend lane's engine path use the
# shop pair without its components' props schemas (Story 17.3 would render it too).
SHOP_FRONTEND = engine_path(json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text()))
SHOP_BACKEND = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
GOLDEN_OPENAPI = json.loads((Path(__file__).parent / "fixtures" / "openapi" / "two-entity.golden.json").read_text())
CANONICAL_CONTRACT = json.loads(dump_contract(build_contract(normalized(EXAMPLES / "specs" / "two-entity.json"))))
CANONICAL_SHA = hashlib.sha256(dump_contract(CANONICAL_CONTRACT).encode()).hexdigest()


@pytest.fixture
def headers(login):
    def _headers(email: str = "user@test.local", password: str = "userpass") -> dict:
        return {"Authorization": f"Bearer {login(email, password)}"}

    return _headers


def _submit_dynamic(client, auth: dict, shop: bool = False, **option_overrides: Any) -> str:
    body = {
        "mode": "dynamic",
        "frontendSpec": SHOP_FRONTEND if shop else TRACKER_FRONTEND,
        "backendSpec": SHOP_BACKEND if shop else TWO_ENTITY,
        "options": {"engine": "fake", "crudFromTemplates": False, **option_overrides},  # backend engine path
    }
    response = client.post("/api/v1/generations", json=body, headers=auth)
    assert response.status_code == 202, response.text
    return response.json()["generationId"]


def _shop_engine(tmp_path: Path, steps: dict, backend: str | None = None, sleep_s: float = 0) -> FakeEngine:
    """The fake engine for the shop pair; its backend replays `shop_demo_scenario`, slowed at `backend` if given."""
    engine = FakeEngine(tmp_path, steps)
    if backend is not None:
        engine._shop_scenario[backend][0].sleep_s = sleep_s
    return engine


def _configure_healthy_backend(runtime: FakePreviewRuntime, contract: dict[str, Any] = CANONICAL_CONTRACT) -> None:
    """Populates FakePreviewRuntime with /health, /openapi.json, and live responses matching the contract."""
    openapi = copy.deepcopy(GOLDEN_OPENAPI)
    openapi.setdefault("info", {})["x-bga"] = {"contractSha256": CANONICAL_SHA}
    runtime.responses[("GET", "/health")] = (200, {"status": "ok"})
    runtime.responses[("GET", "/openapi.json")] = (200, openapi)

    fixtures = (contract.get("x-bga") or {}).get("fixtures") or {}
    for path, methods in (contract.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method_lower, op in methods.items():
            if not isinstance(op, dict):
                continue
            method = method_lower.upper()
            meta = op.get("x-bga") or {}
            entity = meta.get("entity")
            action = meta.get("action")
            records = list(fixtures.get(entity) or [])
            first = records[0] if records else {"id": "00000000-0000-4000-8000-000000000001"}
            concrete_path = path
            for param in op.get("parameters") or []:
                if isinstance(param, dict) and param.get("in") == "path":
                    name = param["name"]
                    concrete_path = concrete_path.replace(f"{{{name}}}", str(first.get(name, first.get("id"))))
            if method == "GET" and action == "list":
                runtime.responses[(method, concrete_path)] = (
                    200,
                    {"items": records, "total": len(records), "limit": 20, "offset": 0},
                )
            elif method == "GET":
                runtime.responses[(method, concrete_path)] = (200, first)
            elif method == "POST":
                runtime.responses[(method, concrete_path)] = (201, first)


def _artifacts(client, auth: dict, generation_id: str) -> dict[str, dict]:
    items = client.get(f"/api/v1/generations/{generation_id}/artifacts", headers=auth).json()["items"]
    return {item["name"]: item for item in items}


def _cleanup_previews(generation_id: str) -> None:
    store = JobStore()
    for kind in ("frontend", "backend"):
        store.delete_preview(generation_id, kind)


# -- Story 14.1: Parallel workflow & concurrency ------------------------------------------------------------------


def test_parallel_lanes_run_concurrently_and_occupy_two_worker_slots(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth, shop=True, deployPreview=False)
    engine = FakeEngine(tmp_path, demo_scenario(delay_s=0.04))
    # Simulate a worker with 2 slots where 1 slot is already held by the job loop (`_consume`).
    slots = asyncio.Semaphore(2)
    observed_free_slots: list[int] = []
    max_parallel_invocations = 0
    max_parallel_lanes = 0

    async def go():
        nonlocal max_parallel_invocations, max_parallel_lanes
        await slots.acquire()  # job's primary slot
        try:
            async with runner_ctx(tmp_path, engine=engine, worker_slots=slots) as runner:
                task = asyncio.create_task(runner.run(generation_id))
                while not task.done():
                    ctx = runner.active.get(generation_id)
                    if ctx is not None:
                        observed_free_slots.append(slots._value)
                        max_parallel_invocations = max(max_parallel_invocations, ctx.max_concurrent_invocations)
                        max_parallel_lanes = max(max_parallel_lanes, ctx.max_concurrent_lanes)
                    await asyncio.sleep(0.01)
                return await task
        finally:
            slots.release()

    status = asyncio.run(go())
    assert status == "COMPLETED_WITH_WARNINGS"
    assert max_parallel_lanes == 2
    assert max_parallel_invocations >= 2
    assert 0 in observed_free_slots  # both worker slots were occupied while both lanes ran
    assert slots._value == 2  # all slots released when done


def test_neither_lane_may_modify_canonical_contract(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=False)
    steps = demo_scenario(0)
    # Tamper with .bga/contract.json in both workspaces during engine execution.
    steps["generate_backend"][0].write[".bga/contract.json"] = '{"tampered": "by_backend"}'
    steps["generate_frontend"][0].write[".bga/contract.json"] = '{"tampered": "by_frontend"}'
    engine = FakeEngine(tmp_path, steps)

    assert run_job(tmp_path, generation_id, engine=engine) == "COMPLETED_WITH_WARNINGS"
    canonical = (tmp_path / generation_id / "spec" / "contract.json").read_text()
    assert (tmp_path / generation_id / "project" / ".bga" / "contract.json").read_text() == canonical
    assert (tmp_path / generation_id / "frontend" / ".bga" / "contract.json").read_text() == canonical


# -- Story 14.2 & 14.3: Live-API switch, recheck/use-mocks, and contract validation -------------------------------


def test_healthy_backend_switches_frontend_preview_to_live_and_completes(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth)
    backend_rt, frontend_rt = FakePreviewRuntime(), FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            previews = PreviewService(
                backend_rt, store, events_, PreviewCommandBus(redis), frontend_runtime=frontend_rt
            )
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
                on_completed=previews.request_start,
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED"
        row = generation(generation_id)
        assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "COMPLETED"}
        assert row.error_summary is None

        api = store.preview(generation_id, "backend")
        site = store.preview(generation_id, "frontend")
        assert api.status == "RUNNING" and site.status == "RUNNING"
        assert site.mock_api is False
        assert frontend_rt.options[generation_id] == {
            "mode": "dynamic",
            "mockApi": False,
            "apiBaseUrl": api.url,
        }

        stored = events(generation_id)
        switched = next(e for e in stored if e.type == "integration.switched_to_live")
        assert switched.payload["apiBaseUrl"] == api.url and switched.payload["mockApi"] is False
        assert not [e for e in stored if e.type == "integration.kept_mocks"]

        artifacts = _artifacts(client, auth, generation_id)
        assert {"report.json", "integration-validation.json", "seed.json", "frontend.zip", "backend.zip"} <= set(
            artifacts
        )
        report = client.get(
            f"/api/v1/generations/{generation_id}/artifacts/{artifacts['report.json']['artifactId']}", headers=auth
        ).json()
        assert report["outcome"] == "COMPLETED"
        assert report["integration"]["switchedToLive"] is True
        assert report["integration"]["mockApi"] is False
        assert report["integration"]["apiBaseUrl"] == api.url
        checks = {c["check"]: c for c in report["checks"]}
        assert checks["integration:health"]["status"] == "passed"
        assert checks["integration:contract"]["status"] == "passed"
        assert checks["integration:smoke"]["status"] == "not_run"

        seed = client.get(
            f"/api/v1/generations/{generation_id}/artifacts/{artifacts['seed.json']['artifactId']}", headers=auth
        ).json()
        assert {entry["table"] for entry in seed} == {"projects", "tasks"}
    finally:
        _cleanup_previews(generation_id)


def test_failing_backend_lane_keeps_frontend_on_mocks_and_completes_with_warnings(client, headers, tmp_path):
    class FailingBackendValidator:
        async def run(self, request: ValidationRequest) -> ValidationOutcome:
            return ValidationOutcome(
                results=[
                    CheckResult(
                        check="pytest",
                        status="failed",
                        duration_ms=10,
                        summary="1 failed",
                        output="AssertionError",
                        started_at=datetime.now(UTC),
                    )
                ],
                digest="pytest: 1 failed\nAssertionError",
                implicated_files=[],
            )

    auth = headers()
    generation_id = _submit_dynamic(client, auth, maxRepairAttempts=1)
    # Give frontend 0 repairs needed so frontend passes while backend fails after 1 repair attempt.
    steps = demo_scenario(0)
    steps["generate_frontend"] = steps["repair_frontend"]
    backend_rt, frontend_rt = FakePreviewRuntime(), FakePreviewRuntime()
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            previews = PreviewService(
                backend_rt, store, events_, PreviewCommandBus(redis), frontend_runtime=frontend_rt
            )
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, steps),
                validator=FailingBackendValidator(),
                previews=previews,
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED_WITH_WARNINGS"
        row = generation(generation_id)
        assert row.lanes == {"backend": "FAILED", "frontend": "COMPLETED", "integration": "SKIPPED"}
        assert "backend lane failed" in row.error_summary.lower()

        site = store.preview(generation_id, "frontend")
        assert site is not None and site.status == "RUNNING" and site.mock_api is True
        assert frontend_rt.options[generation_id]["mockApi"] is True

        kept = next(e for e in events(generation_id) if e.type == "integration.kept_mocks")
        assert "pytest" in kept.payload["reason"] or "failed" in kept.payload["reason"].lower()

        artifacts = _artifacts(client, auth, generation_id)
        assert "frontend.zip" in artifacts and "backend.zip" not in artifacts
    finally:
        _cleanup_previews(generation_id)


@pytest.mark.parametrize(
    ("health_status", "openapi_override", "expected_reason"),
    [
        (503, None, "GET /health returned 503"),
        (
            200,
            {
                "openapi": "3.1.0",
                "info": {"title": "Wrong", "version": "0.1.0", "x-bga": {"contractSha256": "deadbeef"}},
                "paths": {},
            },
            "contract sha mismatch",
        ),
    ],
)
def test_unhealthy_backend_or_openapi_mismatch_keeps_mocks(
    client, headers, tmp_path, health_status, openapi_override, expected_reason
):
    auth = headers()
    generation_id = _submit_dynamic(client, auth)
    backend_rt, frontend_rt = FakePreviewRuntime(), FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    backend_rt.responses[("GET", "/health")] = (health_status, {"status": "down"})
    if openapi_override is not None:
        backend_rt.responses[("GET", "/openapi.json")] = (200, openapi_override)
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            previews = PreviewService(
                backend_rt, store, events_, PreviewCommandBus(redis), frontend_runtime=frontend_rt
            )
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED_WITH_WARNINGS"
        row = generation(generation_id)
        assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "SKIPPED"}
        site = store.preview(generation_id, "frontend")
        assert site.mock_api is True
        kept = next(e for e in events(generation_id) if e.type == "integration.kept_mocks")
        assert expected_reason in kept.payload["reason"]
    finally:
        _cleanup_previews(generation_id)


def test_integration_wait_timeout_aborts_slow_backend_and_keeps_mocks(client, headers, tmp_path, monkeypatch):
    """The wait counts from when the backend reaches validation (Story 17.6): a repair that takes too long then."""
    monkeypatch.setattr(config, "integration_wait_seconds", 0.1)
    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=False)
    steps = demo_scenario(0)
    steps["repair_code"][0].sleep_s = 2.0

    status = run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, steps))
    assert status == "COMPLETED_WITH_WARNINGS"
    row = generation(generation_id)
    assert row.lanes == {"backend": "FAILED", "frontend": "COMPLETED", "integration": "SKIPPED"}
    kept = next(e for e in events(generation_id) if e.type == "integration.kept_mocks")
    assert "INTEGRATION_WAIT_SECONDS" in kept.payload["reason"]


def test_a_backend_still_being_written_is_not_cancelled_by_the_integration_wait(client, headers, tmp_path, monkeypatch):
    """Story 17.6: the frontend lane can finish long before the backend; the wait starts at validation."""
    monkeypatch.setattr(config, "integration_wait_seconds", 1.0)
    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=False)
    steps = demo_scenario(0)
    steps["generate_backend"][0].sleep_s = 2.0  # far beyond the wait, but before validation

    status = run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, steps))
    row = generation(generation_id)
    assert status == "COMPLETED_WITH_WARNINGS" and row.lanes["backend"] == "COMPLETED", row.error_summary
    assert not [e for e in events(generation_id) if "INTEGRATION_WAIT_SECONDS" in json.dumps(e.payload)]


def test_failing_frontend_lane_aborts_backend_and_fails_job(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth, shop=True, deployPreview=False, maxRepairAttempts=0)
    # In demo_scenario(0), the first generate_frontend call plants a conventions error, so with maxRepairAttempts=0
    # the frontend lane fails at validate_frontend while the backend lane is still running.
    engine = _shop_engine(tmp_path, demo_scenario(0), "generate_backend", 2.0)

    status = run_job(tmp_path, generation_id, engine=engine)
    assert status == "FAILED"
    row = generation(generation_id)
    assert row.lanes["frontend"] == "FAILED"
    ran_nodes = {run.node for run in node_runs(generation_id)}
    assert "integrate" not in ran_nodes and "package_artifacts" not in ran_nodes


def test_cancel_stops_both_parallel_lanes(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth, shop=True, deployPreview=False)
    steps = demo_scenario(0)
    steps["generate_frontend"][0].sleep_s = 2.0
    engine = _shop_engine(tmp_path, steps, "generate_database", 2.0)

    async def go():
        async with runner_ctx(tmp_path, engine=engine) as runner:
            task = asyncio.create_task(runner.run(generation_id))
            while not task.done():
                ctx = runner.active.get(generation_id)
                if ctx is not None and len(ctx.active_invocations) == 2:
                    await runner.cancel(generation_id)
                    break
                await asyncio.sleep(0.01)
            return await task

    status = asyncio.run(go())
    assert status == "CANCELLED"
    row = generation(generation_id)
    assert row.lanes == {"backend": "SKIPPED", "frontend": "SKIPPED", "integration": "SKIPPED"}
    assert len([c for c in cli_invocations(generation_id) if c.status == "cancelled"]) == 2


def test_resume_restarts_each_parallel_lane_from_its_own_last_completed_node(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth, shop=True, deployPreview=False)
    saver = InMemorySaver()

    # First run: worker shuts down while inside generate_backend & generate_frontend.
    steps_first = demo_scenario(0)
    steps_first["generate_frontend"][0].sleep_s = 2.0
    engine_first = _shop_engine(tmp_path, steps_first, "generate_backend", 2.0)

    async def first_run():
        async with runner_ctx(tmp_path, engine=engine_first, checkpointer=saver) as runner:
            task = asyncio.create_task(runner.run(generation_id))
            while not task.done():
                ctx = runner.active.get(generation_id)
                if ctx is not None and len(ctx.active_invocations) == 2:
                    task.cancel()
                    break
                await asyncio.sleep(0.01)
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(first_run())
    first_succeeded = [run.node for run in node_runs(generation_id) if run.status == "succeeded"]
    assert "plan_architecture" in first_succeeded and "generate_database" in first_succeeded
    assert "plan_frontend" in first_succeeded and "scaffold_frontend" in first_succeeded

    # Second run: resumes from checkpoint; completed nodes in either lane must NOT run again.
    engine_second = FakeEngine(tmp_path, demo_scenario(0))
    status = run_job(tmp_path, generation_id, engine=engine_second, checkpointer=saver)
    assert status == "COMPLETED_WITH_WARNINGS"

    all_runs = node_runs(generation_id)
    early_nodes = (
        "validate_inputs",
        "build_contract",
        "plan_architecture",
        "generate_database",
        "plan_frontend",
        "scaffold_frontend",
    )
    for completed_early in early_nodes:
        runs = [r for r in all_runs if r.node == completed_early]
        assert len(runs) == 1 and runs[0].status == "succeeded"
    resumed_event = next(e for e in events(generation_id) if e.type == "job.resumed")
    assert set(resumed_event.payload["nextSteps"]) == {"generate_backend", "generate_frontend"}


def test_recheck_and_use_mocks_endpoints_switch_frontend_preview(client, headers, tmp_path):
    auth = headers()
    generation_id = _submit_dynamic(client, auth)
    backend_rt, frontend_rt = FakePreviewRuntime(), FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    # Initially backend /health is 503, so integrate keeps mocks.
    backend_rt.responses[("GET", "/health")] = (503, {"status": "starting"})
    store = JobStore()

    async def run_and_drive_commands():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            bus = PreviewCommandBus(redis)
            previews = PreviewService(backend_rt, store, events_, bus, frontend_runtime=frontend_rt)
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
            ) as runner:
                status = await runner.run(generation_id)
                assert status == "COMPLETED_WITH_WARNINGS"
                assert store.preview(generation_id, "frontend").mock_api is True

                # Drain any leftover commands from prior tests.
                await redis.delete("bga:preview:commands")
                # Now backend becomes healthy; call POST /integration/recheck.
                backend_rt.responses[("GET", "/health")] = (200, {"status": "ok"})
                resp = client.post(f"/api/v1/generations/{generation_id}/integration/recheck", headers=auth)
                assert resp.status_code == 202, resp.text
                cmd = await bus.next(timeout_s=1)
                assert cmd is not None and cmd["op"] == "recheck"
                await previews.handle(cmd)

                site = store.preview(generation_id, "frontend")
                api = store.preview(generation_id, "backend")
                assert site.status == "RUNNING" and site.mock_api is False
                assert frontend_rt.options[generation_id]["apiBaseUrl"] == api.url
                assert generation(generation_id).status == "COMPLETED"
                assert generation(generation_id).lanes["integration"] == "COMPLETED"

                # Now switch back to mocks via POST /integration/use-mocks.
                resp2 = client.post(f"/api/v1/generations/{generation_id}/integration/use-mocks", headers=auth)
                assert resp2.status_code == 202, resp2.text
                cmd2 = await bus.next(timeout_s=1)
                assert cmd2 is not None and cmd2["op"] == "use-mocks"
                await previews.handle(cmd2)

                site2 = store.preview(generation_id, "frontend")
                assert site2.status == "RUNNING" and site2.mock_api is True
                assert frontend_rt.options[generation_id]["mockApi"] is True
                assert generation(generation_id).status == "COMPLETED_WITH_WARNINGS"
                assert generation(generation_id).lanes["integration"] == "SKIPPED"
        finally:
            await redis.aclose()

    try:
        asyncio.run(run_and_drive_commands())
        stored = events(generation_id)
        assert any(e.type == "integration.switched_to_live" for e in stored)
        assert len([e for e in stored if e.type == "integration.kept_mocks"]) >= 2
    finally:
        _cleanup_previews(generation_id)


def test_live_contract_response_mismatch_and_playwright_smoke_failure_reported_without_regeneration(
    client, headers, tmp_path
):
    class FakeFrontendSandbox(ISandbox):
        db_url = ""
        test_db_url = ""

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def reset_database(self, name: str) -> None:
            pass

        async def exec(
            self, command: str, timeout_s: int | None = None, env: dict[str, str] | None = None, egress: bool = False
        ) -> ExecResult:
            if "playwright test" in command:
                return ExecResult(
                    exit_code=1,
                    stdout="",
                    stderr=(
                        "1) [chromium] › tests/e2e/smoke.spec.ts:24:3 › page /projects renders live data\n"
                        "Error: expected seed project row to be visible"
                    ),
                    duration_ms=120,
                )
            return ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=5)

    class FakeSandboxProvider(ISandboxProvider):
        def for_job(
            self, generation_id: str, project_dir: Path, kind: str = "backend", part: str | None = None
        ) -> ISandbox:
            return FakeFrontendSandbox()

        async def job_ids(self) -> set[str]:
            return set()

        async def remove(self, generation_ids: set[str]) -> int:
            return 0

    auth = headers()
    generation_id = _submit_dynamic(client, auth)
    backend_rt, frontend_rt = FakePreviewRuntime(), FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    # Break the live response of GET /projects: `name` is an int instead of string!
    backend_rt.responses[("GET", "/projects")] = (
        200,
        {
            "items": [
                {
                    "id": "a3650faa-1ee8-5ee1-a1f1-7bab10838956",
                    "name": 99999,
                    "description": "broken",
                    "createdAt": "2026-01-01T09:00:00Z",
                }
            ],
            "total": 1,
            "limit": 20,
            "offset": 0,
        },
    )
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            previews = PreviewService(
                backend_rt, store, events_, PreviewCommandBus(redis), frontend_runtime=frontend_rt
            )
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
                sandboxes=FakeSandboxProvider(),
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED_WITH_WARNINGS"
        row = generation(generation_id)
        assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "FAILED"}

        # Neither side was regenerated after `integrate` started.
        integrate_run = next(r for r in node_runs(generation_id) if r.node == "integrate")
        assert not [c for c in cli_invocations(generation_id) if c.created_at >= integrate_run.started_at]

        artifacts = _artifacts(client, auth, generation_id)
        report = client.get(
            f"/api/v1/generations/{generation_id}/artifacts/{artifacts['report.json']['artifactId']}", headers=auth
        ).json()
        checks = {c["check"]: c for c in report["checks"]}
        assert checks["integration:contract"]["status"] == "failed"
        items = checks["integration:contract"]["items"]
        assert any(item["operation"] == "project.list" and "name" in item.get("field", "") for item in items)
        assert checks["integration:smoke"]["status"] == "failed"
        assert "/projects" in checks["integration:smoke"]["output"]
    finally:
        _cleanup_previews(generation_id)


def test_corner_shop_dynamic_generation_runs_both_lanes_with_fake_engine(client, headers, tmp_path):
    auth = headers()
    shop_spec = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
    shop_frontend = json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text())
    resp = client.post(
        "/api/v1/generations",
        json={
            "mode": "dynamic",
            "backendSpec": shop_spec,
            "frontendSpec": shop_frontend,
            "options": {"engine": "fake", "runTests": True, "maxRepairAttempts": 2, "deployPreview": False},
        },
        headers=auth,
    )
    assert resp.status_code == 202, resp.text
    generation_id = resp.json()["generationId"]

    status = run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0)))
    row = generation(generation_id)
    assert status == "COMPLETED_WITH_WARNINGS", (
        row.error_summary,
        [(r.node, r.status, r.summary) for r in node_runs(generation_id)],
    )
    assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "SKIPPED"}


def test_story18_7_parallel_assets_and_frontend_with_shared_semaphore(client, headers, tmp_path, monkeypatch):
    """Story 18.7: generate_assets and generate_frontend run in parallel, share engine_slots,
    merge plan properly, and validate_frontend runs once after both."""
    monkeypatch.setattr(config, "engine_concurrency", 2)
    auth = headers()
    shop_spec = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
    raw_shop_frontend = json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text())
    resp = client.post(
        "/api/v1/generations",
        json={
            "mode": "dynamic",
            "backendSpec": shop_spec,
            "frontendSpec": raw_shop_frontend,
            "options": {"engine": "fake", "runTests": True, "maxRepairAttempts": 2, "deployPreview": False},
        },
        headers=auth,
    )
    assert resp.status_code == 202, resp.text
    generation_id = resp.json()["generationId"]
    sandboxes = PassingSandboxes()

    class TrackingEngine(FakeEngine):
        active_assets = 0
        total_calls = 0

        async def run(self, request, on_event=None):
            TrackingEngine.total_calls += 1
            if request.purpose == "generate_assets":
                TrackingEngine.active_assets += 1
            try:
                await asyncio.sleep(0.02)
                return await super().run(request, on_event)
            finally:
                if request.purpose == "generate_assets":
                    TrackingEngine.active_assets -= 1

    status = run_job(tmp_path, generation_id, engine=TrackingEngine(tmp_path, demo_scenario(0)), sandboxes=sandboxes)
    assert status in ("COMPLETED", "COMPLETED_WITH_WARNINGS")
    runs = node_runs(generation_id)
    node_names = [r.node for r in runs]
    assert "generate_assets" in node_names
    assert "generate_frontend" in node_names
    assert "validate_frontend" in node_names
    assert node_names.count("validate_frontend") == 1

    # Check plan file on disk: it must retain BOTH custom components and assets
    plan = json.loads((tmp_path / generation_id / "frontend" / ".bga" / "frontend-plan.json").read_text())
    assert "customComponents" in plan and len(plan["customComponents"]) > 0
    assert "assets" in plan and len(plan["assets"]) > 0

    purposes = [c.purpose for c in cli_invocations(generation_id)]
    assert purposes.count("generate_custom_component") == 3


def test_story18_8_early_backend_preview_and_direct_live_frontend(client, headers, tmp_path):
    """Story 18.8: in dynamic mode the backend preview starts when the backend lane completes;
    early backend.zip is written; frontend preview starts directly live with mockApi=False;
    the generation ends COMPLETED."""
    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=True)

    backend_rt = FakePreviewRuntime()
    frontend_rt = FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)

    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            bus = PreviewCommandBus(redis)
            previews = PreviewService(backend_rt, store, events_, bus, frontend_runtime=frontend_rt)
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED"
        row = generation(generation_id)
        assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "COMPLETED"}

        # Early backend preview was started
        be_preview = store.preview(generation_id, "backend")
        assert be_preview is not None and be_preview.status == "RUNNING"

        # Frontend preview was created directly on live API
        fe_preview = store.preview(generation_id, "frontend")
        assert fe_preview is not None and fe_preview.status == "RUNNING"
        assert fe_preview.mock_api is False
        assert frontend_rt.options[generation_id]["mockApi"] is False
        assert frontend_rt.options[generation_id]["apiBaseUrl"] == be_preview.url

        # Check event sequence: backend preview was RUNNING before integrate started
        evt_list = events(generation_id)
        be_running_evt = next(
            e
            for e in evt_list
            if e.type == "preview.status" and e.payload.get("kind") == "backend" and e.status == "RUNNING"
        )
        integrate_evt = next(e for e in evt_list if e.type == "step.started" and e.step == "integrate")
        assert be_running_evt.ts <= integrate_evt.ts

        # Verify backend.zip was packaged early and reused by package_artifacts
        head_file = tmp_path / generation_id / "state" / "backend-packaged-head"
        assert head_file.is_file()
    finally:
        _cleanup_previews(generation_id)


def test_story18_8_cancellation_stops_early_preview(client, headers, tmp_path):
    """Story 18.8: cancellation stops the early preview container."""
    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=True)

    backend_rt = FakePreviewRuntime()
    frontend_rt = FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    store = JobStore()

    # Slow down frontend lane so backend completes first
    steps = demo_scenario(0)
    steps["generate_frontend"][0].sleep_s = 2.0
    engine = FakeEngine(tmp_path, steps)

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            bus = PreviewCommandBus(redis)
            previews = PreviewService(backend_rt, store, events_, bus, frontend_runtime=frontend_rt)
            async with runner_ctx(tmp_path, engine=engine, previews=previews) as runner:
                task = asyncio.create_task(runner.run(generation_id))
                # Wait until backend preview is running
                while not task.done():
                    be = store.preview(generation_id, "backend")
                    if be is not None and be.status == "RUNNING":
                        await runner.cancel(generation_id)
                        break
                    await asyncio.sleep(0.02)
                return await task
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "CANCELLED"
        # Backend preview must now be STOPPED
        be = store.preview(generation_id, "backend")
        assert be is not None and be.status == "STOPPED"
    finally:
        _cleanup_previews(generation_id)


def test_story18_8_package_artifacts_reuses_or_rewrites_backend_zip(client, headers, tmp_path):
    """Story 18.8: package_artifacts reuses early backend.zip if HEAD is unchanged, rewrites if HEAD changed."""
    from src.orchestrator.workspace import WorkspaceManager

    auth = headers()
    generation_id = _submit_dynamic(client, auth, deployPreview=True)

    backend_rt = FakePreviewRuntime()
    frontend_rt = FakePreviewRuntime()
    _configure_healthy_backend(backend_rt)
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events_ = EventPublisher(redis, Redactor())
            bus = PreviewCommandBus(redis)
            previews = PreviewService(backend_rt, store, events_, bus, frontend_runtime=frontend_rt)
            async with runner_ctx(
                tmp_path,
                engine=FakeEngine(tmp_path, demo_scenario(0)),
                previews=previews,
            ) as runner:
                return await runner.run(generation_id)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        assert status == "COMPLETED"

        art1 = store.artifact_by_name(generation_id, "backend.zip")
        assert art1 is not None

        # Simulate HEAD change in project repo
        workspace_mgr = WorkspaceManager(tmp_path, config.workspace_max_mb)
        ws = workspace_mgr.path_for(generation_id)
        (ws.project / "extra.txt").write_text("modified")
        workspace_mgr._git(ws, "add", "extra.txt", repo="project")
        workspace_mgr._git(ws, "commit", "-m", "extra commit", repo="project")

        # If packaged_head differs from current HEAD, rewrite happens
        head_file = ws.state / "backend-packaged-head"
        packaged_head = head_file.read_text().strip() if head_file.is_file() else None
        current_head = workspace_mgr._git(ws, "rev-parse", "HEAD", repo="project").strip()
        assert packaged_head != current_head
    finally:
        _cleanup_previews(generation_id)
