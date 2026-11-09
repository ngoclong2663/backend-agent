from datetime import datetime

from src.libs.dtos import CamelModel


class EngineDto(CamelModel):
    name: str
    available: bool
    reason: str | None = None
    drafts_only: bool = False
    drafts: bool = False  # Story 22.8: may draft specs (the draft engine picker lists only these)


class MediaProvidersDto(CamelModel):
    """Epic 27 / 31: which photo and video providers the agent has on (the settings page shows them)."""

    photos: str  # gemini | unsplash | fake | none
    videos: list[str]  # youtube, pixabay (those with a key)


class ListEnginesResponseDto(CamelModel):
    default: str
    draft_default: str | None
    engines: list[EngineDto]
    reported_by_worker: bool
    reported_at: datetime | None = None
    media: MediaProvidersDto | None = None
