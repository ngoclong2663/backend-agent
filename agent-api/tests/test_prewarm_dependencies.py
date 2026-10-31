"""Tests for pre-warmed shared dependencies (Story 18.9).

Verifies that:
1. The shared dependencies fill starts before the engine call returns.
2. An engine failure cancels the background fill.
3. A fill failure does not fail the component (it falls back to pnpm install).
"""

import asyncio
import json

import pytest
from generation_helpers import EXAMPLES
from sqlmodel import Session, delete

from src.engines.fake_engine import FakeEngine, demo_scenario
from src.libs.database import db_session_manager
from src.modules.shared.domain.enums import GenerationMode
from src.modules.shared.infrastructure.models import ComponentCacheModel
from src.orchestrator.component_cache import drop_files
from src.orchestrator.context import JobContext
from src.orchestrator.custom_components import CustomComponents
from src.orchestrator.frontend_scaffold import scaffold_frontend
from src.sandbox import ExecResult, ISandbox, ISandboxProvider
from tests.test_frontend_scaffold import inputs
from workflow_helpers import runner_ctx

SHOP_FRONTEND = json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text())
SHOP_BACKEND = json.loads((EXAMPLES / "specs" / "shop.json").read_text())


@pytest.fixture(autouse=True)
def empty_cache():
    with Session(db_session_manager.engine) as session:
        session.exec(delete(ComponentCacheModel))
        session.commit()
    drop_files()
    yield


def _submit(client, login) -> str:
    headers = {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}
    body = {
        "mode": "dynamic",
        "frontendSpec": SHOP_FRONTEND,
        "backendSpec": SHOP_BACKEND,
        "options": {"engine": "fake", "deployPreview": False},
    }
    response = client.post("/api/v1/generations", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["generationId"]


class PrewarmTrackingSandbox(ISandbox):
    db_url = test_db_url = ""

    def __init__(self, provider: "PrewarmTrackingSandboxes"):
        self.provider = provider
        self.fill_started = False
        self.fill_cancelled = False

    async def start(self):
        pass

    async def stop(self):
        pass

    async def reset_database(self, name):
        pass

    async def shared_dependencies(self):
        self.fill_started = True
        self.provider.events.append("fill_started")
        try:
            if self.provider.fill_error:
                raise RuntimeError("fill error from provider")
            if self.provider.fill_delay_s > 0:
                await asyncio.sleep(self.provider.fill_delay_s)
            self.provider.events.append("fill_completed")
            return "ready-volume"
        except asyncio.CancelledError:
            self.fill_cancelled = True
            self.provider.events.append("fill_cancelled")
            raise

    async def exec(self, command, timeout_s=None, env=None, egress=False):
        self.provider.commands.append(command)
        return ExecResult(exit_code=0, duration_ms=1, stdout="", stderr="")


class PrewarmTrackingSandboxes(ISandboxProvider):
    def __init__(self, fill_delay_s: float = 0.05, fill_error: bool = False):
        self.fill_delay_s = fill_delay_s
        self.fill_error = fill_error
        self.events: list[str] = []
        self.commands: list[str] = []
        self.sandboxes: list[PrewarmTrackingSandbox] = []

    def for_job(self, generation_id, project, kind="backend", part=None):
        sb = PrewarmTrackingSandbox(self)
        self.sandboxes.append(sb)
        return sb

    async def job_ids(self):
        return set()

    async def remove(self, generation_ids):
        return 0


def _build_test_ctx(runner, generation_id: str, engine, sandboxes) -> JobContext:
    ws = runner.workspaces.create(generation_id)
    runner.workspaces.create_frontend(ws)
    return JobContext(
        generation_id=generation_id,
        engine=engine,
        engine_context=runner.engine_context,
        prompts=runner.prompts,
        validator=runner.validator,
        store=runner.store,
        events=runner.events,
        workspaces=runner.workspaces,
        workspace=ws,
        sandboxes=sandboxes,
        template_dir=runner.template_dir,
        mode=GenerationMode.DYNAMIC,
    )


def test_dependency_fill_starts_before_engine_call_returns(client, login, tmp_path):
    """The dependency fill starts concurrently before the engine call returns."""
    generation_id = _submit(client, login)
    sandboxes = PrewarmTrackingSandboxes(fill_delay_s=0.1)

    class DelayedEngine(FakeEngine):
        async def run(self, request, on_event=None):
            if request.purpose == "generate_custom_component":
                # Check that fill was already started before this engine call finishes
                sandboxes.events.append("engine_executing")
                await asyncio.sleep(0.05)
                sandboxes.events.append("engine_done")
            return await super().run(request, on_event)

    engine = DelayedEngine(tmp_path, demo_scenario(0))

    spec, contract, plan = inputs("shop-dynamic")

    async def go():
        async with runner_ctx(tmp_path, engine=engine, sandboxes=sandboxes) as runner:
            ctx = _build_test_ctx(runner, generation_id, engine, sandboxes)
            scaffold_frontend(ctx.workspace.frontend, plan, spec, contract)
            cc = CustomComponents(ctx, plan, spec, contract)
            # Resolve one component
            resolved = await cc.resolve(["ProductGrid"], max_repairs=0)
            return resolved

    res = asyncio.run(go())
    assert res[0].status == "generated"
    # Events order must show fill_started appeared before engine_done
    assert "fill_started" in sandboxes.events
    fill_idx = sandboxes.events.index("fill_started")
    engine_done_idx = sandboxes.events.index("engine_done")
    assert fill_idx < engine_done_idx


def test_engine_failure_cancels_background_fill(client, login, tmp_path):
    """An engine failure cancels the background fill task."""
    generation_id = _submit(client, login)
    sandboxes = PrewarmTrackingSandboxes(fill_delay_s=1.0)  # slow fill

    class FailingEngine(FakeEngine):
        async def run(self, request, on_event=None):
            if request.purpose == "generate_custom_component":
                from src.engines import EngineResult, EngineStatus

                return EngineResult(
                    invocation_id=request.invocation_id,
                    status=EngineStatus.CLI_ERROR,
                    engine="fake",
                    purpose=request.purpose,
                    exit_code=1,
                    duration_ms=10,
                    error_reason="crash",
                )
            return await super().run(request, on_event)

    engine = FailingEngine(tmp_path, demo_scenario(0))

    spec, contract, plan = inputs("shop-dynamic")

    async def go():
        async with runner_ctx(tmp_path, engine=engine, sandboxes=sandboxes) as runner:
            ctx = _build_test_ctx(runner, generation_id, engine, sandboxes)
            scaffold_frontend(ctx.workspace.frontend, plan, spec, contract)
            cc = CustomComponents(ctx, plan, spec, contract)
            return await cc.resolve(["ProductGrid"], max_repairs=0)

    res = asyncio.run(go())
    assert res[0].status == "fallback"
    # Fill must have been cancelled
    assert "fill_cancelled" in sandboxes.events


def test_fill_failure_does_not_fail_component(client, login, tmp_path):
    """A failure in shared_dependencies does not fail the component (falls back to pnpm install)."""
    generation_id = _submit(client, login)
    sandboxes = PrewarmTrackingSandboxes(fill_error=True)
    engine = FakeEngine(tmp_path, demo_scenario(0))

    spec, contract, plan = inputs("shop-dynamic")

    async def go():
        async with runner_ctx(tmp_path, engine=engine, sandboxes=sandboxes) as runner:
            ctx = _build_test_ctx(runner, generation_id, engine, sandboxes)
            scaffold_frontend(ctx.workspace.frontend, plan, spec, contract)
            cc = CustomComponents(ctx, plan, spec, contract)
            return await cc.resolve(["ProductGrid"], max_repairs=0)

    res = asyncio.run(go())
    assert res[0].status == "generated"
    # pnpm install was executed as fallback
    assert any("pnpm install" in cmd for cmd in sandboxes.commands)
