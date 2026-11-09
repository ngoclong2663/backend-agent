"""Story 22.8: drafting is API-only. A spec draft runs on an engine that drafts (the Gemini API engine, or the fake
for tests and demos); the CLI engines write code only. On Antigravity a draft call was 16-22 model turns and
0.4-0.8M input tokens (each turn re-sends what it read); the API engine sends one request of ~6K tokens."""

from src.engines import EngineRegistry
from src.engines.fake_engine import FakeEngine
from src.engines.gemini_api import GeminiApiEngine
from src.engines.port import ICodeEngine
from src.libs.redaction import Redactor


class CliEngine(ICodeEngine):
    """A stand-in for a CLI code engine (Claude Code, Antigravity): writes code, never drafts."""

    name = "cli"

    async def health(self):  # pragma: no cover - not called
        raise NotImplementedError

    async def prepare_workspace(self, workdir, context):  # pragma: no cover
        raise NotImplementedError

    async def run(self, request, on_event=None):  # pragma: no cover
        raise NotImplementedError

    async def cancel(self, invocation_id):  # pragma: no cover
        raise NotImplementedError


def _registry(tmp_path, *names: str, default: str = "cli", draft_default: str | None = None) -> EngineRegistry:
    made = {
        "cli": lambda: CliEngine(),
        "fake": lambda: FakeEngine(tmp_path),
        "gemini_api": lambda: GeminiApiEngine(
            api_key="test-key", model="gemini-test", allowed_root=tmp_path, redactor=Redactor()
        ),
    }
    return EngineRegistry([made[name]() for name in names], default=default, draft_default=draft_default)


def test_only_api_engines_and_the_fake_draft(tmp_path):
    registry = _registry(tmp_path, "cli", "fake", "gemini_api", draft_default="cli")
    assert registry.draft_engine_names() == ["fake", "gemini_api"]
    assert registry.draft_default == "gemini_api", "a CLI draft default falls back to the API engine"
    assert registry.code_engine_names() == ["cli", "fake"]


def test_without_an_api_engine_nothing_but_the_fake_drafts(tmp_path):
    assert _registry(tmp_path, "cli", "fake").draft_default == "fake"
    assert _registry(tmp_path, "cli").draft_default is None


def test_a_cli_draft_engine_is_refused_with_the_reason(tmp_path):
    import pytest

    from src.libs.exceptions import UnprocessableEntityException

    registry = _registry(tmp_path, "cli", "gemini_api")
    assert registry.check_draft_engine("gemini_api") == "gemini_api"
    with pytest.raises(UnprocessableEntityException, match="writes code only; drafts run in one turn on a JSON engine"):
        registry.check_draft_engine("cli")
    with pytest.raises(UnprocessableEntityException, match="set LLM_PROVIDER"):
        _registry(tmp_path, "cli").check_draft_engine(None)


def test_the_api_refuses_a_cli_draft_engine(client, user_headers):
    response = client.post(
        "/api/v1/spec-drafts",
        json={"engine": "claude_code", "mode": "backend", "requirementText": "A tracker for projects and tasks."},
        headers=user_headers,
    )
    assert response.status_code == 422, response.text
    assert "writes code only" in response.json()["error"]["message"]
    one_click = client.post(
        "/api/v1/generations",
        json={
            "mode": "backend",
            "requirement": {"text": "A tracker for projects and tasks.", "format": "text"},
            "options": {"engine": "fake", "draftEngine": "antigravity"},
        },
        headers=user_headers,
    )
    assert one_click.status_code == 422 and "writes code only" in one_click.json()["error"]["message"]


def test_the_engine_list_says_which_engines_draft(client, user_headers):
    engines = {
        engine["name"]: engine for engine in client.get("/api/v1/engines", headers=user_headers).json()["engines"]
    }
    assert engines["fake"]["drafts"] is True
    assert all(not engines[name]["drafts"] for name in ("claude_code", "antigravity") if name in engines)


def test_one_switch_moves_generation_drafts_and_the_llm_steps_together():
    """DEFAULT_ENGINE alone picks every engine: `claude_code` drafts on `claude_code_json` and runs the LLM-only steps
    on `claude_code`, `antigravity` on `antigravity_json` / `antigravity`, even with a Gemini key in the env; the
    explicit DRAFT_ENGINE / LLM_PROVIDER stay as overrides; an engine without a drafting twin keeps the old fallback."""
    from src.configs.config import Config

    base = {"db_url": "postgresql+psycopg://u:p@localhost/db", "jwt_secret": "x" * 40, "gemini_api_key": "key"}
    for engine, drafts in (("claude_code", "claude_code_json"), ("antigravity", "antigravity_json")):
        cfg = Config(**base, default_engine=engine)
        assert (cfg.draft_engine_name, cfg.llm_provider_name) == (drafts, engine)
        assert cfg.fast_draft_models.get(engine), "a fast drafting model of its own"
    pinned = Config(**base, default_engine="claude_code", llm_provider="antigravity")
    assert (pinned.draft_engine_name, pinned.llm_provider_name) == ("antigravity_json", "antigravity")
    assert Config(**base, default_engine="claude_code", draft_engine="gemini_api").draft_engine_name == "gemini_api"
    assert Config(**base, default_engine="fake").draft_engine_name == "gemini_api", "no twin: the API engine"
