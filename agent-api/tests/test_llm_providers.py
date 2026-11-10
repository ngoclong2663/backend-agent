"""Epic 24: one-turn JSON answers on every LLM provider (Stories 24.1, 24.2).

One contract suite runs against `agy` and `claude` (fake CLIs in tests/fixtures/engines/bin) and the Gemini API (an
httpx mock transport): structured output reaches the provider, the answer is parsed and checked against the schema,
a wrong shape is asked again once, a refused schema is retried without it, images reach the model, usage is recorded.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fake_llm import FakeLlmProvider, skeleton

from src.engines import EngineRequest, EngineStatus
from src.engines.gemini_api import GeminiApiEngine
from src.engines.gemini_api.llm import GeminiLlmProvider
from src.engines.json_cli import AgyJsonProvider, ClaudeJsonProvider
from src.engines.llm import Image, LlmError, parse_json_object
from src.engines.llm_engine import LlmDraftEngine
from src.libs.json_schema_check import schema_errors
from src.libs.redaction import Redactor

BIN = Path(__file__).parent / "fixtures" / "engines" / "bin"
SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "object",
            "properties": {
                "answer.json": {
                    "type": "object",
                    "properties": {"roles": {"type": "array", "items": {"type": "string"}}},
                    "required": ["roles"],
                }
            },
        },
        "message": {"type": "string"},
    },
    "required": ["files", "message"],
}
ANSWER = {"files": {"answer.json": {"roles": ["member", "librarian"]}}, "message": "roles listed"}


def _cli(kind: str, root: Path, **overrides):
    common = {"allowed_root": root, "redactor": Redactor(), "default_timeout_s": 20, "max_output_bytes": 2_000_000}
    if kind == "agy":
        values = {
            "binary": str(BIN / "fake_agy_json"),
            "model": "gemini-3.8-flash-medium",
            "auth": "gemini_api_key",
            "gemini_api_key": "gemini-test-key-123",
            "google_application_credentials": None,
        }
        return AgyJsonProvider(**{**values, **overrides}, **common)
    values = {"binary": str(BIN / "fake_claude_json"), "model": "claude-sonnet-5-5", "api_key": None}
    values["credentials_file"] = None
    return ClaudeJsonProvider(**{**values, **overrides}, **common)


def _gemini(root: Path, texts: list[str], seen: list[dict], status_first: int | None = None):
    queue = list(texts)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if status_first is not None and len(seen) == 1:
            return httpx.Response(status_first, json={"error": "schema"})
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
                "modelVersion": "gemini-3.8-flash",
            },
        )

    engine = GeminiApiEngine(
        api_key="AIzaSyTESTKEY0123456789abcdefghijk",
        model="gemini-3.8-flash",
        allowed_root=root,
        redactor=Redactor(),
        prices={"gemini-3.8-flash": {"input": 1.0, "output": 2.0}},
        transport=httpx.MockTransport(handler),
        retry_backoff_s=0,
    )
    return GeminiLlmProvider(engine)


def _records(root: Path, name: str) -> list[dict]:
    home = root / "state" / "engine-home" / name
    return [json.loads(path.read_text()) for path in sorted(home.glob("record-*.json"))]


def _ask(provider, root: Path, prompt="List the roles. MODE=ok", schema=SCHEMA, images=None):
    (root / "state").mkdir(exist_ok=True)
    return asyncio.run(provider.json("draft_app", prompt, schema, images, state_dir=root / "state"))


# -- the CLIs --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_one_turn_with_the_schema_as_structured_output(tmp_path, kind):
    provider = _cli(kind, tmp_path)
    answer = _ask(provider, tmp_path)

    assert answer.data == ANSWER and answer.structured is True
    [record] = _records(tmp_path, provider.name)
    assert record["schema"] == SCHEMA, "the answer schema reaches the CLI through --json-schema"
    assert "MODE=ok" in record["prompt"], "the prompt goes on stdin"
    assert Path(record["cwd"]).name == next(iter((tmp_path / "state" / "llm").iterdir())).name
    assert set(record["files"]) <= {"answer.schema.json"}, "an empty scratch directory: no inputs to read"
    [call] = answer.calls
    assert call.input_tokens > 0 and call.output_tokens > 0


def test_agy_runs_without_tools_or_slash_commands(tmp_path):
    provider = _cli("agy", tmp_path)
    _ask(provider, tmp_path)
    [record] = _records(tmp_path, "antigravity")
    argv = record["argv"]
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert "--disable-slash-commands" in argv and "--json-schema" in argv
    settings = json.loads(
        (
            tmp_path / "state" / "engine-home" / "antigravity" / ".gemini" / "antigravity-cli" / "settings.json"
        ).read_text()
    )
    deny = settings["permissions"]["deny"]
    assert {"command(*)", "write_file(*)", "read_file(*)", "mcp(*)"} <= set(deny)


def test_claude_runs_without_tools_and_bare_only_with_an_api_key(tmp_path):
    subscription = tmp_path / "creds.json"
    subscription.write_text("{}")
    _ask(_cli("claude", tmp_path, credentials_file=str(subscription)), tmp_path)
    [record] = _records(tmp_path, "claude_code")
    argv = record["argv"]
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
    assert "--bare" not in argv, "--bare never reads the subscription login"
    assert record["env"]["CLAUDE_CONFIG_DIR"].startswith(str(tmp_path)), "a fresh config dir: no user hooks"

    other = tmp_path / "api"
    other.mkdir()
    provider = _cli("claude", other, api_key="sk-ant-test-123456", max_budget_usd=0.5)
    answer = _ask(provider, other)
    [record] = _records(other, "claude_code")
    assert "--bare" in record["argv"] and "--max-budget-usd" in record["argv"]
    assert answer.calls[0].cost_usd == 0.0042 and answer.calls[0].cost_source == "reported"


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_fenced_json_without_a_schema(tmp_path, kind):
    answer = _ask(_cli(kind, tmp_path), tmp_path, "List. MODE=fenced", schema=None)
    assert answer.data == ANSWER and answer.structured is None


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_a_refused_schema_is_asked_again_without_it(tmp_path, kind):
    provider = _cli(kind, tmp_path)
    answer = _ask(provider, tmp_path, "List. MODE=refuse_schema")
    assert answer.data == ANSWER and answer.structured is False
    first, second = _records(tmp_path, provider.name)
    assert first["schema"] == SCHEMA and second["schema"] is None


def test_a_structured_output_the_cli_gave_up_on_is_asked_again_without_the_schema(tmp_path):
    """A socials draft on Claude (Haiku) failed: `error_max_structured_output_retries` named no "schema", so the
    draft stopped instead of asking without the schema."""
    provider = _cli("claude", tmp_path)
    answer = _ask(provider, tmp_path, "List. MODE=max_structured")
    assert answer.data == ANSWER and answer.structured is False
    first, second = _records(tmp_path, provider.name)
    assert first["schema"] == SCHEMA and second["schema"] is None


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_a_wrong_shape_is_asked_again_once_with_its_errors(tmp_path, kind):
    provider = _cli(kind, tmp_path)
    answer = _ask(provider, tmp_path, "List. MODE=bad_shape")
    assert answer.data == ANSWER
    first, second = _records(tmp_path, provider.name)
    assert "$.files: expected object" in second["prompt"]
    assert [call.seq for call in answer.calls] == [1, 2]


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_no_json_is_an_error_with_the_start_of_the_answer(tmp_path, kind):
    with pytest.raises(LlmError, match="answer was not JSON.*I cannot answer"):
        _ask(_cli(kind, tmp_path), tmp_path, "List. MODE=notjson")


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_a_tool_attempt_is_noted(tmp_path, kind):
    answer = _ask(_cli(kind, tmp_path), tmp_path, "List. MODE=tool")
    assert answer.data == ANSWER
    assert any("tried tools" in note for note in answer.notes)


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_a_login_problem_is_an_auth_error(tmp_path, kind):
    with pytest.raises(LlmError) as raised:
        _ask(_cli(kind, tmp_path), tmp_path, "List. MODE=auth")
    assert raised.value.reason == "auth"


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_images_are_files_in_the_scratch_directory(tmp_path, kind):
    provider = _cli(kind, tmp_path)
    _ask(provider, tmp_path, images=[Image(data=b"\x89PNG fake", name="screen.png")])
    [record] = _records(tmp_path, provider.name)
    assert "1-screen.png" in record["files"] and "1-screen.png" in record["prompt"]
    if kind == "claude":
        assert record["argv"][record["argv"].index("--tools") + 1] == "Read"


def test_the_account_login_costs_nothing(tmp_path):
    provider = _cli("agy", tmp_path, auth="account", gemini_api_key=None)
    call = provider._model_call(
        __import__("src.engines.json_cli", fromlist=["CliOutcome"]).CliOutcome(
            completed=True, usage={"input_tokens": 10}
        ),
        "gemini-3.8-flash",
        __import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    assert call.cost_usd == 0.0 and call.cost_source == "account"


# -- the Gemini API --------------------------------------------------------------------------------------------------


def test_gemini_sends_the_schema_and_images(tmp_path):
    seen: list[dict] = []
    provider = _gemini(tmp_path, [json.dumps(ANSWER)], seen)
    answer = _ask(provider, tmp_path, images=[Image(data=b"png", name="a.png")])
    assert answer.data == ANSWER and answer.structured is True
    generation = seen[0]["generationConfig"]
    assert generation["responseJsonSchema"] == SCHEMA
    assert seen[0]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"


def test_gemini_wrong_shape_then_refused_schema(tmp_path):
    seen: list[dict] = []
    provider = _gemini(tmp_path, [json.dumps({"files": 1}), json.dumps(ANSWER)], seen)
    answer = _ask(provider, tmp_path)
    assert answer.data == ANSWER and len(answer.calls) == 2
    seen2: list[dict] = []
    refused = _gemini(tmp_path, [json.dumps(ANSWER)], seen2, status_first=400)
    answer = _ask(refused, tmp_path)
    assert answer.structured is False and "responseJsonSchema" not in seen2[1]["generationConfig"]


# -- the draft engine on a provider ----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["agy", "claude"])
def test_a_draft_runs_in_one_cli_turn_and_applies_the_envelope(tmp_path, kind):
    provider = _cli(kind, tmp_path)
    engine = LlmDraftEngine(f"{provider.name}_json", provider, tmp_path)
    (tmp_path / "work").mkdir()
    (tmp_path / "state").mkdir()
    request = EngineRequest(
        purpose="draft_app",
        workdir=tmp_path / "work",
        state_dir=tmp_path / "state",
        prompt="Draft it. MODE=ok",
        response_schema=SCHEMA,
    )
    result = asyncio.run(engine.run(request))
    assert result.status == EngineStatus.OK and result.turns == 1 and result.structured is True
    assert json.loads((tmp_path / "work" / "answer.json").read_text()) == {"roles": ["member", "librarian"]}
    assert result.changed_files == ["answer.json"] and result.usage.input_tokens > 0
    assert len(_records(tmp_path, provider.name)) == 1, "exactly one CLI turn"

    code = asyncio.run(engine.run(request.model_copy(update={"purpose": "generate_code"})))
    assert code.status == EngineStatus.CLI_ERROR and "drafts specs only" in code.error_message


def test_a_draft_engine_reports_a_provider_error(tmp_path):
    engine = LlmDraftEngine("antigravity_json", _cli("agy", tmp_path), tmp_path)
    (tmp_path / "work").mkdir()
    (tmp_path / "state").mkdir()
    request = EngineRequest(
        purpose="draft_app", workdir=tmp_path / "work", state_dir=tmp_path / "state", prompt="MODE=notjson"
    )
    result = asyncio.run(engine.run(request))
    assert result.status == EngineStatus.CLI_ERROR and "not JSON" in result.error_message


# -- helpers ---------------------------------------------------------------------------------------------------------


def test_parse_json_object_finds_the_object():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_schema_errors_cover_the_answer_keywords():
    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["a", "b"]},
            "items": {"type": "array", "items": {"$ref": "#/$defs/item"}, "minItems": 1},
            "n": {"type": "integer", "minimum": 0},
            "either": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["kind", "items"],
        "additionalProperties": False,
        "$defs": {"item": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    }
    assert schema_errors({"kind": "a", "items": [{"id": "x"}], "n": 1, "either": None}, schema) == []
    errors = schema_errors({"kind": "c", "items": [{}], "n": -1, "either": 3, "extra": 1}, schema)
    assert "$.kind: 'c' is not one of 'a', 'b'" in errors
    assert "$.items[0]: missing required 'id'" in errors
    assert "$.n: -1 is below 0" in errors
    assert "$.either: matches none of the allowed shapes" in errors
    assert "$: unexpected property 'extra'" in errors
    assert schema_errors({"kind": "a", "items": []}, schema) == ["$.items: at least 1 item(s), got 0"]
    assert schema_errors(True, {"type": "integer"}) == ["$: expected integer, got boolean"]


def test_the_fake_provider_answers_the_schema_skeleton(tmp_path):
    provider = FakeLlmProvider(responders={})
    answer = _ask(provider, tmp_path)
    assert answer.data == skeleton(SCHEMA) and schema_errors(answer.data, SCHEMA) == []
    assert provider.calls[0]["step"] == "draft_app"


def test_the_claude_json_provider_runs_on_a_setup_token(tmp_path):
    token = "sk-ant-oat01-test-token-abcdef"
    provider = _cli("claude", tmp_path, oauth_token=token)
    health = asyncio.run(provider.health())
    assert health.available and "subscription" in (health.reason or "")
    call = provider.call("prompt", None, tmp_path / "s", tmp_path / "home", [], None, 60)
    assert call.env["CLAUDE_CODE_OAUTH_TOKEN"] == token and "--bare" not in call.argv
    assert provider.redactor.redact(token) != token
