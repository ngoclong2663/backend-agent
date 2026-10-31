"""Dynamic integration lane (Stories 14.2, 14.3): readiness check, MOCK_TEST_API switch and live smoke checks.

After the parallel backend and frontend lanes finish, `integrate`:
1. Restores the canonical `.bga/contract.json` in both workspaces so neither engine could have altered it.
2. Waits up to `INTEGRATION_WAIT_SECONDS` while the backend lane or its preview is still starting, then checks
   that the backend lane is `COMPLETED`, `GET /health` → 200, and `GET /openapi.json` matches the contract.
3. If healthy, restarts the frontend preview with `MOCK_TEST_API=false` and `API_BASE_URL=<backend preview URL>`
   (`integration.switched_to_live`) and runs the live integration checks (`integration:health`,
   `integration:contract`, `integration:smoke`).
4. If not healthy, keeps `MOCK_TEST_API=true` (`integration.kept_mocks`), records the reason and finishes the
   job as `COMPLETED_WITH_WARNINGS`.
"""

import asyncio
import hashlib
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any

from src.configs import config
from src.modules.shared.domain.entities import ValidationRunEntity
from src.modules.shared.domain.enums import GenerationMode, LaneStatus, PreviewStatus
from src.modules.shared.domain.frontend_spec import iter_sections

from .checks.conformance import _admits, _types, compare_contract
from .checks.parity import compare_openapi
from .checks.parsers import junit_failures, last_lines
from .context import JobContext
from .contract import contract_operations, resolve
from .packaging import ArtifactWriter, build_contract_seed, build_seed, build_source_zip
from .state import GenerationState
from .validation import CheckResult, ValidationOutcome, traced_check, write_report

CHECK_PREFIX = "integration:"
JUNIT_PATH = "test-results/e2e-junit.xml"
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
NodeResult = tuple[dict[str, Any], dict[str, Any]]


def _optional_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def _clip(value: Any, limit: int = 300) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except Exception:
        text = str(value)
    return text[:limit]


async def package_lane_preview(state: GenerationState, ctx: JobContext, kind: str) -> None:
    """Packages a completed lane's source ZIP (and seed/OpenAPI for the backend) and starts its preview container
    during a dynamic run so `integrate` can probe the backend and switch the frontend preview."""
    if ctx.mode != GenerationMode.DYNAMIC or ctx.previews is None:
        return
    if kind not in ctx.previews.runtimes:
        return
    if kind == "frontend":
        if not (state["options"].get("frontend") or {}).get("generatePreview", True):
            return
    elif not state["options"].get("deployPreview", True):
        return

    writer = ArtifactWriter(
        Path(config.artifact_root), ctx.generation_id, {a.name: a.id for a in ctx.store.artifacts(ctx.generation_id)}
    )
    if kind == "frontend":
        writer.write("frontend.zip", "frontend", build_source_zip(ctx.workspace.frontend), "application/zip")
    else:
        project = ctx.workspace.project
        writer.write("backend.zip", "source", build_source_zip(project), "application/zip")
        plan = _optional_json(project / ".bga" / "plan.json") or {}
        if plan:
            writer.write_json("plan.json", "plan", plan)
        openapi = _optional_json(ctx.workspace.reports / "openapi.json")
        if openapi:
            writer.write_json("openapi.json", "openapi", openapi)
        contract_path = ctx.workspace.spec_dir / "contract.json"
        if contract_path.is_file() and plan:
            seed_blocks = build_contract_seed(json.loads(contract_path.read_text()), plan)
            if seed_blocks:
                writer.write_json("seed.json", "seed", seed_blocks)
        else:
            spec = _optional_json(project / ".bga" / "spec.json") or {}
            if spec.get("seed") and plan:
                generation = ctx.store.generation(ctx.generation_id)
                ts = (
                    generation.created_at.isoformat()
                    if generation and generation.created_at
                    else "1970-01-01T00:00:00+00:00"
                )
                writer.write_json("seed.json", "seed", build_seed(spec, plan, ctx.generation_id, ts))
        head_file = ctx.workspace.state / "backend-packaged-head"
        head_file.parent.mkdir(parents=True, exist_ok=True)
        head_sha = ctx.workspaces._git(ctx.workspace, "rev-parse", "HEAD", repo="project").strip()
        head_file.write_text(head_sha)
    ctx.store.replace_artifacts(ctx.generation_id, writer.written)
    async with ctx.previews.locks[f"{ctx.generation_id}:{kind}"]:
        existing = ctx.store.preview(ctx.generation_id, kind)
        if existing is None or existing.status not in (PreviewStatus.STARTING, PreviewStatus.RUNNING):
            await ctx.previews.start(ctx.generation_id, kind)


def verify_openapi_matches_contract(
    contract: dict[str, Any],
    contract_sha256: str,
    openapi_doc: Any,
    raw_bytes: bytes | None = None,
    plan: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Story 14.2 AC 1: the backend preview's `/openapi.json` must match the contract sha or conform to every
    contract operation and schema."""
    if not isinstance(openapi_doc, dict):
        return False, "backend /openapi.json did not return a JSON object"
    if raw_bytes and hashlib.sha256(raw_bytes).hexdigest() == contract_sha256:
        return True, None
    info = openapi_doc.get("info") or {}
    declared_sha = (
        (openapi_doc.get("x-bga") or {}).get("contractSha256")
        or (info.get("x-bga") or {}).get("contractSha256")
        or info.get("x-contract-sha256")
    )
    if declared_sha is not None and declared_sha != contract_sha256:
        return False, f"backend /openapi.json contract sha mismatch ({declared_sha[:12]} != {contract_sha256[:12]})"
    if declared_sha == contract_sha256 and "paths" not in openapi_doc:
        return True, None

    actual_ops = contract_operations(openapi_doc)
    for op_id, want in sorted(contract_operations(contract).items()):
        have = actual_ops.get(op_id)
        if have is None:
            return False, f"backend /openapi.json is missing operation {op_id} ({want['method']} {want['path']})"
        if (have["method"], have["path"]) != (want["method"], want["path"]):
            return (
                False,
                f"backend /openapi.json operation {op_id} is {have['method']} {have['path']}, "
                f"contract says {want['method']} {want['path']}",
            )
    problems = (compare_openapi(plan, openapi_doc) if plan else []) + compare_contract(contract, openapi_doc)
    if problems:
        first = problems[0]
        return False, f"backend /openapi.json does not match contract: {first['operation']} {first['message']}"
    return True, None


async def check_backend_ready(
    generation_id: str,
    previews: Any,
    contract: dict[str, Any],
    contract_sha256: str,
    plan: dict[str, Any] | None = None,
    wait_seconds: float = 0,
) -> tuple[bool, str | None, str | None]:
    """Waits up to `wait_seconds` while the backend lane or its preview is still starting, then checks:
    backend lane == COMPLETED, `GET /health` == 200, and `GET /openapi.json` matches the contract."""
    if previews is None:
        return False, "backend preview is not running", None
    store = previews.store
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    last_reason = "backend preview is not running"

    while True:
        generation = store.generation(generation_id)
        if generation is None:
            return False, "generation not found", None
        lane_status = (generation.lanes or {}).get("backend", LaneStatus.PENDING.value)
        if lane_status == LaneStatus.FAILED.value:
            return False, generation.error_summary or "backend lane failed", None
        if lane_status == LaneStatus.SKIPPED.value:
            return False, "backend lane was skipped", None
        if lane_status != LaneStatus.COMPLETED.value:
            last_reason = "backend lane timed out before integration"
            if time.monotonic() < deadline:
                await asyncio.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
                continue
            return False, last_reason, None

        if "backend" not in previews.runtimes or not generation.options.get("deployPreview", True):
            return False, "backend preview is not running", None

        preview = store.preview(generation_id, "backend")
        if preview is None or preview.status == PreviewStatus.STARTING:
            last_reason = (
                "backend preview did not become ready in time" if preview else "backend preview is not running"
            )
            if time.monotonic() < deadline:
                await asyncio.sleep(min(0.2, max(0.01, deadline - time.monotonic())))
                continue
            return False, last_reason, None
        if preview.status != PreviewStatus.RUNNING or not preview.url:
            return False, preview.error or f"backend preview is {preview.status}", None

        health_code, _, _ = await previews.probe(generation_id, "GET", "/health", kind="backend")
        if health_code != 200:
            return False, f"backend GET /health returned {health_code or 'no response'}", None

        openapi_code, openapi_doc, raw_bytes = await previews.probe(
            generation_id, "GET", "/openapi.json", kind="backend"
        )
        if openapi_code != 200:
            return False, f"backend GET /openapi.json returned {openapi_code or 'no response'}", None
        ok, reason = verify_openapi_matches_contract(
            contract, contract_sha256, openapi_doc, raw_bytes=raw_bytes, plan=plan
        )
        if not ok:
            return False, reason, None
        return True, None, preview.url


# -- Story 14.3: live contract & smoke validation -------------------------------------------------------------------


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate_value_against_schema(
    contract: dict[str, Any],
    schema: Any,
    value: Any,
    operation_id: str,
    field: str = "",
    response_preview: str = "",
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Validates a live JSON value against a contract schema; mismatches name the operation and field (14.3 AC 2)."""
    if depth > 6:
        return []
    want_types, want = _types(contract, schema)
    if not want_types or "any" in want_types:
        return []
    actual_type = _json_type(value)
    if not _admits(want_types, actual_type):
        expected = " | ".join(sorted(want_types))
        return [
            {
                "operation": operation_id,
                "field": field or "$",
                "message": f"{operation_id} {field or '$'}: expected {expected}, got {actual_type}",
                "response": response_preview or _clip(value),
            }
        ]
    if value is None:
        return []

    problems: list[dict[str, Any]] = []
    allowed_enum = [v for v in want.get("enum") or [] if v is not None]
    if allowed_enum and value not in allowed_enum:
        problems.append(
            {
                "operation": operation_id,
                "field": field or "$",
                "message": f"{operation_id} {field or '$'}: value {value!r} not in enum {allowed_enum}",
                "response": response_preview or _clip(value),
            }
        )
    if actual_type == "object":
        props = want.get("properties") or {}
        required = set(want.get("required") or [])
        for req_name in sorted(required):
            sub_field = f"{field}.{req_name}" if field else req_name
            if req_name not in value:
                problems.append(
                    {
                        "operation": operation_id,
                        "field": sub_field,
                        "message": f"{operation_id} {sub_field}: missing required field",
                        "response": response_preview or _clip(value),
                    }
                )
        for prop_name, prop_schema in props.items():
            if prop_name in value:
                sub_field = f"{field}.{prop_name}" if field else prop_name
                problems.extend(
                    validate_value_against_schema(
                        contract,
                        prop_schema,
                        value[prop_name],
                        operation_id,
                        field=sub_field,
                        response_preview=response_preview or _clip(value),
                        depth=depth + 1,
                    )
                )
    elif actual_type == "array" and "items" in want:
        for index, item in enumerate(value[:10]):
            sub_field = f"{field}[{index}]" if field else f"[{index}]"
            problems.extend(
                validate_value_against_schema(
                    contract,
                    want["items"],
                    item,
                    operation_id,
                    field=sub_field,
                    response_preview=response_preview or _clip(item),
                    depth=depth + 1,
                )
            )
    return problems


def _resolve_operation_path(path: str, operation: dict[str, Any], contract: dict[str, Any]) -> str | None:
    params = _PATH_PARAM.findall(path)
    if not params:
        return path
    entity = (operation.get("x-bga") or {}).get("entity")
    fixtures = ((contract.get("x-bga") or {}).get("fixtures") or {}).get(entity) or []
    if not fixtures:
        return None
    record = fixtures[0]
    resolved = path
    for param in params:
        val = record.get(param) or record.get("id")
        if val is None:
            return None
        resolved = resolved.replace(f"{{{param}}}", str(val))
    return resolved


async def validate_live_responses(generation_id: str, previews: Any, contract: dict[str, Any]) -> CheckResult:
    """Probes every GET operation on the live backend and validates the response against the contract schema."""
    started = time.monotonic()
    details: list[dict[str, Any]] = []
    checked = 0
    for op_id, entry in sorted(contract_operations(contract).items()):
        if entry["method"] != "GET":
            continue
        operation = entry["operation"]
        if operation.get("security"):
            continue
        path = _resolve_operation_path(entry["path"], operation, contract)
        if path is None:
            continue
        responses = operation.get("responses") or {}
        expected_status = next((code for code in sorted(responses) if code.startswith("2")), "200")
        status_code, body, _ = await previews.probe(generation_id, "GET", path, kind="backend")
        checked += 1
        preview_str = _clip(body)
        if status_code != int(expected_status):
            details.append(
                {
                    "operation": op_id,
                    "field": "$status",
                    "path": path,
                    "message": f"{op_id} ({path}): expected HTTP {expected_status}, got {status_code}",
                    "response": preview_str,
                }
            )
            continue
        schema = ((responses.get(expected_status) or {}).get("content") or {}).get("application/json", {}).get("schema")
        if schema:
            resolved_schema = resolve(contract, schema)
            details.extend(
                validate_value_against_schema(
                    contract, resolved_schema, body, op_id, field="", response_preview=preview_str
                )
            )
    ok = not details
    summary = (
        f"{checked} live operation(s) conform to the contract"
        if ok
        else f"{len(details)} contract schema mismatch(es) in live responses"
    )
    return CheckResult(
        check="contract",
        status="passed" if ok else "failed",
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=summary,
        details=details,
    )


async def check_live_health(generation_id: str, previews: Any, backend_url: str) -> CheckResult:
    """Verifies the backend `/health` is 200 and the frontend preview's `/api/runtime-config` points to it."""
    started = time.monotonic()
    details: list[dict[str, Any]] = []
    code, body, _ = await previews.probe(generation_id, "GET", "/health", kind="backend")
    if code != 200:
        details.append(
            {
                "operation": "health",
                "field": "$status",
                "message": f"backend GET /health returned {code}",
                "response": _clip(body),
            }
        )
    fe_preview = previews.store.preview(generation_id, "frontend")
    if fe_preview is not None and fe_preview.status == PreviewStatus.RUNNING:
        fe_code, fe_cfg, _ = await previews.probe(generation_id, "GET", "/api/runtime-config", kind="frontend")
        if fe_code == 200 and isinstance(fe_cfg, dict):
            if fe_cfg.get("mockApi") is not False or fe_cfg.get("apiBaseUrl") != backend_url:
                details.append(
                    {
                        "page": "/api/runtime-config",
                        "operation": "runtime-config",
                        "field": "mockApi",
                        "message": f"frontend runtime-config did not switch to live: {_clip(fe_cfg)}",
                        "response": _clip(fe_cfg),
                    }
                )
    ok = not details
    return CheckResult(
        check="health",
        status="passed" if ok else "failed",
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="backend /health and frontend live runtime-config ready" if ok else details[0]["message"],
        details=details,
    )


def _proxy_command(generation_id: str, fe_port: int | None, be_port: int | None, play_cmd: str) -> str:
    """Inside the Node sandbox container, `localhost:<port>` is the sandbox's own loopback. When the preview
    containers are on the shared egress network (`bga-preview-fe-<gen>:3000`, `bga-preview-<gen>:8000`), a tiny
    Node TCP forwarder bridges `127.0.0.1:<host_port>` inside the sandbox to the preview containers so Chromium's
    `fetch('http://localhost:<be_port>/...')` and Playwright's `page.goto('http://localhost:<fe_port>/...')` work
    identically to the host browser."""
    slug = generation_id.lower()
    forwards = []
    if fe_port:
        forwards.append({"local": fe_port, "host": f"bga-preview-fe-{slug}", "port": 3000})
    if be_port:
        forwards.append({"local": be_port, "host": f"bga-preview-{slug}", "port": 8000})
    if not forwards:
        return play_cmd
    spec_json = json.dumps(forwards)
    node_bridge = (
        f"const net = require('net'); const rules = {spec_json}; "
        "for (const r of rules) { "
        "for (const bindHost of ['127.0.0.1', '::1']) { "
        "const srv = net.createServer((c) => { "
        "const u = net.connect(r.port, r.host); "
        "c.on('error', () => u.destroy()); u.on('error', () => c.destroy()); "
        "c.pipe(u); u.pipe(c); "
        "}); "
        "srv.on('error', () => {}); "
        "srv.listen(r.local, bindHost); "
        "} "
        "} "
        "setInterval(() => {}, 60000);"
    )
    return (
        f"node -e {shlex.quote(node_bridge)} &\n"
        "BRIDGE_PID=$!\n"
        "trap 'kill $BRIDGE_PID 2>/dev/null || true' EXIT\n"
        "sleep 0.2\n"
        f"{play_cmd}"
    )


def _enrich_smoke_failures(failures: list[dict[str, Any]], frontend_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Maps Playwright JUnit failures back to the failing page route and bound operationId (Story 14.3 AC 3)."""
    by_test_id = {t["id"]: t for t in frontend_plan.get("tests", [])}
    routes_by_page = {r["pageId"]: r for r in frontend_plan.get("routes", [])}
    forms_by_id = {f["id"]: f for f in frontend_plan.get("forms", [])}
    enriched = []
    for item in failures:
        test_name = item.get("test") or ""
        test_id = test_name.split(" ", 1)[0]
        planned = by_test_id.get(test_id, {})
        page_id = planned.get("pageId")
        route = routes_by_page.get(page_id, {}) if page_id else {}
        page_path = planned.get("path") or route.get("route") or item.get("page") or "/"
        operation = item.get("operation")
        if not operation:
            if planned.get("kind") == "form" and planned.get("formId") in forms_by_id:
                operation = forms_by_id[planned["formId"]].get("operationId")
            else:
                for section in iter_sections(route.get("sections", [])):
                    op_id = (section.get("data") or {}).get("operationId")
                    if op_id:
                        operation = op_id
                        break
        enriched.append(
            {
                **item,
                "page": page_path,
                "operation": operation,
                "response": item.get("response") or item.get("excerpt") or item.get("message"),
            }
        )
    return enriched


async def run_playwright_live_smoke(
    ctx: JobContext,
    state: GenerationState,
    frontend_url: str,
    backend_url: str,
    frontend_port: int | None,
    backend_port: int | None,
) -> CheckResult:
    """Runs the frontend's Playwright smoke and form tests in the Node sandbox against the live frontend preview."""
    frontend_options = state["options"].get("frontend") or {}
    if not frontend_options.get("runTests", True):
        return CheckResult(check="smoke", status="skipped", summary="runTests=false")
    sandbox = await ctx.frontend_sandbox()
    if sandbox is None:
        return CheckResult(check="smoke", status="not_run", summary="requires the frontend sandbox runner")

    frontend_project = ctx.workspace.frontend
    frontend_plan = _optional_json(frontend_project / ".bga" / "frontend-plan.json") or {}
    junit = frontend_project / JUNIT_PATH
    junit.unlink(missing_ok=True)
    play_cmd = _proxy_command(
        ctx.generation_id,
        frontend_port,
        backend_port,
        "pnpm exec playwright test",
    )
    run = await sandbox.exec(
        play_cmd,
        timeout_s=240,
        env={
            "PLAYWRIGHT_BASE_URL": frontend_url,
            "MOCK_TEST_API": "false",
            "API_BASE_URL": backend_url,
        },
        egress=True,
    )
    failures = junit_failures(junit.read_text(errors="replace")) if junit.exists() else []
    if not run.ok and not failures:
        failures = [
            {
                "test": "smoke",
                "message": last_lines(run.output, 5) or "Playwright live smoke test failed",
                "excerpt": last_lines(run.output, 25),
            }
        ]
    details = _enrich_smoke_failures(failures, frontend_plan) if not run.ok else []
    summary = (
        f"{len(frontend_plan.get('tests', []))} live Playwright smoke test(s) passed"
        if run.ok
        else f"live Playwright smoke failed ({len(details)} failing test(s))"
    )
    return CheckResult(
        check="smoke",
        status="passed" if run.ok else "failed",
        duration_ms=run.duration_ms,
        summary=summary,
        details=details,
        output=last_lines(run.output, 80) if not run.ok else "",
    )


def _enforce_canonical_contract(ctx: JobContext) -> tuple[dict[str, Any], str]:
    """Story 14.1 AC 2: both lanes read `.bga/contract.json`; neither may change it."""
    canonical_path = ctx.workspace.spec_dir / "contract.json"
    raw = canonical_path.read_bytes()
    for target in (
        ctx.workspace.project / ".bga" / "contract.json",
        ctx.workspace.frontend / ".bga" / "contract.json",
    ):
        if target.parent.is_dir():
            target.write_bytes(raw)
    return json.loads(raw.decode()), hashlib.sha256(raw).hexdigest()


async def integrate(state: GenerationState, ctx: JobContext) -> NodeResult:
    """Node `integrate` (Stories 14.2, 14.3): checks backend readiness, switches the frontend preview to live
    and runs the live contract + Playwright smoke checks."""
    contract, contract_sha256 = _enforce_canonical_contract(ctx)
    plan = _optional_json(ctx.workspace.project / ".bga" / "plan.json")

    # In dynamic mode, backend preview was started early when backend lane completed.
    # If it wasn't started (e.g. preview worker delayed or retry), package and start it now.
    if ctx.previews is not None and ctx.lanes.get("backend") == LaneStatus.COMPLETED.value:
        existing_be = ctx.store.preview(ctx.generation_id, "backend")
        if existing_be is None or existing_be.status not in (PreviewStatus.STARTING, PreviewStatus.RUNNING):
            await package_lane_preview(state, ctx, "backend")

    wait_s = float(state["options"].get("integrationWaitSeconds", config.integration_wait_seconds))
    backend_error = state.get("backend_error") or ctx.backend_aborted_reason
    if ctx.lanes.get("backend") != LaneStatus.COMPLETED.value or backend_error:
        ok, reason, backend_url = (
            False,
            backend_error or f"backend lane is {ctx.lanes.get('backend', 'incomplete').lower()}",
            None,
        )
    else:
        ok, reason, backend_url = await check_backend_ready(
            ctx.generation_id,
            ctx.previews,
            contract,
            contract_sha256,
            plan=plan,
            wait_seconds=wait_s,
        )
    if not ok or not backend_url:
        reason = reason or "backend preview is not running"
        if ctx.previews is not None and "frontend" in ctx.previews.runtimes:
            writer = ArtifactWriter(
                Path(config.artifact_root),
                ctx.generation_id,
                {a.name: a.id for a in ctx.store.artifacts(ctx.generation_id)},
            )
            writer.write("frontend.zip", "frontend", build_source_zip(ctx.workspace.frontend), "application/zip")
            ctx.store.replace_artifacts(ctx.generation_id, writer.written)
            fe_preview = ctx.store.preview(ctx.generation_id, "frontend")
            if fe_preview is None or fe_preview.status not in (PreviewStatus.STARTING, PreviewStatus.RUNNING):
                await ctx.previews.start(
                    ctx.generation_id, "frontend", options_override={"mockApi": True, "apiBaseUrl": ""}
                )
            elif fe_preview.mock_api is not True:
                async with ctx.previews.locks[f"{ctx.generation_id}:frontend"]:
                    await ctx.previews.switch_frontend(ctx.generation_id, mock_api=True, api_base_url="")
        await ctx.emit("integration.kept_mocks", step="integrate", reason=reason, mockApi=True)
        await ctx.set_lane("integration", LaneStatus.SKIPPED, reason=reason)
        info = {"switchedToLive": False, "mockApi": True, "apiBaseUrl": "", "reason": reason}
        return {"integration": info, "integration_reason": reason}, {
            "_status": "skipped",
            "switchedToLive": False,
            "reason": reason,
        }

    assert ctx.previews is not None
    # Package frontend and start directly on live API (Story 18.8: created once, directly live).
    writer = ArtifactWriter(
        Path(config.artifact_root), ctx.generation_id, {a.name: a.id for a in ctx.store.artifacts(ctx.generation_id)}
    )
    writer.write("frontend.zip", "frontend", build_source_zip(ctx.workspace.frontend), "application/zip")
    ctx.store.replace_artifacts(ctx.generation_id, writer.written)
    async with ctx.previews.locks[f"{ctx.generation_id}:frontend"]:
        fe_preview = ctx.store.preview(ctx.generation_id, "frontend")
        if fe_preview is None or fe_preview.status not in (PreviewStatus.STARTING, PreviewStatus.RUNNING):
            await ctx.previews.start(
                ctx.generation_id, "frontend", options_override={"mockApi": False, "apiBaseUrl": backend_url}
            )
            fe_preview = ctx.store.preview(ctx.generation_id, "frontend")
        elif fe_preview.mock_api is not False:
            fe_preview = await ctx.previews.switch_frontend(ctx.generation_id, mock_api=False, api_base_url=backend_url)
    be_preview = ctx.store.preview(ctx.generation_id, "backend")
    frontend_url = fe_preview.url if fe_preview and fe_preview.url else f"http://{config.preview_public_host}:3000"
    await ctx.emit(
        "integration.switched_to_live",
        step="integrate",
        apiBaseUrl=backend_url,
        frontendUrl=fe_preview.url if fe_preview else None,
        contractSha256=contract_sha256,
        mockApi=False,
    )

    results: list[CheckResult] = []
    with traced_check(f"{CHECK_PREFIX}health") as slot:
        health_res = await check_live_health(ctx.generation_id, ctx.previews, backend_url)
        slot.append(health_res)
    results.append(health_res)

    with traced_check(f"{CHECK_PREFIX}contract") as slot:
        contract_res = await validate_live_responses(ctx.generation_id, ctx.previews, contract)
        slot.append(contract_res)
    results.append(contract_res)

    with traced_check(f"{CHECK_PREFIX}smoke") as slot:
        smoke_res = await run_playwright_live_smoke(
            ctx,
            state,
            frontend_url=frontend_url,
            backend_url=backend_url,
            frontend_port=fe_preview.host_port if fe_preview else None,
            backend_port=be_preview.host_port if be_preview else None,
        )
        slot.append(smoke_res)
    results.append(smoke_res)

    for check in results:
        check_name = f"{CHECK_PREFIX}{check.check}"
        ctx.store.add_validation_run(
            ValidationRunEntity(
                generation_id=ctx.generation_id,
                attempt=1,
                check=check_name,
                status=check.status,
                started_at=check.started_at,
                duration_ms=check.duration_ms,
                details={"summary": check.summary, "items": check.details[:50], "output": check.output[-4000:]},
            )
        )
        await ctx.emit(
            "validation.check",
            step="integrate",
            status=check.status,
            check=check_name,
            summary=check.summary,
            durationMs=check.duration_ms,
            attempt=1,
        )

    outcome = ValidationOutcome(results=results, digest="", implicated_files=[])
    write_report(ctx.workspace.reports / "integration-validation.json", outcome)

    failed = [f"{CHECK_PREFIX}{r.check}" for r in results if r.status == "failed"]
    summary_map = {r.check: r.status for r in results}
    if failed:
        first_failed = next(r for r in results if r.status == "failed")
        first_item = first_failed.details[0] if first_failed.details else {}
        detail_msg = first_item.get("message") or first_failed.summary
        fail_reason = f"Live integration check failed ({first_failed.check}): {detail_msg}"
        await ctx.set_lane("integration", LaneStatus.FAILED, reason=fail_reason)
        info = {
            "switchedToLive": True,
            "mockApi": False,
            "apiBaseUrl": backend_url,
            "frontendUrl": fe_preview.url if fe_preview else None,
            "contractSha256": contract_sha256,
            "checks": summary_map,
            "failedChecks": failed,
            "reason": fail_reason,
        }
        return {"integration": info, "integration_reason": fail_reason}, {
            "_status": "failed",
            "switchedToLive": True,
            "apiBaseUrl": backend_url,
            "failedChecks": failed,
        }

    await ctx.set_lane("integration", LaneStatus.COMPLETED)
    info = {
        "switchedToLive": True,
        "mockApi": False,
        "apiBaseUrl": backend_url,
        "frontendUrl": fe_preview.url if fe_preview else None,
        "contractSha256": contract_sha256,
        "checks": summary_map,
        "failedChecks": [],
        "reason": None,
    }
    return {"integration": info, "integration_reason": None}, {
        "switchedToLive": True,
        "apiBaseUrl": backend_url,
        "failedChecks": [],
    }
