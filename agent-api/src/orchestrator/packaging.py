"""Artifact packaging (Story 7.1): source ZIP, OpenAPI, manifest, report, seed, plan/spec copies and patches.

Everything is written to `$ARTIFACT_ROOT/<generation>/<name>` and registered in `artifacts`. Output is
deterministic (sorted ZIP entries, fixed mtimes, artifact ids reused per name), so re-running the node produces
byte-identical files. Failed generations get the diagnostic subset (report, patches, validation reports, logs).
"""

import ast
import hashlib
import io
import json
import re
import tarfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.engines.workspace import ensure_inside, strip_managed_section
from src.libs.ids import new_artifact_id
from src.libs.redaction import Redactor
from src.modules.shared.domain.entities import (
    ArtifactEntity,
    CliInvocationEntity,
    GenerationEntity,
    ModelCallEntity,
    NodeRunEntity,
    SandboxExecEntity,
    ValidationRunEntity,
)
from src.modules.shared.domain.telemetry import ExecutionRecords, rollup

from .backend.validation import CHECKS
from .checks.parity import IGNORED_PATHS, compare_openapi

MANIFEST_VERSION = "1.0"
REPORT_VERSION = "1.1"  # 1.1: usage rollups (wall/engine/sandbox time, model calls, cost by source, per node/model)
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".bga",
    ".claude",
    ".agents",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".next",
    "out",
    "test-results",
    "playwright-report",
}
ZIP_SKIP_FILES = {".env", ".env.local"}
CONTEXT_FILES = {"CLAUDE.md", "AGENTS.md"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
SECRET_NAME = re.compile(r"(SECRET|PASSWORD|TOKEN|API_KEY|_KEY$|DB_URL$)")
UUID_NAMESPACE = uuid.UUID("6f1c2a4e-7d9b-4c3e-9a51-2b8d7e0f4c11")
JSON = "application/json"


@dataclass
class ArtifactWriter:
    """Writes files under `<root>/<generation>/` and remembers their rows; ids are reused per name."""

    root: Path
    generation_id: str
    ids: dict[str, str] = field(default_factory=dict)  # name → id, seeded from existing rows
    written: list[ArtifactEntity] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        return ensure_inside(self.root / self.generation_id, self.root)

    def artifact_id(self, name: str) -> str:
        return self.ids.setdefault(name, new_artifact_id())

    def keep(self, artifact: ArtifactEntity) -> None:
        self.ids[artifact.name] = artifact.id
        self.written = [a for a in self.written if a.name != artifact.name] + [artifact]

    def write(self, name: str, kind: str, data: bytes, content_type: str) -> ArtifactEntity:
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        artifact = ArtifactEntity(
            id=self.artifact_id(name),
            generation_id=self.generation_id,
            kind=kind,
            name=name,
            path=f"{self.generation_id}/{name}",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )
        self.written = [a for a in self.written if a.name != name] + [artifact]
        return artifact

    def write_json(self, name: str, kind: str, document: Any) -> ArtifactEntity:
        return self.write(name, kind, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode(), JSON)


# -- source ZIP --------------------------------------------------------------------------------------------------


def source_files(project: Path) -> list[Path]:
    files = []
    for path in project.rglob("*"):
        relative = path.relative_to(project)
        if ZIP_SKIP_DIRS & set(relative.parts[:-1]):
            continue
        if path.is_file() and not path.is_symlink() and path.name not in ZIP_SKIP_FILES and path.suffix != ".pyc":
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(project).as_posix())


def build_source_zip(project: Path) -> bytes:
    """The project as a user would clone it: no venv, caches, git, agent internals or engine skill copies."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in source_files(project):
            relative = path.relative_to(project).as_posix()
            data = path.read_bytes()
            if relative in CONTEXT_FILES:
                data = strip_managed_section(data.decode()).encode()
                if not data:
                    continue
            info = zipfile.ZipInfo(relative, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if path.stat().st_mode & 0o111 else 0o100644) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


# -- preview runtime (2026-11-08) ---------------------------------------------------------------------------------
# A frontend preview built from frontend.zip runs `pnpm install` and `next build` again (about two minutes); the
# frontend lane's validation has just built the same source. The runtime is that build with the project's own last
# Dockerfile stage, as a gzipped build context: the preview's image is then a copy (about ten seconds).

PREVIEW_RUNTIME = "frontend-runtime.tar.gz"
_FROM_BUILD = re.compile(r"^COPY\s+--from=build\s+((?:--\S+\s+)*)/app/(\S+)\s+(\S+)\s*$")
_COPY = re.compile(r"^COPY\s+((?:--\S+\s+)*)(\S+)\s+(\S+)\s*$")
_ROOT = "rootfs"  # the merged copies' tree in the runtime context


@dataclass
class _Copy:
    flags: str  # e.g. "--chown=node:node " (with its space), or ""
    source: str  # relative to the project
    target: str  # absolute in the image


def _runtime_stage(dockerfile: str) -> tuple[list[str], list[_Copy], int, str | None] | None:
    """The last stage of the project's Dockerfile: its lines without the copies, the copies (copies from the build
    stage read the project's own build output), where the first copy was and the WORKDIR; None when a line cannot
    be mapped (another stage, an ARG image, a relative target without a WORKDIR)."""
    lines = dockerfile.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip().upper().startswith("FROM ")]
    if not starts or "$" in lines[starts[-1]]:
        return None
    kept: list[str] = []
    copies: list[_Copy] = []
    first = -1
    workdir: str | None = None
    for line in lines[starts[-1] :]:
        text = line.strip()
        if text.upper().startswith("WORKDIR "):
            workdir = text.split(None, 1)[1]
        if not text.upper().startswith("COPY "):
            kept.append(line)
            continue
        match = _FROM_BUILD.match(text) or (None if "--from" in text else _COPY.match(text))
        if match is None:
            return None
        flags, source, target = match.groups()
        if not target.startswith("/"):
            if workdir is None or not workdir.startswith("/"):
                return None
            relative = target[2:] if target.startswith("./") else "" if target == "." else target
            target = workdir.rstrip("/") + "/" + relative
        if first < 0:
            first = len(kept)
        copies.append(_Copy(flags, source.rstrip("/"), target))
    return kept, copies, first, workdir


def _image_path(copy: _Copy, source: Path) -> str:
    """Where `COPY <source> <target>` puts the source: a directory's contents into the target directory, a file at
    the target, or into it when the target ends with a slash."""
    target = copy.target.rstrip("/")
    if source.is_file() and copy.target.endswith("/"):
        return f"{target}/{source.name}"
    return target


def build_preview_runtime(project: Path) -> bytes | None:
    """The validated build of a generated frontend as a preview build context (gzipped tar), or None when there is
    none or it is older than a source (the preview then builds the ZIP's Dockerfile). The stage's copies become one
    layer when they share their flags and land in the WORKDIR (three copies of a Node server build twice as long)."""
    dockerfile, build_id = project / "Dockerfile", project / ".next" / "BUILD_ID"
    if not dockerfile.is_file() or not build_id.is_file():
        return None
    stage = _runtime_stage(dockerfile.read_text(errors="replace"))
    if stage is None:
        return None
    kept, copies, first, workdir = stage
    built = build_id.stat().st_mtime
    if any(path.stat().st_mtime >= built for path in source_files(project)):
        return None  # a source changed after the build (or in the same clock tick)
    root = project.resolve()
    sources = [project / copy.source for copy in copies]
    if not all(source.exists() and root in [source.resolve(), *source.resolve().parents] for source in sources):
        return None
    home = (workdir or "").rstrip("/")
    merged = bool(home) and len({copy.flags for copy in copies}) == 1
    merged = merged and all(copy.target.rstrip("/") == home or copy.target.startswith(home + "/") for copy in copies)
    if merged:  # only inside the WORKDIR: system directories keep their owners
        lines = [*kept[:first], f"COPY {copies[0].flags}{_ROOT}{home}/ {home}/", *kept[first:]]
        names = [_ROOT + _image_path(copy, source) for copy, source in zip(copies, sources, strict=True)]
    else:
        lines, names = list(kept), []
        for offset, copy in enumerate(copies):
            lines.insert(first + offset, f"COPY {copy.flags}{copy.source} {copy.target}")
            names.append(copy.source)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=1) as archive:
        text = ("\n".join(lines) + "\n").encode()
        info = tarfile.TarInfo("Dockerfile")
        info.size = len(text)
        archive.addfile(info, io.BytesIO(text))
        for name, source in zip(names, sources, strict=True):
            archive.add(source, arcname=name)  # relative symlinks (pnpm's) stay links
    return buffer.getvalue()


def write_frontend(writer: "ArtifactWriter", project: Path) -> None:
    """frontend.zip and, when the validated build is current, the preview runtime next to it."""
    writer.write("frontend.zip", "frontend", build_source_zip(project), "application/zip")
    runtime = build_preview_runtime(project)
    if runtime is not None:
        writer.write(PREVIEW_RUNTIME, "preview", runtime, "application/gzip")
    elif PREVIEW_RUNTIME in writer.ids:  # an earlier runtime no longer matches the ZIP: empty, so it is not used
        writer.write(PREVIEW_RUNTIME, "preview", b"", "application/gzip")


# -- manifest ----------------------------------------------------------------------------------------------------


def _schema_name(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        inner = _schema_name(schema["items"])
        return f"{inner}[]" if inner else "array"
    return schema.get("type")


def _json_schema(container: dict[str, Any] | None) -> dict[str, Any] | None:
    return ((container or {}).get("content") or {}).get(JSON, {}).get("schema")


def operations_from_openapi(document: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    planned = {op["operationId"]: op for module in plan.get("modules", []) for op in module["operations"]}
    operations = []
    for path, item in sorted(document.get("paths", {}).items()):
        if path in IGNORED_PATHS:
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict) or "operationId" not in operation:
                continue
            responses = operation.get("responses", {})
            success = next((code for code in sorted(responses) if code.startswith("2")), None)
            plan_op = planned.get(operation["operationId"], {})
            auth = (plan_op.get("auth") or {}).get("auth") or ("jwt" if operation.get("security") else "none")
            entry = {
                "operationId": operation["operationId"],
                "method": method.upper(),
                "path": path,
                "auth": auth,
                "requestSchema": _schema_name(_json_schema(operation.get("requestBody"))),
                "responseSchema": _schema_name(_json_schema(responses.get(success))) if success else None,
                "statusCodes": sorted(int(code) for code in responses if code.isdigit()),
            }
            if (plan_op.get("auth") or {}).get("policy"):
                entry["policy"] = plan_op["auth"]["policy"]
            if plan_op.get("rules"):  # Story 10.4: the rules the operation enforces
                entry["rules"] = list(plan_op["rules"])
            operations.append({k: v for k, v in entry.items() if v is not None})
    return sorted(operations, key=lambda op: (op["path"], op["method"]))


def _rules_manifest(spec: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Each spec rule: its kind, the operations that enforce it and who implements it (templates, the engine, or
    nobody: ambiguous or named by no operation)."""
    out = []
    for rule in spec.get("rules", []):
        ops = [
            op
            for module in plan.get("modules", [])
            for op in module["operations"]
            if rule["id"] in (op.get("rules") or [])
        ]
        if any(rule["id"] in (op.get("templatedRules") or []) for op in ops):
            implementation = "template"
        elif any(rule["id"] in (op.get("skippedRules") or []) for op in ops) or not ops:
            implementation = "none"
        else:
            implementation = "engine"
        out.append({"id": rule["id"], "kind": rule["kind"], "operations": sorted(op["operationId"] for op in ops),
                    "implementation": implementation})  # fmt: skip
    return out


def operations_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback when no OpenAPI was exported (sandbox disabled): the planned surface, marked as such."""
    operations = []
    for module in plan.get("modules", []):
        for op in module["operations"]:
            codes = {op["status"], *(error["status"] for error in op.get("errors", []))}
            entry = {
                "operationId": op["operationId"],
                "method": op["method"],
                "path": op["path"],
                "auth": (op.get("auth") or {}).get("auth") or "none",
                "requestSchema": op.get("requestDto"),
                "responseSchema": op.get("responseDto"),
                "statusCodes": sorted(codes),
            }
            operations.append({k: v for k, v in entry.items() if v is not None})
    return sorted(operations, key=lambda op: (op["path"], op["method"]))


def env_variables(project: Path) -> list[dict[str, Any]]:
    """From the generated `.env.ex` (names, comments) and `src/configs/config.py` (fields without default)."""
    required: set[str] = set()
    config_file = project / "src" / "configs" / "config.py"
    if config_file.is_file():
        try:
            tree = ast.parse(config_file.read_text())
        except SyntaxError:
            tree = None
        for node in ast.walk(tree) if tree else []:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is None:
                required.add(node.target.id.upper())
    variables, comment = [], []
    env_file = project / ".env.ex"
    for line in env_file.read_text().splitlines() if env_file.is_file() else []:
        stripped = line.strip()
        if stripped.startswith("#"):
            comment.append(stripped.lstrip("# "))
            continue
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            variables.append(
                {
                    "name": name,
                    "required": name in required,
                    "secret": bool(SECRET_NAME.search(name)),
                    "description": " ".join(comment) or None,
                }
            )
        comment = []
    return variables


def build_manifest(
    *,
    generation: GenerationEntity,
    generator_version: str,
    spec: dict[str, Any],
    plan: dict[str, Any],
    openapi: dict[str, Any] | None,
    scaffold: dict[str, Any],
    validation: dict[str, str],
    artifact_ids: dict[str, str],
    project: Path,
) -> dict[str, Any]:
    operations = operations_from_openapi(openapi, plan) if openapi else operations_from_plan(plan)
    manifest: dict[str, Any] = {
        "manifestVersion": MANIFEST_VERSION,
        "generationId": generation.id,
        "generatorVersion": generator_version,
        "templateRef": scaffold.get("templateRef"),
        "overlayVersion": scaffold.get("overlayVersion"),
        "architecture": plan.get("architecture", "fastapi-skills-hexagonal"),
        "specVersion": spec.get("specVersion"),
        "framework": "fastapi",
        "engine": generation.engine,
        "createdAt": generation.created_at.isoformat() if generation.created_at else None,
        "project": plan.get("project"),
        "api": {
            "openapiArtifactId": artifact_ids.get("openapi"),
            "basePath": "",
            "source": "openapi" if openapi else "plan",
        },
        "operations": operations,
        "contractProblems": compare_openapi(plan, openapi) if openapi else [],
        "env": env_variables(project),
        "artifacts": artifact_ids,
        "validation": {check: validation.get(check, "not_run") for check in CHECKS},
        "modules": [
            {"name": m["name"], "entity": m["entity"], "path": f"src/modules/{m['name']}"}
            for m in plan.get("modules", [])
        ],
        "unresolved": plan.get("unresolved", []),
        "plugins": plan.get("plugins", []),  # Story 10.1
        "rules": _rules_manifest(spec, plan),  # Story 10.4
        "jobs": [  # Story 10.6: kinds, triggers, schedules
            {key: job[key] for key in ("name", "trigger", "action", "maxAttempts") if key in job}
            for job in plan.get("jobs", [])
        ],
        "assumptions": spec.get("x-assumptions", []),
    }
    if spec.get("auth"):
        manifest["auth"] = {"type": spec["auth"].get("type", "jwt"), "tokenType": "bearer"}
        auth = plan.get("auth")
        if auth:  # Story 10.2: how to sign in, and the seeded demo users (the agent UI's "Get token")
            manifest["auth"] |= {
                "login": {"operationId": "auth.login", "path": "/auth/login", "loginField": auth["loginField"]},
                "register": {"operationId": "auth.register", "path": "/auth/register"},
                "me": {"operationId": "auth.me", "path": "/auth/me"},
                "roles": auth["roles"],
                "demoUsers": auth["demoUsers"],
            }
    if plan.get("emails") or plan.get("account"):  # Story 10.7: where the preview's emails land
        from src.sandbox.mail_service import inbox_url

        manifest["email"] = {"inbox": inbox_url(generation.id), "emails": [e["name"] for e in plan.get("emails", [])]}
    if spec.get("x-frontendBindings"):
        manifest["frontendBindings"] = spec["x-frontendBindings"]
    return manifest


# -- seed --------------------------------------------------------------------------------------------------------


def build_seed(spec: dict[str, Any], plan: dict[str, Any], generation_id: str, timestamp: str) -> list[dict[str, Any]]:
    """BackendSpec `seed[]` (entity + API field names) → `scripts/seed.py` blocks (table + column names).
    Missing primary keys and factory defaults (ids, `now`) are filled deterministically, because the generated
    models set them in Python (default_factory), not in the database."""
    from .plugins import extended_spec

    spec = extended_spec(spec)  # Story 10.2: demo users
    models = {model["entity"]: model for model in plan.get("models", [])}
    blocks = []
    for seed_index, seed in enumerate(spec.get("seed", [])):
        model = models.get(seed["entity"])
        if model is None:
            continue
        columns = {column["field"]: column for column in model["columns"]}
        rows = []
        for row_index, record in enumerate(seed["records"]):
            row = {columns[name]["attr"]: value for name, value in record.items() if name in columns}
            for column in model["columns"]:
                if column["attr"] in row:
                    continue
                default = column.get("default") or {}
                if default.get("factory") == "uuid.uuid4":
                    row[column["attr"]] = str(uuid.uuid5(UUID_NAMESPACE, f"{generation_id}:{seed_index}:{row_index}"))
                elif default.get("factory"):
                    row[column["attr"]] = timestamp
                elif "value" in default:
                    row[column["attr"]] = default["value"]
            rows.append(row)
        blocks.append({"table": model["table"], "rows": rows})
    return _parents_first(blocks, plan)


def _parents_first(blocks: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Seed blocks in an order the foreign keys allow: a referenced table's rows before its children's (a plugin's
    entity, the auth-jwt users, comes last in the spec but owns records, Story 10.3)."""
    parents = {
        model["table"]: {fk["references"].partition(".")[0] for fk in model.get("foreignKeys", [])} - {model["table"]}
        for model in plan.get("models", [])
    }
    ordered: list[dict[str, Any]] = []
    pending = list(blocks)
    while pending:
        waiting = [{other["table"] for other in pending if other is not block} for block in pending]
        ready = [
            block
            for block, others in zip(pending, waiting, strict=True)
            if not parents.get(block["table"], set()) & others
        ]
        for block in ready or pending[:1]:  # a cycle: the spec's order, and the database decides
            ordered.append(block)
            pending.remove(block)
    return ordered


def seed_artifact(contract: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]] | dict[str, Any]:
    """`seed.json` (Epic 29): the rows, and, for an app with file fields, the seeded objects with their sample bytes,
    so a preview's media fields play (`scripts/seed.py` uploads them). Without objects, the rows alone, as before."""
    from .samples import storage_objects

    rows = build_contract_seed(contract, plan)
    objects = storage_objects(contract)
    return {"rows": rows, "objects": objects} if objects else rows


def build_contract_seed(contract: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """In dynamic mode, seeds the backend preview database with `x-bga.fixtures` from the contract so the live API
    serves the exact records the frontend and its Playwright smoke tests expect."""
    fixtures = (contract.get("x-bga") or {}).get("fixtures") or {}
    blocks = []
    for model in plan.get("models", []):
        # a link model's records are under its class name without `Model` (Story 10.11)
        records = fixtures.get(model.get("entity") or model["class"].removesuffix("Model")) or []
        if not records:
            continue
        columns = {column["field"]: column["attr"] for column in model["columns"]}
        rows = [{columns[k]: v for k, v in record.items() if k in columns} for record in records]
        blocks.append({"table": model["table"], "rows": rows})
    return _parents_first(blocks, plan)


# -- report ------------------------------------------------------------------------------------------------------


def _ms(start, end) -> int | None:
    return int((end - start).total_seconds() * 1000) if start and end else None


def build_report(
    *,
    generation: GenerationEntity,
    outcome: str,
    error: str | None,
    node_runs: list[NodeRunEntity],
    validation_runs: list[ValidationRunEntity],
    invocations: list[CliInvocationEntity],
    model_calls: list[ModelCallEntity] | None = None,
    sandbox_execs: list[SandboxExecEntity] | None = None,
    integration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps = [run for run in node_runs if run.node != "package_artifacts"]
    attempts = sorted({run.attempt for run in validation_runs})
    by_check: dict[str, ValidationRunEntity] = {}
    for run in validation_runs:
        prev = by_check.get(run.check)
        if prev is None or run.attempt >= prev.attempt:
            by_check[run.check] = run
    latest = list(by_check.values())
    integration_runs = [run for run in latest if run.check.startswith("integration:")]
    by_purpose: dict[str, dict[str, Any]] = {}
    for invocation in invocations:
        bucket = by_purpose.setdefault(
            invocation.purpose, {"calls": 0, "inputTokens": 0, "outputTokens": 0, "costUsd": 0.0, "durationMs": 0}
        )
        bucket["calls"] += 1
        bucket["inputTokens"] += invocation.input_tokens or 0
        bucket["outputTokens"] += invocation.output_tokens or 0
        bucket["costUsd"] = round(bucket["costUsd"] + (invocation.cost_usd or 0.0), 6)
        bucket["durationMs"] += invocation.duration_ms or 0
    first = min((run.started_at for run in steps if run.started_at), default=None)
    last = max((run.finished_at for run in steps if run.finished_at), default=None)
    report: dict[str, Any] = {
        "reportVersion": REPORT_VERSION,
        "generationId": generation.id,
        "outcome": outcome,
        "error": error,
        "engine": generation.engine,
        "durationMs": _ms(first, last),
        "checks": [
            {
                "check": run.check,
                "status": run.status,
                "durationMs": run.duration_ms,
                "summary": run.details.get("summary"),
                **(
                    {"items": run.details["items"]}
                    if run.check.startswith("integration:") and run.details.get("items")
                    else {}
                ),
                **(
                    {"output": run.details["output"]}
                    if run.check.startswith("integration:") and run.details.get("output")
                    else {}
                ),
            }
            for run in latest
        ],
        "validationAttempts": len(attempts),
        "repairs": [
            {
                "attempt": run.attempt,
                "status": run.status,
                "durationMs": _ms(run.started_at, run.finished_at),
                "changedFiles": run.summary.get("changedFiles", []),
            }
            for run in steps
            if run.node == "repair_code"
        ],
        "steps": [
            {
                "node": run.node,
                "attempt": run.attempt,
                "status": run.status,
                "durationMs": _ms(run.started_at, run.finished_at),
            }
            for run in steps
        ],
        "usage": {
            "calls": len(invocations),
            "inputTokens": sum(b["inputTokens"] for b in by_purpose.values()),
            "outputTokens": sum(b["outputTokens"] for b in by_purpose.values()),
            "costUsd": round(sum(b["costUsd"] for b in by_purpose.values()), 6),
            "byPurpose": by_purpose,
            # Pinned to the finished steps (packaging runs inside the job), so repackaging gives the same report.
            **rollup(
                ExecutionRecords(
                    generation=generation.model_copy(update={"started_at": first, "finished_at": last}),
                    node_runs=steps,
                    invocations=invocations,
                    model_calls=model_calls or [],
                    validation_runs=validation_runs,
                    sandbox_execs=sandbox_execs or [],
                )
            ),
        },
    }
    if integration is not None or integration_runs:
        report["integration"] = {
            **(integration or {}),
            "checks": [
                {
                    "check": run.check.removeprefix("integration:"),
                    "status": run.status,
                    "durationMs": run.duration_ms,
                    "summary": run.details.get("summary"),
                    "items": run.details.get("items", []),
                    **({"output": run.details["output"]} if run.details.get("output") else {}),
                }
                for run in integration_runs
            ],
        }
    return report


def report_markdown(report: dict[str, Any], project_name: str | None) -> str:
    lines = [
        f"# Generation report — {project_name or report['generationId']}",
        "",
        f"- Generation: `{report['generationId']}`",
        f"- Outcome: **{report['outcome']}**" + (f" — {report['error']}" if report.get("error") else ""),
        f"- Engine: {report['engine']}",
        f"- Duration: {round((report['durationMs'] or 0) / 1000)} s",
        f"- Validation attempts: {report['validationAttempts']}",
        f"- Engine usage: {report['usage']['calls']} call(s), {report['usage']['inputTokens']:,} input / "
        f"{report['usage']['outputTokens']:,} output tokens, ${report['usage']['costUsd']:.2f}",
        *_cost_lines(report["usage"]),
        "",
        "## Checks (last attempt)",
        "",
        "| Check | Status | Duration | Summary |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {c['check']} | {c['status']} | {c['durationMs'] or 0} ms | {(c['summary'] or '').replace('|', '/')} |"
        for c in report["checks"]
    ]
    lines += ["", "## Steps", "", "| Step | Attempt | Status | Duration |", "|---|---|---|---|"]
    lines += [
        f"| {s['node']} | {s['attempt']} | {s['status']} | {round((s['durationMs'] or 0) / 1000, 1)} s |"
        for s in report["steps"]
    ]
    if report["repairs"]:
        lines += ["", "## Repairs", ""]
        lines += [
            f"- Attempt {r['attempt']} ({r['status']}): {', '.join(r['changedFiles'][:10]) or 'no files changed'}"
            for r in report["repairs"]
        ]
    return "\n".join(lines) + "\n"


def _cost_lines(usage: dict[str, Any]) -> list[str]:
    cost = usage.get("cost")
    if not cost:
        return []
    line = f"- Model calls: {usage['modelCalls']}, cost ${cost['reported']:.4f} reported"
    if cost["estimated"]:
        line += f" + ~${cost['estimated']:.4f} estimated"
    if cost["unpriced"]:
        line += f" ({cost['unpriced']} call(s) without a price)"
    seconds = {key: round((usage.get(key) or 0) / 1000) for key in ("wallMs", "engineMs", "sandboxMs")}
    return [
        line,
        f"- Time: {seconds['wallMs']} s wall, {seconds['engineMs']} s engine, {seconds['sandboxMs']} s sandbox",
    ]


# -- diagnostics -------------------------------------------------------------------------------------------------


def build_logs_zip(logs_dir: Path, redactor: Redactor) -> bytes | None:
    """Engine stdout/stderr logs, redacted (they are stored raw in the job's state directory)."""
    files = sorted(p for p in logs_dir.glob("*.log") if p.is_file()) if logs_dir.is_dir() else []
    if not files:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, redactor.redact(path.read_text(errors="replace")))
    return buffer.getvalue()
