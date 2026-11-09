"""YouTube (Epic 31, Story 31.1): the Data API v3's `search.list` (100 units) with the epic's filters, then
`videos.list` (1 unit) for the duration and whether the video can be embedded; a daily unit counter kept locally
(the quota resets at midnight Pacific time) refuses a search when the margin is spent.

What the YouTube API Services Terms and Developer Policies require, as read on 2026-11-09 and applied here:
- play in YouTube's embedded player, never a download or a re-host (`youtube-nocookie.com/embed/<id>`, Story 31.3);
- show the video's title and its channel with a link back to YouTube (`credit`), no YouTube branding of our own;
- keep API data fresh: ids and metadata are cached for a day, availability is checked again when a site is previewed
  (`available`, D6), and nothing is stored in the generated project but the id, the title and the channel;
- safe search on (`safeSearch=strict`), embeddable results only, the app's language as `relevanceLanguage`;
- one project's quota (10,000 units a day by default): a search costs 100, so the counter stops under `MARGIN`.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from src.configs import get_logger

from .cache import JsonCache, video_cache_dir
from .port import MAX_DURATION, Place, VideoCredit, VideoHit, VideoUnavailable

logger = get_logger(__name__)
API = "https://www.googleapis.com/youtube/v3"
SEARCH_UNITS = 100
LIST_UNITS = 1
DAILY_UNITS = 10_000
MARGIN = 600  # units left under which no search starts (a few list calls stay possible)
PACIFIC = ZoneInfo("America/Los_Angeles")
EMBED = "https://www.youtube-nocookie.com/embed/{id}"
WATCH = "https://www.youtube.com/watch?v={id}"


def _duration_seconds(iso: str) -> int | None:
    """`PT1H2M3S` → seconds."""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _today() -> str:
    return datetime.now(PACIFIC).strftime("%Y-%m-%d")


class YouTubeVideos:
    name = "youtube"

    def __init__(
        self,
        api_key: str,
        cache_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
        daily_units: int = DAILY_UNITS,
    ):
        self._key = api_key
        self._transport = transport
        self._timeout = timeout
        self._cache = JsonCache((cache_dir or video_cache_dir("youtube")) / "youtube.json")
        self.daily_units = daily_units
        self.requests = 0
        self.units = 0  # spent by this instance
        self.exhausted_reason: str | None = None

    # -- the quota (D4) ---------------------------------------------------------------------------------------------

    def units_today(self) -> int:
        state = self._cache.state()
        return int(state.get("units", 0)) if state.get("day") == _today() else 0

    def _spend(self, units: int) -> None:
        self.units += units
        self._cache.set_state(day=_today(), units=self.units_today() + units)

    def _affordable(self, units: int) -> bool:
        return self.units_today() + units <= self.daily_units - MARGIN

    # -- the API ----------------------------------------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any], units: int) -> dict[str, Any]:
        if self.exhausted_reason:
            raise VideoUnavailable(self.exhausted_reason)
        if not self._affordable(units):
            self.exhausted_reason = f"the YouTube quota margin is spent for today ({self.units_today()} units used)"
            raise VideoUnavailable(self.exhausted_reason)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                response = await client.get(f"{API}/{path}", params={**params, "key": self._key})
        except httpx.HTTPError as exc:
            raise VideoUnavailable(f"YouTube could not be reached ({type(exc).__name__})") from exc
        self.requests += 1
        if response.status_code == 403:
            reason = ""
            try:
                errors = response.json().get("error", {}).get("errors") or []
                reason = str(errors[0].get("reason", "")) if errors else ""
            except ValueError:
                pass
            self.exhausted_reason = (
                "the YouTube quota is exhausted (403 quotaExceeded)"
                if "quota" in reason.lower()
                else "YouTube refused the key (403)"
            )
            raise VideoUnavailable(self.exhausted_reason)
        if response.status_code >= 400:
            raise VideoUnavailable(f"YouTube answered {response.status_code}")
        self._spend(units)
        try:
            return response.json()
        except ValueError as exc:
            raise VideoUnavailable("YouTube answered something that is not JSON") from exc

    @staticmethod
    def _key_of(phrase: str, language: str, place: str) -> str:
        return f"{language}|{place}|{' '.join(phrase.lower().split())}"

    async def search(
        self, phrase: str, *, place: Place = "watch", language: str = "en", count: int = 5
    ) -> list[VideoHit]:
        """Embeddable, safe-search videos for the phrase (D2), their duration under the place's limit, with their
        channel as the credit; from the cache on the second call (no units spent)."""
        phrase = " ".join(phrase.split())[:100]
        if not phrase:
            raise VideoUnavailable("no search phrase")
        key = self._key_of(phrase, language, place)
        cached = self._cache.search(key)
        if cached is None:
            duration = "short" if MAX_DURATION[place] <= 240 else "medium"
            found = await self._get(
                "search",
                {
                    "part": "snippet",
                    "type": "video",
                    "videoEmbeddable": "true",
                    "safeSearch": "strict",
                    "videoDuration": duration,
                    "relevanceLanguage": language,
                    "maxResults": max(1, min(count, 10)),
                    "q": phrase,
                },
                SEARCH_UNITS,
            )
            ids = [item["id"]["videoId"] for item in found.get("items") or [] if (item.get("id") or {}).get("videoId")]
            details: dict[str, dict[str, Any]] = {}
            if ids:
                listed = await self._get(
                    "videos", {"part": "contentDetails,status,snippet", "id": ",".join(ids)}, LIST_UNITS
                )
                details = {item["id"]: item for item in listed.get("items") or []}
            cached = []
            for item in found.get("items") or []:
                video_id = (item.get("id") or {}).get("videoId")
                detail = details.get(video_id or "")
                if not video_id or detail is None:
                    continue
                if not (detail.get("status") or {}).get("embeddable", False):
                    continue
                snippet = detail.get("snippet") or item.get("snippet") or {}
                thumbs = snippet.get("thumbnails") or {}
                poster = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
                cached.append(
                    {
                        "id": video_id,
                        "title": snippet.get("title") or "",
                        "channel": snippet.get("channelTitle") or "",
                        "channelId": snippet.get("channelId") or "",
                        "duration": _duration_seconds((detail.get("contentDetails") or {}).get("duration", "")),
                        "poster": poster,
                    }
                )
            self._cache.remember(key, cached)
        hits = []
        for item in cached:
            if item.get("duration") and item["duration"] > MAX_DURATION[place]:
                continue
            credit = VideoCredit(
                provider="youtube",
                name=item.get("channel") or "YouTube",
                source_url=WATCH.format(id=item["id"]),
                profile_url=f"https://www.youtube.com/channel/{item['channelId']}" if item.get("channelId") else None,
                title=item.get("title"),
            )
            hits.append(
                VideoHit(
                    provider="youtube",
                    id=item["id"],
                    title=item.get("title") or "",
                    credit=credit,
                    duration=item.get("duration"),
                    poster=item.get("poster"),
                    page=WATCH.format(id=item["id"]),
                    url=EMBED.format(id=item["id"]),
                )
            )
        if not hits:
            raise VideoUnavailable(f"no YouTube video for '{phrase}'")
        return hits

    async def available(self, ids: list[str]) -> dict[str, bool]:
        """Whether each video still exists and can be embedded (D6; one `videos.list` call, 1 unit)."""
        if not ids:
            return {}
        try:
            listed = await self._get("videos", {"part": "status", "id": ",".join(ids[:50])}, LIST_UNITS)
        except VideoUnavailable:
            return {video_id: True for video_id in ids}  # unknown: not a reason to drop them
        found = {item["id"]: bool((item.get("status") or {}).get("embeddable")) for item in listed.get("items") or []}
        return {video_id: found.get(video_id, False) for video_id in ids}
