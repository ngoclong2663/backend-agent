"""Epic 33 (Story 33.1): the domains' UX tasks judged on recorded drafts.

    python -m scripts.domain_report [--baseline]

Each `tests/fixtures/drafts/domain-<name>/frontend-spec.json` (what the generator planned for that domain's reference
requirement) is judged against `tests/fixtures/domains/tasks/<name>.json`. `--baseline` writes the results to
`tests/fixtures/domains/baseline.json` (taken once, with today's kit, before any domain plugin).
"""

import json
import sys
from datetime import date
from pathlib import Path

from src.orchestrator.frontend.app.domain_tasks import judge, summary

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
TASKS = FIXTURES / "domains" / "tasks"
BASELINE = FIXTURES / "domains" / "baseline.json"


def report() -> dict:
    out: dict = {"date": str(date.today()), "domains": {}}
    for tasks_file in sorted(TASKS.glob("*.json")):
        name = tasks_file.stem
        spec_file = FIXTURES / "drafts" / f"domain-{name}" / "frontend-spec.json"
        if not spec_file.is_file():
            continue
        results = judge(json.loads(spec_file.read_text()), json.loads(tasks_file.read_text())["tasks"])
        out["domains"][name] = {"summary": summary(results), "tasks": results}
    out["summary"] = {
        "tasks": sum(d["summary"]["tasks"] for d in out["domains"].values()),
        "passed": sum(d["summary"]["passed"] for d in out["domains"].values()),
    }
    return out


def main(argv: list[str]) -> int:
    data = report()
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
