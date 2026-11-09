"""Story 18.10: spec drafts through the Gemini API (one request per step), against an httpx mock transport."""

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from generation_helpers import EXAMPLES

from src.configs import config
from src.engines import EngineContext, EngineErrorReason, EngineRegistry, EngineRequest, EngineStatus, PromptLibrary
from src.engines.gemini_api import GeminiApiEngine
from src.libs.jsonpatch import PatchError, apply_patch
from src.libs.redaction import Redactor
from src.orchestrator.drafting.drafts import DraftRunner
from src.orchestrator.store import JobStore

KEY = "AIzaSyTESTKEY0123456789abcdefghijk"
PRICES = {"gemini-3.8-flash": {"input": 1.0, "output": 2.0, "cache_read": 0.1}}


def answer(envelope, *, finish="STOP", usage=None, status=200, raw=None):
    """A `generateContent` answer whose text is `envelope` (an object, or raw text)."""
    text = raw if raw is not None else json.dumps(envelope)
    body = {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": usage or {"promptTokenCount": 1000, "candidatesTokenCount": 200, "thoughtsTokenCount": 50},
        "modelVersion": "gemini-3.8-flash",
    }
    return httpx.Response(status, json=body)


def engine(root: Path, answers, **overrides) -> GeminiApiEngine:
    """An engine whose transport replays `answers` (callables or responses) in order and records the requests."""
    queue = list(answers)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"name": "models/gemini-3.8-flash"})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return item(request) if callable(item) else item

    values = dict(
        api_key=KEY,
        model="gemini-3.8-flash",
        allowed_root=root,
        redactor=Redactor(),
        prices=PRICES,
        transport=httpx.MockTransport(handler),
        retry_backoff_s=0,
    )
    made = GeminiApiEngine(**{**values, **overrides})
    made.requests = requests  # type: ignore[attr-defined]
    return made


def request(root: Path, purpose="draft_frontend_spec", prompt="draft it", **overrides) -> EngineRequest:
    (root / "work").mkdir(exist_ok=True)
    (root / "state").mkdir(exist_ok=True)
    return EngineRequest(purpose=purpose, workdir=root / "work", state_dir=root / "state", prompt=prompt, **overrides)


def run(made: GeminiApiEngine, req: EngineRequest):
    events = []

    async def on_event(event):
        events.append(event)

    return asyncio.run(made.run(req, on_event)), events


# -- the envelope --------------------------------------------------------------------------------------------------


def test_files_are_written_and_the_call_is_priced(tmp_path):
    made = engine(tmp_path, [answer({"files": {"a.json": {"x": 1}, "sub/b.md": "hello"}, "message": "done"})])
    result, events = run(made, request(tmp_path))
    assert result.status == EngineStatus.OK and result.changed_files == ["a.json", "sub/b.md"]
    assert json.loads((tmp_path / "work" / "a.json").read_text()) == {"x": 1}
    assert (tmp_path / "work" / "sub" / "b.md").read_text() == "hello"
    assert result.turns == 1 and len(result.model_calls) == 1 and result.final_message == "done"
    call = result.model_calls[0]
    assert (call.input_tokens, call.output_tokens, call.thinking_tokens) == (1000, 250, 50)
    assert (
        result.usage.cost_usd == pytest.approx((1000 * 1.0 + 250 * 2.0) / 1e6)
        and result.usage.cost_source == "estimated"
    )
    sent = json.loads(made.requests[-1].content)
    assert (
        sent["generationConfig"]["responseMimeType"] == "application/json"
        and sent["contents"][0]["parts"][0]["text"] == "draft it"
    )
    assert made.requests[-1].headers["x-goog-api-key"] == KEY and made.requests[-1].url.path.endswith(
        ":generateContent"
    )
    assert [e.kind.value for e in events] == ["system", "usage", "tool_use", "tool_use", "message"]
    assert Path(result.stdout_ref).is_file(), "the raw answer is logged in the state directory"


def test_patches_apply_to_existing_files_and_a_bad_pointer_is_reported(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "spec.json").write_text(json.dumps({"a": 1, "list": [1]}))
    patches = {"spec.json": [{"op": "replace", "path": "/a", "value": 2}, {"op": "add", "path": "/list/-", "value": 3}]}
    made = engine(tmp_path, [answer({"patches": patches, "message": "patched"})])
    result, _ = run(made, request(tmp_path, purpose="repair_spec"))
    assert result.status == EngineStatus.OK and result.changed_files == ["spec.json"]
    assert json.loads((tmp_path / "work" / "spec.json").read_text()) == {"a": 2, "list": [1, 3]}

    bad = {"spec.json": [{"op": "replace", "path": "/a", "value": 3}, {"op": "remove", "path": "/missing"}]}
    result, _ = run(engine(tmp_path, [answer({"patches": bad})]), request(tmp_path, purpose="repair_spec"))
    assert result.status == EngineStatus.OK, "the operations before the failing one still apply"
    assert json.loads((tmp_path / "work" / "spec.json").read_text())["a"] == 3
    assert "Not applied: spec.json: patch 1 (remove /missing)" in result.final_message

    nothing = {"spec.json": [{"op": "remove", "path": "/missing"}]}
    result, _ = run(engine(tmp_path, [answer({"patches": nothing})]), request(tmp_path, purpose="repair_spec"))
    assert result.status == EngineStatus.CLI_ERROR and "Not applied" in result.error_message


def test_files_outside_the_workdir_are_refused(tmp_path):
    made = engine(tmp_path, [answer({"files": {"../escape.json": {}, "ok.json": {}}})])
    result, _ = run(made, request(tmp_path))
    assert result.status == EngineStatus.OK and result.changed_files == ["ok.json"]
    assert not (tmp_path / "escape.json").exists() and "escape.json" in result.final_message


# -- failures and retries ------------------------------------------------------------------------------------------


def test_rate_limits_and_server_errors_retry_with_backoff(tmp_path):
    answers = [httpx.Response(429, json={"error": "slow down"}), httpx.Response(503), answer({"files": {"a.json": {}}})]
    result, _ = run(engine(tmp_path, answers), request(tmp_path))
    assert result.status == EngineStatus.OK and result.turns == 1, "only the answered request is a model call"

    always = [httpx.Response(429, json={"error": "slow down"})]
    result, _ = run(engine(tmp_path, always), request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR and result.error_reason == EngineErrorReason.RATE_LIMIT


def test_an_answer_that_is_not_json_is_asked_again_once(tmp_path):
    answers = [answer(None, raw="```json\n{not json"), answer({"files": {"a.json": {"ok": True}}})]
    made = engine(tmp_path, answers)
    result, _ = run(made, request(tmp_path, prompt="draft it"))
    assert result.status == EngineStatus.OK and result.turns == 2
    second = json.loads(made.requests[-1].content)["contents"][0]["parts"][0]["text"]
    assert second.startswith("draft it") and "was not valid JSON" in second

    result, _ = run(engine(tmp_path, [answer(None, raw="nope")]), request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR and "not JSON" in result.error_message


def test_blocked_truncated_timeout_and_auth(tmp_path):
    result, _ = run(engine(tmp_path, [answer({"files": {}}, finish="SAFETY")]), request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR and result.error_message == "blocked: SAFETY"

    result, _ = run(engine(tmp_path, [answer({"files": {}}, finish="MAX_TOKENS")]), request(tmp_path))
    assert result.status == EngineStatus.LIMIT_EXCEEDED and result.error_reason == EngineErrorReason.OUTPUT_LIMIT

    def slow(_request):
        raise httpx.ReadTimeout("too slow")

    result, _ = run(engine(tmp_path, [slow]), request(tmp_path, timeout_s=1))
    assert result.status == EngineStatus.TIMEOUT and result.error_reason == EngineErrorReason.TIMEOUT

    result, _ = run(engine(tmp_path, [httpx.Response(403, json={"error": "nope"})]), request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR and result.error_reason == EngineErrorReason.AUTH

    result, _ = run(engine(tmp_path, [], api_key=None), request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR and result.error_reason == EngineErrorReason.AUTH


def test_the_key_never_appears_in_errors_or_logs(tmp_path):
    leak = httpx.Response(500, json={"error": f"key {KEY} rejected"})
    made = engine(tmp_path, [leak, leak, leak])
    result, _ = run(made, request(tmp_path))
    assert result.status == EngineStatus.CLI_ERROR
    assert KEY not in (result.error_message or "") and KEY not in Path(result.stdout_ref).read_text()


def test_code_purposes_are_refused(tmp_path):
    result, _ = run(engine(tmp_path, [answer({"files": {}})]), request(tmp_path, purpose="generate_backend"))
    assert result.status == EngineStatus.CLI_ERROR and "drafts specs only" in result.error_message


def test_cancel_stops_the_request(tmp_path):
    made = engine(tmp_path, [answer({"files": {"a.json": {}}})])

    async def scenario():
        req = request(tmp_path)

        async def cancel_soon():
            await asyncio.sleep(0.01)
            await made.cancel(req.invocation_id)

        async def never(_request):
            await asyncio.sleep(10)
            return answer({"files": {}})

        made.transport = httpx.MockTransport(never)
        task = asyncio.create_task(made.run(req))
        await cancel_soon()
        return await task

    result = asyncio.run(scenario())
    assert result.status == EngineStatus.CANCELLED and result.error_reason == EngineErrorReason.CANCELLED


def test_health_checks_the_model_once_and_says_drafts_only(tmp_path):
    made = engine(tmp_path, [])
    first = asyncio.run(made.health())
    second = asyncio.run(made.health())
    assert first.available and first.drafts_only and second == first
    assert len([r for r in made.requests if r.method == "GET"]) == 1, "cached"
    assert not asyncio.run(engine(tmp_path, [], api_key=None).health()).available
    assert made.drafts_only and made.inline_inputs
    asyncio.run(made.prepare_workspace(tmp_path, EngineContext(conventions="")))  # a no-op


# -- the JSON Patch applier ----------------------------------------------------------------------------------------


def test_json_patch_operations():
    doc = {"a": [1, 2], "b": {"c": 1}}
    patched = apply_patch(
        doc,
        [
            {"op": "add", "path": "/a/-", "value": 3},
            {"op": "replace", "path": "/b/c", "value": 2},
            {"op": "remove", "path": "/a/0"},
            {"op": "move", "from": "/b/c", "path": "/d"},
            {"op": "copy", "from": "/d", "path": "/e~1f"},
            {"op": "test", "path": "/e~1f", "value": 2},
        ],
    )
    assert patched == {"a": [2, 3], "b": {}, "d": 2, "e/f": 2} and doc == {"a": [1, 2], "b": {"c": 1}}
    assert apply_patch(doc, [{"op": "replace", "path": "", "value": {"x": 1}}]) == {"x": 1}
    with pytest.raises(PatchError, match=r"patch 1 \(remove /zz\): no such member 'zz'") as info:
        apply_patch(doc, [{"op": "add", "path": "/k", "value": 1}, {"op": "remove", "path": "/zz"}])
    assert info.value.index == 1
    with pytest.raises(PatchError, match="unknown op"):
        apply_patch(doc, [{"op": "frobnicate", "path": "/a"}])


# -- a draft end to end --------------------------------------------------------------------------------------------


def _draft(client, headers, mode: str, text: str, **body):
    payload = {"mode": mode, "requirementText": text, "engine": "gemini_api", **body}
    response = client.post("/api/v1/spec-drafts", json=payload, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["draftId"]


def _run_draft(root: Path, made: GeminiApiEngine, draft_id: str) -> dict:
    import uuid

    runner = DraftRunner(
        EngineRegistry([made], default="gemini_api"), PromptLibrary(), JobStore(), root, "w-test", EXAMPLES
    )
    asyncio.run(runner.run(draft_id))
    return JobStore().draft(uuid.UUID(draft_id)).model_dump(mode="json")


def test_a_static_draft_through_the_api_inlines_the_inputs(client, user_headers, tmp_path):
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    notes = {
        "assumptions": [{"spec": "frontend", "path": "/pages", "message": "Added an about page"}],
        "unresolved": [],
    }
    made = engine(tmp_path, [answer({"files": {"frontend-spec.json": spec, "notes.json": notes}})])
    draft_id = _draft(client, user_headers, "static", "A website for a two-person design studio: services and work.")
    draft = _run_draft(tmp_path, made, draft_id)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    assert [c["prompt"] for c in draft["usage"]["calls"]] == ["draft_frontend_spec@v11"]
    assert draft["usage"]["modelCalls"] == 1 and draft["usage"]["inputTokens"] == 1000
    prompt = json.loads(made.requests[-1].content)["contents"][0]["parts"][0]["text"]
    assert "## Inputs" in prompt and "FrontendSpec schema digest" in prompt and ".bga/" not in prompt
    assert '"files"' in prompt and "two-person design studio" in prompt
    assert draft["assumptions"][0]["message"] == "Added an about page"
    assert draft["design"] is not None and len(draft["design"]["directions"]) == 3, "directions still come from code"


def test_a_repair_round_sends_the_files_and_applies_patches(client, user_headers, tmp_path):
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    del spec["project"]["mode"]  # invalid for a static draft: MODE_MISMATCH
    fix = {"patches": {"frontend-spec.json": [{"op": "add", "path": "/project/mode", "value": "static"}]}}
    made = engine(tmp_path, [answer({"files": {"frontend-spec.json": spec, "notes.json": {}}}), answer(fix)])
    draft_id = _draft(client, user_headers, "static", "A website for a two-person design studio: services and work.")
    draft = _run_draft(tmp_path, made, draft_id)
    assert [c["prompt"] for c in draft["usage"]["calls"]] == ["draft_frontend_spec@v11", "repair_spec@v3"]
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    repair_prompt = json.loads(made.requests[-1].content)["contents"][0]["parts"][0]["text"]
    assert '"patches"' in repair_prompt and "## The files" in repair_prompt and "SCHEMA_VIOLATION" in repair_prompt


def test_a_repair_that_changes_nothing_ends_the_loop(client, user_headers, tmp_path):
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    del spec["project"]["mode"]
    noop = {
        "patches": {
            "frontend-spec.json": [{"op": "replace", "path": "/project/name", "value": spec["project"]["name"]}]
        }
    }
    made = engine(tmp_path, [answer({"files": {"frontend-spec.json": spec, "notes.json": {}}}), answer(noop)])
    draft_id = _draft(client, user_headers, "static", "A website for a two-person design studio: services and work.")
    draft = _run_draft(tmp_path, made, draft_id)
    assert draft["status"] == "NEEDS_REVIEW"
    assert [c["prompt"] for c in draft["usage"]["calls"]] == ["draft_frontend_spec@v11", "repair_spec@v3"], (
        "the second repair round is not bought: the first changed nothing"
    )
    assert "changed nothing" in draft["error"]


def test_a_static_draft_designs_its_pages_through_the_api(client, user_headers, tmp_path, monkeypatch):
    """Epic 21 on the API engine: `draft_tree` is a draft purpose, one request per page (and the chrome)."""
    monkeypatch.setattr(config, "frontend_trees", True)
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())

    def tree(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        page = re.search(r"trees/([a-z0-9-]+)\.json", prompt).group(1)
        heading = {"type": "h1" if page != "chrome" else "p", "children": [f"Designed {page}"]}
        node = {
            "type": "main" if page != "chrome" else "header",
            "children": [{"type": "section", "children": [heading]}],
        }
        return answer({"files": {f"trees/{page}.json": {"tree": node}}})

    made = engine(tmp_path, [answer({"files": {"frontend-spec.json": spec, "notes.json": {}}}), tree])
    draft_id = _draft(client, user_headers, "static", "A website for a two-person design studio: services and work.")
    draft = _run_draft(tmp_path, made, draft_id)
    assert draft["status"] == "SUCCEEDED", draft["validation"]
    prompts = [call["prompt"] for call in draft["usage"]["calls"]]
    assert prompts[0] == "draft_frontend_spec@v11" and "draft_tree@v1" in prompts, prompts
    assert all(call["status"] == "ok" for call in draft["usage"]["calls"]), draft["usage"]["calls"]
    pages = draft["frontend_spec"]["pages"]
    assert all(page.get("tree") for page in pages), draft["assumptions"]
