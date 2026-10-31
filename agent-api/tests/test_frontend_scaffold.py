"""Frontend base + overlay + generated code (Story 13.2), the conventions checker and the static checks (13.4)."""

import json
import shutil
from pathlib import Path

import pytest
from generation_helpers import EXAMPLES, engine_path, normalized

from src.engines.fake_engine import GOLDEN_FRONTENDS
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_text
from src.orchestrator.checks.frontend_conventions import check_frontend_conventions
from src.orchestrator.contract import build_contract
from src.orchestrator.frontend_codegen import generated_files, type_name
from src.orchestrator.frontend_planner import plan_frontend
from src.orchestrator.frontend_scaffold import (
    BASE_DIR,
    OVERLAY_DIR,
    FrontendTemplateDrift,
    changed_owned,
    check_base,
    load_manifest,
    scaffold_frontend,
)
from src.orchestrator.frontend_validation import (
    eslint_failures,
    routes_check,
    typescript_errors,
)

TRACKER = "project-tracker-dynamic"
LANDING = "static-landing"
SHOP = "shop-dynamic"
BACKEND_SPECS = {TRACKER: "two-entity.json", SHOP: "shop.json"}


def inputs(name: str, engine: bool = False) -> tuple[dict, dict | None, dict]:
    """`engine`: the spec without props schemas, so the golden (engine-written) frontend applies (17.3)."""
    raw = json.loads((EXAMPLES / "frontend-specs" / f"{name}.json").read_text())
    spec = validate_frontend_spec_text(json.dumps(engine_path(raw) if engine else raw)).normalized
    backend = BACKEND_SPECS.get(name)
    contract = build_contract(normalized(EXAMPLES / "specs" / backend)) if backend else None
    return spec, contract, plan_frontend(spec, contract)


def scaffolded(tmp_path: Path, name: str, golden: bool = True) -> tuple[Path, dict]:
    spec, contract, plan = inputs(name, engine=golden)
    project = tmp_path / name
    scaffold_frontend(project, plan, spec, contract)
    if golden:
        shutil.copytree(GOLDEN_FRONTENDS[spec["project"]["name"]], project, dirs_exist_ok=True)
    return project, plan


def test_the_pinned_base_matches_the_overlay_manifest():
    assert check_base() == []
    assert (BASE_DIR / "pnpm-lock.yaml").is_file() and not (BASE_DIR / "node_modules").exists()


def test_drift_in_the_base_is_refused(tmp_path):
    base = tmp_path / "base"
    shutil.copytree(BASE_DIR, base)
    (base / "next.config.ts").write_text("// changed\n")
    spec, contract, plan = inputs(LANDING)
    with pytest.raises(FrontendTemplateDrift, match="next.config.ts: changed"):
        scaffold_frontend(tmp_path / "project", plan, spec, contract, base=base)
    assert not (tmp_path / "project").exists()


def test_static_scaffold_has_content_and_no_api(tmp_path):
    project, plan = scaffolded(tmp_path, LANDING, golden=False)
    assert (project / "src/content/services.json").is_file()
    assert not (project / "src/lib/api").exists() and not (project / "src/mocks").exists()
    assert 'output: "export"' in (project / "next.config.ts").read_text()
    # Story 17.2: the home route renders the spec; the base's demo page is gone.
    assert '<PageRenderer pageId="home" />' in (project / "src/app/page.tsx").read_text()
    ui = sorted(path.stem for path in (project / "src/components/ui").glob("*.tsx"))
    assert ui == plan["shadcn"]
    package = json.loads((project / "package.json").read_text())
    assert package["name"] == "northwind-studio" and package["scripts"]["test:e2e"] == "playwright test"
    assert "# Northwind Studio" in (project / "README.md").read_text()


def test_dynamic_scaffold_has_the_typed_client_and_the_mock_layer(tmp_path):
    project, _ = scaffolded(tmp_path, TRACKER, golden=False)
    types = (project / "src/lib/api/types.ts").read_text()
    assert "export type TProject = {" in types and "export type TListTasksParams = {" in types
    assert '  status?: "TODO" | "IN_PROGRESS" | "DONE";' in types
    operations = (project / "src/lib/api/operations.ts").read_text()
    assert "export function getProject(params: TGetProjectParams): Promise<TProject> {" in operations
    assert 'return request<TProject>("GET", `/projects/${encodeURIComponent(String(params.id))}`);' in operations
    queries = (project / "src/lib/api/queries.ts").read_text()
    assert "export function useListTasks(params: TListTasksParams = {}, options: TQueryOptions = {}) {" in queries
    assert "onSuccess: () => queryClient.invalidateQueries({ queryKey: taskKeys.all })," in queries
    mocks = json.loads((project / "src/mocks/operations.json").read_text())
    task_list = next(op for op in mocks if op["operationId"] == "task.list")
    assert task_list["filters"] == ["projectId", "status"] and task_list["sort"] == ["dueDate", "priority"]
    assert len(json.loads((project / "src/mocks/fixtures.json").read_text())["Task"]) == 3
    forms = (project / "src/lib/forms.ts").read_text()
    assert 'status: z.enum(["TODO", "IN_PROGRESS", "DONE"]).optional(),' in forms
    assert "priority: z.number().int().min(1).max(5).optional()," in forms
    assert (project / ".bga/contract.json").is_file() and 'output: "standalone"' in (
        project / "next.config.ts"
    ).read_text()


def test_generated_files_are_deterministic():
    spec, contract, plan = inputs(TRACKER)
    assert generated_files(plan, spec, contract) == generated_files(plan, spec, contract)
    assert type_name("ProductResponse") == "TProduct" and type_name("ListProductsResponse") == "TListProductsResponse"


def test_smoke_tests_expect_the_first_record_each_page_shows():
    spec, contract, plan = inputs(TRACKER)
    smoke = generated_files(plan, spec, contract)["tests/e2e/smoke.spec.ts"]
    # `/` lists projects newest first (limit 6, sort -createdAt): the third fixture comes first.
    assert '"path": "/",\n    "title": "Overview",\n    "text": "Project name 3"' in smoke
    assert '"text": "Task title 1"' in smoke


def test_the_golden_shop_frontend_meets_the_conventions(tmp_path):
    project, plan = scaffolded(tmp_path, SHOP)
    assert check_frontend_conventions(project, plan) == []


@pytest.mark.parametrize("name", [LANDING, TRACKER, SHOP])
def test_a_rendered_site_meets_the_conventions_without_engine_files(tmp_path, name):
    project, plan = scaffolded(tmp_path, name, golden=False)
    assert plan["rendering"] == "renderer" and check_frontend_conventions(project, plan) == []


VIOLATIONS = [
    ("react-imports", 'import * as React from "react";\n'),
    ("design-tokens", 'export const box = <div className="bg-[#ff0000]" />;\n'),
    ("token-storage", 'localStorage.setItem("authToken", "x");\n'),
    ("network", 'fetch("/api/projects");\n'),
    ("network", 'import { request } from "@/lib/api/client";\n'),
    ("types", "export type Project = { id: string };\n"),
    ("types", "export type TCardProps = { id: string };\n"),
    ("types", "export interface TProject { id: string }\n"),
]


@pytest.mark.parametrize(("rule", "code"), VIOLATIONS, ids=[f"{rule}:{i}" for i, (rule, _) in enumerate(VIOLATIONS)])
def test_conventions_report_each_rule(tmp_path, rule, code):
    project, plan = scaffolded(tmp_path, SHOP)
    path = project / "src/features/products/components/Bad.tsx"
    path.write_text(code)
    found = [(v["rule"], v["file"]) for v in check_frontend_conventions(project, plan)]
    assert (rule, "src/features/products/components/Bad.tsx") in found


def test_conventions_report_owned_changes_missing_files_and_long_components(tmp_path):
    project, plan = scaffolded(tmp_path, SHOP)
    (project / "src/lib/api/queries.ts").write_text("// edited\n")
    (project / "src/components/sections/CardGrid.tsx").unlink()
    (project / "src/app/cart/page.tsx").write_text("export default function Page() {\n  return null;\n}\n")
    logic = "\n".join(f"  const value{i} = {i};" for i in range(35))
    (project / "src/features/products/components/Long.tsx").write_text(
        f"export function Long() {{\n{logic}\n  return (\n    <div />\n  );\n}}\n"
    )
    found = {(v["rule"], v["file"]) for v in check_frontend_conventions(project, plan)}
    assert ("owned-files", "src/lib/api/queries.ts") in found and changed_owned(project) == ["src/lib/api/queries.ts"]
    assert ("plan", "src/components/sections/CardGrid.tsx") in found
    assert ("pages", "src/app/cart/page.tsx") in found
    assert ("custom-hooks", "src/features/products/components/Long.tsx") in found


def test_tool_output_parsers():
    tsc = "src/app/page.tsx(12,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    assert typescript_errors(tsc) == [
        {"file": "src/app/page.tsx", "line": 12, "code": "TS2322",
         "message": "Type 'string' is not assignable to type 'number'."},
    ]  # fmt: skip
    eslint = json.dumps(
        [
            {
                "filePath": "/work/src/app/page.tsx",
                "messages": [
                    {"ruleId": "react-hooks/rules-of-hooks", "severity": 2, "line": 4, "message": "Hook called"},
                    {"ruleId": "no-console", "severity": 1, "line": 5, "message": "warning only"},
                ],
            }
        ]
    )
    assert eslint_failures(eslint) == [
        {"file": "src/app/page.tsx", "line": 4, "code": "react-hooks/rules-of-hooks", "message": "Hook called"}
    ]


def test_routes_check_reads_the_build_output(tmp_path):
    _, _, tracker = inputs(TRACKER)
    project = tmp_path / "dynamic"
    (project / ".next").mkdir(parents=True)
    manifest = {"/page": "/", "/projects/page": "/projects", "/projects/[id]/page": "/projects/[id]"}
    (project / ".next/app-path-routes-manifest.json").write_text(json.dumps(manifest))
    result = routes_check(project, tracker)
    assert result.status == "failed" and result.details == [
        {"file": "src/app/tasks/page.tsx", "message": "route /tasks is not in the build output"}
    ]
    _, _, landing = inputs(LANDING)
    project = tmp_path / "static"
    for route in ("", "services", "work", "about", "contact"):
        (project / "out" / route).mkdir(parents=True, exist_ok=True)
        (project / "out" / route / "index.html").write_text("<html></html>")
    assert routes_check(project, landing).status == "passed"


def test_dockerfiles_agree_with_overlay_pnpm_version():
    manifest = load_manifest()
    pnpm_version = manifest["baseLock"]["pnpmVersion"]
    expected_clause = f"pnpm@{pnpm_version}"

    for mode in ("dynamic", "static"):
        dockerfile = (OVERLAY_DIR / "files" / mode / "Dockerfile").read_text()
        assert expected_clause in dockerfile, f"{mode}/Dockerfile does not use {expected_clause}"
        assert "AS deps" in dockerfile
        assert "pnpm fetch --frozen-lockfile" in dockerfile
