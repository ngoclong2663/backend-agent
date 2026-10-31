"""Requirement drafting (Stories 2.4, 12.4): input checks, the draft API, the draft runner and the worker loop."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session

from src.configs import config
from src.engines import EngineRegistry, PromptLibrary
from src.engines.fake_engine import FakeEngine, FakeStep
from src.libs.database import db_session_manager
from src.libs.queue import JobQueue
from src.libs.redaction import Redactor
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.requirement import RequirementError, check_requirement
from src.modules.shared.infrastructure.models import SpecDraftModel
from src.orchestrator.drafting import DraftRunner, check_draft, draw_images, read_notes, section_catalogue
from src.orchestrator.store import JobStore
from src.orchestrator.worker_service import WorkerService
from src.orchestrator.workspace import WorkspaceManager
from workflow_helpers import build_runner, redis_client

REPO = Path(__file__).parents[2]
REQUIREMENTS = REPO / "examples" / "requirements"
EXAMPLES = REPO / "examples"

pytestmark = pytest.mark.usefixtures("clean_redis")


# -- requirement input ---------------------------------------------------------------------------------------------


def test_requirement_accepts_text_and_markdown_files():
    typed = check_requirement("A shop that sells coffee and tea online.\r\n", 65536)
    assert typed.format == "text" and typed.text == "A shop that sells coffee and tea online.\n"
    md = check_requirement((REQUIREMENTS / "corner-shop.md").read_text(), 65536, "C:\\Users\\me\\corner-shop.md")
    assert md.format == "markdown" and md.file_name == "corner-shop.md" and md.artifact_name == "requirement.md"
    txt = check_requirement("\ufeffA tracker for projects and their tasks.", 65536, "notes.TXT")
    assert txt.format == "text" and txt.text.startswith("A tracker")


@pytest.mark.parametrize(
    ("text", "name", "message"),
    [
        ("   \n", None, "empty"),
        ("Too short", None, "at least"),
        ("x" * 70_000, None, "larger than 64 KB"),
        ("A normal requirement for a shop online", "brief.pdf", "not a text requirement"),
        ("A normal requirement\x00\x01 for a shop online", "brief.txt", "binary"),
    ],
)
def test_requirement_rejects_bad_input(text, name, message):
    with pytest.raises(RequirementError, match=message):
        check_requirement(text, 65536, name)


# -- API -----------------------------------------------------------------------------------------------------------


def _draft(client, headers, **body):
    return client.post("/api/v1/spec-drafts", json={"engine": "fake", **body}, headers=headers)


def test_create_draft_queues_it_and_get_returns_it(client, user_headers, login):
    text = (REQUIREMENTS / "project-tracker.md").read_text()
    response = _draft(
        client, user_headers, mode="dynamic", requirementText=text, requirementFileName="project-tracker.md"
    )
    assert response.status_code == 202, response.text
    draft_id = response.json()["draftId"]
    assert response.json()["status"] == "PENDING"

    async def queued():
        redis = redis_client()
        try:
            return await redis.lrange("bga:drafts:fake", 0, -1)
        finally:
            await redis.aclose()

    assert asyncio.run(queued()) == [draft_id]
    body = client.get(f"/api/v1/spec-drafts/{draft_id}", headers=user_headers).json()
    assert body["mode"] == "dynamic" and body["source"] == "requirement"
    assert body["requirement"] == {"text": text.strip() + "\n", "format": "markdown", "fileName": "project-tracker.md"}
    assert body["backendSpec"] is None and body["validation"] == {"backend": None, "frontend": None, "pair": None}

    other = {"Authorization": f"Bearer {login('other@test.local', 'otherpass')}"}
    assert client.get(f"/api/v1/spec-drafts/{draft_id}", headers=other).status_code == 404


def test_create_draft_rejects_bad_requirements_and_unknown_engines(client, user_headers):
    bad = _draft(client, user_headers, requirementText="A shop selling coffee", requirementFileName="brief.docx")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "REQUIREMENT_INVALID"
    empty = _draft(client, user_headers, requirementText="")
    assert empty.json()["error"]["code"] == "REQUIREMENT_INVALID"
    engine = _draft(client, user_headers, engine="nope", requirementText="A shop selling coffee and tea")
    assert engine.status_code == 422 and engine.json()["error"]["code"] == "ENGINE_UNKNOWN"
    refine = _draft(client, user_headers, source="frontend", mode="static", baseSpec={}, siteJson={})
    assert refine.json()["error"]["code"] == "MODE_INPUT_MISMATCH"
    assert client.post("/api/v1/spec-drafts", json={}).status_code == 401


# -- runner --------------------------------------------------------------------------------------------------------


def _create(client, headers, mode: str, text: str, **body) -> str:
    response = _draft(client, headers, mode=mode, requirementText=text, **body)
    assert response.status_code == 202, response.text
    return response.json()["draftId"]


def _run(root: Path, draft_id: str, engine: FakeEngine | None = None) -> dict:
    engine = engine or FakeEngine(root, {k: v for k, v in _scenario().items()})
    runner = DraftRunner(
        EngineRegistry([engine], default="fake"), PromptLibrary(), JobStore(), root, "w-test", EXAMPLES
    )
    asyncio.run(runner.run(draft_id))
    assert not (root / "drafts" / draft_id).exists(), "the scratch directory is removed"
    return JobStore().draft(uuid.UUID(draft_id)).model_dump(mode="json")


def _scenario() -> dict:
    from src.engines.fake_engine import demo_scenario

    return demo_scenario(delay_s=0)


def test_backend_draft_from_a_markdown_requirement(client, user_headers, tmp_path):
    draft_id = _create(client, user_headers, "backend", (REQUIREMENTS / "corner-shop.md").read_text())
    draft = _run(tmp_path, draft_id)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert draft["backend_spec"]["project"]["name"] == "Corner Shop" and draft["frontend_spec"] is None
    example = json.loads((EXAMPLES / "specs" / "shop.json").read_text())
    assert list(draft["backend_spec"]) == list(example), "the spec keeps the key order the engine wrote"
    assert draft["validation"]["backend"]["valid"] is True and set(draft["validation"]) == {"backend"}
    assert draft["assumptions"][0]["spec"] == "backend" and draft["unresolved"][0]["path"] == "/operations"
    assert [call["prompt"] for call in draft["usage"]["calls"]] == ["draft_spec@v3"]
    assert draft["usage"]["modelCalls"] == 2 and draft["usage"]["inputTokens"] == 1000
    assert draft["attempts"] == 0 and draft["progress"] is None and draft["finished_at"]


def test_static_draft_writes_only_a_frontend_spec(client, user_headers, tmp_path):
    draft_id = _create(client, user_headers, "static", (REQUIREMENTS / "northwind-studio.md").read_text())
    draft = _run(tmp_path, draft_id)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert draft["frontend_spec"]["project"]["mode"] == "static" and draft["backend_spec"] is None
    assert draft["unresolved"] == [] and set(draft["validation"]) == {"frontend"}
    assert draft["usage"]["calls"][0]["prompt"] == "draft_frontend_spec@v5"
    # Story 12.6: three directions, the first applied (the fake engine names none), its notes after the engine's.
    design = draft["design"]
    assert design["selected"] == 0 and len(design["directions"]) == 3
    chosen = design["directions"][0]
    assert draft["frontend_spec"]["theme"]["direction"]["productType"] == chosen["productType"]
    assert draft["frontend_spec"]["theme"]["colors"] == chosen["theme"]["colors"]
    assert draft["assumptions"][0]["message"].startswith("Fake engine")
    assert draft["assumptions"][1]["message"].startswith("Design direction: ")
    # Epic 15: no placeholders; the example's placeholder (work-2) is drawn in the direction's style.
    assets = {asset["id"]: asset for asset in draft["frontend_spec"]["assets"]}
    assert {asset["source"] for asset in assets.values()} == {"generate"}
    work = assets["work-2"]
    assert work["prompt"] == work["alt"] and work["style"].startswith(chosen["style"])
    assert draft["assumptions"][-1]["message"] == "Drawn from their alt text instead of placeholders: work-2"
    from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
    from src.orchestrator.frontend_planner import plan_frontend

    plan = plan_frontend(validate_frontend_spec_data(draft["frontend_spec"]).normalized)
    assert plan["rendering"] == "renderer" and plan["rendererGaps"] == [], "still built with no engine call"


def test_the_engine_picks_a_brief_and_brand_colours_win(client, user_headers, tmp_path):
    spec = (EXAMPLES / "frontend-specs" / "static-landing.json").read_text()
    notes = {"assumptions": [], "unresolved": [],
             "design": {"productType": "E-commerce Luxury", "brandColors": {"primary": "#0E7490"}}}  # fmt: skip
    engine = FakeEngine(
        tmp_path,
        {"draft_frontend_spec": [FakeStep(write={"frontend-spec.json": spec, "notes.json": json.dumps(notes)})]},
    )
    text = "An online shop selling handmade ceramic mugs and plates, with product listings and a cart."
    draft = _run(tmp_path, _create(client, user_headers, "static", text), engine)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert ".bga/design.md" in engine.calls[0].prompt
    design = draft["design"]
    assert design["directions"][design["selected"]]["productType"] == "E-commerce Luxury"
    assert all(item["theme"]["colors"]["primary"] == "#0e7490" for item in design["directions"])
    assert draft["frontend_spec"]["theme"]["colors"]["primary"] == "#0e7490"


def test_placeholder_images_are_drawn_up_to_the_limit(tmp_path):
    images = [{"id": f"img-{i}", "alt": f"Picture {i}"} for i in range(14)]
    images += [
        {"id": "icon", "kind": "icon", "source": "placeholder"},
        {"id": "photo", "source": "upload:upl_abcdef12"},
        {"id": "drawn", "source": "generate", "prompt": "a kite", "style": "ink"},
    ]
    (tmp_path / "frontend-spec.json").write_text(json.dumps({"assets": images}))
    notes = draw_images(tmp_path, None)
    assets = {asset["id"]: asset for asset in json.loads((tmp_path / "frontend-spec.json").read_text())["assets"]}
    drawn = [key for key, asset in assets.items() if asset.get("source") == "generate"]
    assert len(drawn) == 12 and "drawn" in drawn and assets["drawn"]["prompt"] == "a kite"
    assert assets["img-0"] == {"id": "img-0", "alt": "Picture 0", "source": "generate", "prompt": "Picture 0"}
    assert assets["img-11"].get("source") is None and assets["img-13"].get("source") is None
    assert assets["icon"]["source"] == "placeholder" and assets["photo"]["source"] == "upload:upl_abcdef12"
    assert notes[1]["message"].startswith("Left as placeholders (at most 12 drawings per site): img-11, img-12, img-13")
    assert draw_images(tmp_path, None) == notes[1:], "a second pass changes nothing"


def test_backend_drafts_have_no_design(client, user_headers, tmp_path):
    draft = _run(tmp_path, _create(client, user_headers, "backend", (REQUIREMENTS / "corner-shop.md").read_text()))
    assert draft["design"] is None


def test_dynamic_draft_checks_the_pair(client, user_headers, tmp_path):
    draft_id = _create(client, user_headers, "dynamic", (REQUIREMENTS / "project-tracker.md").read_text())
    draft = _run(tmp_path, draft_id)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert set(draft["validation"]) == {"backend", "frontend", "pair"}
    assert draft["validation"]["pair"]["valid"] is True
    assert draft["frontend_spec"]["project"]["mode"] == "dynamic" and draft["backend_spec"]["entities"]


def test_invalid_draft_is_repaired(client, user_headers, tmp_path):
    good = (EXAMPLES / "specs" / "two-entity.json").read_text()
    broken = json.loads(good)
    broken["specVersion"] = "9.9"
    notes = json.dumps({"assumptions": [{"path": "/entities", "reason": "named the entities"}], "unresolved": []})
    engine = FakeEngine(
        tmp_path,
        {
            "draft_spec": [FakeStep(write={"backend-spec.json": json.dumps(broken), "notes.json": notes})],
            "repair_spec": [FakeStep(write={"backend-spec.json": good})],
        },
    )
    draft_id = _create(client, user_headers, "backend", "A tracker for projects and their tasks.")
    draft = _run(tmp_path, draft_id, engine)
    assert draft["status"] == "SUCCEEDED" and draft["attempts"] == 1
    assert [call["purpose"] for call in draft["usage"]["calls"]] == ["draft_spec", "repair_spec"]
    assert draft["assumptions"] == [
        {"path": "/entities", "message": "named the entities", "suggestion": None, "spec": "backend"}
    ]
    repair_prompt = engine.calls[1].prompt
    assert "backend-spec.json" in repair_prompt and "SPEC_VERSION_UNSUPPORTED" in repair_prompt


def test_draft_still_invalid_after_repairs_needs_review(client, user_headers, tmp_path):
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    spec["project"]["mode"] = "dynamic"
    engine = FakeEngine(tmp_path, {"*": [FakeStep(write={"frontend-spec.json": json.dumps(spec)})]})
    draft_id = _create(client, user_headers, "static", "A studio website with our work and a contact page.")
    draft = _run(tmp_path, draft_id, engine)
    assert draft["status"] == "NEEDS_REVIEW" and draft["attempts"] == config.draft_repair_attempts_frontend
    assert draft["validation"]["frontend"]["errors"][0]["code"] == "MODE_MISMATCH"
    assert draft["frontend_spec"]["project"]["name"] == spec["project"]["name"], "the draft is kept for editing"
    assert draft["assumptions"][0]["message"].startswith("The draft came without notes")


def test_engine_failure_or_no_output_fails_the_draft(client, user_headers, tmp_path):
    from src.engines.port import EngineErrorReason, EngineStatus

    crashed = FakeEngine(
        tmp_path, {"*": [FakeStep(status=EngineStatus.CLI_ERROR, error_reason=EngineErrorReason.AUTH)]}
    )
    draft = _run(tmp_path, _create(client, user_headers, "backend", "A tracker for projects and tasks."), crashed)
    assert draft["status"] == "FAILED" and "stopped" in draft["error"]
    assert draft["usage"]["calls"][0]["status"] == "cli_error", "a failed call is still accounted"

    silent = FakeEngine(tmp_path, {"*": [FakeStep()]})
    draft = _run(tmp_path, _create(client, user_headers, "backend", "A tracker for projects and tasks."), silent)
    assert draft["status"] == "FAILED" and draft["error"] == "The engine wrote no spec"


def test_refine_with_ai_drafts_from_the_imported_site(client, user_headers, tmp_path):
    base = json.loads((EXAMPLES / "specs" / "two-entity.json").read_text())
    site = json.loads((EXAMPLES / "frontend" / "revue-de-mode.json").read_text())
    response = _draft(client, user_headers, source="frontend", mode="backend", baseSpec=base, siteJson=site)
    assert response.status_code == 202, response.text
    engine = FakeEngine(tmp_path, _scenario())
    draft = _run(tmp_path, response.json()["draftId"], engine)
    assert draft["status"] == "SUCCEEDED" and draft["source"] == "frontend"
    assert draft["backend_spec"] == base, "the fake returns the importer's draft unchanged"
    prompt = engine.calls[0].prompt
    assert ".bga/base-spec.json" in prompt and ".bga/site.json" in prompt and "x-frontendBindings" in prompt


def test_a_draft_runs_once(client, user_headers, tmp_path):
    draft_id = _create(client, user_headers, "backend", "A tracker for projects and their tasks.")
    engine = FakeEngine(tmp_path, _scenario())
    _run(tmp_path, draft_id, engine)
    _run(tmp_path, draft_id, engine)
    assert len(engine.calls) == 1


def test_check_and_notes_tolerate_engine_output(tmp_path):
    (tmp_path / "frontend-spec.json").write_text("{not json")
    check = check_draft(tmp_path, "static")
    assert check.reports["frontend"].errors[0].code == "JSON_MALFORMED" and not check.ok
    assert check.repair_errors()[0]["file"] == "frontend-spec.json"
    (tmp_path / "notes.json").write_text(
        json.dumps({"assumptions": ["plain", {"x": 1}], "unresolved": [{"message": ""}]})
    )
    assert read_notes(tmp_path, "static") == (
        [{"path": "", "message": "plain", "suggestion": None, "spec": "frontend"}],
        [],
    )
    catalogue = section_catalogue()
    assert "**Hero**" in catalogue and "**Columns**" in catalogue and "secondaryCta" in catalogue


# -- worker --------------------------------------------------------------------------------------------------------


def _service(root: Path, redis, engine: FakeEngine) -> WorkerService:
    registry = EngineRegistry([engine], default=engine.name)
    return WorkerService(
        build_runner(root, redis, engine=engine, worker_id="w-test"),
        JobQueue(redis),
        JobStore(),
        EventPublisher(redis, Redactor()),
        redis,
        registry,
        WorkspaceManager(root, max_mb=200),
        "w-test",
        concurrency=1,
        drafts=DraftRunner(registry, PromptLibrary(), JobStore(), root, "w-test", EXAMPLES),
    )


def test_worker_runs_queued_drafts(client, user_headers, tmp_path):
    draft_id = _create(client, user_headers, "static", (REQUIREMENTS / "northwind-studio.md").read_text())

    async def scenario():
        redis = redis_client()
        stop = asyncio.Event()
        task = asyncio.create_task(_service(tmp_path, redis, FakeEngine(tmp_path, _scenario())).run(stop))
        try:
            for _ in range(200):
                status = JobStore().draft(uuid.UUID(draft_id)).status
                if status not in ("PENDING", "RUNNING"):
                    return status
                await asyncio.sleep(0.1)
            return status
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=15)
            await redis.aclose()

    assert asyncio.run(scenario()) == "SUCCEEDED"


def test_reaper_fails_drafts_whose_worker_stopped(client, user_headers, tmp_path):
    running = _create(client, user_headers, "backend", "A tracker for projects and their tasks.")
    waiting = _create(client, user_headers, "backend", "A tracker for projects and their tasks.")
    fresh = _create(client, user_headers, "backend", "A tracker for projects and their tasks.")
    now = datetime.now(UTC)
    with Session(db_session_manager.engine) as session:
        session.get(SpecDraftModel, uuid.UUID(running)).status = "RUNNING"
        for draft_id, age in ((running, 600), (waiting, config.draft_pending_timeout_seconds + 60), (fresh, 600)):
            session.get(SpecDraftModel, uuid.UUID(draft_id)).updated_at = now - timedelta(seconds=age)
        session.commit()

    async def scenario():
        redis = redis_client()
        try:
            _service(tmp_path, redis, FakeEngine(tmp_path)).reap_drafts(now)
        finally:
            await redis.aclose()

    asyncio.run(scenario())
    drafts = {key: JobStore().draft(uuid.UUID(key)) for key in (running, waiting, fresh)}
    assert drafts[running].status == "FAILED" and "stopped" in drafts[running].error
    assert drafts[waiting].status == "FAILED" and "picked up" in drafts[waiting].error
    assert drafts[fresh].status == "PENDING", "a pending draft gets time for a worker to pick it up"


# -- from draft to generation, and usage ---------------------------------------------------------------------------


def test_generation_from_a_draft_keeps_the_requirement(client, user_headers, login, tmp_path):
    from types import SimpleNamespace

    from src.modules.shared.infrastructure.models import BackendSpecModel
    from src.orchestrator.nodes import _requirement
    from workflow_helpers import generation

    text = (REQUIREMENTS / "corner-shop.md").read_text()
    draft_id = _create(client, user_headers, "backend", text, requirementFileName="corner-shop.md")
    draft = _run(tmp_path, draft_id)
    body = {
        "mode": "backend",
        "backendSpec": draft["backend_spec"],
        "draftId": draft_id,
        "options": {"engine": "fake", "deployPreview": False},
    }
    response = client.post("/api/v1/generations", json=body, headers=user_headers)
    assert response.status_code == 202, response.text
    row = generation(response.json()["generationId"])
    assert row.options["draftId"] == draft_id
    with Session(db_session_manager.engine) as session:
        spec = session.get(BackendSpecModel, row.spec_id)
        assert spec.source == "requirement" and spec.requirement_text == text.strip() + "\n"

    name, kind, data, content_type = _requirement(SimpleNamespace(store=JobStore()), draft_id)
    assert (name, kind, content_type) == ("requirement.md", "requirement", "text/markdown")
    assert data.decode().startswith("# Corner Shop")

    wrong_mode = client.post(
        "/api/v1/generations", json={**body, "mode": "static", "backendSpec": None}, headers=user_headers
    )
    assert wrong_mode.status_code == 422
    unfinished = _create(client, user_headers, "backend", text)
    not_ready = client.post("/api/v1/generations", json={**body, "draftId": unfinished}, headers=user_headers)
    assert not_ready.status_code == 422 and "PENDING" in not_ready.json()["error"]["message"]
    other = {"Authorization": f"Bearer {login('other@test.local', 'otherpass')}"}
    assert client.post("/api/v1/generations", json=body, headers=other).status_code == 404


def test_usage_counts_drafts(client, user_headers, tmp_path):
    before = client.get("/api/v1/usage", headers=user_headers).json()["drafts"]
    draft_id = _create(client, user_headers, "static", (REQUIREMENTS / "northwind-studio.md").read_text())
    _run(tmp_path, draft_id)
    after = client.get("/api/v1/usage", headers=user_headers).json()["drafts"]
    assert after["count"] == before["count"] + 1 and after["succeeded"] == before["succeeded"] + 1
    assert after["modelCalls"] == before["modelCalls"] + 2
    assert after["tokens"]["input"] == before["tokens"]["input"] + 1000
    assert after["byMode"]["static"] >= 1
