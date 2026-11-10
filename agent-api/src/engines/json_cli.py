"""One-turn JSON answers from the CLIs (Story 24.1): `agy` (Antigravity) and `claude` (Claude Code).

Each step is one CLI process in an empty scratch directory: the prompt carries every input, the CLI may use no tool
(no file reads or writes, no terminal, no web, no MCP), and the answer is enforced with `--json-schema` (the same
schema the Gemini API gets as `responseJsonSchema`). The answer is read from the CLI's final result
(`structured_output`, else the response text) and checked against the schema in code by `LlmProvider.json`.

`agy` 1.5.2 (measured 2026-11-07): `--input-format stream-json --output-format stream-json --json-schema <file>`; the
final `result` event carries `structured_output`, and the schema is enforced through a `finish` step (not a tool the
permissions see). `--mode plan` has no effect with `--disable-slash-commands` (agy warns), so tools are refused by the
permissions instead. The prompt goes through stdin: an app draft prompt is larger than one argv string may be.

`claude` 2.1.x: `-p --output-format json --json-schema '<schema>' --tools ""`, the prompt on stdin, a fresh
`CLAUDE_CONFIG_DIR` (no user hooks, plugins or memory) and an empty working directory (no CLAUDE.md). `--bare` only
with an API key: it never reads the subscription (OAuth) login.

The account / subscription logins have no per-token cost: their calls are recorded with cost 0 (`account`).
"""

import asyncio
import json
import shutil
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from src.libs.redaction import Redactor

from .cli_engine import classify_error_text
from .llm import Image, LlmAnswer, LlmError, LlmProvider, parse_json_object
from .port import EngineErrorReason, EngineHealth, EngineStatus, ModelCall
from .pricing import configured_prices, estimate
from .process import ProcessSpec, SubprocessRunner, base_env
from .workspace import ensure_inside

DENY_ALL = ["command(*)", "read_url(*)", "execute_url(*)", "mcp(*)", "write_file(*)"]
SCHEMA_FILE = "answer.schema.json"
IMAGES_NOTE = (
    "\n\nThe images for this step are files in the current directory; open each one to look at it: {names}. "
    "Do not open any other file."
)


@dataclass
class CliOutcome:
    """What one CLI turn printed."""

    completed: bool = False
    text: str = ""
    structured: Any = None
    usage: dict[str, Any] = field(default_factory=dict)
    turns: int | None = None
    session_id: str | None = None
    error: str | None = None
    duration_s: float | None = None
    reported_cost: float | None = None
    tool_attempts: list[str] = field(default_factory=list)


@dataclass
class CliCall:
    argv: list[str]
    env: dict[str, str]
    stdin: bytes


class CliJsonProvider(LlmProvider):
    """Shared plumbing: scratch directory, schema file, images, the process, the answer and its usage."""

    engine_name: str = ""

    def __init__(
        self,
        *,
        binary: str,
        model: str | None,
        allowed_root: Path,
        redactor: Redactor,
        default_timeout_s: float,
        max_output_bytes: int,
        runner: SubprocessRunner | None = None,
    ):
        self.binary = binary
        self.model = model
        self.allowed_root = allowed_root
        self.redactor = redactor
        self.default_timeout_s = default_timeout_s
        self.max_output_bytes = max_output_bytes
        self.runner = runner or SubprocessRunner()
        self._cancels: dict[str, asyncio.Event] = {}

    @abstractmethod
    def call(
        self,
        prompt: str,
        schema: dict[str, Any] | None,
        scratch: Path,
        home: Path,
        images: bool,
        model: str | None,
        timeout_s: float,
    ) -> CliCall:
        pass

    @abstractmethod
    def parse(self, stdout: str) -> CliOutcome:
        pass

    @abstractmethod
    def cost(self, call: ModelCall, outcome: CliOutcome) -> None:
        """Sets the call's cost: 0 on an account / subscription login, else estimated or reported."""

    def redact_argv(self, argv: list[str]) -> list[str]:
        return list(argv)

    async def cancel(self, invocation_id: str) -> bool:
        self._cancels.setdefault(invocation_id, asyncio.Event()).set()
        return True

    async def answer(
        self,
        step: str,
        prompt: str,
        schema: dict[str, Any] | None,
        images: list[Image] | None,
        *,
        state_dir: Path,
        invocation_id: str,
        timeout_s: float | None,
        model: str | None,
    ) -> LlmAnswer:
        state_dir = ensure_inside(state_dir, self.allowed_root)
        scratch = state_dir / "llm" / invocation_id
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        home = state_dir / "engine-home" / self.name
        home.mkdir(parents=True, exist_ok=True)
        if images:
            names = []
            for index, image in enumerate(images):
                name = f"{index + 1}-{Path(image.name).name}"
                (scratch / name).write_bytes(image.data)
                names.append(name)
            prompt += IMAGES_NOTE.format(names=", ".join(names))
        timeout = timeout_s or self.default_timeout_s
        model = model or self.model
        started = datetime.now(UTC)
        notes: list[str] = []

        outcome = await self._turn(
            prompt, schema, scratch, home, bool(images), model, timeout, state_dir, invocation_id
        )
        structured: bool | None = None if schema is None else True
        # the CLI refused the schema, or gave up fitting the model's answer to it (`claude`'s
        # error_max_structured_output_retries, a socials draft on Haiku 2026-11-10): asked once without it, the answer
        # checked against the schema in code (`LlmProvider.json`)
        error = (outcome.error or "").lower()
        if schema is not None and not outcome.completed and ("schema" in error or "structured_output" in error):
            notes.append("the CLI refused the answer schema; asked without it")
            outcome = await self._turn(
                prompt, None, scratch, home, bool(images), model, timeout, state_dir, f"{invocation_id}-noschema"
            )
            structured = False
        calls = [self._model_call(outcome, model, started)] if outcome.usage or outcome.completed else []
        if outcome.tool_attempts:
            notes.append("the model tried tools (refused): " + ", ".join(sorted(set(outcome.tool_attempts))[:5]))
        if not outcome.completed:
            message = self.redactor.redact(outcome.error or "no final result")
            reason = classify_error_text(message)
            raise LlmError(f"{self.name}: {message[:500]}", reason, calls=calls, text=outcome.text[:500])
        if isinstance(outcome.structured, dict):
            data = outcome.structured
        else:
            try:
                data = parse_json_object(outcome.text)
            except ValueError as exc:
                raise LlmError(
                    f"answer was not JSON: {exc}; it began: {self.redactor.redact(outcome.text[:500])!r}",
                    calls=calls,
                    text=outcome.text[:500],
                ) from exc
        return LlmAnswer(
            data=data,
            text=outcome.text,
            calls=calls,
            structured=structured,
            duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            session_id=outcome.session_id,
            notes=notes,
        )

    async def _turn(
        self,
        prompt: str,
        schema: dict[str, Any] | None,
        scratch: Path,
        home: Path,
        images: bool,
        model: str | None,
        timeout: float,
        state_dir: Path,
        invocation_id: str,
    ) -> CliOutcome:
        call = self.call(prompt, schema, scratch, home, images, model, timeout)
        logs = state_dir / "logs"
        spec = ProcessSpec(
            argv=call.argv,
            cwd=scratch,
            env=call.env,
            stdin=call.stdin,
            stdout_path=logs / f"{invocation_id}.{self.engine_name}.stdout.log",
            stderr_path=logs / f"{invocation_id}.{self.engine_name}.stderr.log",
            timeout_s=timeout,
            max_output_bytes=self.max_output_bytes,
        )
        cancel = self._cancels.setdefault(invocation_id, asyncio.Event())
        try:
            result = await self.runner.run(spec, None, cancel)
        finally:
            self._cancels.pop(invocation_id, None)
        if result.cancelled:
            raise LlmError("cancelled", EngineErrorReason.CANCELLED, EngineStatus.CANCELLED)
        if result.timed_out:
            raise LlmError(f"no answer within {timeout:.0f} s", EngineErrorReason.TIMEOUT, EngineStatus.TIMEOUT)
        if result.output_limit_exceeded:
            raise LlmError("output limit exceeded", EngineErrorReason.OUTPUT_LIMIT, EngineStatus.LIMIT_EXCEEDED)
        stdout = spec.stdout_path.read_text(errors="replace") if spec.stdout_path.exists() else ""
        outcome = self.parse(stdout)
        if result.exit_code not in (0, None) and outcome.completed and not outcome.text and outcome.structured is None:
            outcome.completed = False
        if not outcome.completed and not outcome.error:
            stderr = spec.stderr_path.read_text(errors="replace")[-2000:] if spec.stderr_path.exists() else ""
            outcome.error = stderr.strip() or f"exit code {result.exit_code}, no final result"
        return outcome

    def _model_call(self, outcome: CliOutcome, model: str | None, started: datetime) -> ModelCall:
        usage = outcome.usage
        cache_read = int(usage.get("cache_read_tokens") or 0)
        cache_write = int(usage.get("cache_write_tokens") or 0)
        thinking = usage.get("thinking_tokens")
        ended = datetime.now(UTC)
        call = ModelCall(
            seq=1,
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0) + cache_read + cache_write,
            output_tokens=int(usage.get("output_tokens") or 0) + int(thinking or 0),
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            thinking_tokens=int(thinking) if thinking is not None else None,
            started_at=ended - timedelta(seconds=outcome.duration_s) if outcome.duration_s else started,
            ended_at=ended,
            latency_source="reported" if outcome.duration_s else "measured",
        )
        self.cost(call, outcome)
        return call


# -- agy ---------------------------------------------------------------------------------------------------------


class AgyJsonProvider(CliJsonProvider):
    name = "antigravity"
    engine_name = "antigravity_json"

    def __init__(
        self,
        *,
        auth: Literal["gemini_api_key", "adc", "account"],
        gemini_api_key: str | None,
        google_application_credentials: str | None,
        effort: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.auth = auth
        self.gemini_api_key = gemini_api_key
        self.google_application_credentials = google_application_credentials
        self.effort = effort
        self.redactor = self.redactor.with_secrets(gemini_api_key)

    async def health(self) -> EngineHealth:
        from .antigravity.engine import AntigravityEngine

        probe = AntigravityEngine(
            binary=self.binary,
            auth=self.auth,
            gemini_api_key=self.gemini_api_key,
            google_application_credentials=self.google_application_credentials,
            model=self.model,
            allowed_root=self.allowed_root,
            redactor=self.redactor,
            default_timeout_s=self.default_timeout_s,
            default_max_turns=1,
            max_output_bytes=self.max_output_bytes,
        )
        health = await probe.health()
        reason = "Drafts only (JSON)" + (f"; {health.reason}" if health.reason else "")
        return health.model_copy(
            update={"name": self.engine_name, "reason": reason, "drafts_only": True, "drafts": True}
        )

    def call(self, prompt, schema, scratch, home, images, model, timeout_s) -> CliCall:
        allow = [f"read_file({scratch.resolve()})"] if images else []
        deny = list(DENY_ALL) + ([] if images else ["read_file(*)"])
        settings: dict[str, Any] = {"permissions": {"allow": allow, "deny": deny}, "enableTerminalSandbox": True}
        if self.auth == "gemini_api_key":
            settings["modelProvider"] = "gemini"
        argv = [
            self.binary,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--print-timeout",
            f"{int(timeout_s)}s",
        ]
        if schema is not None:
            (scratch / SCHEMA_FILE).write_text(json.dumps(schema))
            argv += ["--json-schema", str((scratch / SCHEMA_FILE).resolve())]
        if model:
            argv += ["--model", model]
        if self.effort:
            argv += ["--effort", self.effort]
        if self.auth == "account":
            argv += ["--settings", json.dumps(settings)]  # the login lives in the real home (see AntigravityEngine)
            home = Path.home()
        else:
            settings_dir = home / ".gemini" / "antigravity-cli"
            settings_dir.mkdir(parents=True, exist_ok=True)
            (settings_dir / "settings.json").write_text(json.dumps(settings, indent=2))
        env = base_env(
            HOME=str(home),
            GEMINI_API_KEY=self.gemini_api_key if self.auth == "gemini_api_key" else None,
            AGY_ADC_AUTH="true" if self.auth == "adc" else None,
            GOOGLE_APPLICATION_CREDENTIALS=self.google_application_credentials if self.auth == "adc" else None,
        )
        message = {"event": "user", "message": {"content": prompt}}
        return CliCall(argv=argv, env=env, stdin=(json.dumps(message) + "\n").encode())

    def parse(self, stdout: str) -> CliOutcome:
        outcome = CliOutcome()
        texts: list[str] = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "init":
                outcome.session_id = event.get("conversation_id")
            elif event.get("event") == "step_update":
                step = event.get("step_update") or {}
                if step.get("step_type") == "agent_response" and step.get("text_delta"):
                    texts.append(step["text_delta"])
                if step.get("step_type") == "tool" and step.get("state") == "DONE":
                    name = (step.get("tool_info") or {}).get("name") or step.get("tool_name") or "?"
                    if name != "finish":
                        outcome.tool_attempts.append(name)
            elif event.get("event") == "result":
                result = event.get("result") or {}
                outcome.session_id = result.get("conversation_id") or outcome.session_id
                outcome.turns = result.get("num_turns")
                outcome.usage = result.get("usage") or {}
                outcome.duration_s = result.get("duration_seconds")
                outcome.structured = result.get("structured_output")
                outcome.text = result.get("response") or "".join(texts)
                if result.get("status", "SUCCESS") == "SUCCESS":
                    outcome.completed = True
                else:
                    outcome.error = str(result.get("error") or result.get("status"))
        if not outcome.text:
            outcome.text = "".join(texts)
        return outcome

    def cost(self, call: ModelCall, outcome: CliOutcome) -> None:
        if self.auth == "account":
            call.cost_usd, call.cost_source = 0.0, "account"
        else:
            estimate([call], configured_prices())


# -- claude ------------------------------------------------------------------------------------------------------


class ClaudeJsonProvider(CliJsonProvider):
    name = "claude_code"
    engine_name = "claude_code_json"

    def __init__(
        self,
        *,
        api_key: str | None,
        credentials_file: str | None,
        effort: str | None = None,
        max_budget_usd: float | None = None,
        oauth_token: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.oauth_token = oauth_token
        self.credentials_file = Path(credentials_file) if credentials_file else None
        self.effort = effort
        self.max_budget_usd = max_budget_usd
        self.redactor = self.redactor.with_secrets(api_key, oauth_token)

    async def health(self) -> EngineHealth:
        if shutil.which(self.binary) is None:
            return EngineHealth(
                name=self.engine_name,
                available=False,
                reason=f"'{self.binary}' not found on PATH",
                drafts_only=True,
                drafts=True,
            )
        if (
            not self.api_key
            and not self.oauth_token
            and not (self.credentials_file and self.credentials_file.is_file())
        ):
            return EngineHealth(
                name=self.engine_name,
                available=False,
                reason="Set ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN or CLAUDE_CREDENTIALS_FILE",
                drafts_only=True,
                drafts=True,
            )
        login = "API key" if self.api_key else "subscription"
        return EngineHealth(
            name=self.engine_name, available=True, reason=f"Drafts only (JSON), {login}", drafts_only=True, drafts=True
        )

    def call(self, prompt, schema, scratch, home, images, model, timeout_s) -> CliCall:
        config_dir = home / ".claude"
        config_dir.mkdir(parents=True, exist_ok=True)
        if not self.api_key and self.credentials_file and self.credentials_file.is_file():
            target = config_dir / ".credentials.json"
            shutil.copyfile(self.credentials_file, target)
            target.chmod(0o600)
        (home / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
        argv = [
            self.binary,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "Read" if images else "",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        if self.api_key:
            argv.append("--bare")  # reads ANTHROPIC_API_KEY only; never on the subscription login
            if self.max_budget_usd:
                argv += ["--max-budget-usd", str(self.max_budget_usd)]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema)]
        if model:
            argv += ["--model", model]
        if self.effort:
            argv += ["--effort", self.effort]
        env = base_env(
            HOME=str(home),
            CLAUDE_CONFIG_DIR=str(config_dir),
            ANTHROPIC_API_KEY=self.api_key,
            CLAUDE_CODE_OAUTH_TOKEN=None if self.api_key else self.oauth_token,
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
        )
        return CliCall(argv=argv, env=env, stdin=prompt.encode())

    def redact_argv(self, argv: list[str]) -> list[str]:
        out = list(argv)
        if "--json-schema" in out:
            out[out.index("--json-schema") + 1] = "<schema>"
        return out

    def parse(self, stdout: str) -> CliOutcome:
        outcome = CliOutcome()
        result: dict[str, Any] | None = None
        for line in reversed(stdout.strip().splitlines()):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("type") == "result":
                result = value
                break
        if result is None:
            try:
                value = json.loads(stdout)
                result = value if isinstance(value, dict) else None
            except ValueError:
                return outcome
        if result is None:
            return outcome
        usage = result.get("usage") or {}
        outcome.usage = {
            "input_tokens": usage.get("input_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or 0,
            "cache_read_tokens": usage.get("cache_read_input_tokens") or 0,
            "cache_write_tokens": usage.get("cache_creation_input_tokens") or 0,
        }
        outcome.turns = result.get("num_turns")
        outcome.session_id = result.get("session_id")
        outcome.duration_s = (result.get("duration_ms") or 0) / 1000 or None
        outcome.reported_cost = result.get("total_cost_usd")
        outcome.structured = result.get("structured_output")
        outcome.text = result.get("result") or ""
        outcome.tool_attempts = [
            str(denial.get("tool_name") or "?")
            for denial in result.get("permission_denials") or []
            if isinstance(denial, dict)
        ]
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            outcome.error = str(result.get("result") or result.get("subtype") or "error")
        else:
            outcome.completed = True
        return outcome

    def cost(self, call: ModelCall, outcome: CliOutcome) -> None:
        if not self.api_key:
            call.cost_usd, call.cost_source = 0.0, "account"
        elif outcome.reported_cost is not None:
            call.cost_usd, call.cost_source = round(float(outcome.reported_cost), 6), "reported"
        else:
            estimate([call], configured_prices())
