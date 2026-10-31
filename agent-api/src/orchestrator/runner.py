import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langsmith import tracing_context

from src.configs import config, get_logger, log_context
from src.engines import EngineContext, EngineRegistry, PromptLibrary, UnknownEngineError
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.enums import (
    TERMINAL_STATUSES,
    GenerationMode,
    GenerationStatus,
    Lane,
    LaneStatus,
    PreviewStatus,
)
from src.modules.shared.domain.generation_modes import (
    UNAVAILABLE_LANES,
    close_lanes,
    initial_lanes,
    overall_status,
)
from src.sandbox import ISandboxProvider, SandboxError

from . import tracing
from .context import EngineFailure, JobCancelled, JobContext
from .frontend_scaffold import FrontendTemplateDrift
from .frontend_validation import StaticFrontendValidationRunner
from .graph import build_graph
from .nodes import PROMPT_VERSIONS, write_artifacts
from .scaffold import TemplateDrift
from .state import GenerationState, Outcome
from .store import JobStore
from .validation import IValidationRunner
from .workspace import DiskLimitExceeded, WorkspaceManager

logger = get_logger(__name__)
TERMINAL = TERMINAL_STATUSES
PROMPTS = ("generate_database", "generate_backend", "generate_tests", "repair_code")


def job_timeout(engine: str) -> int:
    """Default wall-clock limit for a whole job; `options.timeoutSeconds` overrides it."""
    return config.antigravity_job_timeout_seconds if engine == "antigravity" else config.job_timeout_seconds


class JobRunner:
    """Runs (or resumes) one generation through the graph and owns its final status."""

    def __init__(
        self,
        registry: EngineRegistry,
        checkpointer,
        store: JobStore,
        events: EventPublisher,
        workspaces: WorkspaceManager,
        prompts: PromptLibrary,
        validator: IValidationRunner,
        engine_context: EngineContext,
        worker_id: str,
        sandboxes: ISandboxProvider | None = None,
        template_dir: Path | None = None,
        on_completed: Callable[[str], Awaitable[None]] | None = None,
        frontend_engine_context: EngineContext | None = None,
        frontend_validator: Any = None,
        previews: Any = None,
        worker_slots: asyncio.Semaphore | None = None,
    ):
        self.registry = registry
        self.checkpointer = checkpointer
        self.store = store
        self.events = events
        self.workspaces = workspaces
        self.prompts = prompts
        self.validator = validator
        self.engine_context = engine_context
        self.worker_id = worker_id
        self.sandboxes = sandboxes
        self.template_dir = template_dir
        self.on_completed = on_completed  # e.g. deploy the preview (Story 7.3); never affects the job status
        self.frontend_engine_context = frontend_engine_context or engine_context
        self.frontend_validator = frontend_validator or StaticFrontendValidationRunner()
        self.previews = previews
        self.worker_slots = worker_slots
        self.active: dict[str, JobContext] = {}

    async def cancel(self, generation_id: str) -> bool:
        ctx = self.active.get(generation_id)
        if ctx is None:
            return False
        await ctx.request_cancel()
        return True

    async def run(self, generation_id: str) -> GenerationStatus | None:
        generation = self.store.generation(generation_id)
        if generation is None or generation.status in TERMINAL:
            return generation.status if generation else None

        workspace = self.workspaces.create(generation_id)
        try:
            engine = self.registry.get(generation.engine)
        except UnknownEngineError as exc:
            return await self._fail_early(generation_id, "ENGINE_UNKNOWN", str(exc))
        health = await engine.health()
        if not health.available:
            return await self._fail_early(generation_id, "ENGINE_UNAVAILABLE", f"{engine.name}: {health.reason}")

        ctx = JobContext(
            generation_id,
            engine,
            self.engine_context,
            self.prompts,
            self.validator,
            self.store,
            self.events,
            self.workspaces,
            workspace,
            sandboxes=self.sandboxes,
            template_dir=self.template_dir,
            mode=GenerationMode(generation.mode),
            lanes=generation.lanes or initial_lanes(GenerationMode(generation.mode)),
            frontend_engine_context=self.frontend_engine_context,
            frontend_validator=self.frontend_validator,
            previews=self.previews,
            worker_slots=self.worker_slots,
        )
        ctx._status = generation.status
        ctx.trace = await self._open_trace(generation)
        token = log_context.set({"generation_id": generation_id, "trace_id": ctx.trace.trace_id})
        try:
            if generation.cancel_requested:
                return await self._finish(ctx, GenerationStatus.CANCELLED, None)
            self.active[generation_id] = ctx
            try:
                return await self._execute(ctx, generation, workspace)
            finally:
                await ctx.close_sandbox()
                self.active.pop(generation_id, None)
                self.events.forget(generation_id)
        finally:
            log_context.reset(token)
            await tracing.GenerationTrace.flush()

    async def _open_trace(self, generation) -> tracing.GenerationTrace:
        """One trace per generation (Story 8.1): created on the first run, reattached when a job resumes."""
        spec = self.store.spec(generation.spec_id)
        frontend = self.store.frontend_spec(generation.frontend_spec_id)
        inputs = {"generationId": generation.id, "mode": generation.mode, "options": generation.options}
        inputs |= {"specId": str(generation.spec_id)} if generation.spec_id else {}
        inputs |= {"frontendSpecId": str(generation.frontend_spec_id)} if generation.frontend_spec_id else {}
        trace = tracing.GenerationTrace.open(
            generation.id,
            trace_id=generation.trace_id,
            parent=generation.trace_parent,
            inputs=inputs,
            metadata={
                "generation_id": generation.id,
                "owner_id": str(generation.owner_id),
                "engine": generation.engine,
                "mode": generation.mode,
                "spec_sha256": hashlib.sha256(spec.raw_json.encode()).hexdigest() if spec else None,
                "frontend_spec_sha256": hashlib.sha256(frontend.raw_json.encode()).hexdigest() if frontend else None,
                "prompt_versions": {name: PROMPT_VERSIONS[name] for name in PROMPTS},
                "generator_version": config.generator_version,
            },
            tags=[
                generation.engine,
                f"mode:{generation.mode}",
                *([f"spec:{spec.spec_version}"] if spec else []),
                *([f"frontend-spec:{frontend.spec_version}"] if frontend else []),
            ],
        )
        fields = {"trace_id": trace.trace_id, "trace_parent": trace.parent}
        if trace.root.enabled and not generation.langsmith_run_url:
            fields["langsmith_run_url"] = await trace.url()
        self.store.update_generation(generation.id, **fields)
        self.events.bind_trace(generation.id, trace.trace_id)
        return trace

    async def _execute(self, ctx: JobContext, generation, workspace) -> GenerationStatus:
        graph = build_graph(ctx, ctx.mode).compile(checkpointer=self.checkpointer)
        run_config = {
            "configurable": {"thread_id": generation.id},
            "run_name": tracing.ROOT_NAME,
            "tags": [generation.engine],
            "metadata": {"generation_id": generation.id, "engine": generation.engine, "trace_id": ctx.trace.trace_id},
        }
        snapshot = await graph.aget_state(run_config, subgraphs=True)
        inputs: GenerationState | None
        if snapshot.values:
            self.store.abandon_running(generation.id)
            last_commit, frontend_last_commit, next_steps = _checkpoint_state(snapshot)
            if last_commit:
                self.workspaces.reset_to(workspace, last_commit)
            if frontend_last_commit and workspace.frontend.joinpath(".git").exists():
                self.workspaces.reset_to(workspace, frontend_last_commit, repo="frontend")
            await ctx.emit("job.resumed", resumeCount=generation.resume_count, nextSteps=next_steps)
            self.store.update_generation(generation.id, worker_id=self.worker_id)
            if not snapshot.next:
                return await self._finish_from_state(ctx, snapshot.values)
            inputs = None
        else:
            self.store.update_generation(generation.id, worker_id=self.worker_id, started_at=datetime.now(UTC))
            await ctx.emit("job.started", engine=generation.engine, mode=generation.mode, options=generation.options)
            for lane, reason in UNAVAILABLE_LANES.items():
                await ctx.set_lane(lane.value, LaneStatus.SKIPPED, reason)
            inputs = {
                "generation_id": generation.id,
                "mode": generation.mode,
                "spec_id": str(generation.spec_id) if generation.spec_id else None,
                "frontend_spec_id": str(generation.frontend_spec_id) if generation.frontend_spec_id else None,
                "engine": generation.engine,
                "options": generation.options,
                "workspace": str(workspace.root),
                "repair_attempts": 0,
                "frontend_repair_attempts": 0,
                "max_repair_attempts": int(generation.options.get("maxRepairAttempts", 3)),
                "validation": {},
                "failed_checks": [],
                "implicated_files": [],
                "artifact_ids": {},
                "last_commit": self.workspaces.commit(workspace, "job started"),
            }

        try:
            # LangGraph's callback tracer stays off: the spans come from tracing.py, under the generation's root.
            with tracing_context(enabled=False), tracing.under(ctx.trace.root):
                async with asyncio.timeout(generation.options.get("timeoutSeconds") or job_timeout(generation.engine)):
                    final = await graph.ainvoke(inputs, run_config)
        except JobCancelled:
            return await self._finish(ctx, GenerationStatus.CANCELLED, None)
        except TimeoutError:
            await ctx.request_cancel()
            return await self._finish(ctx, GenerationStatus.FAILED, "Job exceeded its time limit", "TIMEOUT")
        except DiskLimitExceeded as exc:
            return await self._finish(ctx, GenerationStatus.FAILED, str(exc), "DISK_LIMIT")
        except TemplateDrift as exc:
            return await self._finish(ctx, GenerationStatus.FAILED, str(exc)[:500], "TEMPLATE_DRIFT")
        except FrontendTemplateDrift as exc:
            return await self._finish(ctx, GenerationStatus.FAILED, str(exc)[:500], "FRONTEND_TEMPLATE_DRIFT")
        except SandboxError as exc:
            return await self._finish(ctx, GenerationStatus.FAILED, f"Sandbox failed: {exc}"[:500], "SANDBOX_ERROR")
        except EngineFailure as exc:
            message = exc.result.error_message or str(exc)
            return await self._finish(ctx, GenerationStatus.FAILED, f"Engine failed: {message}", "ENGINE_ERROR")
        except asyncio.CancelledError:
            if ctx.cancel_requested.is_set():
                return await self._finish(ctx, GenerationStatus.CANCELLED, None)
            raise  # worker shutdown: leave the job active so it resumes from its checkpoint
        except Exception as exc:
            logger.exception("generation crashed", extra={"generation_id": generation.id})
            return await self._finish(ctx, GenerationStatus.FAILED, f"Internal error: {exc}"[:500], "INTERNAL_ERROR")
        return await self._finish_from_state(ctx, final)

    async def _finish_from_state(self, ctx: JobContext, state: dict) -> GenerationStatus:
        outcome = state.get("outcome")
        if outcome == Outcome.COMPLETED:
            status = overall_status(ctx.mode, ctx.lanes)
            fallbacks = _asset_warnings(state)
            if status == GenerationStatus.COMPLETED_WITH_WARNINGS:
                warning = "; ".join(filter(None, [_lane_warnings(ctx.lanes, state), fallbacks]))
                return await self._finish(ctx, status, warning, "LANES_INCOMPLETE")
            if fallbacks:  # Story 15.3: a drawing on its placeholder still makes a working site
                return await self._finish(ctx, GenerationStatus.COMPLETED_WITH_WARNINGS, fallbacks, "ASSET_FALLBACK")
            return await self._finish(ctx, status, None)
        if outcome == Outcome.SPEC_INVALID:
            return await self._finish(ctx, GenerationStatus.FAILED, state.get("error_summary"), "SPEC_INVALID")
        if outcome == Outcome.REPAIR_LIMIT:
            return await self._finish(ctx, GenerationStatus.FAILED, state.get("error_summary"), "REPAIR_LIMIT")
        return await self._finish(ctx, GenerationStatus.FAILED, "Workflow ended without an outcome", "INTERNAL_ERROR")

    async def _finish(
        self, ctx: JobContext, status: GenerationStatus, error: str | None, code: str | None = None
    ) -> GenerationStatus:
        if status in (GenerationStatus.FAILED, GenerationStatus.CANCELLED):
            await ctx.replace_lanes(close_lanes(ctx.lanes, failed=status == GenerationStatus.FAILED))
        if status == GenerationStatus.CANCELLED and ctx.previews is not None:
            for kind in ("backend", "frontend"):
                preview = self.store.preview(ctx.generation_id, kind)
                if preview is not None and preview.status in (PreviewStatus.STARTING, PreviewStatus.RUNNING):
                    try:
                        await ctx.previews.stop(ctx.generation_id, kind, reason="generation cancelled")
                    except Exception:
                        logger.exception(
                            "stopping preview on cancel failed",
                            extra={"generation_id": ctx.generation_id, "kind": kind},
                        )
        if status == GenerationStatus.FAILED:
            try:
                await write_artifacts(ctx, {}, completed=False, error=error)
            except Exception:  # diagnostics are best effort; the failure itself must still be recorded
                logger.exception("diagnostic packaging failed", extra={"generation_id": ctx.generation_id})
        await ctx.set_status(
            status,
            payload={"errorCode": code, "errorSummary": error},
            error_summary=error,
            finished_at=datetime.now(UTC),
        )
        if ctx.trace is not None:
            generation = self.store.generation(ctx.generation_id)
            ctx.trace.close(
                outputs={
                    "status": status,
                    "errorCode": code,
                    "errorSummary": error,
                    "validation": validation_summary(self.store.validation_runs(ctx.generation_id)),
                    "repairAttempts": generation.repair_attempts if generation else None,
                },
                error=f"{code}: {error}" if status == GenerationStatus.FAILED else None,
            )
        logger.info("generation finished", extra={"generation_id": ctx.generation_id, "status": status, "code": code})
        generation = self.store.generation(ctx.generation_id)
        # The preview service decides which previews (backend, frontend) a finished generation gets.
        if status in (GenerationStatus.COMPLETED, GenerationStatus.COMPLETED_WITH_WARNINGS) and self.on_completed:
            try:
                await self.on_completed(ctx.generation_id)
            except Exception:
                logger.exception("preview request failed", extra={"generation_id": ctx.generation_id})
        return status

    async def _fail_early(self, generation_id: str, code: str, message: str) -> GenerationStatus:
        generation = self.store.generation(generation_id)
        self.store.update_generation(
            generation_id,
            status=GenerationStatus.FAILED,
            error_summary=message,
            finished_at=datetime.now(UTC),
            lanes=close_lanes(generation.lanes, failed=False),
        )
        await self.events.publish(
            generation_id,
            "status.changed",
            status=GenerationStatus.FAILED,
            payload={"errorCode": code, "errorSummary": message},
        )
        return GenerationStatus.FAILED


def _checkpoint_state(snapshot) -> tuple[str | None, str | None, list[str]]:
    last_commit = snapshot.values.get("last_commit")
    frontend_last_commit = snapshot.values.get("frontend_last_commit")
    next_steps: list[str] = []
    for task in getattr(snapshot, "tasks", ()) or ():
        sub = getattr(task, "state", None)
        if sub is not None and getattr(sub, "values", None):
            if task.name == "backend_lane" and sub.values.get("last_commit"):
                last_commit = sub.values["last_commit"]
            elif task.name == "frontend_lane" and sub.values.get("frontend_last_commit"):
                frontend_last_commit = sub.values["frontend_last_commit"]
            if getattr(sub, "next", None):
                next_steps.extend(sub.next)
                continue
        next_steps.append(task.name)
    if not next_steps:
        next_steps = list(snapshot.next)
    return last_commit, frontend_last_commit, next_steps


def _lane_warnings(lanes: dict[str, str], state: dict[str, Any] | None = None) -> str:
    """Why a job that finished is COMPLETED_WITH_WARNINGS."""
    notes = []
    state = state or {}
    for lane, status in lanes.items():
        if status == LaneStatus.SKIPPED.value:
            reason = state.get("integration_reason") if lane == "integration" else None
            notes.append(reason or UNAVAILABLE_LANES.get(Lane(lane), f"The {lane} lane was skipped"))
        elif status == LaneStatus.FAILED.value:
            reason = (
                state.get("backend_error")
                if lane == "backend"
                else (state.get("integration_reason") if lane == "integration" else None)
            )
            notes.append(f"The {lane} lane failed: {reason}" if reason else f"The {lane} lane failed")
    return "; ".join(notes)


def _asset_warnings(state: dict[str, Any]) -> str:
    fallbacks = state.get("asset_fallbacks") or []
    if not fallbacks:
        return ""
    return "Images shown as placeholders: " + ", ".join(f"{item['id']} ({item['reason']})" for item in fallbacks)


def validation_summary(runs) -> dict[str, str]:
    """Status per check in the last validation attempt."""
    last = max((run.attempt for run in runs), default=None)
    return {run.check: run.status for run in runs if run.attempt == last}
