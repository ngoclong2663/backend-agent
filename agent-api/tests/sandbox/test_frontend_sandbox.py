"""Builds and tests a generated frontend for real in the Node sandbox (Story 13.4). Opt in with
BGA_SANDBOX_TESTS=1 (needs Docker and `make runner-node`). Workspaces live under .data/ because Docker Desktop
only shares configured host paths."""

import asyncio
import json
import os
import shutil
import uuid

import pytest

from src.modules.shared.domain.frontend_spec import validate_frontend_spec_text
from src.orchestrator.frontend_planner import plan_frontend
from src.orchestrator.frontend_scaffold import scaffold_frontend
from src.orchestrator.frontend_validation import FrontendValidationRequest, SandboxFrontendValidationRunner
from src.sandbox import DockerSandboxProvider
from tests.generation_helpers import EXAMPLES, REPO

pytestmark = pytest.mark.skipif(os.environ.get("BGA_SANDBOX_TESTS") != "1", reason="sandbox tests are opt-in")


@pytest.fixture
def landing():
    spec = validate_frontend_spec_text((EXAMPLES / "frontend-specs" / "static-landing.json").read_text()).normalized
    plan = plan_frontend(spec)
    project = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10] / "frontend"
    scaffold_frontend(project, plan, spec)  # rendered from the spec (Story 17.2): no engine files
    yield project, plan
    shutil.rmtree(project.parent, ignore_errors=True)


def _validate(project, plan):
    async def go():
        sandbox = DockerSandboxProvider().for_job(f"gen_TESTFE{uuid.uuid4().hex[:8].upper()}", project, "frontend")
        try:
            request = FrontendValidationRequest(project=project, plan=plan, run_tests=True, sandbox=sandbox)
            return await SandboxFrontendValidationRunner().run(request)
        finally:
            await sandbox.stop()

    return asyncio.run(go())


def test_golden_static_site_passes_every_check_offline(landing):
    project, plan = landing
    outcome = _validate(project, plan)
    assert outcome.summary == dict.fromkeys(
        ("install", "typecheck", "lint", "conventions", "assets", "build", "routes", "tests"), "passed"
    ), outcome.digest
    assert (project / "out" / "services" / "index.html").is_file()


def test_every_library_section_and_layout_node_builds_and_renders():
    """Story 17.2: the whole section library (every section, every layout node, nested three deep) type-checks,
    lints, builds and renders every page without console errors (the Playwright smoke test)."""
    path = REPO / "agent-api" / "tests" / "fixtures" / "frontend-specs" / "section-library.json"
    result = validate_frontend_spec_text(path.read_text())
    assert result.report.valid and result.report.warnings == [], result.report
    plan = plan_frontend(result.normalized)
    assert plan["rendering"] == "renderer", plan["rendererGaps"]
    project = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10] / "frontend"
    scaffold_frontend(project, plan, result.normalized)
    try:
        outcome = _validate(project, plan)
        assert outcome.summary == dict.fromkeys(
            ("install", "typecheck", "lint", "conventions", "assets", "build", "routes", "tests"), "passed"
        ), outcome.digest
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


def test_a_rendered_dynamic_app_passes_every_check_on_mocks():
    """Story 17.4: project-tracker-dynamic without the engine — data sections through the generated client on the
    mock API, the forms test submits both forms, the smoke test finds the fixtures' text on every page."""
    from tests.test_frontend_scaffold import inputs

    spec, contract, plan = inputs("project-tracker-dynamic")
    assert plan["rendering"] == "renderer", plan["rendererGaps"]
    project = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10] / "frontend"
    scaffold_frontend(project, plan, spec, contract)
    try:
        outcome = _validate(project, plan)
        assert outcome.summary == dict.fromkeys(
            ("install", "typecheck", "lint", "conventions", "assets", "build", "routes", "tests"), "passed"
        ), outcome.digest
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


def test_a_type_error_fails_typecheck_and_skips_build(landing):
    project, plan = landing
    broken = project / "src/features/site/components/Broken.tsx"
    broken.parent.mkdir(parents=True)
    broken.write_text(
        'import { Gallery } from "@/components/sections/Gallery";\n\n'
        "export function Broken() {\n  return <Gallery items={42} />;\n}\n"
    )
    outcome = _validate(project, plan)
    assert outcome.summary["typecheck"] == "failed" and outcome.summary["build"] == "skipped"
    typecheck = next(result for result in outcome.results if result.check == "typecheck")
    assert typecheck.details[0]["file"] == "src/features/site/components/Broken.tsx"
    assert "src/features/site/components/Broken.tsx" in outcome.implicated_files


def test_eslint_autofix_then_every_check_passes_on_the_shared_node_modules():
    """Story 17.5: fixable ESLint findings are fixed before the checks; node_modules comes from the shared, read-only
    volume for this dependency set (no per-project install)."""
    from src.orchestrator.autofix import autofix
    from src.orchestrator.workspace import WorkspaceManager

    spec = validate_frontend_spec_text((EXAMPLES / "frontend-specs" / "static-landing.json").read_text()).normalized
    plan = plan_frontend(spec)
    root = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10]
    manager = WorkspaceManager(root, max_mb=2000)
    workspace = manager.create(f"gen_TESTFEFIX{uuid.uuid4().hex[:6].upper()}")
    project = manager.create_frontend(workspace)
    scaffold_frontend(project, plan, spec)
    manager.commit(workspace, "node:scaffold_frontend attempt:1", repo="frontend")
    helper = project / "src/features/home/format-title.ts"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(
        "export function formatTitle(name: string): string {\n  let title = name.trim();\n  return title;\n}\n"
    )

    async def go():
        sandbox = DockerSandboxProvider().for_job(workspace.root.name, project, "frontend")
        try:
            shared = await sandbox.shared_dependencies()
            fixed = await autofix(manager, workspace, "frontend", sandbox)
            request = FrontendValidationRequest(project=project, plan=plan, run_tests=True, sandbox=sandbox)
            return shared, fixed, await SandboxFrontendValidationRunner().run(request)
        finally:
            await sandbox.stop()

    try:
        shared, fixed, outcome = asyncio.run(go())
        assert shared is not None and shared.startswith("bga-fe-modules-")
        assert fixed.fixed == ["src/features/home/format-title.ts"] and "const title" in helper.read_text()
        assert outcome.summary == dict.fromkeys(
            ("install", "typecheck", "lint", "conventions", "assets", "build", "routes", "tests"), "passed"
        ), outcome.digest
        install = next(result for result in outcome.results if result.check == "install")
        assert "shared node_modules" in install.summary
        assert not any((project / "node_modules").iterdir())  # nothing was copied into the workspace
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_dynamic_generation_switches_to_live_and_passes_live_smoke(client, user_headers):
    """Stories 14.1–14.3: parallel backend + frontend sandboxes, live preview switch and live Playwright smoke."""
    import json

    from src.engines.fake_engine import FakeEngine, demo_scenario
    from src.libs.queue import PreviewCommandBus
    from src.libs.redaction import Redactor
    from src.modules.generations.infrastructure.adapters import EventPublisher
    from src.orchestrator.previews import PreviewService
    from src.orchestrator.store import JobStore
    from src.orchestrator.validation import SandboxValidationRunner
    from src.preview.docker_frontend_preview import DockerFrontendPreviewRuntime
    from src.preview.docker_preview import DockerPreviewRuntime
    from tests.workflow_helpers import TWO_ENTITY, generation, redis_client, runner_ctx

    root = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10]
    root.mkdir(parents=True)
    tracker = json.loads((EXAMPLES / "frontend-specs" / "project-tracker-dynamic.json").read_text())
    resp = client.post(
        "/api/v1/generations",
        json={"mode": "dynamic", "frontendSpec": tracker, "backendSpec": TWO_ENTITY, "options": {"engine": "fake"}},
        headers=user_headers,
    )
    assert resp.status_code == 202, resp.text
    generation_id = resp.json()["generationId"]
    backend_rt, frontend_rt = DockerPreviewRuntime(), DockerFrontendPreviewRuntime()
    store = JobStore()

    async def go():
        redis = redis_client()
        try:
            events = EventPublisher(redis, Redactor())
            previews = PreviewService(backend_rt, store, events, PreviewCommandBus(redis), frontend_runtime=frontend_rt)
            async with runner_ctx(
                root,
                engine=FakeEngine(root, demo_scenario(0)),
                validator=SandboxValidationRunner(),
                frontend_validator=SandboxFrontendValidationRunner(),
                sandboxes=DockerSandboxProvider(),
                previews=previews,
                on_completed=previews.request_start,
            ) as runner:
                try:
                    return await runner.run(generation_id)
                finally:
                    for kind in ("frontend", "backend"):
                        await previews.delete(generation_id, kind)
        finally:
            await redis.aclose()

    try:
        status = asyncio.run(go())
        row = generation(generation_id)
        assert status == "COMPLETED", row.error_summary
        assert row.lanes == {"backend": "COMPLETED", "frontend": "COMPLETED", "integration": "COMPLETED"}
    finally:
        if not os.environ.get("BGA_KEEP_SANDBOX_DIRS"):
            shutil.rmtree(root, ignore_errors=True)


def test_custom_components_pass_isolated_checks_then_come_from_the_cache(client, user_headers):
    """Story 17.3: shop-dynamic's three custom components are generated in parallel, pass their isolated checks
    (tsc, ESLint, the render test on the mock API) in their own sandboxes, and the site passes every check with
    them; the second run takes all three from the cache."""
    import json

    from sqlmodel import Session, delete

    from src.engines.fake_engine import FakeEngine, demo_scenario
    from src.libs.database import db_session_manager
    from src.modules.shared.infrastructure.models import ComponentCacheModel
    from src.orchestrator.component_cache import drop_files
    from tests.workflow_helpers import cli_invocations, generation, node_runs, run_job

    with Session(db_session_manager.engine) as session:
        session.exec(delete(ComponentCacheModel))
        session.commit()
    drop_files()
    root = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10]
    root.mkdir(parents=True)
    body = {
        "mode": "dynamic",
        "frontendSpec": json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text()),
        "backendSpec": json.loads((EXAMPLES / "specs" / "shop.json").read_text()),
        "options": {"engine": "fake", "deployPreview": False},
    }

    def run() -> str:
        response = client.post("/api/v1/generations", json=body, headers=user_headers)
        assert response.status_code == 202, response.text
        generation_id = response.json()["generationId"]
        status = run_job(
            root,
            generation_id,
            engine=FakeEngine(root, demo_scenario(0)),
            sandboxes=DockerSandboxProvider(),
            frontend_validator=SandboxFrontendValidationRunner(),
        )
        assert status == "COMPLETED_WITH_WARNINGS", generation(generation_id).error_summary  # no preview
        assert generation(generation_id).lanes["frontend"] == "COMPLETED"
        return generation_id

    try:
        first = run()
        calls = [c.purpose for c in cli_invocations(first) if "custom" in c.purpose]
        assert calls == ["generate_custom_component"] * 3, calls  # no repair: the isolated checks passed
        summary = next(r.summary for r in node_runs(first) if r.node == "generate_frontend")
        assert summary["fallbacks"] == 0 and summary["cacheHits"] == 0
        second = run()
        assert not [c for c in cli_invocations(second) if "custom" in c.purpose]
        assert next(r.summary for r in node_runs(second) if r.node == "generate_frontend")["cacheHits"] == 3
    finally:
        if not os.environ.get("BGA_KEEP_SANDBOX_DIRS"):
            shutil.rmtree(root, ignore_errors=True)


def test_drawn_and_uploaded_images_build_and_show_on_their_pages(tmp_path):
    """Epic 15: the landing page with its golden drawings converted to components and an uploaded logo in
    public/assets builds offline; `frontend:assets` passes and the smoke test finds every image on its page."""
    import io

    from PIL import Image

    from src.engines.fake_engine import GOLDEN_ASSETS
    from src.orchestrator.frontend_assets import convert_drawing, write_registry

    spec_data = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    spec_data["layout"]["header"]["logo"] = "asset:logo"
    spec_data["assets"].append({"id": "logo", "kind": "logo", "source": "upload:upl_TESTLOGO01", "alt": "Northwind"})
    spec = validate_frontend_spec_text(json.dumps(spec_data)).normalized
    plan = plan_frontend(spec)
    project = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10] / "frontend"
    scaffold_frontend(project, plan, spec)
    try:
        for asset in plan["assets"]:
            if asset["render"] == "svg-component":
                (project / asset["file"]).parent.mkdir(parents=True, exist_ok=True)
                (project / asset["file"]).write_text((GOLDEN_ASSETS / f"{asset['id']}.svg").read_text())
                assert convert_drawing(project, asset)
            elif asset["render"] == "public-file":
                logo = io.BytesIO()
                Image.new("RGB", (96, 96), (20, 60, 120)).save(logo, format="PNG")
                (project / "public/assets").mkdir(parents=True, exist_ok=True)
                (project / "public/assets/logo.png").write_bytes(logo.getvalue())
                asset |= {"file": "public/assets/logo.png", "src": "/assets/logo.png", "width": 96, "height": 96}
        write_registry(project, plan)
        outcome = _validate(project, plan)
        assert outcome.summary == dict.fromkeys(
            ("install", "typecheck", "lint", "conventions", "assets", "build", "routes", "tests"), "passed"
        ), outcome.digest
        home = (project / "out" / "index.html").read_text()
        assert 'data-bga-asset="hero"' in home and 'data-bga-asset="logo"' in home and "<svg" in home
        assert 'src="/assets/logo.png"' in home
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


def test_endless_render_loop_component_fails_fast_in_checks_and_render_test():
    """Story 18.1: A component with an endless render loop is caught by ESLint and skips the render test
    (< 30 s). When only the render test runs, it fails in < 60 s with the render loop message."""
    import time

    from src.orchestrator.custom_components import (
        RENDER_TEST,
        TSCONFIG,
        CustomComponents,
        render_test,
    )
    from tests.test_frontend_scaffold import inputs

    spec, contract, plan = inputs("project-tracker-dynamic")
    root = REPO / ".data" / "test-sandbox" / uuid.uuid4().hex[:10]
    project = root / "frontend"
    scaffold_frontend(project, plan, spec, contract)

    relative = "src/components/custom/LoopComponent.tsx"
    loop_fixture = REPO / "agent-api" / "tests" / "fixtures" / "components" / "loop_component.tsx"
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(loop_fixture.read_text())

    test_file = project / RENDER_TEST
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(render_test(relative, {}, {}, dynamic=True))
    tsconfig = {
        "extends": "./tsconfig.json",
        "compilerOptions": {"incremental": False},
        "include": ["next-env.d.ts", "src/**/*.d.ts", relative, RENDER_TEST],
    }
    (project / TSCONFIG).write_text(json.dumps(tsconfig, indent=2) + "\n")

    async def go():
        sandbox = DockerSandboxProvider().for_job(f"gen_TESTFE{uuid.uuid4().hex[:8].upper()}", project, "frontend")
        try:
            cc = CustomComponents.__new__(CustomComponents)
            # Test 1: isolated checks run lint, lint fails, render test is skipped; finishes < 30 s
            t0 = time.monotonic()
            failures, _ = await cc._checks(project, relative, sandbox, installed=False)
            elapsed_checks = time.monotonic() - t0
            assert elapsed_checks < 30, f"_checks took {elapsed_checks:.1f}s, expected < 30s"
            assert any("lint (ESLint) failed" in f for f in failures), failures
            assert not any("render test failed" in f for f in failures), "render test should have been skipped"

            # Test 2: render test run directly on the loop component fails < 60 s with loop message
            t1 = time.monotonic()
            render = await sandbox.exec(
                f"pnpm exec vitest run {RENDER_TEST} --testTimeout=20000",
                timeout_s=60,
            )
            elapsed_render = time.monotonic() - t1
            assert elapsed_render < 60, f"render test took {elapsed_render:.1f}s, expected < 60s"
            assert not render.ok, "render test should have failed"
            assert "render loop:" in render.output, f"expected loop message in output:\n{render.output}"
        finally:
            await sandbox.stop()

    try:
        asyncio.run(go())
    finally:
        if not os.environ.get("BGA_KEEP_SANDBOX_DIRS"):
            shutil.rmtree(root, ignore_errors=True)
