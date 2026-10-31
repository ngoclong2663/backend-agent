"""Preview lifecycle on the worker (Stories 7.3, 7.4, 13.5): the only place that touches preview containers.

A generation has up to two previews, one per kind: `backend` (the API with its database) and `frontend` (the
static export or the Next.js server). Commands arrive over Redis (PreviewCommandBus) from the API, or from the
runner when a generation completes; `args.kind` picks the preview (default `backend`). Each generation's
commands run one at a time; the previews rows and `preview.status` events report the outcome.
"""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.libs.queue import PreviewCommandBus
from src.modules.generations.infrastructure.adapters import EventPublisher
from src.modules.shared.domain.entities import ArtifactEntity, PreviewEntity
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus, LaneStatus, PreviewStatus
from src.modules.shared.domain.generation_modes import backend_ready, overall_status
from src.preview import IPreviewRuntime, PreviewError, PreviewRequest

from .packaging import ArtifactWriter
from .store import JobStore

logger = get_logger(__name__)
ACTIVE = (PreviewStatus.STARTING, PreviewStatus.RUNNING)
MUTATING = {"start", "restart", "stop", "delete", "reset-db", "recheck", "use-mocks"}
KINDS = ("backend", "frontend")
SOURCES = {"backend": "backend.zip", "frontend": "frontend.zip"}


def _now() -> datetime:
    return datetime.now(UTC)


class PreviewService:
    def __init__(
        self,
        runtime: IPreviewRuntime,
        store: JobStore,
        events: EventPublisher,
        bus: PreviewCommandBus,
        frontend_runtime: IPreviewRuntime | None = None,
    ):
        self.runtimes: dict[str, IPreviewRuntime] = {"backend": runtime}
        if frontend_runtime is not None:
            self.runtimes["frontend"] = frontend_runtime
        self.runtime = runtime
        self.store = store
        self.events = events
        self.bus = bus
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- entry points -------------------------------------------------------------------------------------------

    def startable(self, generation_id: str) -> list[str]:
        """The previews a finished generation gets: the frontend first (the backend's CORS needs its origin)."""
        generation = self.store.generation(generation_id)
        if generation is None:
            return []
        kinds = []
        frontend = generation.options.get("frontend") or {}
        if (
            "frontend" in self.runtimes
            and generation.lanes.get("frontend") == LaneStatus.COMPLETED.value
            and frontend.get("generatePreview", True)
        ):
            kinds.append("frontend")
        if generation.options.get("deployPreview", True) and backend_ready(generation.status, generation.lanes):
            if generation.lanes.get("backend", LaneStatus.COMPLETED.value) == LaneStatus.COMPLETED.value:
                kinds.append("backend")
        return kinds

    async def request_start(self, generation_id: str) -> None:
        """Called by the runner when a generation finishes (Q6: previews start automatically)."""
        for kind in self.startable(generation_id):
            existing = self.store.preview(generation_id, kind)
            if existing is not None and existing.status in ACTIVE:
                continue
            self.store.upsert_preview(generation_id, kind, status=PreviewStatus.STARTING, started_at=_now(), error=None)
            await self._event(generation_id, kind, PreviewStatus.STARTING)
            await self.bus.send("start", generation_id, kind=kind)

    async def handle(self, command: dict[str, Any]) -> None:
        op, generation_id, args = command["op"], command["generationId"], command.get("args") or {}
        kind = args.get("kind", "backend")
        try:
            if kind not in self.runtimes:
                result: Any = {"error": f"no {kind} previews on this worker"}
            elif op in MUTATING:
                async with self.locks[f"{generation_id}:{kind}"]:
                    result = await getattr(self, op.replace("-", "_"))(generation_id, kind)
            elif op == "logs":
                result = {"lines": await self.runtimes[kind].logs(generation_id, int(args.get("tail", 200)))}
            elif op == "requests":
                items = await self.runtimes[kind].request_log(
                    generation_id, args.get("after"), int(args.get("limit", 200))
                )
                result = {"items": items, "cursor": items[-1]["ts"] if items else args.get("after")}
            else:
                result = {"error": f"unknown preview command {op!r}"}
        except Exception as exc:
            logger.exception("preview command failed", extra={"generation_id": generation_id, "op": op})
            result = {"error": str(exc)[:500]}
        if command.get("reply"):
            await self.bus.reply(command["reply"], result)

    # -- commands -----------------------------------------------------------------------------------------------

    async def start(
        self, generation_id: str, kind: str = "backend", options_override: dict[str, Any] | None = None
    ) -> None:
        generation = self.store.generation(generation_id)
        source = self.store.artifact_by_name(generation_id, SOURCES[kind])
        if generation is None or source is None or not self._ready(generation, kind):
            what = "frontend" if kind == "frontend" else "backend"
            await self._fail(
                generation_id, kind, f"only generations with a completed, packaged {what} can be previewed"
            )
            return
        prior = self.store.preview(generation_id, kind)
        current = self.store.upsert_preview(
            generation_id, kind, status=PreviewStatus.STARTING, started_at=_now(), error=None
        )
        await self._event(generation_id, kind, PreviewStatus.STARTING)
        if not await self._make_room(generation_id, kind):
            return

        # Reserve frontend port first if backend is starting, so backend CORS includes the frontend origin
        if kind == "backend" and "frontend" in self.runtimes:
            frontend_opts = generation.options.get("frontend") or {}
            will_generate_fe = generation.mode == "dynamic" and frontend_opts.get("generatePreview", True)
            fe_preview = self.store.preview(generation_id, "frontend")
            if fe_preview is None and (will_generate_fe or "frontend" in self.startable(generation_id)):
                fe_preview = self.store.upsert_preview(generation_id, "frontend", status=PreviewStatus.STOPPED)
            if fe_preview is not None and not fe_preview.host_port:
                fe_ports = await self._ports(generation_id, "frontend", fe_preview)
                if fe_ports:
                    self.store.upsert_preview(generation_id, "frontend", host_port=fe_ports[0])

        ports = await self._ports(generation_id, kind, current)
        if ports and not current.host_port:
            current = self.store.upsert_preview(generation_id, kind, host_port=ports[0])

        seed = self.store.artifact_by_name(generation_id, "seed.json") if kind == "backend" else None
        options = self._options(generation, kind, prior)
        if options_override:
            options.update(options_override)
        request = PreviewRequest(
            generation_id=generation_id,
            source_zip=self._file(source),
            ports=ports,
            seed=self._file(seed).read_bytes() if seed else None,
            options=options,
        )
        try:
            handle = await self.runtimes[kind].deploy(request)
        except PreviewError as exc:
            if exc.log:
                prefix = "frontend-preview" if kind == "frontend" else "preview"
                name = f"{prefix}-build.log" if "build" in str(exc) else f"{prefix}.log"
                self._save_log(generation_id, name, exc.log)
            await self._fail(generation_id, kind, str(exc))
            return
        if handle.build_log:
            self._save_log(generation_id, "frontend-preview-build.log" if kind == "frontend" else "preview-build.log",
                           handle.build_log)  # fmt: skip
        now, url = _now(), f"http://{config.preview_public_host}:{handle.host_port}"
        self.store.upsert_preview(
            generation_id,
            kind,
            status=PreviewStatus.RUNNING,
            container_id=handle.container_id,
            db_container_id=handle.db_container_id or None,
            host_port=handle.host_port,
            url=url,
            started_at=now,
            last_accessed_at=now,
            expires_at=now + timedelta(hours=config.preview_ttl_hours),
            error=None,
            mock_api=request.options.get("mockApi") if kind == "frontend" else None,
        )
        await self._event(generation_id, kind, PreviewStatus.RUNNING, url=url)

    def _ready(self, generation, kind: str) -> bool:
        if kind == "frontend":
            return generation.lanes.get("frontend") == LaneStatus.COMPLETED.value
        return backend_ready(generation.status, generation.lanes)

    def _options(self, generation, kind: str, prior: PreviewEntity | None = None) -> dict[str, Any]:
        if kind == "frontend":
            frontend = generation.options.get("frontend") or {}
            if generation.mode != "dynamic":
                return {"mode": generation.mode}  # a static export has no API, so no mock switch
            if prior is not None and prior.mock_api is False:
                backend = self.store.preview(generation.id, "backend")
                if backend is not None and backend.url:
                    return {"mode": generation.mode, "mockApi": False, "apiBaseUrl": backend.url}
            return {"mode": generation.mode, "mockApi": frontend.get("mockApi", True), "apiBaseUrl": ""}
        origins = [origin for origin in config.preview_cors_origins.split(",") if origin]
        frontend = self.store.preview(generation.id, "frontend")
        if frontend is not None and frontend.host_port:
            # The frontend preview calls this backend once it leaves the mock API (Story 14.2).
            origins += [
                f"http://{config.preview_public_host}:{frontend.host_port}",
                f"http://127.0.0.1:{frontend.host_port}",
            ]
        return {"corsOrigins": ",".join(dict.fromkeys(origins))}

    async def probe(
        self, generation_id: str, method: str, path: str, kind: str = "backend", body: Any = None
    ) -> tuple[int, Any, bytes]:
        if kind not in self.runtimes:
            return 0, None, b""
        return await self.runtimes[kind].probe(generation_id, method, path, body=body)

    async def switch_frontend(
        self, generation_id: str, *, mock_api: bool, api_base_url: str = ""
    ) -> PreviewEntity | None:
        if "frontend" not in self.runtimes:
            return None
        await self.start(
            generation_id,
            "frontend",
            options_override={"mockApi": mock_api, "apiBaseUrl": "" if mock_api else api_base_url},
        )
        frontend = self.store.preview(generation_id, "frontend")
        if not mock_api and "backend" in self.runtimes and frontend is not None and frontend.host_port:
            backend = self.store.preview(generation_id, "backend")
            if backend is not None and backend.status == PreviewStatus.RUNNING:
                await self.start(generation_id, "backend")
        return self.store.preview(generation_id, "frontend")

    async def recheck(self, generation_id: str, kind: str = "frontend") -> dict[str, Any]:
        """Story 14.2: repeats the backend readiness check and switches the frontend preview to live if healthy."""
        from .integration import check_backend_ready

        generation = self.store.generation(generation_id)
        contract_art = self.store.artifact_by_name(generation_id, "contract.json")
        if generation is None or contract_art is None:
            return {"switched": False, "mockApi": True, "apiBaseUrl": "", "reason": "contract not found"}
        raw = self._file(contract_art).read_bytes()
        contract = json.loads(raw.decode())
        plan_art = self.store.artifact_by_name(generation_id, "plan.json")
        plan = json.loads(self._file(plan_art).read_text()) if plan_art and self._file(plan_art).is_file() else None
        ok, reason, backend_url = await check_backend_ready(
            generation_id, self, contract, contract_art.sha256, plan=plan, wait_seconds=0
        )
        if not ok or not backend_url:
            frontend = self.store.preview(generation_id, "frontend")
            if frontend is not None and frontend.mock_api is not True:
                await self.switch_frontend(generation_id, mock_api=True, api_base_url="")
            if self.events is not None:
                await self.events.publish(
                    generation_id,
                    "integration.kept_mocks",
                    status="SKIPPED",
                    payload={"reason": reason, "mockApi": True},
                    lane="integration",
                )
            return {"switched": False, "mockApi": True, "apiBaseUrl": "", "reason": reason}

        frontend = await self.switch_frontend(generation_id, mock_api=False, api_base_url=backend_url)
        lanes = {**(generation.lanes or {}), "integration": LaneStatus.COMPLETED.value}
        new_status = overall_status(GenerationMode(generation.mode), lanes)
        updates: dict[str, Any] = {"lanes": lanes, "status": new_status}
        if new_status == GenerationStatus.COMPLETED:
            updates["error_summary"] = None
        self.store.update_generation(generation_id, **updates)
        if self.events is not None:
            await self.events.publish(
                generation_id,
                "lane.changed",
                status=LaneStatus.COMPLETED.value,
                payload={"lanes": lanes},
                lane="integration",
            )
            await self.events.publish(
                generation_id,
                "integration.switched_to_live",
                status="COMPLETED",
                payload={
                    "apiBaseUrl": backend_url,
                    "frontendUrl": frontend.url if frontend else None,
                    "contractSha256": contract_art.sha256,
                    "mockApi": False,
                },
                lane="integration",
            )
            if new_status != generation.status:
                await self.events.publish(
                    generation_id,
                    "status.changed",
                    status=new_status,
                    payload={"lanes": lanes, "errorCode": None, "errorSummary": updates.get("error_summary")},
                )
        return {"switched": True, "mockApi": False, "apiBaseUrl": backend_url, "reason": None}

    async def use_mocks(self, generation_id: str, kind: str = "frontend") -> dict[str, Any]:
        """Story 14.2: switches the frontend preview back to MOCK_TEST_API=true."""
        await self.switch_frontend(generation_id, mock_api=True, api_base_url="")
        reason = "switched to mocks"
        generation = self.store.generation(generation_id)
        if generation is not None:
            lanes = {**(generation.lanes or {}), "integration": LaneStatus.SKIPPED.value}
            new_status = overall_status(GenerationMode(generation.mode), lanes)
            self.store.update_generation(generation_id, lanes=lanes, status=new_status, error_summary=reason)
            if self.events is not None:
                await self.events.publish(
                    generation_id,
                    "lane.changed",
                    status=LaneStatus.SKIPPED.value,
                    payload={"lanes": lanes, "reason": reason},
                    lane="integration",
                )
        if self.events is not None:
            await self.events.publish(
                generation_id,
                "integration.kept_mocks",
                status="SKIPPED",
                payload={"reason": reason, "mockApi": True},
                lane="integration",
            )
        return {"switched": False, "mockApi": True, "apiBaseUrl": "", "reason": reason}

    async def restart(self, generation_id: str, kind: str = "backend") -> None:
        await self.runtimes[kind].stop(generation_id)
        await self.start(generation_id, kind)

    async def stop(self, generation_id: str, kind: str = "backend", reason: str | None = None) -> None:
        await self.runtimes[kind].stop(generation_id)
        if self.store.preview(generation_id, kind) is not None:
            self.store.upsert_preview(generation_id, kind, status=PreviewStatus.STOPPED, error=reason)
            await self._event(generation_id, kind, PreviewStatus.STOPPED, reason=reason)

    async def delete(self, generation_id: str, kind: str = "backend") -> None:
        await self.runtimes[kind].remove(generation_id)
        self.store.delete_preview(generation_id, kind)
        await self.events.publish(generation_id, "preview.status", status="DELETED", payload={"kind": kind})

    async def reset_db(self, generation_id: str, kind: str = "backend") -> None:
        await self.runtimes[kind].drop_database(generation_id)
        await self.start(generation_id, kind)

    # -- housekeeping (worker periodic task) --------------------------------------------------------------------

    async def expire(self) -> int:
        """Stops RUNNING previews idle past their TTL (PREVIEW_TTL_HOURS, refreshed by /touch)."""
        expired = [p for p in self.store.previews((PreviewStatus.RUNNING,)) if p.expires_at and p.expires_at < _now()]
        for preview in expired:
            if preview.kind not in self.runtimes:
                continue
            async with self.locks[f"{preview.generation_id}:{preview.kind}"]:
                await self.stop(preview.generation_id, preview.kind, reason="idle TTL reached")
        return len(expired)

    async def reconcile(self) -> dict[str, int]:
        """Syncs rows with the containers that really exist: missing/stopped containers → STOPPED, interrupted
        starts → FAILED, containers without a row → removed."""
        changed = removed = 0
        stale_start = _now() - timedelta(
            seconds=config.preview_build_timeout_seconds + config.preview_health_timeout_seconds + 120
        )
        rows_by_kind: dict[str, dict[str, PreviewEntity]] = defaultdict(dict)
        for preview in self.store.previews():
            rows_by_kind[preview.kind][preview.generation_id] = preview
        for kind, runtime in self.runtimes.items():
            states = await runtime.states()
            rows = rows_by_kind.get(kind, {})
            for generation_id, preview in rows.items():
                if self.locks[f"{generation_id}:{kind}"].locked():
                    continue
                state = states.get(generation_id)
                if preview.status == PreviewStatus.RUNNING and (state is None or state.app != "running"):
                    found = state.app if state and state.app else "missing"
                    self.store.upsert_preview(
                        generation_id, kind, status=PreviewStatus.STOPPED, error=f"container not running ({found})"
                    )
                    await self._event(generation_id, kind, PreviewStatus.STOPPED, reason=f"container {found}")
                    changed += 1
                elif (
                    preview.status == PreviewStatus.STARTING and preview.started_at and preview.started_at < stale_start
                ):
                    await self._fail(generation_id, kind, "start was interrupted (worker restarted?)")
                    changed += 1
            for generation_id in set(states) - set(rows):
                await runtime.remove(generation_id)
                removed += 1
        if changed or removed:
            logger.info("previews reconciled", extra={"changed": changed, "removed_orphans": removed})
        return {"changed": changed, "removed": removed}

    # -- helpers ------------------------------------------------------------------------------------------------

    async def _make_room(self, generation_id: str, kind: str) -> bool:
        """PREVIEW_MAX_RUNNING counts other generations' previews (a generation's own two never evict each other)."""
        running = [p for p in self.store.previews(ACTIVE) if p.generation_id != generation_id]
        excess = len({p.generation_id for p in running}) - config.preview_max_running + 1
        if excess <= 0:
            return True
        if not config.preview_evict:
            await self._fail(
                generation_id,
                kind,
                f"{len(running)} previews running (PREVIEW_MAX_RUNNING={config.preview_max_running})",
            )
            return False
        oldest = sorted(running, key=lambda p: p.last_accessed_at or p.started_at or _now())
        victims: list[str] = []
        for preview in oldest:
            if preview.generation_id not in victims:
                victims.append(preview.generation_id)
        for victim in victims[:excess]:
            for preview in running:
                if preview.generation_id == victim and preview.status == PreviewStatus.RUNNING:
                    await self.stop(victim, preview.kind, reason=f"evicted to start {generation_id}")
        return True

    async def _ports(self, generation_id: str, kind: str, current: PreviewEntity) -> list[int]:
        """The preview's previous port first; then free ports; when the range is full, take the port of the least
        recently used stopped preview (its app container is recreated on its next start)."""
        rows = [p for p in self.store.previews() if (p.generation_id, p.kind) != (generation_id, kind)]
        used = {p.host_port for p in rows if p.host_port}
        ports = [current.host_port] if current.host_port else []
        ports += [port for port in config.preview_ports if port not in used and port not in ports]
        if len(ports) < 3:
            stopped = sorted(
                (p for p in rows if p.status in (PreviewStatus.STOPPED, PreviewStatus.FAILED) and p.host_port),
                key=lambda p: p.last_accessed_at or p.started_at or _now(),
            )
            for preview in stopped[:3]:
                if preview.kind in self.runtimes:
                    await self.runtimes[preview.kind].remove_app(preview.generation_id)
                self.store.upsert_preview(preview.generation_id, preview.kind, host_port=None, url=None)
                ports.append(preview.host_port)
        return ports

    def _file(self, artifact: ArtifactEntity) -> Path:
        return Path(config.artifact_root) / artifact.path

    def _save_log(self, generation_id: str, name: str, text: str) -> None:
        writer = ArtifactWriter(Path(config.artifact_root), generation_id)
        existing = self.store.artifact_by_name(generation_id, name)
        if existing:
            writer.ids[name] = existing.id
        writer.write(name, "log", text.encode(), "text/plain")
        self.store.replace_artifacts(generation_id, writer.written)

    async def _fail(self, generation_id: str, kind: str, message: str) -> None:
        self.store.upsert_preview(generation_id, kind, status=PreviewStatus.FAILED, error=message[:2000])
        await self._event(generation_id, kind, PreviewStatus.FAILED, error=message[:500])

    async def _event(self, generation_id: str, kind: str, status: PreviewStatus, **payload: Any) -> None:
        await self.events.publish(generation_id, "preview.status", status=status, payload={"kind": kind, **payload})
