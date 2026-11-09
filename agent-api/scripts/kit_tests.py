"""The app kit's own checks (Epic 28, dev tool): scaffolds an app of the dynamic app flow (default: the every-plugin
workshop bookings), type-checks it in the Node sandbox and runs the kit's vitest files (`src/components/**/*.test.*`,
copied with the kit). Generation itself skips the frontend `tests` check, so this is where the kit's tests run.

    make kit-test
    make kit-test ARGS="--app flashcards:flashcards --keep"
"""

import argparse
import asyncio
import shutil
import uuid

from .design_check_app import app_spec
from .site_check import BUILD_ROOT, DEV_INSTANCE, offline_assets


async def main(args: argparse.Namespace) -> int:
    from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
    from src.orchestrator.frontend.planner import plan_frontend
    from src.orchestrator.frontend.scaffold import scaffold_frontend
    from src.orchestrator.frontend.validation import FrontendValidationRequest, SandboxFrontendValidationRunner
    from src.sandbox import DockerSandboxProvider, docker_sandbox

    docker_sandbox.instance_id = lambda: DEV_INSTANCE
    backend_name, _, outline_name = args.app.partition(":")
    spec, backend, contract = app_spec(backend_name, outline_name or None)
    result = validate_frontend_spec_data(offline_assets(spec))
    assert result.report.valid, [issue.message for issue in result.report.errors][:3]
    plan = plan_frontend(result.normalized, contract)
    target = BUILD_ROOT / f"kit-{uuid.uuid4().hex[:10]}"
    project = target / "frontend"
    scaffold_frontend(project, plan, result.normalized, contract)
    print(f"scaffolded {backend_name} → {project}")
    sandbox = DockerSandboxProvider().for_job(f"gen_KIT{uuid.uuid4().hex[:10].upper()}", project, "frontend")
    code = 1
    try:
        outcome = await SandboxFrontendValidationRunner().run(
            FrontendValidationRequest(project=project, plan=plan, run_tests=False, sandbox=sandbox)
        )
        print({check: status for check, status in outcome.summary.items()})
        if outcome.summary.get("typecheck") != "passed":
            print(outcome.digest[-6000:])
            return 1
        if args.build and outcome.summary.get("build") != "passed":
            print(outcome.digest[-6000:])
            return 1
        pattern = args.pattern or "src/components"
        run = await sandbox.exec(f"pnpm exec vitest run {pattern} --reporter=verbose", timeout_s=600)
        print(run.output[-12000:])
        code = 0 if run.ok else 1
    finally:
        await sandbox.stop()
        if args.keep:
            print(f"kept {target}")
        else:
            shutil.rmtree(target, ignore_errors=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--app", default="workshop-bookings:workshop-bookings", help="<BackendSpec example>[:<outline>]"
    )
    parser.add_argument("--pattern", default=None, help="the vitest files to run (default: src/components)")
    parser.add_argument("--build", action="store_true", help="also require `next build` to pass")
    parser.add_argument("--keep", action="store_true", help="keep the scaffolded project")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
