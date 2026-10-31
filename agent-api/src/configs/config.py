from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_JWT_SECRET = "change-me-to-a-long-random-string"


class Config(BaseSettings):
    app_name: str = "Fullstack Generation Agent"
    port: int = 8000
    log_level: str = "INFO"

    db_url: str
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    auth_cookie_name: str = "bga_token"
    seed_users: str = ""

    cors_origins: str = "http://localhost:3100"
    rate_limit_storage_uri: str = "memory://"
    rate_limit_login: str = "10/minute"

    spec_max_bytes: int = 1_000_000
    frontend_import_max_bytes: int = 5_000_000
    # Requirement drafting (Stories 2.4, 12.4): plain text or Markdown, typed or from a .md / .txt file.
    requirement_max_bytes: int = 65_536
    draft_repair_attempts_backend: int = 1
    draft_repair_attempts_frontend: int = 2
    draft_concurrency: int = 2  # drafts per worker, on top of WORKER_CONCURRENCY generations
    draft_stale_seconds: int = 120  # a running draft without a heartbeat this long is failed
    draft_pending_timeout_seconds: int = 1800  # a draft no worker picked up this long is failed

    default_engine: str = "claude_code"
    enable_fake_engine: bool = True
    fake_engine_delay_seconds: float = 0.3
    engine_timeout_seconds: int = 900
    engine_max_turns: int = 40
    engine_max_output_bytes: int = 20_000_000
    engine_concurrency: int = 3  # parallel custom component generation (Story 17.3)
    engine_skills_dir: str = "/opt/bga/skills"
    # Example specs (repo `examples/`): drafting references and the fake engine's draft fixtures.
    examples_dir: str = "/opt/bga/examples"
    engine_skills: list[str] = ["fastapi-skills"]
    frontend_engine_skills: list[str] = ["nextjs-skills"]  # installed into the frontend workspace (Story 13.2)

    claude_code_bin: str = "claude"
    claude_code_model: str = "claude-sonnet-5-5"
    claude_code_purpose_models: dict[str, str] = {}
    anthropic_api_key: str | None = None
    claude_credentials_file: str | None = None

    antigravity_bin: str = "agy"
    antigravity_model: str = "gemini-3.8-flash-medium"  # `agy models` lists the choices
    antigravity_purpose_models: dict[str, str] = {"generate_assets": "gemini-3.8-flash-low"}
    # agy streams one agent response per tool call, so its "turns" are much smaller than Claude's.
    antigravity_max_turns: int = 150
    antigravity_timeout_seconds: int = 2400
    antigravity_job_timeout_seconds: int = 10800  # a full agy run takes far longer than the 30 min default
    antigravity_auth: Literal["gemini_api_key", "adc", "account"] = "gemini_api_key"
    gemini_api_key: str | None = None
    google_application_credentials: str | None = None

    # USD per 1M tokens, merged over src/engines/pricing.py DEFAULT_PRICES, e.g.
    # {"gemini-4-argon": {"input": 1.25, "output": 10, "cache_read": 0.125}}. A model without a price has no cost.
    model_prices: dict[str, dict[str, float]] = {}

    workspace_root: str = "/tmp/bga/workspaces"
    workspace_max_mb: int = 500
    workspace_retention_hours: int = 72

    template_dir: str = "/opt/bga/fastapi-template"

    sandbox_enabled: bool = True
    sandbox_image: str = "bga-runner:1"
    sandbox_db_image: str = "postgres:18"
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_pids: int = 256
    sandbox_command_timeout_seconds: int = 300
    sandbox_output_bytes: int = 2_000_000
    sandbox_egress_network: str = "bga-sbx-egress"
    # Frontend sandbox (Story 13.4): Node runner, no database; Next.js builds need more memory than pytest.
    frontend_sandbox_image: str = "bga-runner-node:1"
    frontend_sandbox_cpus: float = 2.0
    frontend_sandbox_memory: str = "3g"
    frontend_sandbox_pids: int = 1024
    frontend_sandbox_tmp: str = "1g"
    # Shared pnpm store (named volume, filled from the runner image on first use), so installs run offline. The
    # volume is `<this>-<base lock key>`, so a new frontend base starts from a store that has its packages.
    frontend_store_volume: str = "bga-pnpm-store"
    # Story 17.5: one ready node_modules per dependency set (volume `bga-fe-modules-<key>`), mounted read-only, so
    # a frontend does not copy ~1 GB out of the store on every generation. Off: each project installs its own.
    frontend_shared_modules: bool = True
    # Story 18.1: isolated component render-test timeout (the whole site's unit tests take ~5 s).
    frontend_component_test_timeout_seconds: int = 60

    generator_version: str = "0.8.0"
    # Shared by worker (writes) and API (downloads); outlives workspaces.
    artifact_root: str = "/tmp/bga/artifacts"
    # Site images (Epic 15): generated SVGs per job before the validator warns, repairs before a drawing falls back
    # to its placeholder.
    frontend_max_generated_assets: int = 12
    frontend_asset_repair_limit: int = 1
    # Uploads (Story 15.4): where the API stores them (the worker only reads them), per file and per user limits,
    # and how long an upload no generation uses is kept. Empty: `<ARTIFACT_ROOT>/uploads`.
    upload_root: str = ""
    upload_max_mb: int = 5
    upload_quota_mb: int = 200
    upload_retention_days: int = 30

    # Preview containers (Epic 7): each COMPLETED backend runs as its own container, local-only.
    preview_enabled: bool = True
    preview_port_range: str = "18000-18099"
    preview_bind_host: str = "127.0.0.1"
    preview_public_host: str = "localhost"
    preview_cors_origins: str = "http://localhost:3100"
    preview_max_running: int = 3
    preview_evict: bool = True
    preview_ttl_hours: float = 2
    preview_cpus: float = 1.0
    preview_memory: str = "512m"
    preview_build_timeout_seconds: int = 600
    preview_health_timeout_seconds: int = 60
    preview_reconcile_seconds: int = 300
    preview_command_timeout_seconds: float = 8  # API waiting for the worker (logs); below the Redis socket timeout
    # Dynamic integration (Story 14.2): how long `integrate` waits for the backend lane and its preview before
    # keeping the frontend on its mock API.
    integration_wait_seconds: float = 180

    # LangSmith tracing (Epic 8). Off unless LANGSMITH_TRACING=true and a key is set; the local trace (node runs,
    # CLI invocations, model calls, checks) is recorded either way. LANGSMITH_AGENT_ID (beta, enabled per
    # workspace) sends traces to that agent's environment instead of LANGSMITH_PROJECT.
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "fullstack-generation-agent"
    langsmith_agent_id: str | None = None
    langsmith_agent_environment: str = "local"
    # Model calls and sandbox records of generations finished longer ago are deleted (0 = keep). LangSmith's
    # own retention is a setting of the LangSmith project.
    trace_retention_days: int = 30

    job_timeout_seconds: int = 1800
    worker_lease_ttl_seconds: int = 30
    worker_max_resumes: int = 2
    worker_shutdown_grace_seconds: int = 60
    reaper_interval_seconds: int = 60
    events_cap: int = 5000
    checkpoint_schema: str = "langgraph"
    worker_concurrency: int = 2
    worker_heartbeat_file: str = "/tmp/bga-worker.heartbeat"
    worker_heartbeat_seconds: int = 10
    # Engines this worker runs (comma-separated; empty = all registered). `make up` gives Antigravity's account
    # login to a host worker, because the login lives in the desktop keyring that containers cannot reach.
    worker_engines: str = ""
    # Whether this worker drives preview containers (commands, TTL, reconcile); only one kind of worker should.
    preview_worker: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("langsmith_api_key", "langsmith_agent_id", mode="before")
    @classmethod
    def _blank_is_unset(cls, value):
        return value or None

    @field_validator("claude_code_model", "antigravity_model", mode="before")
    @classmethod
    def _blank_model_means_default(cls, value, info):
        # Compose passes `CLAUDE_CODE_MODEL=` when .env leaves it empty; that means "the default", not "none".
        return cls.model_fields[info.field_name].default if value in (None, "") else value

    @field_validator("claude_code_purpose_models", "antigravity_purpose_models", "model_prices", mode="before")
    @classmethod
    def _parse_dict_or_default(cls, value, info):
        if value in (None, ""):
            return cls.model_fields[info.field_name].default
        if isinstance(value, str):
            import json

            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else cls.model_fields[info.field_name].default
            except Exception:
                return cls.model_fields[info.field_name].default
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _reject_weak_jwt_secret(cls, value: str) -> str:
        if not value or value == EXAMPLE_JWT_SECRET or len(value) < 32:
            raise ValueError("JWT_SECRET must be set to a random string of at least 32 characters")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def worker_engine_list(self) -> list[str]:
        return [name.strip() for name in self.worker_engines.split(",") if name.strip()]

    @property
    def preview_ports(self) -> range:
        low, _, high = self.preview_port_range.partition("-")
        return range(int(low), int(high or low) + 1)


def uploads_dir() -> str:
    """Where uploads live (Story 15.4)."""
    return config.upload_root or f"{config.artifact_root.rstrip('/')}/uploads"


config = Config()
