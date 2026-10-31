import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.engines import (
    EngineContext,
    EngineEvent,
    EngineRequest,
    EngineResult,
    EngineStatus,
    ICodeEngine,
    ModelCall,
    PromptLibrary,
    RenderedPrompt,
)
from src.libs.redaction import default_redactor
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.entities import CliInvocationEntity, ModelCallEntity, SandboxExecEntity
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus, LaneStatus
from src.sandbox import ExecResult, ISandbox, ISandboxProvider

from . import tracing
from .state import NODE_LANE, lane_status_for, status_for
from .store import JobStore
from .validation import IValidationRunner
from .workspace import JobWorkspace, WorkspaceManager

logger = get_logger(__name__)
PROVIDERS = {"claude_code": "anthropic", "antigravity": "google"}
_TOOL_SCRIPT = re.compile(r"/opt/bga/bin/([\w-]+)")
_CURRENT_LANE: ContextVar[str | None] = ContextVar("bga_current_lane", default=None)
_CURRENT_RUN_ID: ContextVar[uuid.UUID | None] = ContextVar("bga_current_run_id", default=None)


class JobCancelled(Exception):
    pass


class BackendLaneAborted(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class EngineFailure(Exception):
    def __init__(self, result: EngineResult):
        super().__init__(f"{result.engine} {result.purpose}: {result.status} ({result.error_reason})")
        self.result = result


class JobContext:
    """Everything a node needs for one generation; nodes stay plain functions of (state, ctx)."""

    def __init__(
        self,
        generation_id: str,
        engine: ICodeEngine,
        engine_context: EngineContext,
        prompts: PromptLibrary,
        validator: IValidationRunner,
        store: JobStore,
        events: EventPublisher,
        workspaces: WorkspaceManager,
        workspace: JobWorkspace,
        sandboxes: ISandboxProvider | None = None,
        template_dir: Path | None = None,
        mode: GenerationMode = GenerationMode.BACKEND,
        lanes: dict[str, str] | None = None,
        frontend_engine_context: EngineContext | None = None,
        frontend_validator: Any = None,
        previews: Any = None,
        worker_slots: asyncio.Semaphore | None = None,
    ):
        self.generation_id = generation_id
        self.mode = mode
        self.lanes: dict[str, str] = dict(lanes or {})
        self._default_lane: str | None = None
        self._default_run_id: uuid.UUID | None = None
        self.engine = engine
        self.engine_context = engine_context
        self.prompts = prompts
        self.validator = validator
        self.store = store
        self.events = events
        self.workspaces = workspaces
        self.workspace = workspace
        self.cancel_requested = asyncio.Event()
        self.active_invocations: set[str] = set()
        self.lane_invocations: dict[str, set[str]] = {"backend": set(), "frontend": set()}
        self.sandboxes = sandboxes
        self.template_dir = template_dir or Path(config.template_dir)
        self._sandbox: ISandbox | None = None
        self._frontend_sandbox: ISandbox | None = None
        self.frontend_engine_context = frontend_engine_context or engine_context
        self.frontend_validator = frontend_validator
        self.previews = previews
        self.worker_slots = worker_slots
        self.active_lanes: set[str] = set()
        self.max_concurrent_lanes: int = 0
        self.max_concurrent_invocations: int = 0
        self._extra_slot_acquired: bool = False
        self.backend_done = asyncio.Event()
        self.backend_validating = asyncio.Event()  # the backend lane reached run_validation
        self.frontend_done = asyncio.Event()
        self.frontend_failed = False
        self.backend_aborted_reason: str | None = None
        self._wait_task: asyncio.Task | None = None
        self._state_lock = asyncio.Lock()
        self._commit_lock = asyncio.Lock()
        self.frontend_plan_lock = asyncio.Lock()
        self.engine_slots = asyncio.Semaphore(max(1, config.engine_concurrency))
        self.background_tasks: list[asyncio.Task] = []
        self._status: GenerationStatus | None = None
        self.trace: tracing.GenerationTrace | None = None

    @property
    def current_lane(self) -> str | None:
        val = _CURRENT_LANE.get()
        return val if val is not None else self._default_lane

    @current_lane.setter
    def current_lane(self, value: str | None) -> None:
        self._default_lane = value
        _CURRENT_LANE.set(value)

    @property
    def current_run_id(self) -> uuid.UUID | None:
        val = _CURRENT_RUN_ID.get()
        return val if val is not None else self._default_run_id

    @current_run_id.setter
    def current_run_id(self, value: uuid.UUID | None) -> None:
        self._default_run_id = value
        _CURRENT_RUN_ID.set(value)

    @property
    def current_invocation(self) -> str | None:
        return next(iter(self.active_invocations), None)

    @current_invocation.setter
    def current_invocation(self, value: str | None) -> None:
        if value is None:
            self.active_invocations.clear()
        else:
            self.active_invocations.add(value)

    async def _activate_lane(self, lane: str) -> None:
        if lane not in ("backend", "frontend") or lane in self.active_lanes:
            return
        if (
            self.active_lanes
            and not self._extra_slot_acquired
            and self.worker_slots is not None
            and not self.worker_slots.locked()
        ):
            await self.worker_slots.acquire()
            self._extra_slot_acquired = True
        self.active_lanes.add(lane)
        self.max_concurrent_lanes = max(self.max_concurrent_lanes, len(self.active_lanes))

    def _deactivate_lane(self, lane: str) -> None:
        if lane in self.active_lanes:
            self.active_lanes.discard(lane)
            if self._extra_slot_acquired and len(self.active_lanes) < 2 and self.worker_slots is not None:
                self._extra_slot_acquired = False
                self.worker_slots.release()
        if lane == "backend":
            self.backend_done.set()
            if self._wait_task is not None:
                self._wait_task.cancel()
        elif lane == "frontend":
            self.frontend_done.set()

    @asynccontextmanager
    async def lane_slot(self, lane: str):
        """Story 14.1: the two parallel lanes count as two worker slots while both are active."""
        await self._activate_lane(lane)
        try:
            yield
        finally:
            self._deactivate_lane(lane)

    def start_integration_wait_watchdog(self) -> None:
        """Story 14.2: once the frontend lane completes, give the backend lane at most INTEGRATION_WAIT_SECONDS,
        counted from when it reaches validation (Story 17.6): a backend still being written is never cancelled
        for being slower than the frontend; the job timeout bounds it."""
        if self.backend_done.is_set() or self._wait_task is not None:
            return

        async def _watch() -> None:
            waits = [asyncio.create_task(self.backend_validating.wait()), asyncio.create_task(self.backend_done.wait())]
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            for wait in waits:
                wait.cancel()
            try:
                await asyncio.wait_for(self.backend_done.wait(), timeout=config.integration_wait_seconds)
            except TimeoutError:
                if not self.backend_done.is_set():
                    await self.abort_backend(
                        f"backend lane timed out after {config.integration_wait_seconds:g}s (INTEGRATION_WAIT_SECONDS)"
                    )

        self._wait_task = asyncio.create_task(_watch())

    async def abort_backend(self, reason: str, *, frontend_failed: bool = False) -> None:
        if frontend_failed:
            self.frontend_failed = True
        if self.backend_aborted_reason is None:
            self.backend_aborted_reason = reason
        for invocation_id in list(self.lane_invocations.get("backend", ())):
            await self.engine.cancel(invocation_id)

    async def emit(self, type: str, step: str | None = None, status: str | None = None, **payload: Any) -> None:
        await self.events.publish(
            self.generation_id, type, step=step, status=status, payload=payload, lane=self.current_lane
        )

    async def set_status(
        self, status: GenerationStatus, step: str | None = None, payload: dict[str, Any] | None = None, **fields: Any
    ) -> None:
        async with self._state_lock:
            self.store.update_generation(self.generation_id, status=status, **fields)
            if status != self._status:
                self._status = status
                await self.emit("status.changed", step=step, status=status, **(payload or {}), lanes=dict(self.lanes))

    async def set_lane(self, lane: str, status: LaneStatus, reason: str | None = None) -> None:
        """Story 12.2: one status per lane, stored on the generation and announced as `lane.changed`."""
        async with self._state_lock:
            if status in (LaneStatus.COMPLETED, LaneStatus.FAILED, LaneStatus.SKIPPED):
                self._deactivate_lane(lane)
            if lane not in self.lanes or self.lanes[lane] == status.value:
                return
            self.lanes[lane] = status.value
            self.store.update_generation(self.generation_id, lanes=dict(self.lanes))
            payload: dict[str, Any] = {"lanes": dict(self.lanes)}
            if reason:
                payload["reason"] = reason
            await self.events.publish(
                self.generation_id, "lane.changed", status=status.value, payload=payload, lane=lane
            )

    async def replace_lanes(self, lanes: dict[str, str]) -> None:
        for lane, status in lanes.items():
            await self.set_lane(lane, LaneStatus(status))

    async def check_cancel(self) -> None:
        if not self.cancel_requested.is_set():
            generation = self.store.generation(self.generation_id)
            if generation is not None and generation.cancel_requested:
                self.cancel_requested.set()
        if self.cancel_requested.is_set():
            raise JobCancelled()
        if self.current_lane == "backend" and self.backend_aborted_reason is not None:
            raise BackendLaneAborted(self.backend_aborted_reason)

    async def request_cancel(self) -> None:
        self.cancel_requested.set()
        for invocation_id in list(self.active_invocations):
            await self.engine.cancel(invocation_id)

    async def enter_node(self, node: str, attempt: int) -> uuid.UUID:
        lane = NODE_LANE.get(node)
        lane_name = lane.value if lane else None
        _CURRENT_LANE.set(lane_name)
        self._default_lane = lane_name
        await self.check_cancel()
        if lane_name in ("backend", "frontend"):
            await self._activate_lane(lane_name)
        if lane is not None:
            await self.set_lane(lane.value, lane_status_for(node))
        await self.set_status(status_for(node), step=node, current_step=node)
        run_id = self.store.start_node(self.generation_id, node, attempt)
        _CURRENT_RUN_ID.set(run_id)
        self._default_run_id = run_id
        await self.emit("step.started", step=node, attempt=attempt)
        return run_id

    async def leave_node(self, node: str, run_id: uuid.UUID, status: str, summary: dict[str, Any]) -> None:
        self.store.finish_node(run_id, status, summary)
        await self.emit("step.finished", step=node, status=status, **summary)

    async def run_engine(
        self,
        node: str,
        purpose: str,
        prompt: RenderedPrompt,
        repo: str = "project",
        workdir_override: Path | None = None,
    ) -> EngineResult:
        """One engine call in the backend project (`repo="project"`) or the frontend (`repo="frontend"`), each
        with its own skill and project rules."""
        await self.check_cancel()
        workdir = workdir_override if workdir_override is not None else self.workspace.repo(repo)
        context = self.frontend_engine_context if repo == "frontend" else self.engine_context
        await self.engine.prepare_workspace(workdir, context)
        request = EngineRequest(
            purpose=purpose,
            workdir=workdir,
            state_dir=self.workspace.state,
            prompt=prompt.text,
            prompt_ref=prompt.ref,
        )
        prompt_id = f"{prompt.ref.id}@{prompt.ref.version}"
        record_id = self.store.add_cli_invocation(
            CliInvocationEntity(
                generation_id=self.generation_id,
                node_run_id=self.current_run_id,
                engine=self.engine.name,
                purpose=purpose,
                status="running",
                prompt_ref=prompt_id,
            )
        )
        await self.emit("engine.started", step=node, engine=self.engine.name, purpose=purpose, prompt=prompt.ref.id)
        engine_span = tracing.current().child(
            f"engine:{self.engine.name}",
            "tool",
            inputs={
                "purpose": purpose,
                "prompt": prompt_id,
                "promptSha256": prompt.ref.sha256,
                "workdir": repo,
                "maxTurns": request.max_turns,
            },
            metadata={"engine": self.engine.name, "purpose": purpose},
        )

        async def forward(event: EngineEvent) -> None:
            await self.emit("engine.event", step=node, kind=event.kind, summary=event.summary)

        lane_key = "frontend" if repo == "frontend" else "backend"
        self.active_invocations.add(request.invocation_id)
        self.lane_invocations.setdefault(lane_key, set()).add(request.invocation_id)
        self.max_concurrent_invocations = max(self.max_concurrent_invocations, len(self.active_invocations))
        try:
            result = await self.engine.run(request, forward)
        except BaseException as exc:
            engine_span.end(error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        finally:
            self.active_invocations.discard(request.invocation_id)
            self.lane_invocations.get(lane_key, set()).discard(request.invocation_id)
        usage = result.usage
        self.store.update_cli_invocation(
            record_id,
            status=result.status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            turns=result.turns,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
            cache_write_tokens=usage.cache_write_tokens if usage else None,
            thinking_tokens=usage.thinking_tokens if usage else None,
            cost_usd=usage.cost_usd if usage else None,
            cost_source=usage.cost_source if usage else None,
            model=(usage.model if usage else None) or next((c.model for c in result.model_calls if c.model), None),
            error_reason=result.error_reason,
            changed_files=[default_redactor().redact(path) for path in result.changed_files[:200]],
            finished_at=datetime.now(UTC),
            argv_redacted=result.argv_redacted,
            stdout_ref=result.stdout_ref,
            stderr_ref=result.stderr_ref,
        )
        self._record_model_calls(record_id, result.model_calls, engine_span)
        engine_span.end(
            outputs={
                "status": result.status,
                "exitCode": result.exit_code,
                "durationMs": result.duration_ms,
                "turns": result.turns,
                "usage": usage.model_dump() if usage else None,
                "costUsd": usage.cost_usd if usage else None,
                "modelCalls": len(result.model_calls),
                "toolsDropped": result.tools_dropped,
                "changedFiles": result.changed_files[:50],
            },
            error=None if result.ok else f"{result.status}: {result.error_message or result.error_reason}",
        )
        await self.emit(
            "engine.finished",
            step=node,
            status=result.status,
            purpose=purpose,
            errorReason=result.error_reason,
            durationMs=result.duration_ms,
            turns=result.turns,
            usage=usage.model_dump() if usage else None,
            changedFiles=result.changed_files[:50],
        )
        if self.cancel_requested.is_set():
            raise JobCancelled()
        if self.current_lane == "backend" and self.backend_aborted_reason is not None:
            raise BackendLaneAborted(self.backend_aborted_reason)
        if result.status == EngineStatus.CANCELLED:
            raise JobCancelled()
        if result.status != EngineStatus.OK:
            raise EngineFailure(result)
        return result

    def _record_model_calls(self, invocation_id: uuid.UUID, calls: list[ModelCall], parent: tracing.Span) -> None:
        """Stores the model calls (Story 8.4) and hangs them, with their tools, under the engine span."""
        redactor = default_redactor()
        for call in calls:
            for tool in call.tools:
                tool.target = redactor.redact(tool.target)  # span names are not covered by the client's hooks
        self.store.add_model_calls(
            [
                ModelCallEntity(
                    generation_id=self.generation_id,
                    cli_invocation_id=invocation_id,
                    node_run_id=self.current_run_id,
                    lane=self.current_lane or "backend",
                    duration_ms=call.duration_ms,
                    tools=[tool.model_dump(mode="json") for tool in call.tools],
                    **call.model_dump(exclude={"tools"}),
                )
                for call in calls
            ]
        )
        provider = PROVIDERS.get(self.engine.name, self.engine.name)
        for call in calls:
            llm = parent.child(
                f"llm:{call.model or 'unknown'} #{call.seq}",
                "llm",
                inputs={"seq": call.seq},
                metadata={
                    "ls_model_name": call.model,
                    "ls_provider": provider,
                    "cost_source": call.cost_source,
                    "latency_source": call.latency_source,
                },
                start_time=call.started_at,
                end_time=call.ended_at,
            )
            for tool in call.tools:
                ended = tool.ended_at or tool.started_at
                llm.child(
                    f"tool:{tool.name} {tool.target}".strip(),
                    "tool",
                    inputs={"target": tool.target},
                    start_time=tool.started_at,
                    end_time=ended,
                ).end(outputs={"isError": tool.is_error}, error="tool error" if tool.is_error else None, end_time=ended)
            usage: dict[str, Any] = {
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "total_tokens": call.input_tokens + call.output_tokens,
                "input_token_details": {
                    "cache_read": call.cache_read_tokens,
                    "cache_creation": call.cache_write_tokens,
                },
            }
            if call.thinking_tokens is not None:
                usage["output_token_details"] = {"reasoning": call.thinking_tokens}
            if call.cost_usd is not None:
                usage["total_cost"] = call.cost_usd
            llm.end(
                outputs={"tools": [tool.name for tool in call.tools], "costSource": call.cost_source},
                usage=usage,
                end_time=call.ended_at,
            )

    @property
    def sandbox_enabled(self) -> bool:
        return self.sandboxes is not None

    async def sandbox(self) -> ISandbox | None:
        """The job's sandbox, started on first use and kept until the job ends (close_sandbox)."""
        if self.sandboxes is None:
            return None
        if self._sandbox is None:
            self._sandbox = RecordingSandbox(self.sandboxes.for_job(self.generation_id, self.workspace.project), self)
        await self._sandbox.start()
        return self._sandbox

    async def frontend_sandbox(self) -> ISandbox | None:
        """The frontend's Node sandbox (Story 13.4): no database, the shared pnpm store, kept until the job ends."""
        if self.sandboxes is None:
            return None
        if self._frontend_sandbox is None:
            inner = self.sandboxes.for_job(self.generation_id, self.workspace.frontend, kind="frontend")
            self._frontend_sandbox = RecordingSandbox(inner, self)
        await self._frontend_sandbox.start()
        return self._frontend_sandbox

    async def close_sandbox(self) -> None:
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
        self.background_tasks.clear()
        for lane in ("backend", "frontend"):
            self._deactivate_lane(lane)
        for attribute in ("_sandbox", "_frontend_sandbox"):
            sandbox = getattr(self, attribute)
            if sandbox is None:
                continue
            try:
                await sandbox.stop()
            except Exception:
                logger.warning("sandbox cleanup failed", extra={"generation_id": self.generation_id}, exc_info=True)
            setattr(self, attribute, None)

    def file_tree(self, limit: int = 300, repo: str = "project") -> str:
        project = self.workspace.repo(repo)
        skip = {".git", ".claude", ".agents", "__pycache__", ".venv"}
        if repo == "frontend":
            skip |= {"node_modules", ".next", "out", "test-results", "playwright-report"}
        files = sorted(
            p.relative_to(project).as_posix()
            for p in project.rglob("*")
            if p.is_file() and not any(part in skip for part in p.relative_to(project).parts)
        )
        shown = files[:limit]
        more = f"\n… and {len(files) - limit} more" if len(files) > limit else ""
        return ("\n".join(shown) or "(empty project)") + more

    def project_path(self, *parts: str) -> Path:
        return self.workspace.project.joinpath(*parts)

    def frontend_path(self, *parts: str) -> Path:
        return self.workspace.frontend.joinpath(*parts)


def exec_label(command: str) -> str:
    """`ruff check …` → `ruff check`, `python /opt/bga/bin/startup_check.py` → `startup_check`."""
    script = _TOOL_SCRIPT.search(command)
    if script:
        return script.group(1)
    words = [w for w in command.replace(";", " ").split() if w not in ("set", "-e")]
    if not words:
        return "sh"
    label = words[0].rsplit("/", 1)[-1]
    if len(words) > 1 and words[1].isalpha():
        label += f" {words[1]}"
    return label[:64]


class RecordingSandbox(ISandbox):
    """Records every sandbox command for the local trace and as a `sandbox:*` span (Stories 8.2, 8.3)."""

    def __init__(self, inner: ISandbox, ctx: JobContext):
        self.inner = inner
        self.ctx = ctx
        self._redactor = default_redactor()

    @property
    def db_url(self) -> str:
        return self.inner.db_url

    @property
    def test_db_url(self) -> str:
        return self.inner.test_db_url

    async def start(self) -> None:
        await self.inner.start()

    async def stop(self) -> None:
        await self.inner.stop()

    async def reset_database(self, name: str) -> None:
        await self.inner.reset_database(name)

    async def shared_dependencies(self) -> str | None:
        return await self.inner.shared_dependencies()

    async def exec(
        self, command: str, timeout_s: int | None = None, env: dict[str, str] | None = None, egress: bool = False
    ) -> ExecResult:
        await self.ctx.check_cancel()
        started = datetime.now(UTC)
        result = await self.inner.exec(command, timeout_s=timeout_s, env=env, egress=egress)
        await self.ctx.check_cancel()
        name = exec_label(command)
        status = "timeout" if result.timed_out else ("ok" if result.ok else "failed")
        ended = started + timedelta(milliseconds=result.duration_ms)
        try:
            self.ctx.store.add_sandbox_exec(
                SandboxExecEntity(
                    generation_id=self.ctx.generation_id,
                    node_run_id=self.ctx.current_run_id,
                    name=name,
                    command=self._redactor.redact(command)[:500],
                    status=status,
                    exit_code=result.exit_code,
                    started_at=started,
                    duration_ms=result.duration_ms,
                )
            )
        except Exception:  # bookkeeping must not fail the job
            logger.warning("could not record a sandbox exec", extra={"generation_id": self.ctx.generation_id})
        tracing.current().child(
            f"sandbox:{name}", "tool", inputs={"command": command[:500]}, start_time=started, end_time=ended
        ).end(
            outputs={"exitCode": result.exit_code, "durationMs": result.duration_ms, "status": status},
            error=None if result.ok else f"exit {result.exit_code}",
            end_time=ended,
        )
        return result
