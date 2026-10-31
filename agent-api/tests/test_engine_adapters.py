import asyncio
import json
from pathlib import Path

import pytest

from src.engines import EngineContext, EngineErrorReason, EngineEventKind, EngineRequest, EngineStatus
from src.engines.antigravity import AntigravityEngine
from src.engines.claude_code import ClaudeCodeEngine
from src.engines.claude_code.stream import ClaudeStreamParser
from src.engines.workspace import WorkspaceViolation
from src.libs.redaction import Redactor

BIN = Path(__file__).parent / "fixtures" / "engines" / "bin"
FIXTURES = Path(__file__).parent / "fixtures" / "engines"
SECRET = "sk-ant-api03-SECRETSECRETSECRET"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "job" / "project").mkdir(parents=True)
    return tmp_path


def _limits(root):
    return {
        "allowed_root": root,
        "redactor": Redactor([SECRET]),
        "default_timeout_s": 10,
        "default_max_turns": 5,
        "max_output_bytes": 2_000_000,
    }


def _claude(root, **overrides):
    values = {"binary": str(BIN / "fake_claude"), "api_key": "test-key-123456", "credentials_file": None, "model": None}
    values.update(overrides)
    return ClaudeCodeEngine(**values, **_limits(root))


def _agy(root, auth="gemini_api_key", model=None, purpose_models=None):
    return AntigravityEngine(
        binary=str(BIN / "fake_agy"),
        auth=auth,
        gemini_api_key="gemini-test-key-123" if auth == "gemini_api_key" else None,
        google_application_credentials=None,
        model=model,
        purpose_models=purpose_models,
        **_limits(root),
    )


def _request(root, prompt="write hello", **overrides):
    values = {"purpose": "probe", "workdir": root / "job" / "project", "state_dir": root / "job" / "state"}
    values.update(overrides)
    return EngineRequest(prompt=prompt, **values)


def _run(engine, request):
    events = []

    async def on_event(event):
        events.append(event)

    return asyncio.run(engine.run(request, on_event)), events


def _record(root, engine_name):
    return json.loads((root / "job" / "state" / "engine-home" / engine_name / "record.json").read_text())


def test_claude_success_is_normalized(root):
    result, events = _run(_claude(root), _request(root))

    assert result.status == EngineStatus.OK
    assert result.turns == 2
    assert result.usage.input_tokens == 150 and result.usage.output_tokens == 20 and result.usage.cost_usd == 0.0123
    assert result.changed_files == ["hello.py"]
    assert result.session_id == "s-1"
    kinds = [event.kind for event in events]
    assert kinds == [
        EngineEventKind.SYSTEM,
        EngineEventKind.TOOL_USE,
        EngineEventKind.TOOL_RESULT,
        EngineEventKind.MESSAGE,
        EngineEventKind.USAGE,
    ]
    assert events[1].summary == "Write hello.py", "paths are workspace-relative"


def test_claude_invocation_is_isolated_and_restricted(root, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "worker-secret-should-not-leak")
    _run(_claude(root), _request(root, prompt="write hello"))
    record = _record(root, "claude_code")
    argv, env = record["argv"], record["env"]

    assert record["prompt"] == "write hello", "prompt goes over stdin"
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit,Glob,Grep,Skill"
    assert argv[argv.index("--allowedTools") + 1] == "Write,Edit,Skill"
    assert not any(t in argv[argv.index("--allowedTools") + 1].split(",") for t in ("Read", "Glob", "Grep"))
    assert "Bash" in argv[argv.index("--disallowedTools") + 1]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--strict-mcp-config" in argv
    assert env["CLAUDE_CONFIG_DIR"].endswith("engine-home/claude_code/.claude")
    assert env["ANTHROPIC_API_KEY"] == "test-key-123456"
    assert "JWT_SECRET" not in env and "DB_URL" not in env


def test_claude_removes_planted_workspace_settings(root):
    project = root / "job" / "project"
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text('{"hooks": {"Stop": []}}')
    (project / ".mcp.json").write_text("{}")

    _run(_claude(root), _request(root))

    assert not (project / ".claude" / "settings.json").exists()
    assert not (project / ".mcp.json").exists()


def test_claude_copies_credentials_only_without_api_key(root, tmp_path):
    credentials = tmp_path / "creds.json"
    credentials.write_text('{"token": "x"}')

    _run(_claude(root, api_key=None, credentials_file=str(credentials)), _request(root))

    copied = root / "job" / "state" / "engine-home" / "claude_code" / ".claude" / ".credentials.json"
    assert copied.read_text() == '{"token": "x"}'
    assert oct(copied.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize(
    ("mode", "status", "reason"),
    [
        ("auth", EngineStatus.CLI_ERROR, EngineErrorReason.AUTH),
        ("max_turns", EngineStatus.LIMIT_EXCEEDED, EngineErrorReason.MAX_TURNS),
        ("crash", EngineStatus.CLI_ERROR, EngineErrorReason.CRASH),
    ],
)
def test_claude_failures_are_classified(root, mode, status, reason):
    result, _ = _run(_claude(root), _request(root, prompt=f"MODE={mode}"))

    assert (result.status, result.error_reason) == (status, reason)


def test_claude_output_flood_hits_the_limit(root):
    engine = _claude(root)
    engine.max_output_bytes = 200_000

    result, _ = _run(engine, _request(root, prompt="MODE=flood"))

    assert result.status == EngineStatus.LIMIT_EXCEEDED
    assert result.error_reason == EngineErrorReason.OUTPUT_LIMIT


def test_claude_cancel_terminates_the_run(root):
    engine = _claude(root)
    request = _request(root, prompt="MODE=sleep", timeout_s=30)

    async def scenario():
        task = asyncio.create_task(engine.run(request))
        await asyncio.sleep(1.0)
        assert await engine.cancel(request.invocation_id)
        return await task

    result = asyncio.run(scenario())

    assert result.status == EngineStatus.CANCELLED


def test_secrets_are_redacted_from_events_and_result(root):
    result, events = _run(_claude(root), _request(root, prompt="MODE=secret"))

    assert SECRET not in result.final_message
    assert all(SECRET not in event.summary for event in events)


def test_workdir_outside_the_root_is_rejected(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")

    with pytest.raises(WorkspaceViolation):
        asyncio.run(_claude(root).run(_request(root, workdir=outside)))


def test_recorded_real_claude_stream_parses():
    parser = ClaudeStreamParser(max_turns=4)
    events = [e for line in (FIXTURES / "claude_stream_ok.jsonl").read_text().splitlines() for e in parser.feed(line)]

    assert parser.run.completed and not parser.run.is_error
    assert parser.run.turns == 2
    assert parser.run.usage.cost_usd > 0
    assert any(e.kind == EngineEventKind.TOOL_USE and e.data["tool"] == "Write" for e in events)


def test_antigravity_success_is_normalized(root):
    result, events = _run(_agy(root), _request(root))

    assert result.status == EngineStatus.OK
    assert result.session_id == "c-1"
    assert result.usage.input_tokens == 140 and result.usage.output_tokens == 25
    assert result.usage.cost_usd is None, "agy reports tokens only"
    assert result.changed_files == ["hello.py"]
    assert [e.summary for e in events if e.kind == EngineEventKind.MESSAGE] == ["Created hello.py."]
    assert any(e.summary == "write_file hello.py" for e in events)


def test_antigravity_invocation_uses_stream_stdin_and_api_key_settings(root):
    _run(_agy(root), _request(root, prompt="write hello"))
    record = _record(root, "antigravity")
    argv = record["argv"]

    assert record["prompt"] == "write hello"
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[argv.index("--print-timeout") + 1] == "10s"
    assert record["settings"]["modelProvider"] == "gemini"
    expected_allow = [
        f"read_file({(root / 'job' / 'project').resolve()})",
        f"write_file({(root / 'job' / 'project').resolve()})",
    ]
    assert record["settings"]["permissions"]["allow"] == expected_allow
    assert "read_file(*)" not in record["settings"]["permissions"]["allow"]
    assert "command(*)" in record["settings"]["permissions"]["deny"]
    assert record["env"]["GEMINI_API_KEY"] == "gemini-test-key-123"


def test_antigravity_auth_failure_is_classified(root):
    result, _ = _run(_agy(root), _request(root, prompt="MODE=auth"))

    assert (result.status, result.error_reason) == (EngineStatus.CLI_ERROR, EngineErrorReason.AUTH)


def test_antigravity_turn_limit_stops_the_run(root):
    result, _ = _run(_agy(root), _request(root, prompt="MODE=many_turns", max_turns=2))

    assert (result.status, result.error_reason) == (EngineStatus.LIMIT_EXCEEDED, EngineErrorReason.MAX_TURNS)
    assert result.duration_ms < 1500


@pytest.mark.parametrize(
    ("factory", "skills_dir", "context_file"),
    [(_claude, ".claude/skills", "CLAUDE.md"), (_agy, ".agents/skills", "AGENTS.md")],
)
def test_prepare_workspace_installs_skill_and_conventions(root, tmp_path, factory, skills_dir, context_file):
    skill = tmp_path / "skills" / "fastapi-skills"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: fastapi-skills\n---\n")
    workdir = root / "job" / "project"

    asyncio.run(factory(root).prepare_workspace(workdir, EngineContext(conventions="RULES", skill_dirs=[skill])))

    assert (workdir / skills_dir / "fastapi-skills" / "SKILL.md").exists()
    assert "RULES" in (workdir / context_file).read_text()


def test_antigravity_account_login_is_host_only(root, monkeypatch):
    from src.engines.antigravity import engine as agy_module

    engine = _agy(root, auth="account")
    monkeypatch.setattr(agy_module, "_in_container", lambda: False)
    assert asyncio.run(engine.health()).available

    monkeypatch.setattr(agy_module, "_in_container", lambda: True)
    health = asyncio.run(engine.health())
    assert not health.available and "GEMINI_API_KEY" in health.reason


def test_antigravity_account_invocation_keeps_the_real_home(root, tmp_path, monkeypatch):
    request = _request(root)
    request.workdir.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    monkeypatch.setenv("HOME", str(tmp_path / "user"))

    invocation = _agy(root, auth="account").build_invocation(request, home, 5, 60)

    settings = json.loads(invocation.argv[invocation.argv.index("--settings") + 1])
    assert invocation.env["HOME"] == str(tmp_path / "user")
    assert not (home / ".gemini").exists() and not (tmp_path / "user" / ".gemini").exists()
    assert "GEMINI_API_KEY" not in invocation.env and "modelProvider" not in settings
    assert settings["permissions"]["deny"][0] == "command(*)"
    expected_allow = [f"read_file({request.workdir.resolve()})", f"write_file({request.workdir.resolve()})"]
    assert settings["permissions"]["allow"] == expected_allow


def test_antigravity_adc_invocation_scopes_allow_rules(root):
    request = _request(root)
    request.workdir.mkdir(parents=True, exist_ok=True)
    home = root / "home_adc"

    engine = AntigravityEngine(
        binary="agy",
        auth="adc",
        gemini_api_key=None,
        google_application_credentials="/creds.json",
        model=None,
        **_limits(root),
    )
    invocation = engine.build_invocation(request, home, 5, 60)
    settings = json.loads((home / ".gemini" / "antigravity-cli" / "settings.json").read_text())
    expected_allow = [f"read_file({request.workdir.resolve()})", f"write_file({request.workdir.resolve()})"]
    assert settings["permissions"]["allow"] == expected_allow
    assert "read_file(*)" not in settings["permissions"]["allow"]
    assert invocation.env["AGY_ADC_AUTH"] == "true"


def test_registry_gives_antigravity_its_own_limits(tmp_path):
    from src.configs.config import Config
    from src.engines.registry import build_engine_registry

    cfg = Config(workspace_root=str(tmp_path), engine_max_turns=40, antigravity_max_turns=150)
    registry = build_engine_registry(cfg)

    assert registry.get("claude_code").default_max_turns == 40
    assert registry.get("antigravity").default_max_turns == 150
    assert registry.get("antigravity").default_timeout_s == cfg.antigravity_timeout_seconds
    assert registry.get("claude_code").model == "claude-sonnet-5-5"
    assert registry.get("antigravity").model == "gemini-3.8-flash-medium"
    assert registry.get("antigravity").purpose_models == {"generate_assets": "gemini-3.8-flash-low"}
    assert registry.get("claude_code").purpose_models == {}


def test_configured_model_is_passed_to_the_cli(root):
    request = _request(root)
    request.workdir.mkdir(parents=True, exist_ok=True)

    agy = _agy(root, auth="account", model="gemini-3.8-flash-medium").build_invocation(request, root / "h1", 5, 60)
    claude = _claude(root, model="claude-sonnet-5-5").build_invocation(request, root / "h2", 5, 60)

    assert agy.argv[agy.argv.index("--model") + 1] == "gemini-3.8-flash-medium"
    assert claude.argv[claude.argv.index("--model") + 1] == "claude-sonnet-5-5"


def test_purpose_model_selection_and_request_override(root):
    agy_engine = _agy(
        root,
        auth="account",
        model="gemini-3.8-flash-medium",
        purpose_models={"generate_assets": "gemini-3.8-flash-low"},
    )
    claude_engine = _claude(
        root,
        model="claude-sonnet-5-5",
        purpose_models={"generate_assets": "claude-haiku-4-5"},
    )

    # 1. generate_assets uses purpose model
    req_assets = _request(root, purpose="generate_assets")
    agy_assets = agy_engine.build_invocation(req_assets, root / "h1", 5, 60)
    claude_assets = claude_engine.build_invocation(req_assets, root / "h2", 5, 60)
    assert agy_assets.argv[agy_assets.argv.index("--model") + 1] == "gemini-3.8-flash-low"
    assert agy_assets.parser.model == "gemini-3.8-flash-low"
    assert claude_assets.argv[claude_assets.argv.index("--model") + 1] == "claude-haiku-4-5"
    assert claude_assets.parser.model == "claude-haiku-4-5"

    # 2. Other purposes use default model
    req_custom = _request(root, purpose="generate_custom_component")
    agy_custom = agy_engine.build_invocation(req_custom, root / "h3", 5, 60)
    claude_custom = claude_engine.build_invocation(req_custom, root / "h4", 5, 60)
    assert agy_custom.argv[agy_custom.argv.index("--model") + 1] == "gemini-3.8-flash-medium"
    assert agy_custom.parser.model == "gemini-3.8-flash-medium"
    assert claude_custom.argv[claude_custom.argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert claude_custom.parser.model == "claude-sonnet-5-5"

    # 3. Explicit request.model wins over purpose model and default
    req_override = _request(root, purpose="generate_assets", model="gemini-explicit-model")
    agy_override = agy_engine.build_invocation(req_override, root / "h5", 5, 60)
    assert agy_override.argv[agy_override.argv.index("--model") + 1] == "gemini-explicit-model"
    assert agy_override.parser.model == "gemini-explicit-model"


def test_antigravity_purpose_model_run_records_model_and_usage(root):
    engine = _agy(
        root,
        model="gemini-3.8-flash-medium",
        purpose_models={"generate_assets": "gemini-3.8-flash-low"},
    )
    result, _ = _run(engine, _request(root, purpose="generate_assets"))

    assert result.status == EngineStatus.OK
    assert result.usage.model == "gemini-3.8-flash-low"
    assert len(result.model_calls) >= 1
    assert all(c.model == "gemini-3.8-flash-low" for c in result.model_calls)
    assert result.usage.cost_source == "estimated"
    assert result.usage.cost_usd is not None and result.usage.cost_usd > 0


# -- model calls and cost (Story 8.4) ---------------------------------------------------------------------------


def _parse(parser, name):
    for line in (FIXTURES / name).read_text().splitlines():
        parser.feed(line)
    return parser.run


def test_claude_model_calls_add_up_to_the_reported_session():
    run = _parse(ClaudeStreamParser(max_turns=4), "claude_stream_ok.jsonl")

    calls = run.model_calls
    assert [call.seq for call in calls] == [1, 2], "one call per message id, not per content block"
    assert sum(call.cost_usd for call in calls) == pytest.approx(run.usage.cost_usd, abs=1e-6)
    assert {call.cost_source for call in calls} == {"reported"}
    assert sum(call.output_tokens for call in calls) == run.usage.output_tokens, "partial counts are scaled"
    assert sum(call.input_tokens for call in calls) == run.usage.input_tokens
    assert calls[0].model.startswith("claude-haiku-4-5") and calls[0].duration_ms > 0
    [write] = calls[0].tools
    assert (write.name, write.target) == ("Write", "/work/project/hello.py") and write.ended_at >= write.started_at


def test_antigravity_model_calls_are_estimated_from_the_price_table():
    from src.engines.antigravity.stream import AntigravityStreamParser

    run = _parse(AntigravityStreamParser(150, "gemini-3.8-flash-medium", prices=None), "agy_stream_ok.jsonl")

    calls = run.model_calls
    assert len(calls) == 5 and {call.latency_source for call in calls} == {"reported"}
    assert sum(call.input_tokens for call in calls) == run.usage.input_tokens == 18188 + 28038
    assert calls[0].duration_ms == 6194 and calls[1].cache_read_tokens == 6386
    assert {call.cost_source for call in calls} == {"estimated"}
    assert (
        run.usage.cost_usd == pytest.approx(sum(call.cost_usd for call in calls))
        and run.usage.cost_source == "estimated"
    )
    assert [(t.name, t.target) for t in calls[0].tools] == [
        ("read_file", "/work/project/src/modules/shared/domain/entities/task_entity.py")
    ], "agy sends tool parameters as a Python repr"


def test_unknown_model_has_no_cost():
    from src.engines.antigravity.stream import AntigravityStreamParser

    run = _parse(AntigravityStreamParser(150, "gemini-4-argon-medium"), "agy_stream_ok.jsonl")

    assert all(call.cost_usd is None for call in run.model_calls) and run.usage.cost_usd is None


def test_price_table_matches_prefixes_and_takes_overrides(monkeypatch):
    from src.configs import config
    from src.engines.pricing import configured_prices, price_for

    monkeypatch.setattr(config, "model_prices", {"gemini-4-argon": {"input": 1.0, "output": 8.0}})
    prices = configured_prices()

    assert price_for("gemini-3.8-flash-medium", prices)["input"] == 0.75
    assert price_for("gemini-4-argon-medium", prices)["output"] == 8.0
    assert price_for("claude-sonnet-5-5", prices)["cache_read"] == 0.20
    assert price_for("mystery-model", prices) is None


def test_engine_result_carries_model_calls_with_workspace_relative_tools(root):
    result, _ = _run(_agy(root, model="gemini-3.8-flash-medium"), _request(root))

    [call, _] = result.model_calls
    assert (call.input_tokens, call.output_tokens, call.cache_read_tokens) == (100, 15, 40)
    assert [(tool.name, tool.target) for tool in call.tools] == [("write_file", "hello.py")]
    assert call.cost_source == "estimated" and result.usage.model == "gemini-3.8-flash-medium"
