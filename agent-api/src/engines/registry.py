from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from src.configs import config as default_config
from src.libs.redaction import default_redactor

from .antigravity import AntigravityEngine
from .claude_code import ClaudeCodeEngine
from .fake_engine import FakeEngine, demo_scenario
from .port import EngineContext, EngineHealth, ICodeEngine
from .prompts import PromptLibrary
from .workspace import directory_sha256


class UnknownEngineError(LookupError):
    pass


class EngineRegistry:
    def __init__(self, engines: list[ICodeEngine], default: str):
        self.engines = {engine.name: engine for engine in engines}
        self.default = default

    def names(self) -> list[str]:
        return list(self.engines)

    def get(self, name: str | None = None) -> ICodeEngine:
        key = name or self.default
        if key not in self.engines:
            raise UnknownEngineError(f"Unknown engine '{key}'. Available: {', '.join(self.engines)}")
        return self.engines[key]

    async def health(self) -> list[EngineHealth]:
        return [await engine.health() for engine in self.engines.values()]


class SkillInfo(BaseModel):
    name: str
    path: Path
    sha256: str


def engine_skills(cfg=default_config, names: list[str] | None = None) -> list[SkillInfo]:
    root = Path(cfg.engine_skills_dir)
    return [
        SkillInfo(name=name, path=root / name, sha256=directory_sha256(root / name))
        for name in (cfg.engine_skills if names is None else names)
        if (root / name / "SKILL.md").is_file()
    ]


def build_engine_context(prompts: PromptLibrary, cfg=default_config) -> EngineContext:
    return EngineContext(conventions=prompts.conventions(), skill_dirs=[skill.path for skill in engine_skills(cfg)])


def build_frontend_engine_context(prompts: PromptLibrary, cfg=default_config) -> EngineContext:
    """The frontend lane's engine context: nextjs-skills and the frontend project rules (Story 13.2)."""
    skills = engine_skills(cfg, cfg.frontend_engine_skills)
    return EngineContext(conventions=prompts.frontend_conventions(), skill_dirs=[skill.path for skill in skills])


def build_engine_registry(cfg=default_config) -> EngineRegistry:
    root = Path(cfg.workspace_root)
    redactor = default_redactor()
    limits = {
        "allowed_root": root,
        "redactor": redactor,
        "default_timeout_s": cfg.engine_timeout_seconds,
        "default_max_turns": cfg.engine_max_turns,
        "max_output_bytes": cfg.engine_max_output_bytes,
    }
    engines: list[ICodeEngine] = [
        ClaudeCodeEngine(
            binary=cfg.claude_code_bin,
            api_key=cfg.anthropic_api_key,
            credentials_file=cfg.claude_credentials_file,
            model=cfg.claude_code_model,
            purpose_models=cfg.claude_code_purpose_models,
            **limits,
        ),
        AntigravityEngine(
            binary=cfg.antigravity_bin,
            auth=cfg.antigravity_auth,
            gemini_api_key=cfg.gemini_api_key,
            google_application_credentials=cfg.google_application_credentials,
            model=cfg.antigravity_model,
            purpose_models=cfg.antigravity_purpose_models,
            **{
                **limits,
                "default_timeout_s": cfg.antigravity_timeout_seconds,
                "default_max_turns": cfg.antigravity_max_turns,
            },
        ),
    ]
    if cfg.enable_fake_engine:
        engines.append(FakeEngine(allowed_root=root, scenario=demo_scenario(cfg.fake_engine_delay_seconds)))
    return EngineRegistry(engines, default=cfg.default_engine)


@lru_cache
def get_engine_registry() -> EngineRegistry:
    return build_engine_registry()
