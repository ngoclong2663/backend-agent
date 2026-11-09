"""Builds a FrontendSpec with the section renderer in the Node sandbox and runs `scripts/design-check.mjs` on it
(Stories 17.7, 20.1). Shared by the design diversity report and the section-library design check. Dev tools only.
A dynamic spec (Story 20.4) is planned against its BackendSpec's API contract and checked on the mock API.

Needs Docker and the `bga-runner-node` image (`make runner-node`). Projects are built under `.data/` (Docker Desktop
only shares configured host paths); generated drawings and photos are shown as placeholders, since they need an
engine or the image API.
"""

import copy
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
# The running stack's worker removes sandboxes of its own deployment whose generation it does not know
# (`cleanup_sandboxes`); the checks' sandboxes carry their own instance label, so a check can run while the stack is up.
DEV_INSTANCE = "design-check"
DESIGN_CHECK = REPO / "scripts" / "design-check.mjs"
BUILD_ROOT = REPO / ".data" / "test-sandbox"


def offline_assets(spec: dict[str, Any]) -> dict[str, Any]:
    """Generated drawings and photos need an engine or the image API; the checks show them as placeholders."""
    out = copy.deepcopy(spec)
    for asset in out.get("assets") or []:
        if isinstance(asset, dict) and asset.get("source") in ("generate", "photo"):
            asset["source"] = "placeholder"
    return out


def default_routes(plan: dict[str, Any]) -> list[str]:
    """Every page without route parameters; in a dynamic app also one record page per resource (the route tests'
    example paths, which the mock API serves)."""
    routes = [route["route"] for route in plan["routes"] if not route["params"]]
    if plan["project"]["mode"] == "dynamic":
        examples = [test["path"] for test in plan["tests"] if test["kind"] == "route" and test.get("path")]
        routes += [path for path in examples if path not in routes]
    return routes


def _contract(backend: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.integration.contract import build_contract

    checked = validate_spec_data(backend) if backend else None
    if checked is None or checked.normalized is None:
        print(f"  {name}: a dynamic spec needs a valid BackendSpec for its API contract")
        return None
    return build_contract(checked.normalized)


async def check_site(
    spec: dict[str, Any],
    shots: Path,
    routes: list[str] | None = None,
    widths: str | None = None,
    schemes: str | None = None,
    backend: dict[str, Any] | None = None,
    motion: bool = False,
    prepare: Any = None,
    login: str | None = None,
    sign_in: str | None = None,
    passes: list[dict[str, Any]] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Builds `spec` (dynamic: against `backend`'s contract) and runs the design check on `routes` (default:
    `default_routes`). The screenshots and `report.json` land in `shots`; returns the report, or None when the spec
    or the build failed (the reason is printed). `motion` adds the motion and no-JavaScript passes (Story 20.6).
    `login` (`email:password`, Story 30.1) signs in on `sign_in` (default `/login`) before the shots. `passes` (Story
    30.1: one per area, `{"name", "routes", "login"}`) runs the check once per pass on the same build, into
    `shots/<name>/`, and returns the reports by name."""
    from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
    from src.orchestrator.frontend.planner import plan_frontend
    from src.orchestrator.frontend.scaffold import scaffold_frontend
    from src.orchestrator.frontend.validation import FrontendValidationRequest, SandboxFrontendValidationRunner
    from src.sandbox import DockerSandboxProvider, docker_sandbox

    docker_sandbox.instance_id = lambda: DEV_INSTANCE

    result = validate_frontend_spec_data(offline_assets(spec))
    if not result.report.valid:
        print(f"  {shots.name}: spec invalid: {[issue.message for issue in result.report.errors][:3]}")
        return None
    contract = None
    if result.normalized["project"]["mode"] == "dynamic":
        contract = _contract(backend, shots.name)
        if contract is None:
            return None
    plan = plan_frontend(result.normalized, contract)
    routes = routes or default_routes(plan)
    target = BUILD_ROOT / f"check-{uuid.uuid4().hex[:10]}"
    project = target / "frontend"
    scaffold_frontend(project, plan, result.normalized, contract)
    if prepare is not None:  # Story 23.12: a dev tool's change to the scaffold before the build (fake view slots)
        prepare(project, result.normalized)
    sandbox = DockerSandboxProvider().for_job(f"gen_CHK{uuid.uuid4().hex[:10].upper()}", project, "frontend")
    try:
        outcome = await SandboxFrontendValidationRunner().run(
            FrontendValidationRequest(project=project, plan=plan, run_tests=False, sandbox=sandbox)
        )
        if outcome.summary.get("build") != "passed":
            print(f"  {shots.name}: build {outcome.summary}\n{outcome.digest[-3000:]}")
            return None
        shutil.copy(DESIGN_CHECK, project / "design-check.mjs")
        reports: dict[str, Any] = {}
        for item in passes or [{"name": "", "routes": routes, "login": login}]:
            options = (
                ("DESIGN_CHECK_WIDTHS", widths),
                ("DESIGN_CHECK_SCHEMES", schemes),
                ("DESIGN_CHECK_MOTION", "1"),
                ("DESIGN_CHECK_LOGIN", item.get("login")),
                ("DESIGN_CHECK_SIGN_IN", sign_in),
            )
            env = {key: value for key, value in options if value and (key != "DESIGN_CHECK_MOTION" or motion)}
            env |= extra_env or {}  # Story 30.3: the plugin gates (recipes, states, a11y)
            folder = f"shots/{item['name']}" if item.get("name") else "shots"
            run = await sandbox.exec(
                f"node design-check.mjs {folder} {' '.join(item['routes'])}", timeout_s=1800, env=env
            )
            report = project / folder / "report.json"
            if not run.ok or not report.is_file():
                print(f"  {shots.name}: design check failed\n{run.output[-3000:]}")
                return None
            reports[item.get("name") or ""] = json.loads(report.read_text())
        shutil.rmtree(shots, ignore_errors=True)
        shutil.copytree(project / "shots", shots)
        return reports if passes else reports[""]
    finally:
        await sandbox.stop()
        shutil.rmtree(target, ignore_errors=True)
