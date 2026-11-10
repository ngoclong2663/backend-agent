from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sse_starlette import EventSourceResponse

from src.modules.auth.presenter import AdminUserDep, CurrentUserDep
from src.modules.generations.presenter.dtos import (
    ArtifactDto,
    ArtifactListDto,
    CancelGenerationResponseDto,
    ContinueGenerationRequestDto,
    CreateGenerationRequestDto,
    CreateGenerationResponseDto,
    GenerationDetailDto,
    GenerationPageDto,
    GenerationSummaryDto,
)
from src.modules.generations.usecases import (
    ArtifactUsecaseDep,
    BrowseFilesUsecaseDep,
    CancelGenerationUsecaseDep,
    ContinueGenerationInputs,
    ContinueGenerationUsecaseDep,
    CreateGenerationUsecaseDep,
    GenerationInputs,
    GetGenerationUsecaseDep,
    GetTraceUsecaseDep,
    GetValidationUsecaseDep,
    GetWorkflowGraphUsecaseDep,
    ListGenerationsUsecaseDep,
    RequirementInput,
    StreamGenerationEventsUsecaseDep,
)
from src.modules.generations.usecases.screen_feedback_usecase import ScreenFeedbackUsecaseDep, plugin_requests
from src.modules.previews.presenter.dtos import PreviewDto
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus

generation_router = APIRouter(prefix="/api/v1/generations", tags=["generations"])


@generation_router.post("", response_model=CreateGenerationResponseDto, status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    body: CreateGenerationRequestDto,
    user: CurrentUserDep,
    usecase: CreateGenerationUsecaseDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> CreateGenerationResponseDto:
    generation = await usecase.execute(
        user,
        GenerationInputs(
            mode=body.mode,
            requirement=RequirementInput(**body.requirement.model_dump()) if body.requirement else None,
            backend_spec=body.backend_spec,
            spec_id=body.spec_id,
            frontend_spec=body.frontend_spec,
            frontend_spec_id=body.frontend_spec_id,
            draft_id=body.draft_id,
        ),
        body.options.model_dump(by_alias=True),
        idempotency_key,
    )
    return CreateGenerationResponseDto(
        generation_id=generation.id, status=generation.status, created_at=generation.created_at
    )


@generation_router.post(
    "/{generation_id}/continue", response_model=CreateGenerationResponseDto, status_code=status.HTTP_202_ACCEPTED
)
async def continue_generation(
    generation_id: str,
    body: ContinueGenerationRequestDto,
    user: CurrentUserDep,
    usecase: ContinueGenerationUsecaseDep,
) -> CreateGenerationResponseDto:
    generation = await usecase.execute(
        generation_id,
        user,
        ContinueGenerationInputs(
            backend_spec=body.backend_spec,
            frontend_spec=body.frontend_spec,
        ),
    )
    return CreateGenerationResponseDto(
        generation_id=generation.id, status=generation.status, created_at=generation.created_at
    )


@generation_router.get("", response_model=GenerationPageDto)
async def list_generations(
    user: CurrentUserDep,
    usecase: ListGenerationsUsecaseDep,
    status_filter: Annotated[GenerationStatus | None, Query(alias="status")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    scope: Annotated[str, Query(pattern="^(mine|all)$")] = "mine",
) -> GenerationPageDto:
    page = await usecase.execute(user, status_filter, cursor, limit, all_owners=scope == "all")
    return GenerationPageDto(
        items=[
            GenerationSummaryDto(
                generation_id=item.generation.id,
                mode=item.generation.mode,
                project_name=item.project_name,
                status=item.generation.status,
                lanes=item.generation.lanes,
                current_step=item.generation.current_step,
                engine=item.generation.engine,
                repair_attempts=item.generation.repair_attempts,
                created_at=item.generation.created_at,
                started_at=item.generation.started_at,
                finished_at=item.generation.finished_at,
                frontend_preview=PreviewDto.from_entity(item.frontend_preview) if item.frontend_preview else None,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@generation_router.get("/graph", response_model=dict[str, Any])
async def get_workflow_graph(
    _: CurrentUserDep,
    usecase: GetWorkflowGraphUsecaseDep,
    mode: Annotated[GenerationMode, Query()] = GenerationMode.BACKEND,
) -> dict[str, Any]:
    return await usecase.execute(mode)


@generation_router.get("/plugin-requests", response_model=dict[str, Any])
async def list_plugin_requests(user: AdminUserDep) -> dict[str, Any]:
    """Epic 33 (Story 33.14): what users asked of their screens that no plugin could do, newest first."""
    return {"items": plugin_requests()}


@generation_router.get("/{generation_id}", response_model=GenerationDetailDto)
async def get_generation(generation_id: str, user: CurrentUserDep, usecase: GetGenerationUsecaseDep):
    return GenerationDetailDto.from_detail(await usecase.execute(generation_id, user))


@generation_router.post(
    "/{generation_id}/cancel", response_model=CancelGenerationResponseDto, status_code=status.HTTP_202_ACCEPTED
)
async def cancel_generation(
    generation_id: str, user: CurrentUserDep, usecase: CancelGenerationUsecaseDep
) -> CancelGenerationResponseDto:
    generation = await usecase.execute(generation_id, user)
    return CancelGenerationResponseDto(
        generation_id=generation.id, status=generation.status, cancel_requested=generation.cancel_requested
    )


class ScreenFeedbackRequestDto(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    target: str | None = Field(default=None, max_length=200)  # `<page id>/<section id>` (`data-bga-section`)
    comment: str = Field(min_length=1, max_length=1000)


@generation_router.post("/{generation_id}/feedback", response_model=dict[str, Any])
async def screen_feedback(
    generation_id: str, body: ScreenFeedbackRequestDto, user: CurrentUserDep, usecase: ScreenFeedbackUsecaseDep
) -> dict[str, Any]:
    """Epic 33 (Story 33.14): a comment on a screen, turned into changes of the app's choices (the revised
    FrontendSpec to generate again), a data change, or a plugin request."""
    return await usecase.execute(generation_id, user, body.target, body.comment)


@generation_router.get("/{generation_id}/events")
async def stream_generation_events(
    generation_id: str,
    user: CurrentUserDep,
    usecase: StreamGenerationEventsUsecaseDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> EventSourceResponse:
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else (after or 0)
    return EventSourceResponse(await usecase.execute(generation_id, user, start), ping=15)


@generation_router.get("/{generation_id}/validation", response_model=dict[str, Any])
async def get_validation(generation_id: str, user: CurrentUserDep, usecase: GetValidationUsecaseDep) -> dict[str, Any]:
    return await usecase.execute(generation_id, user)


@generation_router.get("/{generation_id}/artifacts", response_model=ArtifactListDto)
async def list_artifacts(generation_id: str, user: CurrentUserDep, usecase: ArtifactUsecaseDep) -> ArtifactListDto:
    return ArtifactListDto(items=[ArtifactDto.from_entity(a) for a in await usecase.list(generation_id, user)])


@generation_router.get("/{generation_id}/artifacts/{artifact_id}", response_class=FileResponse)
async def download_artifact(
    generation_id: str, artifact_id: str, user: CurrentUserDep, usecase: ArtifactUsecaseDep
) -> FileResponse:
    artifact, path = await usecase.file(generation_id, artifact_id, user)
    return FileResponse(path, media_type=artifact.content_type, filename=artifact.name)


@generation_router.get("/{generation_id}/files", response_model=dict[str, Any])
async def browse_files(
    generation_id: str,
    user: CurrentUserDep,
    usecase: BrowseFilesUsecaseDep,
    path: Annotated[str, Query(max_length=512)] = "",
    source: Literal["backend", "frontend"] = "backend",
) -> dict[str, Any]:
    return await usecase.execute(generation_id, user, path, source)


@generation_router.get("/{generation_id}/trace", response_model=dict[str, Any])
async def get_trace(generation_id: str, user: CurrentUserDep, usecase: GetTraceUsecaseDep) -> dict[str, Any]:
    """Span tree (node, engine, model call, tool, check, sandbox) plus usage rollups; spans of a running job have
    `endedAt: null`. `langsmithUrl` deep-links to the LangSmith trace when tracing is on."""
    return await usecase.trace(generation_id, user)


@generation_router.get("/{generation_id}/trace/spans/{span_id}/output", response_model=dict[str, Any])
async def get_span_output(
    generation_id: str,
    span_id: str,
    user: CurrentUserDep,
    usecase: GetTraceUsecaseDep,
    stream: Annotated[Literal["stdout", "stderr"], Query()] = "stdout",
    tail: Annotated[int, Query(ge=1, le=20000)] = 500,
) -> dict[str, Any]:
    return await usecase.output(generation_id, span_id, user, stream, tail)


@generation_router.get("/{generation_id}/usage", response_model=dict[str, Any])
async def get_generation_usage(generation_id: str, user: CurrentUserDep, usecase: GetTraceUsecaseDep) -> dict[str, Any]:
    return await usecase.usage(generation_id, user)
