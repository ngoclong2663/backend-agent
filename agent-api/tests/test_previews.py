import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from preview_fakes import FakePreviewRuntime

from src.configs import config
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.libs.queue import PreviewCommandBus
from src.libs.redaction import Redactor
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.enums import PreviewStatus
from src.orchestrator.previews import PreviewService
from src.orchestrator.store import JobStore
from workflow_helpers import completed_generation, events, redis_client, run_job, submit

pytestmark = pytest.mark.usefixtures("clean_redis")
STORE = JobStore()


@pytest.fixture(scope="module")
def completed(client, tmp_path_factory):
    return completed_generation(client, tmp_path_factory.mktemp("workspaces"))


@pytest.fixture(autouse=True)
def no_other_previews():
    for preview in STORE.previews():
        STORE.delete_preview(preview.generation_id, preview.kind)
    yield


def run(runtime: FakePreviewRuntime, *steps):
    """Runs (method, generation_id) steps against a PreviewService wired to the test DB and Redis."""

    async def go():
        redis = redis_client()
        try:
            service = PreviewService(runtime, STORE, EventPublisher(redis, Redactor()), PreviewCommandBus(redis))
            results = []
            for method, *args in steps:
                results.append(await getattr(service, method)(*args))
            return results
        finally:
            await redis.aclose()

    return asyncio.run(go())


def _artifact_names(generation_id: str) -> set[str]:
    return {a.name for a in STORE.artifacts(generation_id)}


def test_start_runs_the_backend_and_records_its_url(client, user_headers, completed):
    runtime = FakePreviewRuntime()

    run(runtime, ("start", completed))

    preview = STORE.preview(completed)
    assert preview.status == PreviewStatus.RUNNING and preview.host_port == config.preview_ports[0]
    assert preview.url == f"http://localhost:{preview.host_port}"
    assert timedelta(hours=1.9) < preview.expires_at - preview.started_at <= timedelta(hours=2)
    assert "preview-build.log" in _artifact_names(completed)
    assert [e.status for e in events(completed) if e.type == "preview.status"][-2:] == ["STARTING", "RUNNING"]
    body = client.get(f"/api/v1/generations/{completed}/preview", headers=user_headers).json()
    assert body["docsUrl"] == f"{preview.url}/docs" and body["openapiUrl"] == f"{preview.url}/openapi.json"
    detail = client.get(f"/api/v1/generations/{completed}", headers=user_headers).json()
    assert detail["preview"]["status"] == "RUNNING"


def test_a_failed_build_is_reported_with_its_log(completed):
    run(FakePreviewRuntime(fail="image build failed: pip"), ("start", completed))

    preview = STORE.preview(completed)
    assert preview.status == PreviewStatus.FAILED and "image build failed" in preview.error
    assert "preview-build.log" in _artifact_names(completed)


def test_stop_restart_reset_and_delete(completed):
    runtime = FakePreviewRuntime()
    run(runtime, ("start", completed), ("stop", completed))
    assert STORE.preview(completed).status == PreviewStatus.STOPPED

    run(runtime, ("restart", completed))
    preview = STORE.preview(completed)
    assert preview.status == PreviewStatus.RUNNING and preview.host_port == config.preview_ports[0]

    run(runtime, ("reset_db", completed))
    assert ("drop_database", completed) in runtime.calls and STORE.preview(completed).status == PreviewStatus.RUNNING

    run(runtime, ("delete", completed))
    assert STORE.preview(completed) is None and completed not in runtime.containers


def _running_previews(client, user_headers, count: int) -> list[str]:
    """Other generations with RUNNING previews, oldest access first."""
    ids = [submit(client, user_headers) for _ in range(count)]
    now = datetime.now(UTC)
    for index, generation_id in enumerate(ids):
        STORE.upsert_preview(
            generation_id,
            status=PreviewStatus.RUNNING,
            host_port=config.preview_ports[index],
            started_at=now,
            last_accessed_at=now - timedelta(minutes=10 - index),
        )
    return ids


def test_starting_beyond_the_limit_evicts_the_least_recently_used(client, user_headers, completed):
    others = _running_previews(client, user_headers, config.preview_max_running)
    runtime = FakePreviewRuntime()

    run(runtime, ("start", completed))

    assert STORE.preview(completed).status == PreviewStatus.RUNNING
    assert STORE.preview(completed).host_port == config.preview_ports[len(others)], "ports in use are skipped"
    evicted = STORE.preview(others[0])
    assert evicted.status == PreviewStatus.STOPPED and completed in evicted.error
    assert all(STORE.preview(g).status == PreviewStatus.RUNNING for g in others[1:])


def test_without_eviction_the_limit_fails_the_start(client, user_headers, completed, monkeypatch):
    monkeypatch.setattr(config, "preview_evict", False)
    _running_previews(client, user_headers, config.preview_max_running)

    run(FakePreviewRuntime(), ("start", completed))

    assert STORE.preview(completed).status == PreviewStatus.FAILED
    assert "PREVIEW_MAX_RUNNING" in STORE.preview(completed).error


def test_idle_previews_expire(completed):
    runtime = FakePreviewRuntime()
    run(runtime, ("start", completed))
    STORE.upsert_preview(completed, expires_at=datetime.now(UTC) - timedelta(seconds=1))

    assert run(runtime, ("expire",)) == [1]

    preview = STORE.preview(completed)
    assert preview.status == PreviewStatus.STOPPED and preview.error == "idle TTL reached"


def test_reconcile_syncs_rows_with_containers(client, user_headers, completed):
    runtime = FakePreviewRuntime()
    run(runtime, ("start", completed))
    runtime.containers[completed].app = "exited"  # e.g. crashed, or stopped by hand
    stuck = submit(client, user_headers)
    STORE.upsert_preview(stuck, status=PreviewStatus.STARTING, started_at=datetime.now(UTC) - timedelta(hours=1))
    runtime.containers["gen_ORPHAN"] = runtime.containers[completed].__class__(app="running", db="running")

    [result] = run(runtime, ("reconcile",))

    assert result == {"changed": 2, "removed": 1}
    assert STORE.preview(completed).status == PreviewStatus.STOPPED
    assert STORE.preview(stuck).status == PreviewStatus.FAILED
    assert "gen_ORPHAN" not in runtime.containers


def test_command_bus_round_trip(completed):
    runtime = FakePreviewRuntime()
    runtime.requests[completed] = [
        {"ts": "2026-10-26T10:00:00+00:00", "method": "GET", "path": "/tasks", "operationId": "task.list"},
        {"ts": "2026-10-26T10:00:01+00:00", "method": "POST", "path": "/tasks", "operationId": "task.create"},
    ]

    async def go():
        redis = redis_client()
        try:
            bus = PreviewCommandBus(redis)
            service = PreviewService(runtime, STORE, EventPublisher(redis, Redactor()), bus)

            async def worker():
                await service.handle(await bus.next(timeout_s=2))

            _, reply = await asyncio.gather(
                worker(), bus.call("requests", completed, after="2026-10-26T10:00:00+00:00", limit=10)
            )
            return reply
        finally:
            await redis.aclose()

    reply = asyncio.run(go())

    assert [item["operationId"] for item in reply["items"]] == ["task.create"]
    assert reply["cursor"] == "2026-10-26T10:00:01+00:00"


def test_seed_artifact_is_handed_to_the_preview(client, user_headers, tmp_path):
    from workflow_helpers import TWO_ENTITY

    spec = {**TWO_ENTITY, "seed": [{"entity": "Project", "records": [{"name": "Seeded"}]}]}
    generation_id = completed_generation(client, tmp_path, spec=spec)
    runtime = FakePreviewRuntime()

    run(runtime, ("start", generation_id))

    assert b'"table": "projects"' in runtime.seeds[generation_id]


def test_frontend_and_backend_start_concurrently_and_reserve_ports(completed):
    from pathlib import Path

    from src.orchestrator.packaging import ArtifactWriter

    writer = ArtifactWriter(Path(config.artifact_root), completed)
    writer.write("frontend.zip", "archive", b"PK\x05\x06" + b"\x00" * 18, "application/zip")
    STORE.replace_artifacts(completed, STORE.artifacts(completed) + writer.written)
    STORE.update_generation(
        completed,
        lanes={"backend": "COMPLETED", "frontend": "COMPLETED"},
        options={"deployPreview": True, "frontend": {"generatePreview": True}},
    )

    backend_rt = FakePreviewRuntime()
    frontend_rt = FakePreviewRuntime()

    async def go():
        redis = redis_client()
        try:
            service = PreviewService(
                backend_rt,
                STORE,
                EventPublisher(redis, Redactor()),
                PreviewCommandBus(redis),
                frontend_runtime=frontend_rt,
            )
            await asyncio.gather(
                service.start(completed, "frontend"),
                service.start(completed, "backend"),
            )
        finally:
            await redis.aclose()

    asyncio.run(go())

    fe_preview = STORE.preview(completed, "frontend")
    be_preview = STORE.preview(completed, "backend")

    assert fe_preview.status == PreviewStatus.RUNNING
    assert be_preview.status == PreviewStatus.RUNNING
    assert fe_preview.host_port is not None
    assert be_preview.host_port is not None
    assert fe_preview.host_port != be_preview.host_port
    assert str(fe_preview.host_port) in backend_rt.options[completed]["corsOrigins"]

    STORE.delete_preview(completed, "frontend")
    STORE.delete_preview(completed, "backend")


# -- API -----------------------------------------------------------------------------------------------------------


def _bus_next():
    async def go():
        redis = redis_client()
        try:
            return await PreviewCommandBus(redis).next(timeout_s=1)
        finally:
            await redis.aclose()

    return asyncio.run(go())


def test_api_start_records_the_request_and_queues_a_command(client, user_headers, completed):
    url = f"/api/v1/generations/{completed}/preview"

    response = client.post(f"{url}/start", headers=user_headers)

    assert response.status_code == 202 and response.json()["status"] == "STARTING"
    assert _bus_next() == {"op": "start", "generationId": completed, "args": {"kind": "backend"}}
    assert client.post(f"{url}/touch", headers=user_headers).status_code == 409, "not running yet"
    listed = client.get("/api/v1/previews", headers=user_headers).json()["items"]
    assert [p["generationId"] for p in listed] == [completed]


def test_api_touch_extends_a_running_preview(client, user_headers, completed):
    run(FakePreviewRuntime(), ("start", completed))
    STORE.upsert_preview(completed, expires_at=datetime.now(UTC) + timedelta(minutes=1))

    response = client.post(f"/api/v1/generations/{completed}/preview/touch", headers=user_headers)

    assert response.status_code == 200
    expires = datetime.fromisoformat(response.json()["expiresAt"])
    assert expires - datetime.now(UTC) > timedelta(hours=1.9)


def test_api_rejects_previews_of_unfinished_generations(client, user_headers):
    generation_id = submit(client, user_headers)

    response = client.post(f"/api/v1/generations/{generation_id}/preview/start", headers=user_headers)

    assert response.status_code == 409 and response.json()["error"]["code"] == "GENERATION_NOT_COMPLETED"
    assert client.post(f"/api/v1/generations/{generation_id}/preview/stop", headers=user_headers).status_code == 404


def test_api_limit_without_eviction(client, user_headers, completed, monkeypatch):
    monkeypatch.setattr(config, "preview_evict", False)
    _running_previews(client, user_headers, config.preview_max_running)

    response = client.post(f"/api/v1/generations/{completed}/preview/start", headers=user_headers)

    assert response.status_code == 409 and response.json()["error"]["code"] == "PREVIEW_LIMIT_REACHED"


def test_api_logs_need_a_worker(client, user_headers, completed):
    run(FakePreviewRuntime(), ("start", completed))

    response = client.get(f"/api/v1/generations/{completed}/preview/logs", headers=user_headers)

    assert response.status_code == 503 and response.json()["error"]["code"] == "WORKER_UNAVAILABLE"


def test_api_previews_are_owner_scoped(client, user_headers, login, completed):
    run(FakePreviewRuntime(), ("start", completed))
    other = {"Authorization": f"Bearer {login('other@test.local', 'otherpass')}"}
    admin = {"Authorization": f"Bearer {login('admin@test.local', 'adminpass')}"}

    assert client.get(f"/api/v1/generations/{completed}/preview", headers=other).status_code == 404
    assert client.post(f"/api/v1/generations/{completed}/preview/stop", headers=other).status_code == 404
    assert client.get("/api/v1/previews", headers=other).json()["items"] == []
    assert len(client.get("/api/v1/previews", params={"scope": "all"}, headers=admin).json()["items"]) == 1


def test_runner_requests_a_preview_on_completion(client, user_headers, tmp_path):
    requested = []

    async def on_completed(generation_id):
        requested.append(generation_id)

    wanted = submit(client, user_headers, deployPreview=True)
    skipped = submit(client, user_headers)  # deployPreview=False

    fast = FakeEngine(tmp_path, demo_scenario(0))
    assert run_job(tmp_path, wanted, engine=fast, on_completed=on_completed) == "COMPLETED"
    assert run_job(tmp_path, skipped, engine=fast, on_completed=on_completed) == "COMPLETED"

    # The runner reports every finished generation; the preview service decides which previews it gets.
    assert requested == [wanted, skipped]
    service = PreviewService(FakePreviewRuntime(), STORE, None, None, frontend_runtime=FakePreviewRuntime())
    assert service.startable(wanted) == ["backend"]
    assert service.startable(skipped) == []


def test_request_log_parsing_keeps_only_app_calls():
    from src.preview.docker_preview import parse_request_lines

    text = "\n".join(
        [
            'INFO:     172.22.0.1:1 - "GET /projects HTTP/1.1" 200 OK',
            '{"ts": "2026-10-26T10:00:00+00:00", "message": "request", "method": "OPTIONS", "path": "/projects"}',
            '{"ts": "2026-10-26T10:00:01+00:00", "message": "request", "method": "GET", "path": "/projects",'
            ' "route": "/projects", "operationId": "project.list", "status": 200, "durationMs": 4.2}',
            '{"ts": "2026-10-26T10:00:02+00:00", "message": "task created"}',
        ]
    )

    items = parse_request_lines(text, after=None)

    assert [(i["method"], i["operationId"], i["status"]) for i in items] == [("GET", "project.list", 200)]
    assert parse_request_lines(text, after="2026-10-26T10:00:01+00:00") == []
