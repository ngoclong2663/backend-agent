import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ConfigDict, Field

from src.libs.dtos import CamelModel
from src.modules.previews.presenter.dtos import PreviewDto
from src.modules.shared.domain.entities import ArtifactEntity
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus

if TYPE_CHECKING:
    from src.modules.generations.usecases.get_generation_usecase import GenerationDetail


class FrontendOptionsDto(CamelModel):
    """Frontend lane options (Story 12.2); used from Epic 13 on."""

    model_config = ConfigDict(extra="forbid")

    run_tests: bool = True
    generate_preview: bool = True
    mock_api: bool = True


class GenerationOptionsDto(CamelModel):
    """Backend lane options (unchanged), the engine for every lane, and `frontend` for the frontend lane."""

    model_config = ConfigDict(extra="forbid")

    max_repair_attempts: int = Field(default=3, ge=0, le=10)
    run_tests: bool = True
    generate_dockerfile: bool = True
    deploy_preview: bool = True
    engine: Literal["claude_code", "antigravity", "fake"] | None = None
    # Story 18.10: the engine that drafts the specs of a one-click generation (empty: the server's draft default).
    draft_engine: (
        Literal["antigravity_json", "claude_code_json", "gemini_api", "claude_code", "antigravity", "fake"] | None
    ) = None
    # Epic 24: the provider of this generation's LLM-only steps (Epic 26's business workflows); empty: LLM_PROVIDER
    llm_provider: Literal["antigravity", "claude_code", "gemini_api"] | None = None
    # Epic 26 (D7): the business layer (workflows, tour, evaluation) of a dynamic generation; empty: BUSINESS_WORKFLOWS
    business_workflows: bool | None = None
    # 2026-11-08: how a one-click generation's draft thinks (fast: FAST_DRAFT_MODELS); empty: DRAFT_SPEED
    draft_speed: Literal["fast", "thorough"] | None = None
    # Epic 34 (D7): the design turn of a dynamic draft's theme; empty: DESIGN_THEMES
    design_themes: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=60, le=7200)
    # Story 17.6: CRUD modules, models and tests from templates; false makes the engine write the whole backend.
    crud_from_templates: bool = True
    frontend: FrontendOptionsDto | None = None


class RequirementDto(CamelModel):
    text: str | None = None
    format: str | None = None
    file_name: str | None = None


class CreateGenerationRequestDto(CamelModel):
    """Inputs per mode (checked by the use case, 422 MODE_INPUT_MISMATCH otherwise):
    backend: `backendSpec` | `specId`; static: `frontendSpec` | `frontendSpecId`; dynamic: one of each.
    Or Story 19.10: `requirement` for one-click generation directly from requirement text."""

    mode: GenerationMode = GenerationMode.BACKEND
    requirement: RequirementDto | None = None
    backend_spec: dict[str, Any] | None = None
    spec_id: uuid.UUID | None = None
    frontend_spec: dict[str, Any] | None = None
    frontend_spec_id: uuid.UUID | None = None
    # The draft the specs came from (Stories 2.4, 12.4): its requirement is kept as `requirement.md` / `.txt`.
    draft_id: uuid.UUID | None = None
    options: GenerationOptionsDto = GenerationOptionsDto()


class ContinueGenerationRequestDto(CamelModel):
    """Story 19.10: resume a generation in NEEDS_REVIEW with edited specs."""

    backend_spec: dict[str, Any] | None = None
    frontend_spec: dict[str, Any] | None = None


class CreateGenerationResponseDto(CamelModel):
    generation_id: str
    status: GenerationStatus
    created_at: datetime | None


class EngineInvocationDto(CamelModel):
    id: str
    node_run_id: str | None
    engine: str
    purpose: str
    status: str
    exit_code: int | None
    duration_ms: int | None
    turns: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    created_at: datetime | None


class StepDto(CamelModel):
    id: str
    node: str
    attempt: int
    status: str
    summary: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    invocations: list[EngineInvocationDto]


class UsageTotalsDto(CamelModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ArtifactDto(CamelModel):
    artifact_id: str
    kind: str
    name: str
    size: int
    sha256: str
    content_type: str
    created_at: datetime | None

    @classmethod
    def from_entity(cls, artifact: ArtifactEntity) -> "ArtifactDto":
        return cls(
            artifact_id=artifact.id,
            kind=artifact.kind,
            name=artifact.name,
            size=artifact.size,
            sha256=artifact.sha256,
            content_type=artifact.content_type,
            created_at=artifact.created_at,
        )


class ArtifactListDto(CamelModel):
    items: list[ArtifactDto]


class GenerationDetailDto(CamelModel):
    generation_id: str
    mode: GenerationMode
    spec_id: str | None
    frontend_spec_id: str | None
    project_name: str | None
    status: GenerationStatus
    lanes: dict[str, str]
    current_step: str | None
    engine: str
    options: dict[str, Any]
    repair_attempts: int
    resume_count: int
    cancel_requested: bool
    validation: dict[str, str]
    steps: list[StepDto]
    usage: UsageTotalsDto
    artifacts: list[ArtifactDto]
    preview: PreviewDto | None
    frontend_preview: PreviewDto | None = None
    trace: dict[str, Any]
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_detail(cls, detail: "GenerationDetail") -> "GenerationDetailDto":
        generation = detail.generation
        invocations: dict[str | None, list[EngineInvocationDto]] = {}
        for invocation in detail.invocations:
            dto = EngineInvocationDto.model_validate(invocation.model_dump(mode="json"))
            invocations.setdefault(dto.node_run_id, []).append(dto)
        return cls(
            generation_id=generation.id,
            mode=generation.mode,
            spec_id=str(generation.spec_id) if generation.spec_id else None,
            frontend_spec_id=str(generation.frontend_spec_id) if generation.frontend_spec_id else None,
            project_name=detail.project_name,
            status=generation.status,
            lanes=generation.lanes,
            current_step=generation.current_step,
            engine=generation.engine,
            options=generation.options,
            repair_attempts=generation.repair_attempts,
            resume_count=generation.resume_count,
            cancel_requested=generation.cancel_requested,
            validation=detail.validation,
            steps=[
                StepDto(
                    id=str(step.id),
                    node=step.node,
                    attempt=step.attempt,
                    status=step.status,
                    summary=step.summary,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                    invocations=invocations.get(str(step.id), []),
                )
                for step in detail.steps
            ],
            usage=UsageTotalsDto(
                input_tokens=sum(i.input_tokens or 0 for i in detail.invocations),
                output_tokens=sum(i.output_tokens or 0 for i in detail.invocations),
                cost_usd=round(sum(i.cost_usd or 0.0 for i in detail.invocations), 6),
            ),
            artifacts=[ArtifactDto.from_entity(a) for a in detail.artifacts],
            preview=PreviewDto.from_entity(detail.preview) if detail.preview else None,
            frontend_preview=PreviewDto.from_entity(detail.frontend_preview) if detail.frontend_preview else None,
            trace={"traceId": generation.trace_id, "langsmithUrl": generation.langsmith_run_url},
            error=generation.error_summary,
            created_at=generation.created_at,
            started_at=generation.started_at,
            finished_at=generation.finished_at,
        )


class GenerationSummaryDto(CamelModel):
    generation_id: str
    mode: GenerationMode
    project_name: str | None
    status: GenerationStatus
    lanes: dict[str, str]
    current_step: str | None
    engine: str
    repair_attempts: int
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    frontend_preview: PreviewDto | None = None


class GenerationPageDto(CamelModel):
    items: list[GenerationSummaryDto]
    next_cursor: str | None


class CancelGenerationResponseDto(CamelModel):
    generation_id: str
    status: GenerationStatus
    cancel_requested: bool
