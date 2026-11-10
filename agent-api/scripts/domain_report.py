"""Epic 33 (Story 33.1): the domains' UX tasks judged on recorded drafts.

    python -m scripts.domain_report [--baseline | --replan]

Each `tests/fixtures/drafts/domain-<name>/frontend-spec.json` (what the generator planned for that domain's reference
requirement) is judged against `tests/fixtures/domains/tasks/<name>.json`. `--baseline` writes the results to
`tests/fixtures/domains/baseline.json` (taken once, with today's kit, before any domain plugin). `--replan` builds the
newest recording of each domain again with today's plugins (its domain applied) and judges that.
"""

import json
import sys
from datetime import date
from pathlib import Path

from src.orchestrator.frontend.app.domain_tasks import judge, summary

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
TASKS = FIXTURES / "domains" / "tasks"
BASELINE = FIXTURES / "domains" / "baseline.json"


def _without_features(backend: dict) -> dict:
    """A recorded draft as the model wrote it: the entities features merged (and what names them) taken out."""
    names = {name for attached in backend.get("features") or [] for name in attached.get("entities") or []}
    out = {k: v for k, v in backend.items() if k != "features"}
    out["entities"] = [e for e in backend.get("entities") or [] if e["name"] not in names]
    out["relationships"] = [
        r for r in backend.get("relationships") or [] if r.get("from") not in names and r.get("to") not in names
    ]
    for key in ("operations", "rules", "policies"):
        out[key] = [item for item in backend.get(key) or [] if item.get("entity") not in names]
    return out


def replanned(name: str, domain: str | None = None) -> dict:
    """A recorded draft built again with today's plugins: its domain applied, its screens planned (Story 33.7+).
    `domain`: the domain to build it on, as if the model had named it (the drafts recorded before Story 33.6)."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.drafting.app import app_theme
    from src.orchestrator.drafting.domains import apply_domain
    from src.orchestrator.frontend.app.outline import complete_outline
    from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
    from src.orchestrator.integration.contract import build_contract

    folder = FIXTURES / "drafts" / f"domain-{name}"
    backend = _without_features(json.loads((folder / "backend-spec.json").read_text()))
    outline = json.loads((folder / "app-outline.json").read_text())
    if domain:
        outline["domain"] = {"name": domain}
    merged, block, _ = apply_domain(backend, outline)
    normalized = validate_spec_data(merged).normalized
    completed, _ = complete_outline(outline, normalized, build_contract(normalized, build_plan(normalized)))
    if block:
        completed["domain"] = block
    normalized, completed, _ = ensure_aggregates(normalized, completed)
    contract = build_contract(normalized, build_plan(normalized))
    return app_frontend_spec(normalized, completed, app_theme(None), contract).spec


def report(replan: bool = False) -> dict:
    out: dict = {"date": str(date.today()), "domains": {}}
    for tasks_file in sorted(TASKS.glob("*.json")):
        name = tasks_file.stem
        drafts = (
            sorted((FIXTURES / "drafts").glob(f"domain-{name}*"))
            if replan
            else [FIXTURES / "drafts" / f"domain-{name}"]
        )
        folder = drafts[-1] if drafts else None  # with --replan: the newest recording (`domain-socials-v10`)
        if folder is None or not (folder / "frontend-spec.json").is_file():
            continue
        spec = (
            replanned(folder.name.removeprefix("domain-"))
            if replan
            else json.loads((folder / "frontend-spec.json").read_text())
        )
        results = judge(spec, json.loads(tasks_file.read_text())["tasks"])
        out["domains"][name] = {"draft": folder.name, "summary": summary(results), "tasks": results}
    out["summary"] = {
        "tasks": sum(d["summary"]["tasks"] for d in out["domains"].values()),
        "passed": sum(d["summary"]["passed"] for d in out["domains"].values()),
    }
    return out


def main(argv: list[str]) -> int:
    data = report(replan="--replan" in argv)
    for name, domain in data["domains"].items():
        print(f"{name}: {domain['summary']['passed']}/{domain['summary']['tasks']}")
        for task in domain["tasks"]:
            mark = "pass" if task["passed"] else "FAIL"
            print(f"  {mark} {task['id']}" + (f" ({task['why']})" if task["why"] else ""))
    print(f"all: {data['summary']['passed']}/{data['summary']['tasks']}")
    if "--baseline" in argv:
        BASELINE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
