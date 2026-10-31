"""The workflow nodes (FR-09; `validate_inputs` and `build_contract` for frontend modes, Epic 12).
Each is `async (state, ctx) -> (state update, step summary)`."""

import hashlib
import json
import shlex
import uuid
from pathlib import Path
from typing import Any

from src.configs import config
from src.libs.redaction import default_redactor
from src.modules.shared.domain.backend_spec import SpecIssue, validate_spec_text
from src.modules.shared.domain.entities import ValidationRunEntity
from src.modules.shared.domain.enums import GenerationMode, LaneStatus
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_text
from src.modules.shared.domain.generation_modes import overall_status

from .autofix import autofix_before_validation
from .backend_codegen import (
    codegen_gaps,
    database_files,
    database_gaps,
    is_crud,
    module_files,
    module_tests,
    routers_file,
)
from .checks.consistency import check_spec_pair
from .checks.parity import compare_schema
from .context import EngineFailure, JobContext
from .contract import build_contract as contract_for
from .contract import dump_contract
from .frontend_nodes import FRONTEND_NODE_FUNCTIONS
from .integration import integrate, package_lane_preview
from .migrations import ensure_migration, reflect_schema, verify_migration
from .packaging import (
    MANIFEST_VERSION,
    ArtifactWriter,
    build_contract_seed,
    build_logs_zip,
    build_manifest,
    build_report,
    build_seed,
    build_source_zip,
    report_markdown,
)
from .planner import build_plan, dump_plan
from .scaffold import SCAFFOLD_INFO, add_owned, record_owned, scaffold_project
from .state import GenerationState, Outcome
from .validation import ValidationRequest, write_report

DIGEST_LIMIT = 30_000
PROMPT_VERSIONS = {
    "generate_database": "v2",
    "generate_backend": "v3",
    "complete_backend": "v1",
    "generate_tests": "v2",
    "repair_code": "v3",
}
CONTRACT_REF = ".bga/contract.json"
# kind → name of the artifacts the manifest and the generation detail point at
MAIN_ARTIFACTS = {
    "source": "backend.zip",
    "openapi": "openapi.json",
    "manifest": "manifest.json",
    "report": "report.json",
}
NodeResult = tuple[dict[str, Any], dict[str, Any]]


def _read_json(ctx: JobContext, ref: str) -> dict[str, Any]:
    return json.loads(ctx.project_path(ref).read_text())


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _check_backend_spec(state: GenerationState, ctx: JobContext):
    spec = ctx.store.spec(uuid.UUID(state["spec_id"]))
    result = validate_spec_text(spec.raw_json)
    _write_json(ctx.workspace.spec_dir / "validation-report.json", result.report.model_dump(mode="json"))
    (ctx.workspace.spec_dir / "spec.raw.json").write_text(spec.raw_json)
    if result.report.valid:
        _write_json(ctx.project_path(".bga", "spec.json"), result.normalized)
    return result


async def validate_spec(state: GenerationState, ctx: JobContext) -> NodeResult:
    result = _check_backend_spec(state, ctx)
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


def _issue_dump(issue: SpecIssue, spec: str) -> dict[str, Any]:
    data = issue.model_dump(mode="json", exclude_none=True)
    if "backend_path" in data:
        data["backendPath"] = data.pop("backend_path")
    return {"spec": spec, **data}


async def validate_inputs(state: GenerationState, ctx: JobContext) -> NodeResult:
    """Static and dynamic modes (Stories 12.1, 12.5): the FrontendSpec, in dynamic mode also the BackendSpec and
    the frontend ↔ contract consistency check, all before any engine time is spent."""
    frontend = ctx.store.frontend_spec(uuid.UUID(state["frontend_spec_id"]))
    result = validate_frontend_spec_text(frontend.raw_json)
    spec_dir = ctx.workspace.spec_dir
    (spec_dir / "frontend-spec.raw.json").write_text(frontend.raw_json)
    _write_json(spec_dir / "frontend-validation-report.json", result.report.model_dump(mode="json"))
    errors = [_issue_dump(issue, "frontend") for issue in result.report.errors]
    warnings = len(result.report.warnings)
    if result.normalized is not None and result.normalized["project"]["mode"] != state["mode"]:
        errors.append(
            {
                "spec": "frontend",
                "code": "MODE_INPUT_MISMATCH",
                "path": "/project/mode",
                "message": f"The FrontendSpec is for a '{result.normalized['project']['mode']}' site, "
                f"the generation is '{state['mode']}'",
            }
        )

    update: dict[str, Any] = {}
    if state["mode"] == GenerationMode.DYNAMIC:
        backend = _check_backend_spec(state, ctx)
        errors += [_issue_dump(issue, "backend") for issue in backend.report.errors]
        warnings += len(backend.report.warnings)
        if result.normalized is not None and backend.normalized is not None:
            consistency = check_spec_pair(result.normalized, backend.normalized)
            _write_json(spec_dir / "consistency-report.json", [i.model_dump(mode="json") for i in consistency])
            errors += [_issue_dump(issue, "consistency") for issue in consistency]
        update["spec_ref"] = ".bga/spec.json"

    if errors:
        await ctx.emit("spec.invalid", step="validate_inputs", errors=errors[:20], total=len(errors))
        first = errors[0]
        summary = f"{len(errors)} input error(s); first: {first['spec']} {first['path']} {first['message']}"
        return {"spec_valid": False, "outcome": Outcome.SPEC_INVALID, "error_summary": summary}, {
            "_status": "failed",
            "errors": len(errors),
        }
    _write_json(spec_dir / "frontend-spec.json", result.normalized)
    pages = len(result.normalized["pages"])
    await ctx.emit("inputs.valid", step="validate_inputs", pages=pages, warnings=warnings)
    return {**update, "spec_valid": True, "frontend_ref": str(spec_dir / "frontend-spec.json")}, {
        "pages": pages,
        "warnings": warnings,
    }


def _contract_copy(ctx: JobContext):
    """The canonical contract, outside the project (engines cannot edit it)."""
    return ctx.workspace.spec_dir / "contract.json"


async def build_contract(state: GenerationState, ctx: JobContext) -> NodeResult:
    """Story 12.3: the API contract, before either lane starts; stored as an artifact and in the workspace."""
    spec = _read_json(ctx, state["spec_ref"])
    plan = build_plan(spec)
    text = dump_contract(contract_for(spec, plan))
    _contract_copy(ctx).write_text(text)
    project_copy = ctx.project_path(*CONTRACT_REF.split("/"))
    project_copy.parent.mkdir(parents=True, exist_ok=True)
    project_copy.write_text(text)
    writer = ArtifactWriter(
        Path(config.artifact_root), ctx.generation_id, {a.name: a.id for a in ctx.store.artifacts(ctx.generation_id)}
    )
    artifact = writer.write("contract.json", "contract", text.encode(), "application/json")
    ctx.store.replace_artifacts(ctx.generation_id, [artifact])
    operations = sum(len(module["operations"]) for module in plan["modules"])
    summary = {"operations": operations, "sha256": artifact.sha256, "bytes": artifact.size}
    await ctx.emit("contract.ready", step="build_contract", artifactId=artifact.id, **summary)
    return {"contract_ref": CONTRACT_REF}, summary


async def plan_architecture(state: GenerationState, ctx: JobContext) -> NodeResult:
    plan = build_plan(_read_json(ctx, state["spec_ref"]))
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


async def _scaffold(state: GenerationState, ctx: JobContext, project_name: str) -> None:
    """Template + overlay, formatted once, owned files recorded, committed as `node:scaffold` (Story 5.2)."""
    project = ctx.workspace.project
    if (project / SCAFFOLD_INFO).exists():
        return
    info = scaffold_project(
        ctx.template_dir, project, project_name, bool(state["options"].get("generateDockerfile", True))
    )
    sandbox = await ctx.sandbox()
    if sandbox is not None:
        # The pinned template is not ruff-clean (import order, unused names); normalize it once.
        await sandbox.exec("ruff check --fix -q . ; ruff format -q .", timeout_s=120)
    record_owned(project)
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
    spec = _read_json(ctx, state["spec_ref"])
    plan = _read_json(ctx, state["plan_ref"])
    await _scaffold(state, ctx, spec["project"]["name"])
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
    plan = _read_json(ctx, state["plan_ref"])
    if not _templates(state):
        changed = 0
        for module in plan["modules"]:
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
    spec = _read_json(ctx, state["spec_ref"])
    files = {"src/routers.py": routers_file(plan)}
    owned = ["src/routers.py"]
    generated: dict[str, list[str]] = {}
    for module in plan["modules"]:
        module_code = module_files(plan, spec, module)
        files |= module_code
        generated[module["name"]] = sorted(module_code)
        if not codegen_gaps(module):
            owned += list(module_code)
    await _write_generated(ctx, files, owned)
    await ctx.emit("backend.generated", step="generate_backend", part="modules", files=len(files))
    completed = []
    for module in plan["modules"]:
        gaps = codegen_gaps(module)
        if not gaps:
            continue
        prompt = ctx.prompts.render(
            "complete_backend",
            PROMPT_VERSIONS["complete_backend"],
            module=module,
            module_json=_module_json(module),
            gaps=gaps,
            generated_files=generated[module["name"]],
            spec_path=state["spec_ref"],
            plan_path=state["plan_ref"],
            contract_path=state.get("contract_ref"),
            file_tree=ctx.file_tree(),
        )
        await ctx.run_engine("generate_backend", "complete_backend", prompt)
        completed.append(module["name"])
    return {}, {
        "modules": len(plan["modules"]),
        "generatedFiles": len(files),
        "engineCalls": len(completed),
        "completedByEngine": completed,
    }


def _module_json(module: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in module.items() if k != "tests"}, indent=2, sort_keys=True)


async def generate_tests(state: GenerationState, ctx: JobContext) -> NodeResult:
    if not state["options"].get("runTests", True):
        return {}, {"_status": "skipped", "reason": "runTests=false"}
    plan = _read_json(ctx, state["plan_ref"])
    templates = _templates(state)
    if templates:
        spec = _read_json(ctx, state["spec_ref"])
        files: dict[str, str] = {}
        for module in plan["modules"]:
            files |= module_tests(plan, spec, module)
        owned = [module["testFile"] for module in plan["modules"] if not codegen_gaps(module)]
        await _write_generated(ctx, files, owned)
    engine_calls = 0
    for module in plan["modules"]:
        cases = module["tests"]
        if templates:
            custom = {op["operationId"] for op in module["operations"] if not is_crud(op)}
            cases = [case for case in cases if case["operationId"] in custom]
            if not cases:
                continue
        prompt = ctx.prompts.render(
            "generate_tests",
            PROMPT_VERSIONS["generate_tests"],
            module=module,
            test_cases=cases,
            spec_path=state["spec_ref"],
            plan_path=state["plan_ref"],
        )
        await ctx.run_engine("generate_tests", "generate_tests", prompt)
        engine_calls += 1
    return {}, {"modules": len(plan["modules"]), "engineCalls": engine_calls}


async def run_validation(state: GenerationState, ctx: JobContext) -> NodeResult:
    attempt = state.get("repair_attempts", 0) + 1
    ctx.backend_validating.set()  # the integration wait starts now at the earliest (Story 17.6)
    contract = None
    if state.get("contract_ref"):
        canonical = _contract_copy(ctx).read_text()
        ctx.project_path(*CONTRACT_REF.split("/")).write_text(canonical)  # undo any edit by the engine
        contract = json.loads(canonical)
    fixes = await autofix_before_validation(ctx, "project", attempt, "run_validation")
    request = ValidationRequest(
        project=ctx.workspace.project,
        plan=_read_json(ctx, state["plan_ref"]),
        run_tests=bool(state["options"].get("runTests", True)),
        sandbox=await ctx.sandbox(),
        contract=contract,
    )
    outcome = await ctx.validator.run(request)
    for name, document in request.artifacts.items():
        _write_json(ctx.workspace.reports / f"{name}.json", document)
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
    digest_path.write_text(outcome.digest[:DIGEST_LIMIT])

    failed = outcome.failed_checks
    update: dict[str, Any] = {
        "validation": outcome.summary,
        "failed_checks": failed,
        "failure_digest_ref": str(digest_path),
        "implicated_files": outcome.implicated_files,
    }
    at_limit = failed and state.get("repair_attempts", 0) >= state["max_repair_attempts"]
    message = f"Validation still failing after {state.get('repair_attempts', 0)} repair attempt(s): {', '.join(failed)}"
    if state.get("mode") == GenerationMode.DYNAMIC:
        # Dynamic mode: the backend lane ends here; the frontend lane runs either way (on mocks if this failed).
        if not failed:
            await ctx.set_lane("backend", LaneStatus.COMPLETED)
            await package_lane_preview(state, ctx, "backend")
        elif at_limit:
            await ctx.set_lane("backend", LaneStatus.FAILED, reason=message)
            update["backend_error"] = message
    elif at_limit:
        update["outcome"] = Outcome.REPAIR_LIMIT
        update["error_summary"] = message
    return update, {"_status": "failed" if failed else "succeeded", "failedChecks": failed, **fixes}


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


def _optional_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def _requirement(ctx: JobContext, draft_id: str | None) -> tuple[str, str, bytes, str] | None:
    """The requirement the specs were drafted from (Stories 2.4, 12.4), as an artifact."""
    draft = ctx.store.draft(uuid.UUID(draft_id)) if draft_id else None
    if draft is None or not draft.requirement_text:
        return None
    markdown = draft.requirement_format == "markdown"
    name, content_type = ("requirement.md", "text/markdown") if markdown else ("requirement.txt", "text/plain")
    return name, "requirement", draft.requirement_text.encode(), content_type


async def write_artifacts(ctx: JobContext, state: dict[str, Any], completed: bool, error: str | None = None):
    """Story 7.1 (COMPLETED: everything) and 7.2 (FAILED: report, patches, validation reports, engine logs)."""
    generation = ctx.store.generation(ctx.generation_id)
    workspace, project = ctx.workspace, ctx.workspace.project
    writer = ArtifactWriter(
        Path(config.artifact_root), ctx.generation_id, {a.name: a.id for a in ctx.store.artifacts(ctx.generation_id)}
    )
    spec = _optional_json(project / ".bga" / "spec.json") or {}
    plan = _optional_json(project / ".bga" / "plan.json") or {}

    if (workspace.spec_dir / "spec.raw.json").is_file():
        writer.write("spec.json", "spec", (workspace.spec_dir / "spec.raw.json").read_bytes(), "application/json")
    if (workspace.spec_dir / "frontend-spec.raw.json").is_file():
        raw = (workspace.spec_dir / "frontend-spec.raw.json").read_bytes()
        writer.write("frontend-spec.json", "spec", raw, "application/json")
    requirement = _requirement(ctx, generation.options.get("draftId"))
    if requirement is not None:
        writer.write(*requirement)
    if _contract_copy(ctx).is_file():
        writer.write("contract.json", "contract", _contract_copy(ctx).read_bytes(), "application/json")
    if plan:
        writer.write_json("plan.json", "plan", plan)
    for name, diff in ctx.workspaces.repair_patches(workspace):
        writer.write(name, "patch", diff.encode(), "text/x-diff")
    for path in sorted(workspace.reports.glob("validation-*.json")):
        writer.write(path.name, "validation", path.read_bytes(), "application/json")
    frontend_plan = _optional_json(workspace.frontend / ".bga" / "frontend-plan.json") or {}
    if frontend_plan:
        writer.write_json("frontend-plan.json", "plan", frontend_plan)
    patches = ctx.workspaces.repair_patches(
        workspace, repo="frontend", node="repair_frontend", prefix="frontend-repair"
    )
    for name, diff in patches:
        writer.write(name, "patch", diff.encode(), "text/x-diff")
    for path in sorted(workspace.reports.glob("frontend-validation-*.json")):
        writer.write(path.name, "validation", path.read_bytes(), "application/json")
    if (workspace.reports / "integration-validation.json").is_file():
        writer.write(
            "integration-validation.json",
            "validation",
            (workspace.reports / "integration-validation.json").read_bytes(),
            "application/json",
        )
    lanes = generation.lanes or {"backend": "COMPLETED"}

    report = build_report(
        generation=generation,
        outcome=overall_status(GenerationMode(generation.mode), generation.lanes).value if completed else "FAILED",
        error=error,
        node_runs=ctx.store.node_runs(ctx.generation_id),
        validation_runs=ctx.store.validation_runs(ctx.generation_id),
        invocations=ctx.store.cli_invocations(ctx.generation_id),
        model_calls=ctx.store.model_calls(ctx.generation_id),
        sandbox_execs=ctx.store.sandbox_execs(ctx.generation_id),
        integration=state.get("integration"),
    )
    writer.write_json("report.json", "report", report)
    frontend = _optional_json(workspace.spec_dir / "frontend-spec.json") or {}
    project_name = (spec.get("project") or frontend.get("project") or {}).get("name")
    writer.write("report.md", "report", report_markdown(report, project_name).encode(), "text/markdown")

    operations = 0
    frontend_ready = completed and frontend_plan and lanes.get("frontend") == LaneStatus.COMPLETED.value
    if frontend_ready:
        writer.write("frontend.zip", "frontend", build_source_zip(workspace.frontend), "application/zip")
    if completed and plan and lanes.get("backend") == LaneStatus.COMPLETED.value:
        head_file = workspace.state / "backend-packaged-head"
        packaged_head = head_file.read_text().strip() if head_file.is_file() else None
        current_head = ctx.workspaces._git(workspace, "rev-parse", "HEAD", repo="project").strip()
        existing_backend = ctx.store.artifact_by_name(ctx.generation_id, "backend.zip")
        reuse_backend = (
            existing_backend is not None
            and packaged_head == current_head
            and (Path(config.artifact_root) / existing_backend.path).is_file()
        )
        if reuse_backend:
            writer.keep(existing_backend)
            existing_seed = ctx.store.artifact_by_name(ctx.generation_id, "seed.json")
            if existing_seed is not None and (Path(config.artifact_root) / existing_seed.path).is_file():
                writer.keep(existing_seed)
            existing_openapi = ctx.store.artifact_by_name(ctx.generation_id, "openapi.json")
            if existing_openapi is not None and (Path(config.artifact_root) / existing_openapi.path).is_file():
                writer.keep(existing_openapi)
            openapi = _optional_json(workspace.reports / "openapi.json")
        else:
            writer.write("backend.zip", "source", build_source_zip(project), "application/zip")
            openapi = _optional_json(workspace.reports / "openapi.json")
            if openapi:
                writer.write_json("openapi.json", "openapi", openapi)
            if _contract_copy(ctx).is_file():
                contract = json.loads(_contract_copy(ctx).read_text())
                writer.write_json("seed.json", "seed", build_contract_seed(contract, plan))
            elif spec.get("seed"):
                timestamp = generation.created_at.isoformat() if generation.created_at else "1970-01-01T00:00:00+00:00"
                writer.write_json("seed.json", "seed", build_seed(spec, plan, ctx.generation_id, timestamp))
            head_file.parent.mkdir(parents=True, exist_ok=True)
            head_file.write_text(current_head)
        artifact_ids = {
            kind: writer.artifact_id(name)
            for kind, name in MAIN_ARTIFACTS.items()
            if kind != "openapi" or openapi is not None
        }
        if _contract_copy(ctx).is_file():
            artifact_ids["contract"] = writer.artifact_id("contract.json")
        if frontend_ready:
            artifact_ids["frontend"] = writer.artifact_id("frontend.zip")
        manifest = build_manifest(
            generation=generation,
            generator_version=config.generator_version,
            spec=spec,
            plan=plan,
            openapi=openapi,
            scaffold=_optional_json(project / SCAFFOLD_INFO) or {},
            validation=state.get("validation") or {},
            artifact_ids=artifact_ids,
            project=project,
        )
        operations = len(manifest["operations"])
        if frontend_ready:
            manifest["frontend"] = frontend_manifest(frontend_plan, ctx, state)
        writer.write_json("manifest.json", "manifest", manifest)
    elif frontend_ready:
        artifact_ids = {"frontend": writer.artifact_id("frontend.zip"), "report": writer.artifact_id("report.json")}
        manifest = {
            "manifestVersion": MANIFEST_VERSION,
            "generationId": generation.id,
            "generatorVersion": config.generator_version,
            "engine": generation.engine,
            "mode": generation.mode,
            "createdAt": generation.created_at.isoformat() if generation.created_at else None,
            "project": frontend_plan.get("project"),
            "artifacts": artifact_ids,
            "frontend": frontend_manifest(frontend_plan, ctx, state),
        }
        writer.write_json("manifest.json", "manifest", manifest)
    if not completed:
        logs = build_logs_zip(workspace.state / "logs", default_redactor())
        if logs:
            writer.write("engine-logs.zip", "log", logs, "application/zip")

    ctx.store.replace_artifacts(ctx.generation_id, writer.written)
    for artifact in writer.written:
        await ctx.emit(
            "artifact.created",
            step="package_artifacts",
            artifactId=artifact.id,
            name=artifact.name,
            kind=artifact.kind,
            size=artifact.size,
        )
    main = {*MAIN_ARTIFACTS.values(), "contract.json", "frontend.zip"}
    return {artifact.kind: artifact.id for artifact in writer.written if artifact.name in main}, operations


def _manifest_asset(asset: dict[str, Any]) -> dict[str, Any]:
    """Epic 15: each asset with how it ended up rendered, its file and hash (drawings and uploads)."""
    drawn = asset["render"] == "svg-component" and asset.get("drawn")
    uploaded = asset["render"] == "public-file" and asset.get("src")
    entry: dict[str, Any] = {
        "id": asset["id"],
        "source": asset["source"],
        "render": asset["render"] if drawn or uploaded or asset["render"] in ("remote", "icon") else "placeholder",
        "file": asset.get("file") if drawn or uploaded else None,
        "sha256": asset.get("sha256"),
    }
    if asset["render"] == "svg-component":
        entry["cached"] = bool(asset.get("cached"))
        if asset.get("fallback"):
            entry["fallback"] = asset["fallback"]
    return entry


def frontend_manifest(plan: dict[str, Any], ctx: JobContext, state: dict[str, Any]) -> dict[str, Any]:
    """Story 13.5: what the Integration Agent needs to know about the generated frontend."""
    scaffold = _optional_json(ctx.frontend_path(".bga", "scaffold.json")) or {}
    contract = ctx.workspace.spec_dir / "contract.json"
    section: dict[str, Any] = {
        "mode": plan["project"]["mode"],
        "framework": "nextjs",
        "skill": "nextjs-skills",
        "base": scaffold.get("base"),
        "routes": [
            {"pageId": route["pageId"], "route": route["route"], "title": route["title"]} for route in plan["routes"]
        ],
        "theme": {key: plan["theme"][key] for key in ("colorScheme", "radius", "density", "fonts")},
        "validation": state.get("frontend_validation") or {},
        "env": ["MOCK_TEST_API", "API_BASE_URL"] if plan["project"]["mode"] == "dynamic" else [],
        "assets": [_manifest_asset(asset) for asset in plan.get("assets", [])],
    }
    if contract.is_file():
        section["contractSha256"] = hashlib.sha256(contract.read_bytes()).hexdigest()
    return section


async def package_artifacts(state: GenerationState, ctx: JobContext) -> NodeResult:
    if ctx.mode == GenerationMode.BACKEND:
        await ctx.set_lane("backend", LaneStatus.COMPLETED)
    artifact_ids, operations = await write_artifacts(ctx, state, completed=True)
    summary = {"artifacts": sorted(artifact_ids), "operations": operations}
    return {"outcome": Outcome.COMPLETED, "artifact_ids": artifact_ids}, summary


NODE_FUNCTIONS = {
    **FRONTEND_NODE_FUNCTIONS,
    "validate_inputs": validate_inputs,
    "build_contract": build_contract,
    "validate_spec": validate_spec,
    "plan_architecture": plan_architecture,
    "generate_database": generate_database,
    "generate_backend": generate_backend,
    "generate_tests": generate_tests,
    "run_validation": run_validation,
    "repair_code": repair_code,
    "integrate": integrate,
    "package_artifacts": package_artifacts,
}
