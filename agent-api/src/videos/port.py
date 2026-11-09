"""The video provider port (Epic 31, Story 31.1): a phrase and a place → one video with its credit.

Two kinds of hit (the epic's table): a `youtube` hit is embedded in YouTube's own player (a facade, loaded on play);
a `pixabay` hit is an MP4 file our own `<video>` plays (a hero background loop, a seeded video field). Every hit
carries the credit the provider asks for (D5). A provider that has nothing (no key, no quota, an error) raises
`VideoUnavailable` with the reason; the draft goes on (D6 of Epic 27 holds here too).
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

Place = Literal["watch", "background", "seed"]
# How long a clip may be per place (seconds): a background loops a few seconds, a card the same; a watched video
# is anything the provider's "short" filter gives (under four minutes on YouTube)
MAX_DURATION: dict[str, int] = {"background": 45, "seed": 240, "watch": 1200}


class VideoUnavailable(Exception):
    """No video: no key, out of quota or requests, refused, no result, or the network."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class VideoCredit:
    provider: Literal["youtube", "pixabay"]
    name: str  # the channel (YouTube) or the author (Pixabay)
    source_url: str  # the video's own page
    profile_url: str | None = None  # the channel or the author's page
    title: str | None = None


@dataclass
class VideoHit:
    provider: Literal["youtube", "pixabay"]
    id: str
    title: str
    credit: VideoCredit
    duration: int | None = None  # seconds
    # YouTube: the video id is enough; Pixabay: the chosen file
    url: str | None = None
    poster: str | None = None  # a thumbnail URL (YouTube's may be hotlinked; Pixabay's is downloaded, Story 31.2)
    width: int | None = None
    height: int | None = None
    size: int | None = None  # bytes of the chosen file
    page: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def asset_fields(self) -> dict[str, Any]:
        """What a FrontendSpec `video` asset keeps of the hit (code-only fields, Story 31.3)."""
        out: dict[str, Any] = {"provider": self.provider, "id": self.id, "title": self.title}
        for key in ("url", "poster", "width", "height", "duration"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    def credit_fields(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self.credit).items() if v is not None}


class IVideoProvider(Protocol):
    name: str

    async def search(self, phrase: str, *, place: Place, language: str = "en", count: int = 5) -> list[VideoHit]: ...

    async def available(self, ids: list[str]) -> dict[str, bool]: ...
