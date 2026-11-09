"""Pixabay (Epic 31, Story 31.2): stock video files under the Pixabay Content License, searched with `api/videos/`.

What Pixabay's API documentation requires (read 2026-11-08, quoted in the story) and how it is kept here:
- "Videos may be embedded directly in your applications": the chosen file is linked, never copied (unless
  `PIXABAY_STORE_VIDEOS` asks to store it, a later measurement);
- images may not be hotlinked: the poster thumbnail is downloaded once into the asset cache and shipped with the
  site or uploaded with the app's seed (`poster_bytes`);
- 100 requests per 60 s per key: `X-RateLimit-Remaining` is read and a margin stops the searching;
- "requests must be cached for 24 hours": every search is kept a day, keyed by phrase, language and place;
- "show your users where the images and videos are from": the credit "Video by <user> on Pixabay" with links;
- Cloudflare in front answers curl's default client name with a challenge: a descriptive `User-Agent` is sent.
"""

from pathlib import Path
from typing import Any

import httpx

from src.configs import get_logger

from .cache import JsonCache, video_cache_dir
from .port import MAX_DURATION, Place, VideoCredit, VideoHit, VideoUnavailable

logger = get_logger(__name__)
API = "https://pixabay.com/api/videos/"
SITE = "https://pixabay.com/"
MARGIN = 10  # requests left under which no search starts
# Per place: the smallest width that fits it, and the byte budget of the file (Story 31.2)
MIN_WIDTH: dict[str, int] = {"background": 1280, "watch": 1280, "seed": 960}
BYTE_BUDGET: dict[str, int] = {"background": 6_000_000, "watch": 12_000_000, "seed": 12_000_000}
SIZES = ("tiny", "small", "medium", "large")


def _orientation(width: int, height: int) -> str:
    if width > height * 1.1:
        return "landscape"
    if height > width * 1.1:
        return "portrait"
    return "square"


def choose_file(hit: dict[str, Any], place: Place) -> dict[str, Any] | None:
    """The smallest of the hit's files at least as wide as the place needs and under its byte budget (a 4K source's
    `tiny` is 1280×720 and may be too heavy: files are chosen by their numbers, never by their name)."""
    files = hit.get("videos") or {}
    candidates = []
    for name in SIZES:
        item = files.get(name) or {}
        if not item.get("url") or not item.get("width"):
            continue
        candidates.append({**item, "name": name})
    fitting = [
        item
        for item in sorted(candidates, key=lambda item: (int(item.get("size") or 0), int(item["width"])))
        if int(item["width"]) >= MIN_WIDTH[place] and 0 < int(item.get("size") or 0) <= BYTE_BUDGET[place]
    ]
    return fitting[0] if fitting else None


class PixabayVideos:
    name = "pixabay"

    def __init__(
        self,
        api_key: str,
        user_agent: str,
        cache_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ):
        self._key = api_key
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._transport = transport
        self._timeout = timeout
        self._dir = cache_dir or video_cache_dir("pixabay")
        self._cache = JsonCache(self._dir / "pixabay.json")
        self.requests = 0
        self.remaining: int | None = None
        self.exhausted_reason: str | None = None

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        if self.exhausted_reason:
            raise VideoUnavailable(self.exhausted_reason)
        if self.remaining is not None and self.remaining <= MARGIN:
            self.exhausted_reason = "out of Pixabay requests this minute"
            raise VideoUnavailable(self.exhausted_reason)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=self._headers, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise VideoUnavailable(f"Pixabay could not be reached ({type(exc).__name__})") from exc
        self.requests += 1
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.remaining = int(remaining)
        if response.status_code == 429:
            self.exhausted_reason = (
                "Pixabay's front answered a challenge (429): the client name was refused"
                if response.headers.get("cf-mitigated")
                else "out of Pixabay requests this minute (429)"
            )
            raise VideoUnavailable(self.exhausted_reason)
        if response.status_code in (400, 401, 403):
            self.exhausted_reason = f"Pixabay refused the key ({response.status_code})"
            raise VideoUnavailable(self.exhausted_reason)
        if response.status_code >= 400:
            raise VideoUnavailable(f"Pixabay answered {response.status_code}")
        return response

    @staticmethod
    def _key_of(phrase: str, language: str, place: str) -> str:
        return f"{language}|{place}|{' '.join(phrase.lower().split())}"

    async def search(
        self, phrase: str, *, place: Place = "seed", language: str = "en", count: int = 5
    ) -> list[VideoHit]:
        """Film clips (`video_type=film`, safe search) for the phrase whose orientation and duration fit the place,
        each with the file chosen by width and size, its poster thumbnail and the credit; cached for a day."""
        phrase = " ".join(phrase.split())[:100]
        if not phrase:
            raise VideoUnavailable("no search phrase")
        key = self._key_of(phrase, language, place)
        cached = self._cache.search(key)
        if cached is None:
            response = await self._get(
                API,
                {
                    "key": self._key,
                    "q": phrase,
                    "lang": language[:2],
                    "video_type": "film",
                    "safesearch": "true",
                    "min_width": MIN_WIDTH[place],
                    "per_page": max(3, min(count * 3, 20)),
                    "order": "popular",
                },
            )
            try:
                items = response.json().get("hits") or []
            except ValueError as exc:
                raise VideoUnavailable("Pixabay answered something that is not JSON") from exc
            cached = []
            for item in items:
                large = (item.get("videos") or {}).get("large") or (item.get("videos") or {}).get("medium") or {}
                width, height = int(large.get("width") or 0), int(large.get("height") or 0)
                cached.append(
                    {
                        "id": str(item.get("id")),
                        "pageURL": item.get("pageURL"),
                        "tags": item.get("tags") or "",
                        "duration": item.get("duration"),
                        "user": item.get("user") or "Unknown",
                        "user_id": item.get("user_id"),
                        "orientation": _orientation(width, height) if width and height else "landscape",
                        "videos": item.get("videos") or {},
                    }
                )
            self._cache.remember(key, cached)
        wanted = "portrait" if place == "seed-portrait" else "landscape"
        hits = []
        for item in cached:
            if item.get("orientation") != wanted:
                continue
            if item.get("duration") and int(item["duration"]) > MAX_DURATION[place]:
                continue
            chosen = choose_file(item, place)
            if chosen is None:
                continue
            credit = VideoCredit(
                provider="pixabay",
                name=str(item.get("user") or "Unknown"),
                source_url=str(item.get("pageURL") or SITE),
                profile_url=f"https://pixabay.com/users/{item.get('user')}-{item.get('user_id')}/"
                if item.get("user_id")
                else SITE,
                title=str(item.get("tags") or "").split(",")[0].strip() or None,
            )
            hits.append(
                VideoHit(
                    provider="pixabay",
                    id=item["id"],
                    title=str(item.get("tags") or "")[:120],
                    credit=credit,
                    duration=int(item["duration"]) if item.get("duration") else None,
                    url=chosen["url"],
                    poster=chosen.get("thumbnail"),
                    width=int(chosen["width"]),
                    height=int(chosen.get("height") or 0) or None,
                    size=int(chosen.get("size") or 0) or None,
                    page=item.get("pageURL"),
                    extra={"file": chosen["name"]},
                )
            )
        if not hits:
            raise VideoUnavailable(f"no Pixabay clip fits '{phrase}' for a {place}")
        return hits

    async def poster_bytes(self, hit: VideoHit) -> bytes | None:
        """The poster thumbnail, downloaded once into the asset cache (Pixabay's images may not be hotlinked)."""
        if not hit.poster:
            return None
        target = self._dir / "posters" / f"{hit.id}.jpg"
        if target.is_file():
            return target.read_bytes()
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(hit.poster, headers=self._headers, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or not response.content:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return response.content

    async def available(self, ids: list[str]) -> dict[str, bool]:
        """Whether each file link still answers (a HEAD each; a dead link is the place's fallback, D6)."""
        out: dict[str, bool] = {}
        for url in ids:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    response = await client.head(url, headers=self._headers, follow_redirects=True)
                out[url] = response.status_code < 400
            except httpx.HTTPError:
                out[url] = False
        return out
