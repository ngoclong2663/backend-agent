"""Backend lane nodes (FR-09): validate_spec, plan_architecture, generate_database, generate_backend, run_validation
and repair_code. Each is `async (state, ctx) -> (state update, step summary)`."""

import json
import shlex
import uuid
from typing import Any

from src.modules.shared.domain.backend_spec import validate_spec_text
from src.modules.shared.domain.entities import ValidationRunEntity
from src.modules.shared.domain.enums import GenerationMode, LaneStatus

from ..autofix import autofix_before_validation
from ..checks.parity import compare_schema
from ..context import CONTRACT_REF, EngineFailure, JobContext, contract_copy, read_json, write_json
from ..integration.contract import build_contract as contract_for
from ..integration.integrate import package_lane_preview
from ..plugins.app import owned_plugin_files
from ..state import GenerationState, NodeResult, Outcome
from .codegen import (
    codegen_gaps,
    database_files,
    database_gaps,
    is_crud,
    module_files,
    module_tests,
    routers_file,
)
from .completion import complete_modules, module_context
from .migrations import ensure_migration, reflect_schema, verify_migration
from .planner import build_plan, dump_plan
from .scaffold import OWNED_INFO, SCAFFOLD_INFO, add_owned, record_owned, scaffold_project
from .validation import ValidationRequest, generator_bug_files, write_report

DIGEST_LIMIT = 30_000


PROMPT_VERSIONS = {
    "generate_database": "v2",
    "generate_backend": "v3",
    "complete_backend": "v6",
    "repair_code": "v3",
}


def check_backend_spec(state: GenerationState, ctx: JobContext):
    spec = ctx.store.spec(uuid.UUID(state["spec_id"]))
    result = validate_spec_text(spec.raw_json)
    write_json(ctx.workspace.spec_dir / "validation-report.json", result.report.model_dump(mode="json"))
    (ctx.workspace.spec_dir / "spec.raw.json").write_text(spec.raw_json)
    if result.report.valid:
        write_json(ctx.project_path(".bga", "spec.json"), result.normalized)
    return result


async def validate_spec(state: GenerationState, ctx: JobContext) -> NodeResult:
    result = check_backend_spec(state, ctx)
    if not result.report.valid:
        errors = result.report.errors
        await ctx.emit(
            "spec.invalid",
            step="validate_spec",
            errors=[issue.model_dump(mode="json") for issue in errors[:20]],
            total=len(errors),
        )
        summary = f"BackendSpec has {len(errors)} error(s); first: {errors[0].path} {errors[0].message}"
        return {"spec_valid": False, "outcome": Outcome.SPEC_INVALID, "error_summary": summary}, {
            "_status": "failed",
            "errors": len(errors),
        }
    return {"spec_valid": True, "spec_ref": ".bga/spec.json"}, {"warnings": len(result.report.warnings)}


async def plan_architecture(state: GenerationState, ctx: JobContext) -> NodeResult:
    plan = build_plan(read_json(ctx, state["spec_ref"]))
    path = ctx.project_path(".bga", "plan.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_plan(plan))
    summary = {
        "modules": len(plan["modules"]),
        "models": len(plan["models"]),
        "operations": sum(len(m["operations"]) for m in plan["modules"]),
        "tests": len(plan["tests"]),
        "unresolved": len(plan["unresolved"]),
    }
    await ctx.emit("plan.ready", step="plan_architecture", **summary)
    return {"plan_ref": ".bga/plan.json"}, summary


async def _scaffold(state: GenerationState, ctx: JobContext, project_name: str, plan: dict[str, Any]) -> None:
    """Template + overlay, formatted once, owned files recorded, committed as `node:scaffold` (Story 5.2)."""
    project = ctx.workspace.project
    if (project / SCAFFOLD_INFO).exists():
        return
    seed_assets_note = ""
    spec = state.get("spec") or {}
    seed = spec.get("seed") or []
    has_seed_assets = False
    if isinstance(seed, list):
        for entry in seed:
            if isinstance(entry, dict):
                records = entry.get("records") or []
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict) and any(
                            isinstance(v, str) and v.startswith("asset:") for v in record.values()
                        ):
                            has_seed_assets = True
                            break
            if has_seed_assets:
                break
    elif isinstance(seed, dict):
        for records in seed.values():
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict) and any(
                        isinstance(v, str) and v.startswith("asset:") for v in record.values()
                    ):
                        has_seed_assets = True
                        break
            if has_seed_assets:
                break
    if has_seed_assets:
        seed_assets_note = (
            "## Seed data\n\n"
            "Image fields of seed records name frontend assets; "
            "the generated frontend serves the file at `/assets/<id>.webp`."
        )
    info = scaffold_project(
        ctx.template_dir,
        project,
        project_name,
        bool(state["options"].get("generateDockerfile", True)),
        seed_assets_note=seed_assets_note,
        plan=plan,
    )
    sandbox = await ctx.sandbox()
    if sandbox is not None:
        # The pinned template is not ruff-clean (import order, unused names); normalize it once.
        await sandbox.exec("ruff check --fix -q . ; ruff format -q .", timeout_s=120)
    record_owned(project)
    add_owned(project, owned_plugin_files(plan))  # Story 10.1: what the plugins wrote is the generator's too
    ctx.workspaces.commit(ctx.workspace, "node:scaffold")
    await ctx.emit("scaffold.done", step="generate_database", **info)


async def _schema_post_check(ctx: JobContext, plan: dict[str, Any]) -> dict[str, Any]:
    """Story 5.3: autogenerate the migration in the sandbox and compare the migrated schema with the plan.
    Problems are reported here and enforced by run_validation (where repair can fix them)."""
    sandbox = await ctx.sandbox()
    if sandbox is None:
        return {"migration": "not_run"}
    generated, _ = await ensure_migration(sandbox, ctx.workspace.project)
    if generated is not None and not generated.ok:
        result = {"migration": "autogenerate_failed"}
    else:
        verify = await verify_migration(sandbox)
        schema, _ = await reflect_schema(sandbox) if verify.ok else (None, None)
        problems = compare_schema(plan, schema) if schema is not None else None
        result = {
            "migration": "ok" if verify.ok else "failed",
            "schemaProblems": len(problems) if problems is not None else None,
        }
        if problems:
            result["firstProblems"] = [f"{p['table']}: {p['message']}" for p in problems[:5]]
    await ctx.emit("schema.check", step="generate_database", **result)
    return result


def _templates(state: GenerationState) -> bool:
    """Story 17.6: CRUD code from templates (`options.crudFromTemplates`, default on)."""
    return bool(state["options"].get("crudFromTemplates", True))


async def _write_generated(ctx: JobContext, files: dict[str, str], owned: list[str]) -> None:
    """Writes generated files, formats them with the sandbox's ruff (as the scaffold step does for the template)
    and records `owned` as generator-owned."""
    project = ctx.workspace.project
    for relative, text in files.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    sandbox = await ctx.sandbox()
    python = sorted(relative for relative in files if relative.endswith(".py"))
    if sandbox is not None and python:
        paths = shlex.join(python)
        await sandbox.exec(f"ruff check --fix -q {paths} ; ruff format -q {paths}", timeout_s=120)
    add_owned(project, owned)


async def generate_database(state: GenerationState, ctx: JobContext) -> NodeResult:
    spec = read_json(ctx, state["spec_ref"])
    plan = read_json(ctx, state["plan_ref"])
    await _scaffold(state, ctx, spec["project"]["name"], plan)
    gaps = database_gaps(plan) if _templates(state) else ["crudFromTemplates=false"]
    if not gaps:
        files = database_files(plan)
        await _write_generated(ctx, files, list(files))
        await ctx.emit("backend.generated", step="generate_database", part="database", files=len(files))
        return {}, {"generatedFiles": len(files), "engineCalls": 0, **await _schema_post_check(ctx, plan)}
    prompt = ctx.prompts.render(
        "generate_database",
        PROMPT_VERSIONS["generate_database"],
        project_name=spec["project"]["name"],
        spec_path=state["spec_ref"],
        plan_path=state["plan_ref"],
        models=plan["models"],
        file_tree=ctx.file_tree(),
    )
    result = await ctx.run_engine("generate_database", "generate_database", prompt)
    summary = {"changedFiles": len(result.changed_files), "engineCalls": 1, "templateGaps": gaps}
    return {}, {**summary, **await _schema_post_check(ctx, plan)}


async def generate_backend(state: GenerationState, ctx: JobContext) -> NodeResult:
    plan = read_json(ctx, state["plan_ref"])
    if not _templates(state):
        changed = 0
        for module in plan["modules"]:
            if module.get("plugin"):  # Story 10.1: a plugin wrote it at scaffold time
                continue
            prompt = ctx.prompts.render(
                "generate_backend",
                PROMPT_VERSIONS["generate_backend"],
                module=module,
                module_json=_module_json(module),
                spec_path=state["spec_ref"],
                plan_path=state["plan_ref"],
                contract_path=state.get("contract_ref"),
                file_tree=ctx.file_tree(),
            )
            result = await ctx.run_engine("generate_backend", "generate_backend", prompt)
            changed += len(result.changed_files)
        return {}, {"modules": len(plan["modules"]), "changedFiles": changed, "engineCalls": len(plan["modules"])}
    # Story 17.6: every module's CRUD code from templates; the engine only completes what is not CRUD.
    spec = read_json(ctx, state["spec_ref"])
    files = {"src/routers.py": routers_file(plan)}
    owned = ["src/routers.py"]
    generated: dict[str, list[str]] = {}
    run_tests = state["options"].get("runTests", True)
    for module in plan["modules"]:
        if module.get("plugin"):  # Story 10.1: a plugin wrote it at scaffold time
            continue
        # Story 18.11: the template tests come with the code; no engine call writes tests.
        module_code = module_files(plan, spec, module) | (module_tests(plan, spec, module) if run_tests else {})
        files |= module_code
        generated[module["name"]] = sorted(module_code)
        if not codegen_gaps(module):
            owned += list(module_code)
    await _write_generated(ctx, files, owned)
    await ctx.emit("backend.generated", step="generate_backend", part="modules", files=len(files))
    contract = read_json(ctx, state["contract_ref"]) if state.get("contract_ref") else contract_for(spec, plan)

    def render(module: dict[str, Any]):
        # Story 18.13: the prompt carries what the module needs (read from the project as it is now)
        return ctx.prompts.render(
            "complete_backend",
            PROMPT_VERSIONS["complete_backend"],
            module=module,
            module_json=_module_json(module),
            gaps=codegen_gaps(module),
            pack=module_context(ctx.workspace.project, plan, spec, contract, module, generated[module["name"]]),
            spec_path=state["spec_ref"],
            plan_path=state["plan_ref"],
            contract_path=state.get("contract_ref"),
            journeys=[],  # Story 22.8: journeys left with the legacy dynamic flow; the prompt's block stays empty
        )

    pending = [module for module in plan["modules"] if codegen_gaps(module)]
    completion = await complete_modules(ctx, pending, render) if pending else {"completedByEngine": []}
    return {}, {
        "modules": len(plan["modules"]),
        "generatedFiles": len(files),
        "engineCalls": len(pending) + len(completion.get("conflicts", [])),
        **completion,
    }


def _module_json(module: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in module.items() if k != "tests"}, indent=2, sort_keys=True)


async def run_validation(state: GenerationState, ctx: JobContext) -> NodeResult:
    attempt = state.get("repair_attempts", 0) + 1
    contract = None
    if state.get("contract_ref"):
        canonical = contract_copy(ctx).read_text()
        ctx.project_path(*CONTRACT_REF.split("/")).write_text(canonical)  # undo any edit by the engine
        contract = json.loads(canonical)
    fixes = await autofix_before_validation(ctx, "project", attempt, "run_validation")
    plan = read_json(ctx, state["plan_ref"])
    # Story 18.11: the template tests must exist (no engine writes the custom operations' tests any more); the
    # custom operations get one smoke call each, following the contract (backend mode: one built from the spec).
    crud_ops = {op["operationId"] for module in plan["modules"] for op in module["operations"] if is_crud(op)}
    required = [test for test in plan.get("tests", []) if test["operationId"] in crud_ops] if _templates(state) else []
    request = ValidationRequest(
        project=ctx.workspace.project,
        plan=plan,
        run_tests=bool(state["options"].get("runTests", True)),
        sandbox=await ctx.sandbox(),
        contract=contract,
        smoke_contract=contract or contract_for(read_json(ctx, state["spec_ref"]), plan),
        required_tests=required,
    )
    outcome = await ctx.validator.run(request)
    for name, document in request.artifacts.items():
        write_json(ctx.workspace.reports / f"{name}.json", document)
    for check in outcome.results:
        ctx.store.add_validation_run(
            ValidationRunEntity(
                generation_id=ctx.generation_id,
                attempt=attempt,
                check=check.check,
                status=check.status,
                started_at=check.started_at,
                duration_ms=check.duration_ms,
                details={"summary": check.summary, "items": check.details[:50], "output": check.output[-4000:]},
            )
        )
        await ctx.emit(
            "validation.check",
            step="run_validation",
            status=check.status,
            check=check.check,
            summary=check.summary,
            durationMs=check.duration_ms,
            attempt=attempt,
        )
    write_report(ctx.workspace.reports / f"validation-{attempt}.json", outcome)
    digest_path = ctx.workspace.reports / f"digest-{attempt}.txt"
    owned = _owned(ctx)
    owned_failing = sorted(set(outcome.implicated_files) & owned)
    digest = outcome.digest
    if owned_failing:
        digest += (
            "\n\nGenerator-owned files (restored before every check, never edit them; fix the code around them): "
            + ", ".join(owned_failing)
        )
    digest_path.write_text(digest[:DIGEST_LIMIT])

    failed = outcome.failed_checks
    update: dict[str, Any] = {
        "validation": outcome.summary,
        "failed_checks": failed,
        "failure_digest_ref": str(digest_path),
        "implicated_files": outcome.implicated_files,
    }
    at_limit = failed and state.get("repair_attempts", 0) >= state["max_repair_attempts"]
    message = f"Validation still failing after {state.get('repair_attempts', 0)} repair attempt(s): {', '.join(failed)}"
    bug_files = generator_bug_files(outcome, owned)
    if bug_files:  # Story 18.11: no engine call can fix these; say so at once
        at_limit = True
        message = (
            f"Generator bug: {', '.join(failed)} failed only in generator-owned files ({', '.join(bug_files)}); "
            "the engine may not edit them, so no repair was tried"
        )
        if state.get("mode") != GenerationMode.DYNAMIC:
            update["outcome"] = Outcome.GENERATOR_BUG
            update["error_summary"] = message
    if state.get("mode") == GenerationMode.DYNAMIC:
        # Dynamic mode: the backend lane ends here; the frontend lane runs either way (on mocks if this failed).
        if not failed:
            await ctx.set_lane("backend", LaneStatus.COMPLETED)
            await package_lane_preview(state, ctx, "backend")
        elif at_limit:
            await ctx.set_lane("backend", LaneStatus.FAILED, reason=message)
            update["backend_error"] = message
    elif at_limit and not bug_files:
        update["outcome"] = Outcome.REPAIR_LIMIT
        update["error_summary"] = message
    summary = {"_status": "failed" if failed else "succeeded", "failedChecks": failed, **fixes}
    if outcome.warnings:
        summary["warnings"] = outcome.warnings
    return update, summary


def _owned(ctx: JobContext) -> set[str]:
    path = ctx.workspace.project / OWNED_INFO
    return set(json.loads(path.read_text())) if path.is_file() else set()


async def repair_code(state: GenerationState, ctx: JobContext) -> NodeResult:
    attempt = state.get("repair_attempts", 0) + 1
    ctx.store.update_generation(ctx.generation_id, repair_attempts=attempt)
    await ctx.emit(
        "repair.attempt",
        step="repair_code",
        attempt=attempt,
        maxAttempts=state["max_repair_attempts"],
        failedChecks=state.get("failed_checks", []),
    )
    digest_ref = state.get("failure_digest_ref")
    digest = open(digest_ref).read() if digest_ref else ""
    prompt = ctx.prompts.render(
        "repair_code",
        PROMPT_VERSIONS["repair_code"],
        attempt=attempt,
        max_attempts=state["max_repair_attempts"],
        failed_checks=state.get("failed_checks", []),
        implicated_files=state.get("implicated_files", []),
        failure_digest=digest or "(no output captured)",
        plan_path=state["plan_ref"],
        contract_path=state.get("contract_ref"),
    )
    try:
        result = await ctx.run_engine("repair_code", "repair_code", prompt)
    except EngineFailure:
        # An engine hiccup is not a code failure: retry once before giving up (Story 6.3).
        await ctx.emit("engine.retry", step="repair_code", attempt=attempt)
        result = await ctx.run_engine("repair_code", "repair_code", prompt)
    return {"repair_attempts": attempt}, {"attempt": attempt, "changedFiles": result.changed_files[:50]}


BACKEND_NODE_FUNCTIONS = {
    "validate_spec": validate_spec,
    "plan_architecture": plan_architecture,
    "generate_database": generate_database,
    "generate_backend": generate_backend,
    "run_validation": run_validation,
    "repair_code": repair_code,
}
