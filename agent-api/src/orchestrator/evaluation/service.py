"""Story 26.5: the business evaluation of a generation, after its previews are up. **Information only** (Epic 26
D4): it never changes the generation's status, never adds warnings to it and never triggers a repair; an error in the
evaluation is the evaluation's (`evaluation_runs.status` FAILED), never the generation's.

`request_auto` (the runner's `on_completed`, after the preview request) queues a run for a generation drafted with
business workflows; "Run again" queues one through the API. The worker that can call the run's LLM provider takes it
(`bga:evaluations:<provider>`) and `run` does the work: the frozen expectations checked against the live backend as
each role's demo user (`checker.py`), a screenshot per step (`walker.py`), the screens judged and the summary written
by the provider. The score is computed from the checked lines, never written by a model.
"""

import asyncio
import io
import json
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.engines import PromptLibrary, build_llm_provider
from src.engines.llm import Image, LlmError
from src.modules.evaluations.usecases.evaluation_usecase import evaluation_dir, evaluation_queue
from src.modules.shared.domain.enums import PreviewStatus

from ..business.binding import compact_operations
from ..business.flow import BusinessFlow, usage_record
from ..business.model import (
    OUTCOME_JUDGE_SCHEMA,
    SECOND_LOOK_SCHEMA,
    STEP_JUDGE_SCHEMA,
    SUMMARY_SCHEMA,
    expectation_texts,
)
from ..store import JobStore
from .api import Api
from .checker import Checker, score

logger = get_logger(__name__)
CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))
MAX_JUDGED = 12  # screens judged per run (each is one provider call)


def evaluation_state_dir(run_id: uuid.UUID | str) -> Path:
    """The provider's scratch dir for one run: inside WORKSPACE_ROOT, where the CLI providers may run (Epic 24; the
    report and screenshots stay under ARTIFACT_ROOT)."""
    return Path(config.workspace_root) / "evaluations" / str(run_id)


def _in_container() -> bool:
    return any(marker.exists() for marker in CONTAINER_MARKERS)


def reachable(url: str) -> str:
    """A preview's `localhost` URL as this worker reaches it (a containerized worker goes through the host)."""
    if _in_container():
        return url.replace("://localhost", "://host.docker.internal").replace("://127.0.0.1", "://host.docker.internal")
    return url


class EvaluationService:
    def __init__(self, store: JobStore, prompts: PromptLibrary, redis=None, events=None):
        self.store = store
        self.prompts = prompts
        self.redis = redis
        self.events = events
        self.switch_timeout_s = 600.0  # a frontend preview rebuilds for the live API (minutes on a cold cache)

    # -- queueing -------------------------------------------------------------------------------------------------

    def business_of(self, generation_id: str) -> tuple[Any, dict[str, Any] | None]:
        generation = self.store.generation(generation_id)
        draft_id = ((generation.options or {}) if generation else {}).get("draftId")
        if generation is None or not draft_id:
            return generation, None
        try:
            draft = self.store.draft(uuid.UUID(str(draft_id)))
        except ValueError:
            return generation, None
        data = draft.business if draft else None
        return generation, data if data and data.get("binding") else None

    async def request_auto(self, generation_id: str) -> None:
        """After a generation completed: queue its evaluation when its draft has bound business workflows."""
        generation, data = self.business_of(generation_id)
        if generation is None or data is None or self.redis is None:
            return
        provider = (generation.options or {}).get("llmProvider") or data.get("provider") or config.llm_provider_name
        run = self.store.create_evaluation(generation_id, "auto", provider)
        message = json.dumps({"evaluationId": str(run.id), "generationId": generation_id})
        await self.redis.rpush(evaluation_queue(provider), message)
        await self._publish(generation_id, run.id, "PENDING")

    async def _publish(self, generation_id: str, run_id: Any, status: str, **payload: Any) -> None:
        if self.events is None:
            return
        try:
            await self.events.publish(
                generation_id, "evaluation.status", status=status, payload={"evaluationId": str(run_id), **payload}
            )
        except Exception:  # an event is a hint for the UI, never a reason to stop
            logger.warning("evaluation event failed", extra={"generation_id": generation_id})

    # -- one run --------------------------------------------------------------------------------------------------

    async def run(self, run_id: uuid.UUID) -> None:
        run = self.store.evaluation(run_id)
        if run is None:
            return
        generation_id = run.generation_id
        started = datetime.now(UTC)
        self.store.update_evaluation(run_id, status="RUNNING", started_at=started, progress="waiting for the previews")
        await self._publish(generation_id, run_id, "RUNNING")
        try:
            report, usage = await self._evaluate(run_id, generation_id, run.provider, run.expectations_from)
        except Exception as exc:  # the evaluation's own failure; the generation is untouched (D4)
            logger.exception("evaluation failed", extra={"generation_id": generation_id})
            self.store.update_evaluation(
                run_id, status="FAILED", error=f"{type(exc).__name__}: {exc}"[:2000], progress=None,
                finished_at=datetime.now(UTC),
            )  # fmt: skip
            await self._publish(generation_id, run_id, "FAILED")
            return
        self.store.update_evaluation(
            run_id, status="DONE", score=report["score"], report=report, usage=usage, progress=None,
            finished_at=datetime.now(UTC),
        )  # fmt: skip
        await self._publish(generation_id, run_id, "DONE", score=report["score"])

    async def _live_frontend(self, run_id: uuid.UUID, generation_id: str, previews: dict[str, Any]) -> Any:
        """The frontend preview on the live API: the checker's records exist only there, and a preview started again
        (expired, or started by hand) runs on the mocks. Only the preview is switched (`switch-frontend`), never the
        generation (D4: no integration recheck). None when it does not get there."""
        frontend, backend = previews.get("frontend"), previews.get("backend")
        if frontend is None or frontend.mock_api is False:
            return frontend
        if backend is None or not backend.url or self.redis is None:
            return None
        await self._progress(run_id, "connecting the screens to the live API")
        from src.libs.queue.preview_commands import PreviewCommandBus

        from ..previews import wait_settled

        await PreviewCommandBus(self.redis).send(
            "switch-frontend", generation_id, kind="frontend", mockApi=False, apiBaseUrl=backend.url
        )
        row = await wait_settled(self.store, generation_id, "frontend", self.switch_timeout_s, mock_api=False)
        if row is None or row.status != PreviewStatus.RUNNING or row.mock_api is not False:
            return None
        return row

    async def _progress(self, run_id: uuid.UUID, text: str) -> None:
        self.store.update_evaluation(run_id, progress=text[:120])

    async def _wait_previews(self, generation_id: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        found: dict[str, Any] = {}
        while time.monotonic() < deadline:
            for kind in ("backend", "frontend"):
                preview = self.store.preview(generation_id, kind)
                if preview is not None and preview.status == PreviewStatus.RUNNING and preview.url:
                    found[kind] = preview
            if "backend" in found and "frontend" in found:
                return found
            if any(
                (p := self.store.preview(generation_id, kind)) is not None and p.status == PreviewStatus.FAILED
                for kind in ("backend",)
            ):
                break
            await asyncio.sleep(5)
        return found

    def _artifact(self, generation_id: str, name: str) -> bytes | None:
        artifact = self.store.artifact_by_name(generation_id, name)
        if artifact is None:
            return None
        path = Path(config.artifact_root) / artifact.path
        return path.read_bytes() if path.is_file() else None

    def _app_json(self, generation_id: str) -> dict[str, Any]:
        archive = self._artifact(generation_id, "frontend.zip")
        if archive is None:
            return {}
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            name = next((n for n in zipped.namelist() if n.endswith("src/content/app.json")), None)
            return json.loads(zipped.read(name)) if name else {}

    async def _evaluate(
        self, run_id: uuid.UUID, generation_id: str, provider_name: str | None, expectations_from: str | None = None
    ):
        """`expectations_from` (Story 26.7): another generation's frozen expectations, bound to this app first (the
        same requirement generated without the business layer is measured the same way)."""
        _, data = self.business_of(expectations_from or generation_id)
        if data is None:
            raise RuntimeError("the generation has no bound business workflows")
        business, expected, binding = data["business"], data["expected"], data["binding"]
        previews = await self._wait_previews(generation_id, config.evaluation_preview_wait_seconds)
        if "backend" not in previews:
            raise RuntimeError("the backend preview is not running")
        contract_bytes = self._artifact(generation_id, "contract.json")
        if contract_bytes is None:
            raise RuntimeError("the generation has no contract.json artifact")
        contract = json.loads(contract_bytes)
        operations = compact_operations(contract)
        app = self._app_json(generation_id)
        auth_app = app.get("auth") or {}
        roles: dict[str, list[str]] = {}
        for user in auth_app.get("demoUsers") or []:
            roles.setdefault(user["role"], []).append(user["login"])
        auth = (
            {
                "login": (auth_app.get("login") or {}).get("path", "/auth/login"),
                "field": auth_app.get("loginField", "email"),
                "password": auth_app.get("password") or "demo12345",
                "signIn": auth_app.get("signIn") or "/login",
                "me": (auth_app.get("me") or {}).get("path", "/auth/me"),
                "register": (auth_app.get("register") or {}).get("path") or "/auth/register",
                "roles": roles,
            }
            if auth_app
            else None
        )
        out = evaluation_dir(generation_id, str(run_id))
        shots = out / "shots"
        provider = build_llm_provider(provider_name) if provider_name else build_llm_provider()
        state = evaluation_state_dir(run_id)
        state.mkdir(parents=True, exist_ok=True)
        calls: list[dict[str, Any]] = []
        loop = asyncio.get_running_loop()

        async def ask(purpose: str, prompt_id: str, schema: dict[str, Any], images=None, **context: Any):
            rendered = self.prompts.render(prompt_id, "v1", **context)
            answer = await provider.json(purpose, rendered.text, schema, images, state_dir=state)
            calls.append(usage_record(provider, rendered.ref, answer, purpose))
            return answer.data

        def second_look(step, bound, result, ops):
            future = asyncio.run_coroutine_threadsafe(
                ask(
                    "evaluate_second_look",
                    "second_look",
                    SECOND_LOOK_SCHEMA,
                    step=json.dumps(step, indent=1, ensure_ascii=False),
                    bound=json.dumps(bound, indent=1, ensure_ascii=False),
                    result=json.dumps(result, indent=1, ensure_ascii=False, default=str)[:4000],
                    operations=json.dumps(ops, ensure_ascii=False),
                ),
                loop,
            )
            try:
                return future.result(timeout=config.llm_timeout_seconds + 60)
            except (LlmError, TimeoutError, Exception):
                return None

        if expectations_from:
            await self._progress(run_id, "binding the workflows to this app")
            binding = await self._bind_here(generation_id, business, expected, contract, provider, state, calls)

        walker = None
        screens_note = None
        if "frontend" in previews and config.evaluation_screenshots:
            live = await self._live_frontend(run_id, generation_id, previews)
            if live is None:
                previews.pop("frontend")
                screens_note = "no screenshots: the frontend preview stayed on the mocks, not the live API"
            else:
                previews["frontend"] = live
        frontend_url = reachable(previews["frontend"].url) if "frontend" in previews else None
        if frontend_url and config.evaluation_screenshots:
            await self._progress(run_id, "starting the browser")
            try:
                from .walker import Walker

                walker = await asyncio.to_thread(Walker, shots)
            except Exception as exc:
                logger.warning("evaluation browser unavailable", extra={"error": str(exc)[:300]})
        log_lines: list[str] = []
        tour_results: list[dict[str, Any]] = []
        if walker is not None and app.get("workflows"):
            # Story 28.6: each role's guided tour, played on the mocks (never the live API), before the checks
            await self._progress(run_id, "playing the guided tour")
            from .tour import play_tours

            try:
                tour_results = await asyncio.to_thread(
                    play_tours, walker, previews["frontend"].url, app, auth, log_lines.append
                )
            except Exception as exc:  # information only: a failed play never ends the evaluation
                logger.warning("tour play failed", extra={"error": str(exc)[:300]})
                log_lines.append(f"  tour play failed: {str(exc)[:200]}")
        await self._progress(run_id, "checking the workflows")
        checker = Checker(
            api=Api(reachable(previews["backend"].url), auth, operations),
            second_look=second_look,
            log=log_lines.append,
            business=business,
            expected=expected,
            binding=binding,
            walker=walker,
            frontend=(previews["frontend"].url if "frontend" in previews else ""),
            routes={pid: page.get("route") for pid, page in (app.get("pages") or {}).items()},
            auth=auth,
        )
        try:
            results = await asyncio.to_thread(checker.run)
        finally:
            if walker is not None:
                await asyncio.to_thread(walker.close)
        await self._progress(run_id, "judging the screens")
        judged = await self._judge(results, business, shots, ask)
        lines = results["lines"]
        computed = score(lines)
        await self._progress(run_id, "writing the summary")
        summary: dict[str, Any] | None
        try:
            compact = {
                "score": computed,
                "failed": [line for line in lines if line["result"] == "fail"][:40],
                "paths": [
                    {k: p.get(k) for k in ("workflow", "path", "completed", "stopped")} for p in results["paths"]
                ],
                "screens": judged[:12],
            }
            summary = await ask(
                "evaluate_summary",
                "summarize_business",
                SUMMARY_SCHEMA,
                business=json.dumps({k: business.get(k) for k in ("app", "values", "workflows", "scope")}, indent=1),
                results=json.dumps(compact, indent=1, ensure_ascii=False, default=str),
            )
        except LlmError as exc:
            summary = {"summary": "", "values": [], "gaps": [], "improvements": [], "error": str(exc)[:300]}
        report = {
            "score": computed,
            "lines": lines,
            "paths": results["paths"],
            "users": results.get("users"),
            "binding": {"problems": binding.get("problems") or [], "steps": len(binding.get("steps") or [])},
            "expectationsFrom": expectations_from,
            "judged": judged,
            "tour": tour_results,
            "summary": summary,
            "texts": data.get("texts") or expectation_texts(business, expected),
            "business": {k: business.get(k) for k in ("app", "values", "actors", "workflows", "scope")},
            "log": log_lines[-200:],
            "screenshots": walker is not None,
            **({"screenshotsNote": screens_note} if screens_note else {}),
        }
        usage = {
            "provider": provider.name,
            "calls": calls,
            "costUsd": round(sum(c["costUsd"] or 0 for c in calls), 6),
            "inputTokens": sum(c["inputTokens"] for c in calls),
            "outputTokens": sum(c["outputTokens"] for c in calls),
        }
        (out / "evaluation.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
        return json.loads(json.dumps(report, default=str)), usage

    async def _bind_here(
        self,
        generation_id: str,
        business: dict[str, Any],
        expected: dict[str, Any],
        contract: dict[str, Any],
        provider,
        state: Path,
        calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Another generation's workflows bound to this app's contract and screens (the draft-time binding call)."""
        generation = self.store.generation(generation_id)
        spec = self.store.spec(generation.spec_id) if generation else None
        frontend = self.store.frontend_spec(generation.frontend_spec_id) if generation else None
        if spec is None or frontend is None:
            raise RuntimeError("the generation has no BackendSpec or FrontendSpec to bind the workflows to")
        flow = BusinessFlow(provider, self.prompts, state)
        try:
            return await flow.bind(
                business, expected, json.loads(spec.raw_json), contract, json.loads(frontend.raw_json)
            )
        finally:
            calls.extend(flow.calls)

    async def _judge(self, results: dict[str, Any], business: dict[str, Any], shots: Path, ask) -> list[dict[str, Any]]:
        """Opinions on the screens (never in the score): one provider call per screenshot, at most MAX_JUDGED."""
        steps = {(w["id"], s["id"]): s for w in business.get("workflows") or [] for s in w.get("steps") or []}
        actors = {a["id"]: a.get("name", a["id"]) for a in business.get("actors") or []}
        judged: list[dict[str, Any]] = []
        for path in results.get("paths") or []:
            for shot in path.get("shots") or []:
                if len(judged) >= MAX_JUDGED or not shot.get("file"):
                    continue
                file = shots / Path(shot["file"]).name
                if not file.is_file():
                    continue
                step = steps.get((path["workflow"], shot.get("step"))) or {}
                target = (
                    f" (the {step.get('record')} should become '{step['statusAfter']}')"
                    if step.get("statusAfter")
                    else ""
                )
                try:
                    answer = await ask(
                        "evaluate_judge_step",
                        "judge_step",
                        STEP_JUDGE_SCHEMA,
                        images=[Image(data=file.read_bytes(), name=file.name)],
                        actor=actors.get(step.get("actor", ""), step.get("actor", "user")),
                        action=step.get("action", shot.get("step", "")),
                        target=target,
                        page=shot.get("page", ""),
                        text=(shot.get("text") or "")[:1500],
                    )
                except LlmError as exc:
                    answer = {"error": str(exc)[:200]}
                judged.append({"workflow": path["workflow"], "path": path["path"], "step": shot.get("step"),
                               "file": file.name, **answer})  # fmt: skip
            for shot in path.get("outcomes") or []:
                if len(judged) >= MAX_JUDGED or not shot.get("file"):
                    continue
                file = shots / Path(shot["file"]).name
                if not file.is_file():
                    continue
                try:
                    answer = await ask(
                        "evaluate_judge_outcome",
                        "judge_outcome",
                        OUTCOME_JUDGE_SCHEMA,
                        images=[Image(data=file.read_bytes(), name=file.name)],
                        actor=actors.get(shot.get("as", ""), shot.get("as", "user")),
                        expect=shot.get("expect", ""),
                        text=(shot.get("text") or "")[:1500],
                    )
                except LlmError as exc:
                    answer = {"error": str(exc)[:200]}
                judged.append({"workflow": path["workflow"], "path": path["path"], "outcome": shot.get("as"),
                               "file": file.name, **answer})  # fmt: skip
        return judged
