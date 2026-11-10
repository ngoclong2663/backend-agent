import asyncio
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from src.configs import get_logger
from src.libs.redaction import Redactor

from .port import (
    EngineErrorReason,
    EngineEvent,
    EngineRequest,
    EngineResult,
    EngineStatus,
    EngineUsage,
    ICodeEngine,
    ModelCall,
    OnEngineEvent,
    ToolCall,
)
from .pricing import Price, configured_prices
from .process import ProcessOutcome, ProcessSpec, SubprocessRunner
from .workspace import changed_files, ensure_inside, snapshot

logger = get_logger(__name__)
MAX_TOOL_SPANS = 200


@dataclass
class ParsedRun:
    """What a stream parser learned from the CLI's output; folded into the normalized EngineResult."""

    completed: bool = False
    is_error: bool = False
    error_reason: EngineErrorReason | None = None
    error_message: str | None = None
    turns: int | None = None
    usage: EngineUsage | None = None
    session_id: str | None = None
    final_message: str | None = None
    turn_limit_hit: bool = False
    events: list[EngineEvent] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    tools_dropped: int = 0


class StreamParser:
    def __init__(self, max_turns: int | None, model: str | None = None, prices: Mapping[str, Price] | None = None):
        self.max_turns = max_turns
        self.model = model  # the configured model, for CLIs whose stream does not name it
        self.prices = prices
        self.run = ParsedRun()
        self._tools = 0

    @abstractmethod
    def feed(self, line: str) -> list[EngineEvent]:
        """Parses one stdout line; set `self.run.turn_limit_hit` to stop the process."""

    def price_table(self) -> Mapping[str, Price]:
        return self.prices if self.prices is not None else configured_prices()

    def add_tool(self, call: ModelCall, tool: ToolCall) -> ToolCall | None:
        """Tool spans are sampled to MAX_TOOL_SPANS per invocation (Story 8.2); the rest are only counted."""
        self._tools += 1
        if self._tools > MAX_TOOL_SPANS:
            self.run.tools_dropped += 1
            return None
        call.tools.append(tool)
        return tool


@dataclass
class Invocation:
    argv: list[str]
    env: dict[str, str]
    stdin: bytes | None
    parser: StreamParser


class CliEngine(ICodeEngine):
    """Shared plumbing for CLI engines: path guard, isolation, limits, event streaming, normalized result."""

    def __init__(
        self,
        allowed_root: Path,
        redactor: Redactor,
        default_timeout_s: float,
        default_max_turns: int,
        max_output_bytes: int,
        runner: SubprocessRunner | None = None,
    ):
        self.allowed_root = allowed_root
        self.redactor = redactor
        self.default_timeout_s = default_timeout_s
        self.default_max_turns = default_max_turns
        self.max_output_bytes = max_output_bytes
        self.runner = runner or SubprocessRunner()
        self._cancels: dict[str, asyncio.Event] = {}

    @abstractmethod
    def build_invocation(self, request: EngineRequest, home: Path, max_turns: int, timeout_s: float) -> Invocation:
        pass

    @abstractmethod
    def redact_argv(self, argv: list[str]) -> list[str]:
        pass

    async def cancel(self, invocation_id: str) -> bool:
        # setdefault, not get: a cancel that lands just before run() registers the invocation must not be lost.
        self._cancels.setdefault(invocation_id, asyncio.Event()).set()
        return True

    async def run(self, request: EngineRequest, on_event: OnEngineEvent | None = None) -> EngineResult:
        workdir = ensure_inside(request.workdir, self.allowed_root)
        state_dir = ensure_inside(request.state_dir, self.allowed_root)
        home = state_dir / "engine-home" / self.name
        home.mkdir(parents=True, exist_ok=True)
        logs = state_dir / "logs"
        max_turns = request.max_turns or self.default_max_turns
        timeout_s = request.timeout_s or self.default_timeout_s

        invocation = self.build_invocation(request, home, max_turns, timeout_s)
        parser = invocation.parser
        spec = ProcessSpec(
            argv=invocation.argv,
            cwd=workdir,
            env=invocation.env,
            stdin=invocation.stdin,
            stdout_path=logs / f"{request.invocation_id}.{self.name}.stdout.log",
            stderr_path=logs / f"{request.invocation_id}.{self.name}.stderr.log",
            timeout_s=timeout_s,
            max_output_bytes=self.max_output_bytes,
        )

        prefix = f"{workdir}/"

        def clean(value):
            # Events go to the UI and traces: workspace-relative paths, no secrets.
            if isinstance(value, str):
                return self.redactor.redact(value.replace(prefix, ""))
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value

        async def on_line(line: str) -> bool:
            for event in parser.feed(line):
                if on_event is not None:
                    await on_event(
                        event.model_copy(update={"summary": clean(event.summary), "data": clean(event.data)})
                    )
            return parser.run.turn_limit_hit

        before = snapshot(workdir)
        cancel = self._cancels.setdefault(request.invocation_id, asyncio.Event())
        try:
            outcome = await self.runner.run(spec, on_line, cancel)
        finally:
            self._cancels.pop(request.invocation_id, None)
        after = snapshot(workdir)

        result = self._normalize(request, parser.run, outcome, spec)
        result.changed_files = changed_files(before, after)
        for call in result.model_calls:
            for tool in call.tools:
                tool.target = clean(tool.target)
        logger.info(
            "engine run finished",
            extra={
                "engine": self.name,
                "purpose": request.purpose,
                "invocation_id": request.invocation_id,
                "status": result.status,
                "duration_ms": result.duration_ms,
            },
        )
        return result

    def _normalize(self, request: EngineRequest, parsed: ParsedRun, outcome: ProcessOutcome, spec: ProcessSpec):
        status, reason, message = EngineStatus.OK, None, None
        if outcome.cancelled:
            status, reason = EngineStatus.CANCELLED, EngineErrorReason.CANCELLED
        elif outcome.timed_out:
            status, reason = EngineStatus.TIMEOUT, EngineErrorReason.TIMEOUT
        elif outcome.output_limit_exceeded:
            status, reason = EngineStatus.LIMIT_EXCEEDED, EngineErrorReason.OUTPUT_LIMIT
        elif outcome.stopped_by_callback or parsed.error_reason == EngineErrorReason.MAX_TURNS:
            status, reason = EngineStatus.LIMIT_EXCEEDED, EngineErrorReason.MAX_TURNS
        elif parsed.is_error:
            status, reason, message = (
                EngineStatus.CLI_ERROR,
                parsed.error_reason or EngineErrorReason.CRASH,
                parsed.error_message,
            )
        elif outcome.exit_code != 0 or not parsed.completed:
            status, reason = EngineStatus.CLI_ERROR, self.classify_stderr(spec.stderr_path)
            message = f"exit code {outcome.exit_code}" + ("" if parsed.completed else ", no final result event")

        return EngineResult(
            invocation_id=request.invocation_id,
            engine=self.name,
            purpose=request.purpose,
            status=status,
            error_reason=reason,
            error_message=self.redactor.redact(message) if message else None,
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
            turns=parsed.turns,
            usage=parsed.usage,
            session_id=parsed.session_id,
            final_message=self.redactor.redact(parsed.final_message) if parsed.final_message else None,
            argv_redacted=[self.redactor.redact(arg) for arg in self.redact_argv(spec.argv)],
            stdout_ref=str(spec.stdout_path),
            stderr_ref=str(spec.stderr_path),
            prompt_ref=request.prompt_ref,
            model_calls=parsed.model_calls,
            tools_dropped=parsed.tools_dropped,
        )

    @staticmethod
    def classify_stderr(path: Path) -> EngineErrorReason:
        text = path.read_text(errors="replace")[-4000:].lower() if path.exists() else ""
        return classify_error_text(text)


def classify_error_text(text: str) -> EngineErrorReason:
    text = text.lower()
    if any(hint in text for hint in ("authentication", "api key", "/login", "unauthorized", "401", "log in")):
        return EngineErrorReason.AUTH
    if any(hint in text for hint in ("rate limit", "rate_limit", "429", "overloaded", "quota", "resource_exhausted")):
        return EngineErrorReason.RATE_LIMIT
    return EngineErrorReason.CRASH


# A model call that never got its answer: the network or the provider's API failed, not the engine's work. agy, for
# one, ends a run with `API error (attempt 1): request failed: Post "…": read tcp …: read: operation timed out` when a
# call drops, even after the model has written its files and its summary.
NETWORK_HINTS = (
    "request failed",
    "timed out",
    "connection reset",
    "connection refused",
    "broken pipe",
    "unexpected eof",
    "tls handshake",
    "no such host",
    "deadline exceeded",
    "service unavailable",
    "socket hang up",
    "econnreset",
    " 502 ",
    " 503 ",
    " 504 ",
)


def is_network_failure(result: EngineResult) -> bool:
    """Whether a failed run died on the network or the provider's API (worth running once more), not on its work."""
    if result.status != EngineStatus.CLI_ERROR or result.error_reason != EngineErrorReason.CRASH:
        return False
    text = f" {(result.error_message or '').lower()} "
    return any(hint in text for hint in NETWORK_HINTS)
