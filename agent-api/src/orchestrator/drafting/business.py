"""The business layer around an app draft (Epic 26, Stories 26.1–26.4), for `drafts.DraftRunner`.

Before `draft_app`: discovery and the frozen expectations, and the brief that replaces the requirement in the draft
prompt (the user's own text stays the draft's `requirement_text`). After it: the binding against the drafted
contract and screens, and the tour, which goes into the FrontendSpec's app outline (`app.workflows`) so the generated
app's `app.json` carries it. A provider error never fails the draft: the draft goes on without the business layer,
with a note (Epic 26 D4: the business layer informs, it does not gate).
"""

from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.engines import PromptLibrary
from src.engines.llm import LlmError, LlmProvider
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.entities import SpecDraftEntity

from ..backend.planner import build_plan
from ..business.binding import tour_workflows
from ..business.flow import BusinessFlow
from ..business.model import brief, expectation_texts
from ..integration.contract import build_contract

logger = get_logger(__name__)
PROVIDER_OF_ENGINE = {"antigravity_json": "antigravity", "claude_code_json": "claude_code", "gemini_api": "gemini_api"}


def business_on(draft: SpecDraftEntity) -> bool:
    """`businessWorkflows` from the draft's request, else BUSINESS_WORKFLOWS (Epic 26 D7). A fake-engine draft has no
    model to discover a business with: only when its request asks for it (and the runner is given a provider)."""
    wanted = (draft.inputs or {}).get("businessWorkflows")
    if wanted is None and draft.engine == "fake":
        return False
    return config.business_workflows if wanted is None else bool(wanted)


def design_on(draft: SpecDraftEntity) -> bool:
    """`designThemes` from the draft's request, else DESIGN_THEMES (Epic 34 D7); a fake-engine draft only when asked."""
    wanted = (draft.inputs or {}).get("designThemes")
    if wanted is None and draft.engine == "fake":
        return False
    return config.design_themes if wanted is None else bool(wanted)


def draft_model(draft: SpecDraftEntity, engine_name: str) -> str | None:
    """The model of every call of a `fast` draft (its request's `draftSpeed`, else DRAFT_SPEED): the provider's
    FAST_DRAFT_MODELS entry; None for a thorough draft or a provider without one (its own model)."""
    speed = (draft.inputs or {}).get("draftSpeed") or config.draft_speed
    if speed != "fast":
        return None
    provider = (draft.inputs or {}).get("llmProvider") or PROVIDER_OF_ENGINE.get(engine_name)
    return config.fast_draft_models.get(provider or "")


def draft_provider(draft: SpecDraftEntity, engine_name: str) -> LlmProvider | None:
    """The provider of the draft's business steps: the request's, else the draft engine's, else LLM_PROVIDER. None for
    a fake-engine draft that names none: there is no model to discover a business with."""
    from src.engines import build_llm_provider

    name = (draft.inputs or {}).get("llmProvider")
    if name is None and engine_name == "fake":
        return None
    return build_llm_provider(name or PROVIDER_OF_ENGINE.get(engine_name))


class DraftBusiness:
    def __init__(self, provider: LlmProvider, prompts: PromptLibrary, state_dir: Path, model: str | None = None):
        self.flow = BusinessFlow(provider, prompts, state_dir, model)
        self.data: dict[str, Any] = {"provider": provider.name}

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.flow.calls

    @property
    def ready(self) -> bool:
        return "business" in self.data and "expected" in self.data

    async def before(self, requirement: str) -> str | None:
        """Discovery and expectations; returns the brief for the draft prompt, or None when they failed."""
        try:
            business = await self.flow.discover(requirement)
            expected = await self.flow.expect(requirement, business)
        except LlmError as exc:
            logger.warning("business discovery failed", extra={"error": str(exc)[:300]})
            self.data["error"] = f"The business workflows could not be discovered: {str(exc)[:300]}"
            return None
        self.data |= {"business": business, "expected": expected, "texts": expectation_texts(business, expected)}
        return brief(requirement, business)

    async def after(self, backend_spec: dict[str, Any] | None, frontend_spec: dict[str, Any] | None) -> None:
        """The binding and the tour; the tour goes into `frontend_spec["app"]["workflows"]` (in place)."""
        if not self.ready or not backend_spec or not frontend_spec:
            return
        result = validate_spec_data(backend_spec)
        if result.normalized is None:
            return
        backend = result.normalized
        contract = build_contract(backend, build_plan(backend))
        try:
            binding = await self.flow.bind(
                self.data["business"], self.data["expected"], backend, contract, frontend_spec
            )
        except LlmError as exc:
            logger.warning("business binding failed", extra={"error": str(exc)[:300]})
            self.data["error"] = f"The workflows could not be bound to the app: {str(exc)[:300]}"
            return
        tour = tour_workflows(self.data["business"], binding, frontend_spec)
        self.data |= {"binding": binding, "tour": tour}
        if tour and isinstance(frontend_spec.get("app"), dict):
            frontend_spec["app"]["workflows"] = tour

    def notes(self) -> list[dict[str, Any]]:
        out = []
        if self.data.get("error"):
            out.append(
                {"spec": "frontend", "path": "/app/workflows", "message": self.data["error"], "suggestion": None}
            )
        problems = (self.data.get("binding") or {}).get("problems") or []
        if problems:
            message = f"{len(problems)} workflow step(s) could not be bound to the app; see the Business tab"
            out.append({"spec": "frontend", "path": "/app/workflows", "message": message, "suggestion": None})
        return out
