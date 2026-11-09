from fastapi import APIRouter

from src.configs import config
from src.images.factory import photos_enabled
from src.modules.auth.presenter import CurrentUserDep
from src.modules.engines.presenter.dtos import EngineDto, ListEnginesResponseDto, MediaProvidersDto
from src.modules.engines.usecases import ListEnginesUsecaseDep
from src.videos.factory import enabled_providers

engine_router = APIRouter(prefix="/api/v1/engines", tags=["engines"])


@engine_router.get("", response_model=ListEnginesResponseDto)
async def list_engines(_: CurrentUserDep, usecase: ListEnginesUsecaseDep) -> ListEnginesResponseDto:
    catalog = await usecase.execute()
    return ListEnginesResponseDto(
        default=catalog.default,
        draft_default=catalog.draft_default,
        engines=[
            EngineDto(name=e.name, available=e.available, reason=e.reason, drafts_only=e.drafts_only, drafts=e.drafts)
            for e in catalog.engines
        ],
        reported_by_worker=catalog.reported_by_worker,
        reported_at=catalog.reported_at,
        media=MediaProvidersDto(
            photos=config.image_provider if photos_enabled() else "none", videos=enabled_providers()
        ),
    )
