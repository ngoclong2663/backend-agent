"""Story 17.3: custom components of a rendered site, generated in parallel, checked in isolation and cached."""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from generation_helpers import EXAMPLES
from sqlmodel import Session, delete, select

from src.configs import config
from src.engines.fake_engine import FakeEngine, FakeStep, demo_scenario
from src.libs.database import db_session_manager
from src.modules.shared.infrastructure.models import ComponentCacheModel
from src.orchestrator.component_cache import (
    cached_file,
    closest_section,
    component_file,
    component_key,
    drop_files,
    sample_props,
)
from src.orchestrator.frontend_validation import CheckResult, StaticFrontendValidationRunner, _outcome
from src.sandbox import ExecResult, ISandbox, ISandboxProvider
from workflow_helpers import cli_invocations, events, generation, node_runs, run_job

SHOP_FRONTEND = json.loads((EXAMPLES / "frontend-specs" / "shop-dynamic.json").read_text())
SHOP_BACKEND = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
CUSTOM = ("CartList", "ProductDetail", "ProductGrid")


class PassingSandbox(ISandbox):
    """Every command succeeds; the shared node_modules are ready."""

    db_url = test_db_url = ""

    def __init__(self, provider: "PassingSandboxes"):
        self.provider = provider

    async def start(self):
        pass

    async def stop(self):
        pass

    async def reset_database(self, name):
        pass

    async def shared_dependencies(self):
        return "bga-fe-modules-test"

    async def exec(self, command, timeout_s=None, env=None, egress=False):
        self.provider.commands.append(command)
        return ExecResult(exit_code=0, duration_ms=1, stdout="", stderr="")


class PassingSandboxes(ISandboxProvider):
    def __init__(self):
        self.parts: list[str | None] = []
        self.commands: list[str] = []

    def for_job(self, generation_id, project, kind="backend", part=None):
        self.parts.append(part)
        return PassingSandbox(self)

    async def job_ids(self):
        return set()

    async def remove(self, generation_ids):
        return 0


class BuildBreaksOnce(StaticFrontendValidationRunner):
    """The first validation reports a failed build caused by `file`; later ones are the static checks."""

    def __init__(self, file: str):
        self.file, self.runs = file, 0

    async def run(self, request):
        self.runs += 1
        if self.runs > 1:
            return await super().run(request)
        detail = {"file": self.file, "line": 3, "message": "Type error: cannot find name 'Grid'"}
        return _outcome([CheckResult(check="build", status="failed", summary="build failed", details=[detail])])


@pytest.fixture(autouse=True)
def empty_cache():
    with Session(db_session_manager.engine) as session:
        session.exec(delete(ComponentCacheModel))
        session.commit()
    drop_files()
    yield


def cache_rows() -> list[ComponentCacheModel]:
    with Session(db_session_manager.engine) as session:
        return list(session.exec(select(ComponentCacheModel).order_by(ComponentCacheModel.name)))


def submit_shop(client, login, frontend=None, **options) -> str:
    headers = {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}
    body = {
        "mode": "dynamic",
        "frontendSpec": frontend or SHOP_FRONTEND,
        "backendSpec": SHOP_BACKEND,
        "options": {"engine": "fake", "deployPreview": False, **options},
    }
    response = client.post("/api/v1/generations", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["generationId"]


def frontend_summary(generation_id: str) -> dict:
    return next(r.summary for r in node_runs(generation_id) if r.node == "generate_frontend")


def purposes(generation_id: str) -> list[str]:
    return sorted(c.purpose for c in cli_invocations(generation_id) if "frontend" in c.purpose or "custom" in c.purpose)


# -- keys, sample props, fallbacks ------------------------------------------------------------------------------------


def test_the_key_is_what_the_component_is_made_from_not_its_name():
    component = {"name": "ProductGrid", "description": "Cards  with\nprices", "uses": ["card", "badge"]}
    component["propsSchema"] = {"type": "object", "properties": {"limit": {"type": "integer"}}}
    key = component_key(component, "lock", "1")
    same = {**component, "name": "Products", "description": "Cards with prices", "uses": ["badge", "card", "card"]}
    assert component_key(same, "lock", "1") == key and len(key) == 64
    assert component_key({**component, "description": "Cards"}, "lock", "1") != key
    assert component_key({**component, "uses": ["card"]}, "lock", "1") != key
    assert component_key({**component, "propsSchema": {}}, "lock", "1") != key
    assert component_key(component, "new base", "1") != key and component_key(component, "lock", "2") != key


def test_component_cache_key_changes_with_prompt_version(monkeypatch):
    from src.orchestrator import component_cache

    component = {"name": "ProductGrid", "description": "Cards with prices"}
    key_v2 = component_key(component, "lock", "1")
    monkeypatch.setattr(component_cache, "PROMPT_VERSION", "v1")
    key_v1 = component_key(component, "lock", "1")
    assert key_v1 != key_v2


def test_sample_props_follow_the_schema():
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "limit": {"type": "integer", "default": 12},
            "size": {"enum": ["sm", "lg"]},
            "since": {"type": "string", "format": "date"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "owner": {"type": "object", "properties": {"email": {"type": "string", "format": "email"}}},
        },
    }
    assert sample_props(schema) == {
        "title": "Sample text",
        "limit": 12,
        "size": "sm",
        "since": "2026-10-29",
        "tags": ["Sample text"],
        "owner": {"email": "user@example.com"},
    }


def test_the_fallback_fits_the_sections_binding():
    grid = {"name": "ProductGrid", "uses": ["card"]}
    listing = {"data": {"kind": "operation", "action": "list"}}
    assert closest_section(listing, grid) == "CardGrid"
    assert closest_section(listing, {"name": "OrderTable"}) == "DataTable"
    assert closest_section({"data": {"kind": "content"}}, {"name": "Lines"}) == "List"
    assert closest_section({"data": {"kind": "operation", "action": "get"}}, grid) == "DetailView"
    assert closest_section({}, grid) == "RichText"


# -- the workflow -----------------------------------------------------------------------------------------------------


def test_shop_first_run_generates_three_components_and_the_second_takes_them_from_the_cache(client, login, tmp_path):
    sandboxes = PassingSandboxes()
    first = submit_shop(client, login)
    engine = FakeEngine(tmp_path, demo_scenario(0))
    assert run_job(tmp_path, first, engine=engine, sandboxes=sandboxes) == "COMPLETED_WITH_WARNINGS"  # no preview
    assert generation(first).lanes["frontend"] == "COMPLETED"
    assert purposes(first) == ["generate_custom_component"] * 3  # no page or shell call, no repair
    assert frontend_summary(first) | {"customComponents": 3, "engineCalls": 3, "cacheHits": 0, "fallbacks": 0} == (
        frontend_summary(first)
    )
    # One sandbox per component (its own part label), each running the isolated checks on its scratch copy.
    assert len([p for p in sandboxes.parts if p and p.startswith("c-")]) == 3
    assert sum("tsc -p tsconfig.component.json" in c for c in sandboxes.commands) == 3
    assert sum(c.startswith("pnpm exec vitest run tests/unit/custom-") for c in sandboxes.commands) == 3
    rows = cache_rows()
    assert [row.name for row in rows] == list(CUSTOM) and {row.source_generation_id for row in rows} == {first}
    plan = json.loads((tmp_path / first / "frontend" / ".bga" / "frontend-plan.json").read_text())
    registry = (tmp_path / first / "frontend" / "src/components/renderer/registry.ts").read_text()
    for name in CUSTOM:
        entry = plan["customComponents"][name]
        assert entry["status"] == "generated" and entry["file"] == component_file(entry["key"])
        assert cached_file(entry["key"]).is_file() and (tmp_path / first / "frontend" / entry["file"]).is_file()
        assert f'import {name}Custom from "@/components/custom/{entry["key"]}";' in registry
    assert not (tmp_path / first / "scratch").exists()

    second = submit_shop(client, login)
    assert run_job(tmp_path, second, engine=FakeEngine(tmp_path, demo_scenario(0)), sandboxes=PassingSandboxes()) == (
        "COMPLETED_WITH_WARNINGS"
    )
    assert purposes(second) == []
    assert frontend_summary(second) | {"engineCalls": 0, "cacheHits": 3} == frontend_summary(second)
    assert len([e for e in events(second) if e.type == "component.cache_hit"]) == 3
    assert [row.hits for row in cache_rows()] == [1, 1, 1]

    headers = {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}
    usage = client.get("/api/v1/usage", headers=headers).json()
    assert usage["totals"]["cacheHits"] == 3 and usage["catalogueCandidates"] == []
    admin = {"Authorization": f"Bearer {login('admin@test.local', 'adminpass')}"}
    candidates = client.get("/api/v1/usage?scope=all", headers=admin).json()["catalogueCandidates"]
    assert sorted(c["name"] for c in candidates) == list(CUSTOM) and {c["hits"] for c in candidates} == {1}


def test_engine_calls_stay_within_engine_concurrency(client, login, tmp_path, monkeypatch):
    class Tracking(FakeEngine):
        active = peak = 0

        async def run(self, request, on_event=None):
            if request.purpose != "generate_custom_component":
                return await super().run(request, on_event)
            Tracking.active += 1
            Tracking.peak = max(Tracking.peak, Tracking.active)
            try:
                await asyncio.sleep(0.05)
                return await super().run(request, on_event)
            finally:
                Tracking.active -= 1

    monkeypatch.setattr(config, "engine_concurrency", 2)
    generation_id = submit_shop(client, login)
    run_job(tmp_path, generation_id, engine=Tracking(tmp_path, demo_scenario(0)), sandboxes=PassingSandboxes())
    assert purposes(generation_id).count("generate_custom_component") == 3 and Tracking.peak == 2


def test_a_failing_component_is_repaired_in_isolation_then_cached(client, login, tmp_path):
    scenario = demo_scenario(0)
    scenario["generate_custom_component"] = [FakeStep(plant_component_defect=True)]
    generation_id = submit_shop(client, login)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario), sandboxes=PassingSandboxes()) == (
        "COMPLETED_WITH_WARNINGS"
    )
    assert purposes(generation_id) == ["generate_custom_component"] * 3 + ["repair_custom_component"] * 3
    assert frontend_summary(generation_id)["engineCalls"] == 6 and len(cache_rows()) == 3
    repair = next(c for c in cli_invocations(generation_id) if c.purpose == "repair_custom_component")
    assert repair.prompt_ref == "repair_custom_component@v3"


def test_a_component_that_cannot_be_generated_falls_back_without_failing_the_job(client, login, tmp_path):
    scenario = demo_scenario(0)
    scenario["generate_custom_component"] = [FakeStep(status="cli_error", error_reason="crash")]
    generation_id = submit_shop(client, login)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario), sandboxes=PassingSandboxes()) == (
        "COMPLETED_WITH_WARNINGS"
    )
    assert generation(generation_id).lanes["frontend"] == "COMPLETED"
    fallbacks = [e.payload for e in events(generation_id) if e.type == "component.fallback"]
    assert sorted(f["fallback"][0] for f in fallbacks) == ["CardGrid", "DetailView", "List"]
    assert all(f["reason"].startswith("engine failed") for f in fallbacks) and cache_rows() == []
    registry = (tmp_path / generation_id / "frontend/src/components/renderer/registry.ts").read_text()
    assert "ProductGrid: CardGrid as unknown" in registry and "@/components/custom/" not in registry


def test_without_a_sandbox_components_are_used_but_never_cached(client, login, tmp_path):
    generation_id = submit_shop(client, login)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED_WITH_WARNINGS"
    assert purposes(generation_id) == ["generate_custom_component"] * 3 and cache_rows() == []
    assert all(e.payload["cached"] is False for e in events(generation_id) if e.type == "component.generated")


def test_a_cached_component_that_breaks_the_build_is_evicted_and_generated_again(client, login, tmp_path):
    first = submit_shop(client, login)
    run_job(tmp_path, first, engine=FakeEngine(tmp_path, demo_scenario(0)), sandboxes=PassingSandboxes())
    plan = json.loads((tmp_path / first / "frontend/.bga/frontend-plan.json").read_text())
    broken = plan["customComponents"]["ProductGrid"]["key"]

    second = submit_shop(client, login)
    validator = BuildBreaksOnce(component_file(broken))
    status = run_job(
        tmp_path,
        second,
        engine=FakeEngine(tmp_path, demo_scenario(0)),
        sandboxes=PassingSandboxes(),
        frontend_validator=validator,
    )
    assert status == "COMPLETED_WITH_WARNINGS" and validator.runs == 2
    [evicted] = [e.payload for e in events(second) if e.type == "component.evicted"]
    assert evicted["keys"] == [broken]
    # Regenerated once, instead of an engine repair of the site; cached again from this generation.
    assert purposes(second) == ["generate_custom_component"]
    repair = next(r for r in node_runs(second) if r.node == "repair_frontend")
    assert repair.summary["regenerated"] == ["ProductGrid"] and repair.summary["engineCalls"] == 1
    assert {row.name: row.source_generation_id for row in cache_rows()}["ProductGrid"] == second


def test_a_spec_without_props_schemas_still_goes_to_the_engine(client, login, tmp_path):
    spec = copy.deepcopy(SHOP_FRONTEND)
    spec["components"][0].pop("propsSchema")
    generation_id = submit_shop(client, login, frontend=spec)
    run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0)))
    plan = json.loads((tmp_path / generation_id / "frontend/.bga/frontend-plan.json").read_text())
    assert plan["rendering"] == "engine" and "customComponents" not in plan
    assert "generate_custom_component" not in purposes(generation_id)


def test_only_admins_purge_the_cache(client, login, tmp_path):
    generation_id = submit_shop(client, login)
    run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0)), sandboxes=PassingSandboxes())
    keys = [row.key for row in cache_rows()]
    assert len(keys) == 3 and all(cached_file(key).is_file() for key in keys)
    assert client.delete("/api/v1/cache/components").status_code == 401
    user = {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}
    assert client.delete("/api/v1/cache/components", headers=user).status_code == 403
    admin = {"Authorization": f"Bearer {login('admin@test.local', 'adminpass')}"}
    response = client.delete("/api/v1/cache/components", headers=admin)
    assert response.status_code == 200 and response.json() == {"purged": 3}
    assert cache_rows() == [] and not any(cached_file(key).exists() for key in keys)
    assert not Path(config.artifact_root, "cache", "components").exists()


# -- Story 18.1: fail-fast component checks & interrupted engine handling ---------------------------------------------


class CommandTrackingSandbox(PassingSandbox):
    def __init__(self, provider: "CommandTrackingSandboxes"):
        super().__init__(provider)
        self.provider = provider

    async def exec(self, command, timeout_s=None, env=None, egress=False):
        self.provider.recorded_execs.append((command, timeout_s))
        self.provider.commands.append(command)
        if self.provider.lint_fails and "eslint" in command:
            return ExecResult(exit_code=1, duration_ms=1, stdout="lint error", stderr="")
        return ExecResult(exit_code=0, duration_ms=1, stdout="", stderr="")


class CommandTrackingSandboxes(PassingSandboxes):
    def __init__(self, lint_fails: bool = False):
        super().__init__()
        self.lint_fails = lint_fails
        self.recorded_execs: list[tuple[str, int | None]] = []

    def for_job(self, generation_id, project, kind="backend", part=None):
        self.parts.append(part)
        return CommandTrackingSandbox(self)


def test_lint_failure_skips_render_test(client, login, tmp_path):
    sandboxes = CommandTrackingSandboxes(lint_fails=True)
    generation_id = submit_shop(client, login)
    run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0)), sandboxes=sandboxes)
    assert any("eslint" in cmd for cmd in sandboxes.commands)
    assert not any("vitest run" in cmd for cmd in sandboxes.commands)


def test_render_test_exec_uses_timeout_and_flag(client, login, tmp_path):
    sandboxes = CommandTrackingSandboxes(lint_fails=False)
    generation_id = submit_shop(client, login)
    run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0)), sandboxes=sandboxes)
    vitest_execs = [item for item in sandboxes.recorded_execs if "vitest run" in item[0]]
    assert len(vitest_execs) == 3
    for cmd, timeout_s in vitest_execs:
        assert "--testTimeout=20000" in cmd
        assert timeout_s == config.frontend_component_test_timeout_seconds


def test_interrupted_engine_keeps_component_if_file_changed_and_checks_pass(client, login, tmp_path):
    scenario = demo_scenario(0)
    scenario["generate_custom_component"] = [FakeStep(custom_component=True, status="cli_error", error_reason="crash")]
    generation_id = submit_shop(client, login)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario), sandboxes=PassingSandboxes()) == (
        "COMPLETED_WITH_WARNINGS"
    )
    summary = frontend_summary(generation_id)
    assert summary["fallbacks"] == 0 and summary["customComponents"] == 3
    generated_events = [e for e in events(generation_id) if e.type == "component.generated"]
    assert len(generated_events) == 3
    assert all("cli_error" in e.payload.get("engineError", "") for e in generated_events)


def test_interrupted_engine_falls_back_if_file_unchanged(client, login, tmp_path):
    scenario = demo_scenario(0)
    scenario["generate_custom_component"] = [FakeStep(custom_component=False, status="cli_error", error_reason="crash")]
    generation_id = submit_shop(client, login)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario), sandboxes=PassingSandboxes()) == (
        "COMPLETED_WITH_WARNINGS"
    )
    summary = frontend_summary(generation_id)
    assert summary["fallbacks"] == 3 and summary["cacheHits"] == 0
