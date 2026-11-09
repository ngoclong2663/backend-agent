"""Epic 31 (Stories 31.1, 31.2): the YouTube and Pixabay providers against recorded responders on httpx's
MockTransport (no network): the filters, embeddable results only, the file chosen by width and byte budget, the
caches, the quota and request limits, a challenge page, and the errors that end a search without ending the draft."""

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from src.videos.pixabay import PixabayVideos, choose_file
from src.videos.port import VideoUnavailable
from src.videos.youtube import YouTubeVideos, _duration_seconds

# -- YouTube ----------------------------------------------------------------------------------------------------------


def _search_item(video_id: str) -> dict:
    snippet = {"title": f"Talk {video_id}", "channelTitle": "Chan"}
    return {"id": {"kind": "youtube#video", "videoId": video_id}, "snippet": snippet}


def _video_item(video_id: str, embeddable: bool = True, duration: str = "PT3M20S") -> dict:
    return {
        "id": video_id,
        "status": {"embeddable": embeddable},
        "contentDetails": {"duration": duration},
        "snippet": {
            "title": f"Talk {video_id}",
            "channelTitle": "Chan",
            "channelId": "UC123",
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        },
    }


class _YouTubeApi:
    """TESTING ONLY (docs/development/test-doubles.md): the Data API's search and videos answers."""

    def __init__(self, status: int = 200, embeddable: dict[str, bool] | None = None):
        self.calls: list[httpx.Request] = []
        self.status = status
        self.embeddable = embeddable or {"v1": True, "v2": False, "v3": True}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status == 403:
            return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [_search_item(v) for v in self.embeddable]})
        ids = parse_qs(request.url.query.decode())["id"][0].split(",")
        known = [v for v in ids if v in self.embeddable]  # an id YouTube no longer has is not in the answer
        return httpx.Response(200, json={"items": [_video_item(v, self.embeddable[v]) for v in known]})

    @property
    def searches(self):
        return [c for c in self.calls if c.url.path.endswith("/search")]


def _youtube(tmp_path, api) -> YouTubeVideos:
    return YouTubeVideos("yt-key", cache_dir=tmp_path / "yt", transport=httpx.MockTransport(api))


def test_youtube_searches_with_the_epics_filters_keeps_embeddable_videos_and_credits_them(tmp_path):
    api = _YouTubeApi()
    provider = _youtube(tmp_path, api)
    hits = asyncio.run(provider.search("ceramics wheel throwing", place="watch", language="en"))
    params = parse_qs(api.searches[0].url.query.decode())
    assert params["type"] == ["video"] and params["videoEmbeddable"] == ["true"]
    assert params["safeSearch"] == ["strict"] and params["relevanceLanguage"] == ["en"]
    assert params["videoDuration"] == ["medium"]
    assert [hit.id for hit in hits] == ["v1", "v3"], "the unembeddable one is filtered out"
    assert hits[0].credit.name == "Chan" and hits[0].credit.source_url == "https://www.youtube.com/watch?v=v1"
    assert hits[0].credit.profile_url == "https://www.youtube.com/channel/UC123" and hits[0].duration == 200
    assert hits[0].poster.endswith("/v1/hqdefault.jpg")
    assert hits[0].url == "https://www.youtube-nocookie.com/embed/v1"
    assert provider.units == 101 and provider.units_today() == 101


def test_youtube_answers_from_the_cache_and_counts_the_days_units(tmp_path):
    api = _YouTubeApi()
    provider = _youtube(tmp_path, api)
    asyncio.run(provider.search("ceramics", place="watch"))
    again = _youtube(tmp_path, api)
    asyncio.run(again.search("Ceramics  ", place="watch"))
    assert len(api.searches) == 1 and again.units == 0 and again.units_today() == 101
    asyncio.run(again.search("ceramics", place="seed"))  # another place: its own search (a short one)
    assert len(api.searches) == 2 and parse_qs(api.searches[1].url.query.decode())["videoDuration"] == ["short"]
    with pytest.raises(VideoUnavailable):  # a background wants clips under 45 s: three-minute talks never fit
        asyncio.run(again.search("ceramics", place="background"))


def test_youtube_stops_under_the_quota_margin_and_on_quota_exceeded(tmp_path):
    api = _YouTubeApi()
    provider = YouTubeVideos("k", cache_dir=tmp_path / "yt", transport=httpx.MockTransport(api), daily_units=650)
    with pytest.raises(VideoUnavailable) as refused:
        asyncio.run(provider.search("ceramics", place="watch"))
    assert "margin" in refused.value.reason and api.calls == []
    exhausted = _youtube(tmp_path / "other", _YouTubeApi(status=403))
    with pytest.raises(VideoUnavailable) as refused:
        asyncio.run(exhausted.search("ceramics", place="watch"))
    assert "quotaExceeded" in refused.value.reason and exhausted.exhausted_reason
    broken = _youtube(tmp_path / "broken", _YouTubeApi(status=500))
    with pytest.raises(VideoUnavailable):
        asyncio.run(broken.search("ceramics", place="watch"))


def test_youtube_availability_and_durations(tmp_path):
    provider = _youtube(tmp_path, _YouTubeApi())
    assert asyncio.run(provider.available(["v1", "v2", "v9"])) == {"v1": True, "v2": False, "v9": False}
    assert _duration_seconds("PT1H2M3S") == 3723 and _duration_seconds("PT45S") == 45
    assert _duration_seconds("x") is None


# -- Pixabay ----------------------------------------------------------------------------------------------------------


def _file(hit_id: int, name: str, width: int, height: int, size: int) -> dict:
    return {
        "url": f"https://cdn.pixabay.com/video/{hit_id}_{name}.mp4",
        "width": width,
        "height": height,
        "size": size,
        "thumbnail": f"https://cdn.pixabay.com/video/{hit_id}_{name}.jpg",
    }


def _pixabay_hit(hit_id: int, duration: int = 30, landscape: bool = True, medium_size: int = 9_000_000) -> dict:
    w, h = (1920, 1080) if landscape else (1080, 1920)
    files = {
        "large": _file(hit_id, "large", w, h, 30_000_000),
        "medium": _file(hit_id, "medium", 1280 if landscape else 720, 720 if landscape else 1280, medium_size),
        "small": _file(hit_id, "small", 960, 540, 4_000_000),
        "tiny": _file(hit_id, "tiny", 640, 360, 2_500_000),
    }
    return {
        "id": hit_id,
        "pageURL": f"https://pixabay.com/videos/id-{hit_id}/",
        "tags": "ocean, waves, sea",
        "duration": duration,
        "user": "Sea Films",
        "user_id": 42,
        "videos": files,
    }


# 1: a 9 MB medium file (a player, not a background); 2: too long for a background; 3: portrait; 4: a 5 MB medium
# file (fits a background)
DEFAULT_HITS = [
    _pixabay_hit(1),
    _pixabay_hit(2, duration=70),
    _pixabay_hit(3, landscape=False),
    _pixabay_hit(4, medium_size=5_000_000),
]


class _PixabayApi:
    """TESTING ONLY (docs/development/test-doubles.md): Pixabay's videos answers, with its rate-limit headers."""

    def __init__(self, hits=None, status: int = 200, remaining: int = 98, challenge: bool = False):
        self.calls: list[httpx.Request] = []
        self.hits = hits if hits is not None else DEFAULT_HITS
        self.status, self.remaining, self.challenge = status, remaining, challenge

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        headers = {"x-ratelimit-limit": "100", "x-ratelimit-remaining": str(self.remaining), "x-ratelimit-reset": "60"}
        if request.url.path.endswith(".jpg"):
            return httpx.Response(200, content=b"\xff\xd8\xff poster", headers={"content-type": "image/jpeg"})
        if self.challenge:
            return httpx.Response(429, text="<html>Just a moment</html>", headers={"cf-mitigated": "challenge"})
        if self.status != 200:
            return httpx.Response(self.status, text="nope", headers=headers)
        return httpx.Response(200, json={"total": 500, "totalHits": 500, "hits": self.hits}, headers=headers)


def _pixabay(tmp_path, api) -> PixabayVideos:
    return PixabayVideos("px-key", "bga_test/1.0", cache_dir=tmp_path / "px", transport=httpx.MockTransport(api))


def test_pixabay_sends_the_descriptive_user_agent_filters_by_place_and_chooses_the_file_by_size(tmp_path):
    api = _PixabayApi()
    provider = _pixabay(tmp_path, api)
    hits = asyncio.run(provider.search("ocean waves", place="background"))
    request = api.calls[0]
    assert request.headers["user-agent"] == "bga_test/1.0"
    params = parse_qs(request.url.query.decode())
    assert params["video_type"] == ["film"] and params["safesearch"] == ["true"] and params["min_width"] == ["1280"]
    # a background: hit 2 is too long, hit 3 portrait, hit 1's wide files are over 6 MB: only hit 4 fits
    assert [hit.id for hit in hits] == ["4"] and hits[0].size == 5_000_000 and hits[0].extra["file"] == "medium"
    seeds = asyncio.run(provider.search("ocean waves", place="seed"))
    # 70 s fits a card; a seed needs 960 px, so the 4 MB small file is the smallest that fits
    assert [hit.id for hit in seeds] == ["1", "2", "4"] and seeds[0].extra["file"] == "small"
    assert seeds[0].credit.name == "Sea Films" and seeds[0].credit.source_url == "https://pixabay.com/videos/id-1/"
    assert seeds[0].credit.profile_url == "https://pixabay.com/users/Sea Films-42/"
    assert seeds[0].poster.endswith("1_small.jpg") and seeds[0].duration == 30 and seeds[0].width == 960
    assert provider.remaining == 98 and len(api.calls) == 2  # two places, two searches; the same place is cached
    asyncio.run(_pixabay(tmp_path, api).search("ocean waves", place="seed"))
    assert len(api.calls) == 2


def test_pixabay_picks_the_smallest_file_that_is_wide_enough_and_within_budget():
    four_k = _pixabay_hit(9)
    four_k["videos"] = {
        "large": {"url": "l", "width": 3840, "height": 2160, "size": 80_000_000, "thumbnail": "l.jpg"},
        "medium": {"url": "m", "width": 2560, "height": 1440, "size": 30_000_000, "thumbnail": "m.jpg"},
        "small": {"url": "s", "width": 1920, "height": 1080, "size": 11_000_000, "thumbnail": "s.jpg"},
        "tiny": {"url": "t", "width": 1280, "height": 720, "size": 16_800_000, "thumbnail": "t.jpg"},
    }
    assert choose_file(four_k, "seed")["url"] == "s", "the 4K source's tiny file is 16.8 MB: the small one fits"
    assert choose_file(four_k, "background") is None, "nothing wide enough under 6 MB"
    assert choose_file(_pixabay_hit(1), "watch")["name"] == "medium"


def test_pixabay_limits_challenges_and_errors_end_the_search_not_the_draft(tmp_path):
    low = _pixabay(tmp_path, _PixabayApi(remaining=5))
    asyncio.run(low.search("ocean", place="seed"))  # the answer says 5 are left
    with pytest.raises(VideoUnavailable) as refused:
        asyncio.run(low.search("mountains", place="seed"))
    assert "out of Pixabay requests" in refused.value.reason
    challenged = _pixabay(tmp_path / "c", _PixabayApi(challenge=True))
    with pytest.raises(VideoUnavailable) as refused:
        asyncio.run(challenged.search("ocean", place="seed"))
    assert "challenge" in refused.value.reason
    broken = _pixabay(tmp_path / "b", _PixabayApi(status=500))
    with pytest.raises(VideoUnavailable):
        asyncio.run(broken.search("ocean", place="seed"))
    empty = _pixabay(tmp_path / "e", _PixabayApi(hits=[]))
    with pytest.raises(VideoUnavailable) as refused:
        asyncio.run(empty.search("ocean", place="seed"))
    assert "no Pixabay clip" in refused.value.reason


def test_pixabay_posters_are_downloaded_once_into_the_cache(tmp_path):
    api = _PixabayApi()
    provider = _pixabay(tmp_path, api)
    hit = asyncio.run(provider.search("ocean waves", place="seed"))[0]
    data = asyncio.run(provider.poster_bytes(hit))
    assert data and data.startswith(b"\xff\xd8") and (tmp_path / "px" / "posters" / "1.jpg").is_file()
    asyncio.run(provider.poster_bytes(hit))
    assert len([c for c in api.calls if c.url.path.endswith(".jpg")]) == 1
    cache = json.loads((tmp_path / "px" / "pixabay.json").read_text())
    assert list(cache["searches"]) == ["en|seed|ocean waves"]
