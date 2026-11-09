import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status

from src.configs import config
from src.libs.http import read_body_limited
from src.modules.auth.presenter import CurrentUserDep
from src.modules.shared.domain.backend_spec import LATEST_SPEC_VERSION
from src.modules.shared.domain.enums import SpecSource
from src.modules.shared.domain.frontend_spec import LATEST_FRONTEND_SPEC_VERSION
from src.modules.specs.presenter.dtos import (
    CheckSpecPairRequestDto,
    CreateSpecDraftRequestDto,
    CreateSpecDraftResponseDto,
    CreateSpecResponseDto,
    FrontendImportResponseDto,
    GetFrontendSpecResponseDto,
    GetSpecDraftResponseDto,
    GetSpecResponseDto,
    RegenerateAssetRequestDto,
    SpecIssueDto,
    SpecPairReportDto,
    ValidationReportDto,
)
from src.modules.specs.usecases import (
    CheckSpecPairUsecaseDep,
    CreateFrontendSpecUsecaseDep,
    CreateSpecDraftUsecaseDep,
    CreateSpecUsecaseDep,
    DraftRequest,
    GetFrontendSpecSchemaUsecaseDep,
    GetFrontendSpecUsecaseDep,
    GetSpecDraftUsecaseDep,
    GetSpecSchemaUsecaseDep,
    GetSpecUsecaseDep,
    ImportFrontendSpecUsecaseDep,
    RegenerateAssetUsecaseDep,
    ValidateFrontendSpecUsecaseDep,
    ValidateSpecUsecaseDep,
)

spec_router = APIRouter(prefix="/api/v1/specs", tags=["specs"])
spec_import_router = APIRouter(prefix="/api/v1/spec-imports", tags=["specs"])

# The body is read raw (to keep the submitted spec byte-for-byte and report malformed JSON ourselves),
# so the request schema is declared for the docs only.
_RAW_JSON_BODY = {"requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}}


@spec_router.get("/schema", response_model=dict[str, Any])
async def get_spec_schema(
    _: CurrentUserDep,
    usecase: GetSpecSchemaUsecaseDep,
    version: Annotated[str, Query()] = LATEST_SPEC_VERSION,
) -> dict[str, Any]:
    return await usecase.execute(version)


@spec_router.post("/validate", response_model=ValidationReportDto, openapi_extra=_RAW_JSON_BODY)
async def validate_spec(request: Request, _: CurrentUserDep, usecase: ValidateSpecUsecaseDep) -> ValidationReportDto:
    raw = await read_body_limited(request, config.spec_max_bytes)
    return ValidationReportDto.from_domain(await usecase.execute(raw))


@spec_router.post(
    "",
    response_model=CreateSpecResponseDto,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_RAW_JSON_BODY,
)
async def create_spec(
    request: Request,
    user: CurrentUserDep,
    usecase: CreateSpecUsecaseDep,
    source: Annotated[SpecSource, Query()] = SpecSource.JSON,
) -> CreateSpecResponseDto:
    raw = await read_body_limited(request, config.spec_max_bytes)
    created = await usecase.execute(raw, user.id, source)
    return CreateSpecResponseDto(
        spec_id=str(created.spec.id),
        spec_version=created.spec.spec_version,
        warnings=[SpecIssueDto.from_domain(issue) for issue in created.warnings],
    )


@spec_router.get("/{spec_id}", response_model=GetSpecResponseDto)
async def get_spec(spec_id: uuid.UUID, user: CurrentUserDep, usecase: GetSpecUsecaseDep) -> GetSpecResponseDto:
    return GetSpecResponseDto.from_entity(await usecase.execute(spec_id, user))


@spec_import_router.post("/frontend", response_model=FrontendImportResponseDto, openapi_extra=_RAW_JSON_BODY)
async def import_frontend_spec(
    request: Request,
    _: CurrentUserDep,
    usecase: ImportFrontendSpecUsecaseDep,
    include_admin_crud: Annotated[bool, Query(alias="includeAdminCrud")] = True,
) -> FrontendImportResponseDto:
    raw = await read_body_limited(request, config.frontend_import_max_bytes)
    return FrontendImportResponseDto.from_domain(await usecase.execute(raw, include_admin_crud))


# -- FrontendSpecs (Story 12.1, 12.5) ----------------------------------------------------------------------------

design_plugin_router = APIRouter(prefix="/api/v1/design-plugins", tags=["frontend-specs"])


@design_plugin_router.get("")
async def list_design_plugins(_: CurrentUserDep) -> dict[str, list[dict[str, Any]]]:
    """Epic 30 (Story 30.2): the ready design plugins by kind (name, label, when to choose it, archetypes, needs,
    fallback, family, preview), for the review's Design panel; no hand-kept list in the UI."""
    from src.modules.shared.domain.frontend_spec.design_registry import registry_digest

    return registry_digest()


frontend_spec_router = APIRouter(prefix="/api/v1/frontend-specs", tags=["frontend-specs"])


@frontend_spec_router.get("/schema", response_model=dict[str, Any])
async def get_frontend_spec_schema(
    _: CurrentUserDep,
    usecase: GetFrontendSpecSchemaUsecaseDep,
    version: Annotated[str, Query()] = LATEST_FRONTEND_SPEC_VERSION,
) -> dict[str, Any]:
    return await usecase.execute(version)


@frontend_spec_router.post("/validate", response_model=ValidationReportDto, openapi_extra=_RAW_JSON_BODY)
async def validate_frontend_spec(
    request: Request,
    user: CurrentUserDep,
    usecase: ValidateFrontendSpecUsecaseDep,
    backend_spec_id: Annotated[uuid.UUID | None, Query(alias="backendSpecId")] = None,
) -> ValidationReportDto:
    """FrontendSpec validation; with `backendSpecId` also the consistency check against that BackendSpec's API
    contract (dynamic mode). Consistency issues carry `backendPath`, a pointer into the BackendSpec."""
    raw = await read_body_limited(request, config.spec_max_bytes)
    return ValidationReportDto.from_domain(await usecase.execute(raw, user, backend_spec_id))


@frontend_spec_router.post("/check-pair", response_model=SpecPairReportDto)
async def check_spec_pair(
    body: CheckSpecPairRequestDto, _: CurrentUserDep, usecase: CheckSpecPairUsecaseDep
) -> SpecPairReportDto:
    """Consistency of an unsaved FrontendSpec + BackendSpec pair (Story 9.7a), so editor text can be checked
    before either is stored. Only the consistency issues are returned; each spec's own errors come from its
    `/validate`. Issues carry `path` (FrontendSpec) and, where known, `backendPath` (BackendSpec)."""
    result = await usecase.execute(body.frontend_spec, body.backend_spec)
    report = ValidationReportDto.from_domain(result.report)
    return SpecPairReportDto(**report.model_dump(), checked=result.checked, contract=result.contract)


@frontend_spec_router.post(
    "",
    response_model=CreateSpecResponseDto,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_RAW_JSON_BODY,
)
async def create_frontend_spec(
    request: Request, user: CurrentUserDep, usecase: CreateFrontendSpecUsecaseDep
) -> CreateSpecResponseDto:
    raw = await read_body_limited(request, config.spec_max_bytes)
    created = await usecase.execute(raw, user.id)
    return CreateSpecResponseDto(
        spec_id=str(created.spec.id),
        spec_version=created.spec.spec_version,
        warnings=[SpecIssueDto.from_domain(issue) for issue in created.warnings],
    )


@frontend_spec_router.get("/{spec_id}", response_model=GetFrontendSpecResponseDto)
async def get_frontend_spec(
    spec_id: uuid.UUID, user: CurrentUserDep, usecase: GetFrontendSpecUsecaseDep
) -> GetFrontendSpecResponseDto:
    return GetFrontendSpecResponseDto.from_entity(await usecase.execute(spec_id, user))


# -- Drafts (Stories 2.4, 12.4) ----------------------------------------------------------------------------------

spec_draft_router = APIRouter(prefix="/api/v1/spec-drafts", tags=["spec-drafts"])


@spec_draft_router.post("", response_model=CreateSpecDraftResponseDto, status_code=status.HTTP_202_ACCEPTED)
async def create_spec_draft(
    body: CreateSpecDraftRequestDto, user: CurrentUserDep, usecase: CreateSpecDraftUsecaseDep
) -> CreateSpecDraftResponseDto:
    """Queues a draft job: a requirement (plain text or Markdown, up to 64 KB) becomes a BackendSpec (`backend`),
    a FrontendSpec (`static`) or both (`dynamic`). Poll `GET /spec-drafts/{id}`; the draft is never submitted."""
    draft = await usecase.execute(user, DraftRequest(**body.model_dump()))
    return CreateSpecDraftResponseDto(draft_id=str(draft.id), status=draft.status)


@spec_draft_router.get("/{draft_id}", response_model=GetSpecDraftResponseDto)
async def get_spec_draft(
    draft_id: uuid.UUID, user: CurrentUserDep, usecase: GetSpecDraftUsecaseDep
) -> GetSpecDraftResponseDto:
    return GetSpecDraftResponseDto.from_entity(await usecase.execute(draft_id, user))


@spec_draft_router.post("/{draft_id}/assets/{asset_id}/regenerate", response_model=dict[str, Any])
async def regenerate_draft_asset(
    draft_id: uuid.UUID,
    asset_id: str,
    user: CurrentUserDep,
    usecase: RegenerateAssetUsecaseDep,
    body: RegenerateAssetRequestDto | None = None,
) -> dict[str, Any]:
    prompt = body.prompt if body else None
    style = body.style if body else None
    return await usecase.execute(draft_id, asset_id, user, prompt=prompt, style=style)
