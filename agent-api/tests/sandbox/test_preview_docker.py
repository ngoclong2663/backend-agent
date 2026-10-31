"""A generated backend really runs as its own container (Stories 7.1, 7.3, 7.4). Opt in with BGA_SANDBOX_TESTS=1
(needs Docker, the runner image and network access for the preview image's pip install).

The preview image is built from backend.zip alone, so this also proves the ZIP starts on its own (DoD step 13)."""

import asyncio
import json
import os
import shutil
import time
import uuid

import docker
import httpx
import pytest

from src.engines import EngineContext, PromptLibrary
from src.engines.registry import engine_skills
from src.libs.queue import PreviewCommandBus
from src.libs.redaction import Redactor
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.enums import PreviewStatus
from src.orchestrator.previews import PreviewService
from src.orchestrator.store import JobStore
from src.orchestrator.validation import SandboxValidationRunner
from src.preview.docker_preview import DockerPreviewRuntime, names
from src.sandbox import DockerSandboxProvider
from tests.generation_helpers import REPO
from tests.workflow_helpers import TWO_ENTITY, generation, redis_client, run_job, submit

pytestmark = pytest.mark.skipif(os.environ.get("BGA_SANDBOX_TESTS") != "1", reason="sandbox tests are opt-in")
SEEDED = {"entity": "Project", "records": [{"name": "Seeded project", "description": "from seed[]"}]}


def _call(runtime, store, method, *args):
    async def go():
        redis = redis_client()
        service = PreviewService(runtime, store, EventPublisher(redis, Redactor()), PreviewCommandBus(redis))
        try:
            return await getattr(service, method)(*args)
        finally:
            await redis.aclose()

    return asyncio.run(go())


def test_completed_backend_runs_as_its_own_container(client, user_headers):
    root = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10]
    root.mkdir(parents=True)
    runtime, store = DockerPreviewRuntime(), JobStore()
    generation_id = submit(client, user_headers, spec={**TWO_ENTITY, "seed": [SEEDED]})
    try:
        skills = [skill.path for skill in engine_skills()]
        context = EngineContext(conventions=PromptLibrary().conventions(), skill_dirs=skills)
        status = run_job(
            root,
            generation_id,
            validator=SandboxValidationRunner(),
            sandboxes=DockerSandboxProvider(),
            engine_context=context,
        )
        assert status == "COMPLETED", generation(generation_id).error_summary
        artifacts = {a.name: a for a in store.artifacts(generation_id)}
        assert {"backend.zip", "openapi.json", "manifest.json", "seed.json"} <= set(artifacts)
        detail = client.get(f"/api/v1/generations/{generation_id}", headers=user_headers).json()
        manifest_id = next(a["artifactId"] for a in detail["artifacts"] if a["name"] == "manifest.json")
        manifest = client.get(f"/api/v1/generations/{generation_id}/artifacts/{manifest_id}", headers=user_headers)
        assert manifest.json()["api"]["source"] == "openapi" and manifest.json()["contractProblems"] == []

        _call(runtime, store, "start", generation_id)

        preview = store.preview(generation_id)
        assert preview.status == PreviewStatus.RUNNING, preview.error
        api = httpx.Client(base_url=preview.url, timeout=10)
        projects = api.get("/projects").json()
        assert [p["name"] for p in projects["items"]] == ["Seeded project"], "seed.json loaded into the empty DB"
        created = api.post("/projects", json={"name": "Preview project"})
        assert created.status_code == 201, created.text
        task = api.post("/tasks", json={"projectId": created.json()["id"], "title": "Try the preview"})
        assert task.status_code == 201, task.text
        assert api.get(f"/tasks/{task.json()['id']}").json()["title"] == "Try the preview"
        assert api.get("/tasks/00000000-0000-0000-0000-000000000000").status_code == 404

        requests = asyncio.run(runtime.request_log(generation_id, None, 50))
        assert ["project.list", "project.create", "task.create", "task.get", "task.get"] == [
            r["operationId"] for r in requests
        ]
        assert all(isinstance(r["durationMs"], int | float) for r in requests)
        logs = asyncio.run(runtime.logs(generation_id, 200))
        assert logs and not any(_secret_leak(line, generation_id) for line in logs)

        _call(runtime, store, "stop", generation_id)
        assert docker.from_env().containers.get(names(generation_id)["app"]).status == "exited"
        _call(runtime, store, "start", generation_id)
        restarted = store.preview(generation_id)
        assert restarted.status == PreviewStatus.RUNNING and restarted.host_port == preview.host_port
        assert len(api.get("/projects").json()["items"]) == 2, "data survives stop/start"

        _call(runtime, store, "reset_db", generation_id)
        assert [p["name"] for p in api.get("/projects").json()["items"]] == ["Seeded project"]
    finally:
        _call(runtime, store, "delete", generation_id)
        time.sleep(1)
        client_ = docker.from_env()
        assert client_.containers.list(all=True, filters={"label": f"bga.preview={generation_id}"}) == []
        assert not client_.images.list(name=names(generation_id)["image"].split(":")[0])
        if not os.environ.get("BGA_KEEP_SANDBOX_DIRS"):
            shutil.rmtree(root, ignore_errors=True)


def _secret_leak(line: str, generation_id: str) -> bool:
    from src.preview.docker_preview import secret

    return secret(generation_id, "db") in line or secret(generation_id, "jwt") in line


def test_cached_preview_builds_reuse_dependency_layers(tmp_path):
    from src.orchestrator.packaging import build_source_zip
    from src.preview.docker_frontend_preview import DockerFrontendPreviewRuntime
    from src.preview.docker_preview import DockerPreviewRuntime
    from tests.generation_helpers import golden_project
    from tests.test_frontend_scaffold import scaffolded

    d_client = docker.from_env()

    # 1. Backend golden project built twice under different generation ids
    proj1 = golden_project(tmp_path / "proj1")
    zip1 = tmp_path / "b1.zip"
    zip1.write_bytes(build_source_zip(proj1))

    proj2 = golden_project(tmp_path / "proj2")
    (proj2 / "src" / "note.txt").write_text("site2-different")
    zip2 = tmp_path / "b2.zip"
    zip2.write_bytes(build_source_zip(proj2))

    rt = DockerPreviewRuntime()
    gen1 = "gen_tbe1_" + uuid.uuid4().hex[:6]
    gen2 = "gen_tbe2_" + uuid.uuid4().hex[:6]

    try:
        log1 = rt._ensure_image(gen1, zip1)
        log2 = rt._ensure_image(gen2, zip2)

        # Second build must reuse pip install layer from cache
        assert log1 is not None and len(log1) > 0
        assert log2 is not None
        assert "Using cache" in log2 or "CACHED" in log2

        # Check plain docker build . on unzipped backend works
        unpacked = tmp_path / "unpacked_be"
        shutil.unpack_archive(zip1, unpacked)
        image, _ = d_client.images.build(path=str(unpacked), rm=True)
        assert image is not None
        d_client.images.remove(image.id, force=True)
    finally:
        asyncio.run(rt.remove(gen1))
        asyncio.run(rt.remove(gen2))

    # bga-be-deps must survive preview removal
    assert len(d_client.images.list(name="bga-be-deps")) >= 1

    # 2. Frontend golden project built twice under different site names
    fe_proj1, _ = scaffolded(tmp_path / "fe1", "shop-dynamic", golden=True)
    fe_zip1 = tmp_path / "fe1.zip"
    fe_zip1.write_bytes(build_source_zip(fe_proj1))

    fe_proj2, _ = scaffolded(tmp_path / "fe2", "shop-dynamic", golden=True)
    pkg = json.loads((fe_proj2 / "package.json").read_text())
    pkg["name"] = "different-shop-site"
    (fe_proj2 / "package.json").write_text(json.dumps(pkg, indent=2))
    fe_zip2 = tmp_path / "fe2.zip"
    fe_zip2.write_bytes(build_source_zip(fe_proj2))

    fe_rt = DockerFrontendPreviewRuntime()
    fe_gen1 = "gen_tfe1_" + uuid.uuid4().hex[:6]
    fe_gen2 = "gen_tfe2_" + uuid.uuid4().hex[:6]

    try:
        fe_log1 = fe_rt._ensure_image(fe_gen1, fe_zip1)
        fe_log2 = fe_rt._ensure_image(fe_gen2, fe_zip2)

        # Second build must reuse pnpm fetch layer from cache
        assert fe_log1 is not None and len(fe_log1) > 0
        assert fe_log2 is not None
        assert "Using cache" in fe_log2 or "CACHED" in fe_log2

        # Check plain docker build . on unzipped frontend works
        unpacked_fe = tmp_path / "unpacked_fe"
        shutil.unpack_archive(fe_zip1, unpacked_fe)
        fe_image, _ = d_client.images.build(path=str(unpacked_fe), rm=True)
        assert fe_image is not None
        d_client.images.remove(fe_image.id, force=True)
    finally:
        asyncio.run(fe_rt.remove(fe_gen1))
        asyncio.run(fe_rt.remove(fe_gen2))

    # bga-fe-deps must survive preview removal
    assert len(d_client.images.list(name="bga-fe-deps")) >= 1
