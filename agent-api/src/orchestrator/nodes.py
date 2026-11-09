"""The workflow's node table (each lane's nodes, Epic 12) and the artifacts both lanes end with
(`package_artifacts`, `write_artifacts`)."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from src.configs import config
from src.libs.redaction import default_redactor
from src.modules.shared.domain.enums import GenerationMode, LaneStatus
from src.modules.shared.domain.generation_modes import overall_status

from .backend.nodes import BACKEND_NODE_FUNCTIONS
from .backend.scaffold import SCAFFOLD_INFO
from .context import JobContext, contract_copy
from .frontend.nodes import FRONTEND_NODE_FUNCTIONS
from .integration.nodes import INTEGRATION_NODE_FUNCTIONS
from .packaging import (
    MANIFEST_VERSION,
    ArtifactWriter,
    build_logs_zip,
    build_manifest,
    build_report,
    build_seed,
    build_source_zip,
    report_markdown,
    seed_artifact,
    write_frontend,
)
from .state import GenerationState, NodeResult, Outcome

# kind → name of the artifacts the manifest and the generation detail point at
MAIN_ARTIFACTS = {
    "source": "backend.zip",
    "openapi": "openapi.json",
    "manifest": "manifest.json",
    "report": "report.json",
}


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
    if contract_copy(ctx).is_file():
        writer.write("contract.json", "contract", contract_copy(ctx).read_bytes(), "application/json")
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
        write_frontend(writer, workspace.frontend)
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
            if contract_copy(ctx).is_file():
                contract = json.loads(contract_copy(ctx).read_text())
                writer.write_json("seed.json", "seed", seed_artifact(contract, plan))
            else:  # the spec's seed, and what plugins add to it (Story 10.2: demo users)
                timestamp = generation.created_at.isoformat() if generation.created_at else "1970-01-01T00:00:00+00:00"
                seed = build_seed(spec, plan, ctx.generation_id, timestamp)
                if seed:
                    writer.write_json("seed.json", "seed", seed)
            head_file.parent.mkdir(parents=True, exist_ok=True)
            head_file.write_text(current_head)
        artifact_ids = {
            kind: writer.artifact_id(name)
            for kind, name in MAIN_ARTIFACTS.items()
            if kind != "openapi" or openapi is not None
        }
        if contract_copy(ctx).is_file():
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
        "env": ["MOCK_TEST_API", "API_BASE_URL", "API_INTERNAL_URL", "AUTH_TOKEN_STORAGE"]
        if plan["project"]["mode"] == "dynamic"
        else [],
        "assets": [_manifest_asset(asset) for asset in plan.get("assets", [])],
    }
    if contract.is_file():
        section["contractSha256"] = hashlib.sha256(contract.read_bytes()).hexdigest()
    return section


async def package_artifacts(state: GenerationState, ctx: JobContext) -> NodeResult:
    if ctx.mode == GenerationMode.BACKEND:
        await ctx.set_lane("backend", LaneStatus.COMPLETED)
    elif ctx.mode == GenerationMode.STATIC:
        await ctx.set_lane("frontend", LaneStatus.COMPLETED)
    artifact_ids, operations = await write_artifacts(ctx, state, completed=True)
    summary = {"artifacts": sorted(artifact_ids), "operations": operations}
    return {"outcome": Outcome.COMPLETED, "artifact_ids": artifact_ids}, summary


NODE_FUNCTIONS = {
    **FRONTEND_NODE_FUNCTIONS,
    **INTEGRATION_NODE_FUNCTIONS,
    **BACKEND_NODE_FUNCTIONS,
    "package_artifacts": package_artifacts,
}
