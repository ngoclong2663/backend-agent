"""`complete_backend` context pack and modules in parallel (Story 18.13), and the frontend warning checks."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from src.engines import PromptLibrary
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.orchestrator.backend.codegen import codegen_gaps, database_files, module_files
from src.orchestrator.backend.completion import complete_modules, module_context, related_entities
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.frontend.validation import conventions_check, only_in_tests, typescript_errors
from src.orchestrator.integration.contract import build_contract
from tests.generation_helpers import normalized
from tests.workflow_helpers import events, node_runs, run_job, submit

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
OVERLAY = Path(__file__).resolve().parents[1] / "templates" / "fastapi_overlay" / "files"
FLASHCARDS = json.loads((EXAMPLES / "specs" / "flashcards.json").read_text())


def _flashcards_project(root: Path):
    spec = normalized(EXAMPLES / "specs" / "flashcards.json")
    plan = build_plan(spec)
    files = database_files(plan)
    generated = {}
    for module in plan["modules"]:
        code = module_files(plan, spec, module)
        files |= code
        generated[module["name"]] = sorted(code)
    for name in ("__init__", "base_exception", "error_codes"):
        relative = f"src/libs/exceptions/{name}.py"
        files[relative] = (OVERLAY / relative).read_text()
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text)
    return spec, plan, generated


def _module(plan, name):
    return next(m for m in plan["modules"] if m["name"] == name)


# -- context pack ------------------------------------------------------------------------------------------------------


def test_related_entities_follow_foreign_keys_and_what_the_operations_name(tmp_path):
    spec, plan, _ = _flashcards_project(tmp_path)
    # a foreign key, and "Creates a ReviewLog" in `card.review`'s description
    assert related_entities(plan, spec, _module(plan, "cards")) == ["Deck", "ReviewLog"]
    assert related_entities(plan, spec, _module(plan, "decks")) == ["Card"]


def test_the_pack_carries_operations_files_and_related_ports(tmp_path):
    spec, plan, generated = _flashcards_project(tmp_path)
    cards = _module(plan, "cards")
    pack = module_context(tmp_path, plan, spec, build_contract(spec, plan), cards, generated["cards"])

    assert "### `card.review`" in pack and "### `card.listDue`" in pack
    assert "SM-2" in pack  # the spec's description
    assert "$ref" not in pack and '"rating"' in pack  # the contract operation, schemas resolved
    assert '"mock"' not in pack  # mock plans are left out
    assert "### `src/modules/cards/presenter/router.py`" in pack
    assert "### `src/modules/cards/__init__.py`" not in pack  # empty packages say nothing
    assert "### `src/modules/shared/infrastructure/models/card_model.py`" in pack
    assert "from src.modules.review_logs.ports.output import IReviewLogRepoDep" in pack
    assert "### `src/modules/decks/ports/output/deck_repository.py`" in pack
    assert "class ConflictException" in pack
    assert "`CardResponseDto.from_entity(record, self.card_repo.references([record]))`" in pack  # Story 10.0b
    assert "tests/modules" not in pack  # the engine writes no tests


def test_the_v5_prompt_inlines_the_pack_and_says_not_to_read_files(tmp_path):
    spec, plan, generated = _flashcards_project(tmp_path)
    cards = _module(plan, "cards")
    pack = module_context(tmp_path, plan, spec, None, cards, generated["cards"])
    prompt = PromptLibrary().render(
        "complete_backend",
        "v5",
        module=cards,
        module_json="{}",
        gaps=codegen_gaps(cards),
        pack=pack,
        spec_path=".bga/spec.json",
        plan_path=".bga/plan.json",
        contract_path=None,
        journeys=[],
    )
    text = prompt.text
    assert text.startswith("# Task: complete the `cards` module")  # the fake engine keys on this heading
    assert "Everything you need is in this prompt" in text and "Do not list or read other project files" in text
    assert "- card.review: custom operation" in text
    assert '<untrusted-data name="module_context">' in text
    assert "Current project files" not in text  # no file tree any more
    assert len(text) < 48 * 1024


# -- modules in parallel -----------------------------------------------------------------------------------------------


class _Ctx:
    """Just what `complete_modules` uses of a JobContext; `writes` says what each module's engine call writes."""

    def __init__(self, root: Path, writes: dict[str, dict[str, str]]):
        self.workspace = SimpleNamespace(root=root, project=root / "project")
        self.workspace.project.mkdir(parents=True)
        (self.workspace.project / "src").mkdir()
        (self.workspace.project / "src" / "shared.py").write_text("base\n")
        self.engine_slots = asyncio.Semaphore(3)
        self.writes = writes
        self.calls: list[tuple[str, Path]] = []
        self.active = self.peak = 0

    async def run_engine(self, node, purpose, prompt, repo="project", workdir_override=None):
        workdir = workdir_override or self.workspace.project
        self.calls.append((prompt, workdir))
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.02)
        (workdir / ".claude").mkdir(exist_ok=True)  # what an adapter's prepare step writes: never merged
        (workdir / ".claude" / "skill.md").write_text("skill\n")
        for relative, text in self.writes[prompt].items():
            (workdir / relative).parent.mkdir(parents=True, exist_ok=True)
            (workdir / relative).write_text(text)
        self.active -= 1

    async def emit(self, *args, **kwargs):
        pass


def _complete(ctx, names):
    return asyncio.run(complete_modules(ctx, [{"name": name} for name in names], lambda module: module["name"]))


def test_modules_run_at_once_in_scratch_copies_and_merge_back(tmp_path):
    ctx = _Ctx(tmp_path, {"decks": {"src/decks.py": "decks\n"}, "cards": {"src/cards.py": "cards\n"}})
    summary = _complete(ctx, ["decks", "cards"])

    project = ctx.workspace.project
    assert summary == {"completedByEngine": ["decks", "cards"], "parallel": True, "conflicts": []}
    assert ctx.peak == 2
    assert all(workdir != project for _, workdir in ctx.calls)  # each in its own copy
    assert (project / "src/decks.py").read_text() == "decks\n" and (project / "src/cards.py").read_text() == "cards\n"
    assert not (project / ".claude").exists()  # adapter files stay in the scratch copies
    assert not (tmp_path / "scratch").exists()


def test_a_conflict_runs_the_later_module_again_on_the_merged_code(tmp_path):
    writes = {"decks": {"src/shared.py": "decks\n"}, "cards": {"src/shared.py": "cards\n", "src/cards.py": "c\n"}}
    ctx = _Ctx(tmp_path, writes)
    summary = _complete(ctx, ["decks", "cards"])

    project = ctx.workspace.project
    assert summary["conflicts"] == ["cards"]
    assert [workdir for prompt, workdir in ctx.calls if prompt == "cards"][-1] == project  # rerun in the project
    assert (project / "src/shared.py").read_text() == "cards\n"  # decks merged first, then cards ran on top
    assert (project / "src/cards.py").read_text() == "c\n"


def test_the_same_change_from_two_modules_is_not_a_conflict(tmp_path):
    ctx = _Ctx(tmp_path, {"decks": {"src/shared.py": "same\n"}, "cards": {"src/shared.py": "same\n"}})
    assert _complete(ctx, ["decks", "cards"])["conflicts"] == []
    assert len(ctx.calls) == 2


def test_one_module_runs_in_the_project_itself(tmp_path):
    ctx = _Ctx(tmp_path, {"cards": {"src/cards.py": "c\n"}})
    assert _complete(ctx, ["cards"]) == {"completedByEngine": ["cards"], "parallel": False}
    assert ctx.calls == [("cards", ctx.workspace.project)]


def test_flashcards_modules_complete_in_parallel(client, user_headers, tmp_path):
    generation_id = submit(client, user_headers, spec=FLASHCARDS, crudFromTemplates=True)
    engine = FakeEngine(tmp_path, demo_scenario(0.2))

    assert run_job(tmp_path, generation_id, engine=engine) in ("COMPLETED", "COMPLETED_WITH_WARNINGS")
    summary = next(run.summary for run in node_runs(generation_id) if run.node == "generate_backend")
    assert summary["completedByEngine"] == ["decks", "cards"] and summary["parallel"] is True
    assert summary["conflicts"] == [] and summary["engineCalls"] == 2
    engine_events = [
        e.type
        for e in events(generation_id)
        if e.type.startswith("engine.") and e.payload.get("purpose") == "complete_backend"
    ]
    assert engine_events[:2] == ["engine.started", "engine.started"]  # both running before either finished
    project = tmp_path / generation_id / "project"
    assert (project / "src/modules/cards/usecases/review_card_usecase.py").is_file()
    assert (project / "src/modules/decks/usecases/stats_deck_usecase.py").is_file()
    assert not (tmp_path / generation_id / "scratch").exists()
    prompts = [call.prompt for call in engine.calls if call.purpose == "complete_backend"]
    assert all("Everything you need is in this prompt" in prompt for prompt in prompts)


# -- frontend warnings -------------------------------------------------------------------------------------------------


def test_frontend_conventions_findings_are_a_warning(tmp_path, monkeypatch):
    finding = {"rule": "type-not-interface", "file": "src/lib/a.ts", "message": "use `type`"}
    monkeypatch.setattr("src.orchestrator.frontend.validation.check_frontend_conventions", lambda *_: [finding])
    result = conventions_check(tmp_path, {})
    assert result.status == "warning" and result.details == [finding]
    monkeypatch.setattr("src.orchestrator.frontend.validation.check_frontend_conventions", lambda *_: [])
    assert conventions_check(tmp_path, {}).status == "passed"


def test_type_errors_only_in_test_files_are_a_warning():
    only_tests = "tests/unit/a.test.tsx(3,1): error TS2322: x\nsrc/lib/b.spec.ts(1,1): error TS2304: y\n"
    errors = typescript_errors(only_tests)
    assert [e["file"] for e in errors] == ["tests/unit/a.test.tsx", "src/lib/b.spec.ts"]
    assert only_in_tests(only_tests, errors)

    app = only_tests + "src/app/page.tsx(2,5): error TS2322: z\n"
    assert not only_in_tests(app, typescript_errors(app))
    unparsed = only_tests + "next-env.d.ts(1,1): error TS1005: w\n"  # not parsed: it may be anywhere
    assert not only_in_tests(unparsed, typescript_errors(unparsed))


def test_related_entities_skip_a_link_table_without_an_entity():
    """gen_01M6Z6HPQQ0WMJ3ZSZGABM70NR (2026-11-09, Lantern Audio): the draft had an `EpisodeGuest` entity and a
    many-to-many Episode–Guest relationship, so the relations plugin added a link table with no entity; the context
    pack escaped its None name and the backend lane crashed."""
    spec = normalized(Path(__file__).parent / "fixtures" / "specs" / "lantern-audio-m2m.json")
    plan = build_plan(spec)
    # the planner now drops such a many-to-many (the join entity is the relationship); the context pack must still
    # take a plan with an entity-less model, as a many-to-many without a join entity plans one
    plan["models"].append({"entity": None, "table": "episodes_guests", "class": "EpisodeGuestLinkModel", "columns": []})
    for module in plan["modules"]:
        related = related_entities(plan, spec, module)
        assert None not in related and all(isinstance(name, str) for name in related)
    episodes = _module(plan, "episodes")
    assert "Guest" in related_entities(plan, spec, episodes) or "Show" in related_entities(plan, spec, episodes)
