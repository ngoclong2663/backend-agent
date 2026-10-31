"""The frontend lane (Epic 13): plan → scaffold → generate → validate ⇄ repair. Same shape as the backend nodes:
`async (state, ctx) -> (state update, step summary)`. Paths in state are relative to the frontend repository
(`<workspace>/frontend`), except `frontend_ref`, the normalized FrontendSpec in the workspace's spec directory."""

import asyncio
import json
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.modules.shared.domain.entities import ValidationRunEntity
from src.modules.shared.domain.enums import GenerationMode, LaneStatus
from src.modules.shared.domain.frontend_spec import iter_sections

from .autofix import autofix_before_validation
from .component_cache import CUSTOM_DIR, drop_files
from .context import EngineFailure, JobContext
from .custom_components import CustomComponents, Resolved
from .frontend_assets import (
    copy_uploads,
    due_fallbacks,
    fall_back,
    generate_assets,
    redraw_after_repair,
    write_registry,
)
from .frontend_planner import dump_frontend_plan, plan_frontend
from .frontend_scaffold import scaffold_frontend
from .frontend_validation import FrontendValidationRequest
from .integration import package_lane_preview
from .state import GenerationState, Outcome
from .validation import write_report

logger = get_logger(__name__)

DIGEST_LIMIT = 30_000
FRONTEND_PROMPTS = {"generate_frontend_shell": "v1", "generate_frontend_page": "v1", "repair_frontend": "v2"}
PLAN_REF = ".bga/frontend-plan.json"
CHECK_PREFIX = "frontend:"
NodeResult = tuple[dict[str, Any], dict[str, Any]]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _contract(ctx: JobContext) -> dict[str, Any] | None:
    path = ctx.workspace.spec_dir / "contract.json"
    return _json(path) if path.is_file() else None


def _plan(ctx: JobContext, state: GenerationState) -> dict[str, Any]:
    return _json(ctx.frontend_path(state["frontend_plan_ref"]))


async def plan_frontend_node(state: GenerationState, ctx: JobContext) -> NodeResult:
    spec = _json(Path(state["frontend_ref"]))
    plan = plan_frontend(spec, _contract(ctx))
    ctx.workspaces.create_frontend(ctx.workspace)
    path = ctx.frontend_path(PLAN_REF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontend_plan(plan))
    summary = {
        "routes": len(plan["routes"]),
        "components": len(plan["components"]),
        "shadcn": len(plan["shadcn"]),
        "bindings": len(plan["data"]),
        "forms": len(plan["forms"]),
        "tests": len(plan["tests"]),
    }
    await ctx.emit("frontend.plan.ready", step="plan_frontend", **summary)
    return {"frontend_plan_ref": PLAN_REF}, summary


async def scaffold_frontend_node(state: GenerationState, ctx: JobContext) -> NodeResult:
    """Story 13.2: pinned base + overlay + generated client, mocks, forms, theme and tests."""
    plan = _plan(ctx, state)
    info = scaffold_frontend(ctx.workspace.frontend, plan, _json(Path(state["frontend_ref"])), _contract(ctx))
    summary = {"mode": info["mode"], "shadcn": len(info["shadcn"]), "generated": len(info["generated"])}
    if any(asset["render"] == "public-file" for asset in plan.get("assets", [])):
        # Story 15.4: the user's uploads go to public/assets/ and into the registry.
        missing = copy_uploads(ctx.workspace.frontend, plan, ctx.store.upload)
        write_registry(ctx.workspace.frontend, plan)
        summary["uploads"] = sum(1 for asset in plan["assets"] if asset["render"] == "public-file") - len(missing)
        for asset_id in missing:
            await ctx.emit("frontend.asset.missing", step="scaffold_frontend", id=asset_id, reason="upload deleted")
    await ctx.emit("frontend.scaffold.done", step="scaffold_frontend", **summary)
    if ctx.sandboxes is not None and config.frontend_shared_modules:

        async def _prewarm():
            try:
                sb = ctx.sandboxes.for_job(ctx.generation_id, ctx.workspace.frontend, kind="frontend", part="prewarm")
                await sb.shared_dependencies()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(
                    "prewarm shared modules failed",
                    extra={"generation_id": ctx.generation_id, "error": str(e)},
                )

        ctx.background_tasks.append(asyncio.create_task(_prewarm()))
    return {}, summary


async def _resolve_components(
    state: GenerationState, ctx: JobContext, plan: dict[str, Any], names: list[str] | None = None
) -> list[Resolved]:
    spec = _json(Path(state["frontend_ref"]))
    resolved = await CustomComponents(ctx, plan, spec, _contract(ctx)).resolve(names, state["max_repair_attempts"])
    async with ctx.frontend_plan_lock:
        current_plan = json.loads(ctx.frontend_path(PLAN_REF).read_text())
        current_plan["customComponents"] = plan["customComponents"]
        ctx.frontend_path(PLAN_REF).write_text(dump_frontend_plan(current_plan))
    return resolved


def _components_summary(resolved: list[Resolved]) -> dict[str, Any]:
    return {
        "customComponents": sum(len(r.names) for r in resolved),
        "cacheHits": sum(1 for r in resolved if r.status == "hit"),
        "fallbacks": sum(1 for r in resolved if r.status == "fallback"),
        "engineCalls": sum(r.engine_calls for r in resolved),
        "savedEngineMs": sum(r.saved_ms for r in resolved),
    }


async def generate_frontend(state: GenerationState, ctx: JobContext) -> NodeResult:
    """Story 13.3: outside-in — the shell and shared components first, then one engine call per page.
    Story 17.2: a plan the section library can render was fully written by the scaffold; no engine call.
    Story 17.3: except for its custom components, generated in parallel or taken from the component cache."""
    plan = _plan(ctx, state)
    if plan.get("rendering") == "renderer":
        sections = sum(1 for route in plan["routes"] for _ in iter_sections(route["sections"]))
        summary: dict[str, Any] = {"pages": len(plan["routes"]), "sections": sections, "engineCalls": 0}
        update: dict[str, Any] = {}
        if plan.get("customComponents"):
            resolved = await _resolve_components(state, ctx, plan)
            summary |= _components_summary(resolved)
            update["cached_components"] = sorted(r.key for r in resolved if r.status == "hit")
        await ctx.emit("frontend.rendered", step="generate_frontend", **summary)
        return update, {**summary, "rendering": "renderer"}
    common = {
        "plan_path": state["frontend_plan_ref"],
        "spec_path": ".bga/frontend-spec.json",
        "mode": plan["project"]["mode"],
    }
    prompt = ctx.prompts.render(
        "generate_frontend_shell",
        FRONTEND_PROMPTS["generate_frontend_shell"],
        shell=plan["shell"],
        components=plan["components"],
        shadcn=plan["shadcn"],
        theme=plan["theme"],
        file_tree=ctx.file_tree(repo="frontend"),
        **common,
    )
    result = await ctx.run_engine("generate_frontend", "generate_frontend", prompt, repo="frontend")
    changed = len(result.changed_files)
    forms = {form["id"]: form for form in plan["forms"]}
    for route in plan["routes"]:
        prompt = ctx.prompts.render(
            "generate_frontend_page",
            FRONTEND_PROMPTS["generate_frontend_page"],
            route=route,
            route_json=json.dumps(route, indent=2, sort_keys=True, ensure_ascii=False),
            data=[binding for binding in plan["data"] if binding["pageId"] == route["pageId"]],
            forms=[forms[s["form"]] for s in iter_sections(route["sections"]) if s.get("form") in forms],
            file_tree=ctx.file_tree(repo="frontend"),
            **common,
        )
        result = await ctx.run_engine("generate_frontend", "generate_frontend", prompt, repo="frontend")
        changed += len(result.changed_files)
    return {}, {"pages": len(plan["routes"]), "changedFiles": changed}


async def validate_frontend(state: GenerationState, ctx: JobContext) -> NodeResult:
    attempt = state.get("frontend_repair_attempts", 0) + 1
    canonical_contract = ctx.workspace.spec_dir / "contract.json"
    if canonical_contract.is_file():
        frontend_contract = ctx.frontend_path(".bga", "contract.json")
        frontend_contract.parent.mkdir(parents=True, exist_ok=True)
        frontend_contract.write_text(canonical_contract.read_text())  # undo any edit by the engine
    fixes = await autofix_before_validation(ctx, "frontend", attempt, "validate_frontend")
    plan = _plan(ctx, state)
    # Story 15.3: drawings still failing after their repairs show their placeholder; they never fail the lane.
    attempts_left = state.get("frontend_repair_attempts", 0) < state["max_repair_attempts"]
    fallbacks = due_fallbacks(ctx.workspace.frontend, plan, config.frontend_asset_repair_limit, attempts_left)
    if fallbacks:
        fall_back(ctx.workspace.frontend, plan, fallbacks)
        for asset_id, reason in fallbacks.items():
            await ctx.emit("frontend.asset.fallback", step="validate_frontend", id=asset_id, reason=reason)
    frontend_options = state["options"].get("frontend") or {}
    request = FrontendValidationRequest(
        project=ctx.workspace.frontend,
        plan=plan,
        run_tests=bool(frontend_options.get("runTests", True)),
        sandbox=await ctx.frontend_sandbox(),
    )
    outcome = await ctx.frontend_validator.run(request)
    for check in outcome.results:
        ctx.store.add_validation_run(
            ValidationRunEntity(
                generation_id=ctx.generation_id,
                attempt=attempt,
                check=f"{CHECK_PREFIX}{check.check}",
                status=check.status,
                started_at=check.started_at,
                duration_ms=check.duration_ms,
                details={"summary": check.summary, "items": check.details[:50], "output": check.output[-4000:]},
            )
        )
        await ctx.emit(
            "validation.check",
            step="validate_frontend",
            status=check.status,
            check=f"{CHECK_PREFIX}{check.check}",
            summary=check.summary,
            durationMs=check.duration_ms,
            attempt=attempt,
        )
    write_report(ctx.workspace.reports / f"frontend-validation-{attempt}.json", outcome)
    digest_path = ctx.workspace.reports / f"frontend-digest-{attempt}.txt"
    digest_path.write_text(outcome.digest[:DIGEST_LIMIT])

    failed = outcome.failed_checks
    update: dict[str, Any] = {
        "frontend_validation": outcome.summary,
        "frontend_failed_checks": failed,
        "frontend_digest_ref": str(digest_path),
        "frontend_implicated_files": outcome.implicated_files,
    }
    if fallbacks:
        known = state.get("asset_fallbacks") or []
        update["asset_fallbacks"] = [*known, *({"id": k, "reason": v} for k, v in fallbacks.items())]
    evicted = await _evict_broken_components(state, ctx, failed, outcome.implicated_files)
    if evicted:
        update["evicted_components"] = evicted
    limit = state["max_repair_attempts"]
    if not failed:
        await ctx.set_lane("frontend", LaneStatus.COMPLETED)
        if ctx.mode == GenerationMode.DYNAMIC:
            ctx.start_integration_wait_watchdog()
            await package_lane_preview(state, ctx, "frontend")
    elif state.get("frontend_repair_attempts", 0) >= limit:
        message = (
            f"Frontend validation still failing after {state.get('frontend_repair_attempts', 0)} repair "
            f"attempt(s): {', '.join(failed)}"
        )
        await ctx.set_lane("frontend", LaneStatus.FAILED, reason=message)
        await ctx.abort_backend("frontend lane failed", frontend_failed=True)
        update["outcome"] = Outcome.REPAIR_LIMIT
        update["error_summary"] = message
    return update, {"_status": "failed" if failed else "succeeded", "failedChecks": failed, **fixes}


async def _evict_broken_components(
    state: GenerationState, ctx: JobContext, failed: list[str], implicated: list[str]
) -> list[str]:
    """Story 17.3: cached components that broke the site's typecheck or build leave the cache (once per job): the
    ones the failures point at, or every hit of this job when they point at none of them."""
    hits = state.get("cached_components") or []
    if not hits or state.get("evicted_components") or not {"typecheck", "build"} & set(failed):
        return []
    broken = [key for key in hits if f"{CUSTOM_DIR}/{key}.tsx" in implicated] or hits
    for key in broken:
        ctx.store.evict_component_cache(key)
        drop_files(key)
    await ctx.emit("component.evicted", step="validate_frontend", keys=broken, failedChecks=failed)
    return broken


async def repair_frontend(state: GenerationState, ctx: JobContext) -> NodeResult:
    attempt = state.get("frontend_repair_attempts", 0) + 1
    await ctx.emit(
        "repair.attempt",
        step="repair_frontend",
        attempt=attempt,
        maxAttempts=state["max_repair_attempts"],
        failedChecks=state.get("frontend_failed_checks", []),
    )
    evicted = set(state.get("evicted_components") or [])
    if evicted & set(state.get("cached_components") or []):
        # The evicted components are generated again (they now miss the cache) instead of an engine repair.
        plan = _plan(ctx, state)
        names = [name for name, entry in plan["customComponents"].items() if entry.get("key") in evicted]
        resolved = await _resolve_components(state, ctx, plan, names)
        remaining = sorted(set(state["cached_components"]) - evicted)
        return {"frontend_repair_attempts": attempt, "cached_components": remaining}, {
            "attempt": attempt,
            "regenerated": names,
            **_components_summary(resolved),
        }
    digest_ref = state.get("frontend_digest_ref")
    digest = Path(digest_ref).read_text() if digest_ref else ""
    prompt = ctx.prompts.render(
        "repair_frontend",
        FRONTEND_PROMPTS["repair_frontend"],
        attempt=attempt,
        max_attempts=state["max_repair_attempts"],
        failed_checks=state.get("frontend_failed_checks", []),
        implicated_files=state.get("frontend_implicated_files", []),
        failure_digest=digest or "(no output captured)",
        plan_path=state["frontend_plan_ref"],
        asset_files=sorted(
            path for path in state.get("frontend_implicated_files", []) if path.startswith("src/assets/svg/")
        ),
    )
    try:
        result = await ctx.run_engine("repair_frontend", "repair_frontend", prompt, repo="frontend")
    except EngineFailure:
        await ctx.emit("engine.retry", step="repair_frontend", attempt=attempt)
        result = await ctx.run_engine("repair_frontend", "repair_frontend", prompt, repo="frontend")
    summary: dict[str, Any] = {"attempt": attempt, "changedFiles": result.changed_files[:50]}
    plan = _plan(ctx, state)
    if any(asset["render"] == "svg-component" for asset in plan.get("assets", [])):
        # Story 15.3: the engine may have redrawn an SVG; its component and the registry follow.
        repaired = redraw_after_repair(ctx.workspace.frontend, plan, state.get("frontend_implicated_files", []))
        if repaired:
            summary["assetsRepaired"] = repaired
    return {"frontend_repair_attempts": attempt}, summary


FRONTEND_NODE_FUNCTIONS = {
    "plan_frontend": plan_frontend_node,
    "scaffold_frontend": scaffold_frontend_node,
    "generate_assets": generate_assets,
    "generate_frontend": generate_frontend,
    "validate_frontend": validate_frontend,
    "repair_frontend": repair_frontend,
}
