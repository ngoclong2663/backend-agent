"""Epic 31 (Stories 31.3, 31.4): videos in sites and apps: `video` assets drafted as a search are resolved through
the providers in each place's order (fake providers here), the Video section and the hero's background video are
typed and rendered, trees accept the library's video pieces only, seeded video fields get a file or a watch link
with their credit, and the prompt names videos only when a provider is on."""

import asyncio
import json
from pathlib import Path

import pytest

from src.engines import PromptLibrary
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.modules.shared.domain.frontend_spec.catalogue import BUILTIN_SECTIONS
from src.modules.shared.domain.frontend_spec.section_props import HeroProps, VideoProps
from src.modules.shared.domain.frontend_spec.trees import DATA_COMPONENTS, asset_refs
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.frontend.app.files import app_data
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.asset_registry import assets_ts, external_images_note
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.frontend.renderer import registry_ts, section_props_ts
from src.orchestrator.integration.contract import build_contract
from src.videos.port import VideoCredit, VideoHit, VideoUnavailable
from src.videos.stock import VideoSearch, stock_seed_videos, stock_site_videos

EXAMPLES = Path(__file__).parents[2] / "examples"


class FakeProvider:
    """TESTING ONLY: a provider with scripted hits per phrase (docs/development/test-doubles.md)."""

    def __init__(self, name: str, hits: dict[str, list[VideoHit]] | None = None, fail: str | None = None):
        self.name = name
        self.hits = hits or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def search(self, phrase, *, place, language="en", count=5):
        self.calls.append((phrase, place))
        if self.fail:
            raise VideoUnavailable(self.fail)
        found = self.hits.get(phrase) or self.hits.get("*")
        if not found:
            raise VideoUnavailable(f"no {self.name} video for '{phrase}'")
        return found

    async def available(self, ids):
        return {i: True for i in ids}


def _yt(video_id: str) -> VideoHit:
    credit = VideoCredit(
        "youtube",
        "Chan",
        f"https://www.youtube.com/watch?v={video_id}",
        "https://www.youtube.com/channel/UC1",
        f"Talk {video_id}",
    )
    return VideoHit(
        "youtube",
        video_id,
        f"Talk {video_id}",
        credit,
        200,
        url=f"https://www.youtube-nocookie.com/embed/{video_id}",
        poster=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )


def _px(hit_id: str) -> VideoHit:
    credit = VideoCredit(
        "pixabay", "Sea Films", f"https://pixabay.com/videos/id-{hit_id}/", "https://pixabay.com/users/sea-42/"
    )
    return VideoHit(
        "pixabay",
        hit_id,
        "ocean, waves",
        credit,
        30,
        url=f"https://cdn.pixabay.com/video/{hit_id}.mp4",
        poster=f"https://cdn.pixabay.com/video/{hit_id}.jpg",
        width=1280,
        height=720,
        size=5_000_000,
    )


def _search(youtube: FakeProvider | None, pixabay: FakeProvider | None) -> VideoSearch:
    order = {"watch": [youtube, pixabay], "background": [pixabay], "seed": [pixabay, youtube]}
    return VideoSearch(lambda place: [p for p in order[place] if p is not None])


# -- 31.3: sites ------------------------------------------------------------------------------------------------------


def test_site_videos_follow_each_places_order_and_fall_back_to_the_other_provider():
    youtube = FakeProvider("youtube", {"a potter at the wheel": [_yt("v1")], "*": [_yt("v2")]})
    pixabay = FakeProvider("pixabay", {"waves on a beach": [_px("p1")], "a potter at the wheel": [_px("p2")]})
    assets = [
        {
            "id": "talk",
            "kind": "video",
            "source": "search",
            "query": "a potter at the wheel",
            "place": "watch",
            "alt": "A potter",
        },
        {
            "id": "loop",
            "kind": "video",
            "source": "search",
            "query": "waves on a beach",
            "place": "background",
            "alt": "Waves",
        },
        {
            "id": "demo",
            "kind": "video",
            "source": "search",
            "query": "glazing a bowl",
            "place": "watch",
            "alt": "Glazing",
        },
        {"id": "hero", "kind": "image", "source": "photo", "alt": "unchanged"},
    ]
    notes = asyncio.run(stock_site_videos(assets, _search(youtube, pixabay)))
    talk, loop, demo, hero = assets
    assert talk["source"] == "youtube" and talk["video"]["id"] == "v1" and talk["credit"]["provider"] == "youtube"
    assert talk["credit"]["title"] == "Talk v1" and talk["credit"]["name"] == "Chan"
    assert loop["source"] == "pixabay" and loop["video"]["url"].endswith("p1.mp4") and loop["video"]["width"] == 1280
    assert demo["source"] == "youtube" and demo["video"]["id"] == "v2", "YouTube's wildcard answered the watch"
    assert hero == {"id": "hero", "kind": "image", "source": "photo", "alt": "unchanged"}
    assert youtube.calls == [("a potter at the wheel", "watch"), ("glazing a bowl", "watch")]
    assert pixabay.calls == [("waves on a beach", "background")]
    assert "talk (youtube)" in notes[0]["message"] and "loop (pixabay)" in notes[0]["message"]


def test_without_a_result_the_asset_is_a_placeholder_and_the_draft_goes_on():
    youtube = FakeProvider("youtube", fail="the YouTube quota is exhausted (403 quotaExceeded)")
    pixabay = FakeProvider("pixabay", {})
    assets = [{"id": "talk", "kind": "video", "source": "search", "query": "x", "place": "watch", "alt": "x"}]
    notes = asyncio.run(stock_site_videos(assets, _search(youtube, pixabay)))
    assert assets[0]["source"] == "placeholder" and "video" not in assets[0]
    assert "No video found" in notes[0]["message"] and "quota" in notes[0]["message"]
    nothing = asyncio.run(stock_site_videos([dict(assets[0], source="search")], _search(None, None)))
    assert "no video provider is on" in nothing[0]["message"]


def test_a_draft_makes_a_handful_of_searches_and_never_reuses_a_video():
    pixabay = FakeProvider("pixabay", {"*": [_px("p1")]})
    search = _search(None, pixabay)
    search.budget = 2
    assets = [
        {"id": f"v{n}", "kind": "video", "source": "search", "query": f"clip {n}", "place": "background", "alt": "c"}
        for n in range(4)
    ]
    asyncio.run(stock_site_videos(assets, search))
    assert assets[0]["source"] == "pixabay"
    assert assets[1]["source"] == "placeholder", "the only result is already used"
    assert assets[2]["source"] == "placeholder" and search.searches == 2


def test_video_assets_and_sections_are_typed_and_the_validator_keeps_videos_to_the_library():
    spec = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())
    spec["assets"].append(
        {"id": "talk", "kind": "video", "source": "search", "query": "a talk", "place": "watch", "alt": "A talk"}
    )
    spec["assets"].append(
        {"id": "loop", "kind": "video", "source": "search", "query": "waves", "place": "background", "alt": "Waves"}
    )
    spec["pages"][0]["sections"].append(
        {"id": "videos", "component": "Video", "content": {"title": "Watch", "video": "asset:talk"}}
    )
    hero = next(s for s in spec["pages"][0]["sections"] if s["component"] == "Hero")
    hero["content"]["backgroundVideo"] = "asset:loop"
    hero["content"]["variant"] = "banner"
    result = validate_frontend_spec_data(spec)
    assert result.report.valid, [issue.message for issue in result.report.errors]
    assert "Video" in BUILTIN_SECTIONS and VideoProps.model_validate({"video": "asset:talk"}).video == "asset:talk"
    with pytest.raises(ValueError):
        VideoProps.model_validate({"title": "nothing to watch"})
    assert HeroProps.model_validate({"heading": "x", "backgroundVideo": "asset:loop"}).background_video == "asset:loop"
    # a search on an image, a search without a query, and a resolved source written by hand are refused
    bad = json.loads(json.dumps(spec))
    bad["assets"][-2]["kind"] = "image"
    bad["assets"].append({"id": "noq", "kind": "video", "source": "search", "alt": None, "decorative": True})
    bad["assets"].append({"id": "hand", "kind": "video", "source": "youtube", "alt": "x"})
    codes = [(i.path, i.message) for i in validate_frontend_spec_data(bad).report.errors]
    assert any("cannot be a video search" in m for _, m in codes)
    assert any("needs a `query`" in m for _, m in codes)
    assert any("written by the drafting code" in m for _, m in codes)
    # a resolved asset (as the drafting code writes it) is valid and renders through the registry
    spec["assets"][-2] |= {
        "source": "youtube",
        "video": {
            "provider": "youtube",
            "id": "v1",
            "title": "Talk",
            "poster": "https://i.ytimg.com/vi/v1/hqdefault.jpg",
        },
        "credit": {
            "provider": "youtube",
            "name": "Chan",
            "profileUrl": "https://www.youtube.com/channel/UC1",
            "sourceUrl": "https://www.youtube.com/watch?v=v1",
            "title": "Talk",
        },
    }
    spec["assets"][-1] |= {
        "source": "pixabay",
        "video": {
            "provider": "pixabay",
            "id": "p1",
            "url": "https://cdn.pixabay.com/video/p1.mp4",
            "poster": "/assets/loop-poster.jpg",
            "width": 1280,
            "height": 720,
            "duration": 30,
        },
        "credit": {
            "provider": "pixabay",
            "name": "Sea Films",
            "profileUrl": "https://pixabay.com/users/sea-42/",
            "sourceUrl": "https://pixabay.com/videos/id-p1/",
        },
    }
    normalized = validate_frontend_spec_data(spec)
    assert normalized.report.valid, [issue.message for issue in normalized.report.errors]
    plan = plan_frontend(normalized.normalized, None)
    planned = {asset["id"]: asset for asset in plan["assets"]}
    assert planned["talk"]["render"] == "video-embed" and planned["talk"]["video"]["id"] == "v1"
    assert (
        planned["loop"]["render"] == "video-file" and planned["loop"]["posterFile"] == "public/assets/loop-poster.jpg"
    )
    registry = assets_ts(plan)
    assert '"video-embed" | "video-file"' in registry and 'video: {"provider": "youtube", "id": "v1"' in registry
    assert (
        '"poster": "/assets/loop-poster.jpg"' in registry and '"provider": "pixabay", "name": "Sea Films"' in registry
    )
    sections = registry_ts(plan)
    assert 'import { Video } from "@/components/sections/Video";' in sections
    assert "export type TVideoContent" in section_props_ts() and "backgroundVideo?: string" in section_props_ts()
    readme = external_images_note(plan)
    assert (
        "Videos (embedded or linked" in readme
        and "Talk (Chan on YouTube, https://www.youtube.com/watch?v=v1)" in readme
    )
    assert "Sea Films on Pixabay" in readme


def test_trees_take_the_librarys_video_pieces_bound_to_an_asset_and_still_refuse_raw_video():
    assert {"VideoEmbed", "BackgroundVideo"} <= DATA_COMPONENTS
    tree = {
        "type": "section",
        "children": [
            {"type": "VideoEmbed", "props": {"asset": "asset:talk"}},
            {"type": "img", "props": {"src": "asset:hero"}},
        ],
    }
    assert sorted(asset_refs(tree)) == [("hero", "/children/1/props/src"), ("talk", "/children/0/props/asset")]
    from src.modules.shared.domain.frontend_spec.trees import classify

    assert classify("VideoEmbed") == "data" and classify("video") == "removed" and classify("iframe") == "removed"


def test_the_static_prompt_names_videos_only_when_a_provider_is_on():
    context = {
        "mode": "static",
        "requirement_text": "A pottery school.",
        "requirement_format": "plain",
        "frontend_schema_path": "s.json",
        "frontend_schema_digest_path": "d.md",
        "frontend_example_path": "e.json",
        "sections_path": "sections.md",
        "output_frontend_path": "frontend-spec.json",
        "notes_path": "notes.json",
        "design_path": None,
        "stock_phrases": "",
        "photos_enabled": True,
        "max_photos": 8,
        "inline": False,
    }
    with_videos = PromptLibrary().render("draft_frontend_spec", "v11", **context, videos_enabled=True).text
    without = PromptLibrary().render("draft_frontend_spec", "v11", **context, videos_enabled=False).text
    assert (
        '`"source": "search"`' in with_videos and "`Video` section" in with_videos and "backgroundVideo" in with_videos
    )
    assert "search" not in without.split("- Videos")[0] or "- Videos" not in without
    assert "- Videos" not in without


# -- 31.4: apps -------------------------------------------------------------------------------------------------------


def test_seeded_video_fields_get_a_pixabay_file_first_then_a_youtube_link_and_their_credit():
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / "media-library.json").read_text())).normalized
    pixabay = FakeProvider("pixabay", {"Flat washes Lesson": [_px("p1")]})
    youtube = FakeProvider("youtube", {"*": [_yt("v1"), _yt("v2")]})
    assets, notes = asyncio.run(stock_seed_videos(backend, _search(youtube, pixabay)))
    lessons = next(seed for seed in backend["seed"] if seed["entity"] == "Lesson")["records"]
    assert lessons[0]["video"] == "https://cdn.pixabay.com/video/p1.mp4", "Pixabay first: plays in our player"
    assert lessons[1]["video"] == "https://www.youtube.com/watch?v=v1", "then YouTube, as a watch link"
    assert lessons[2]["video"] == "https://www.youtube.com/watch?v=v2"
    assert lessons[1]["poster"] == "https://i.ytimg.com/vi/v1/hqdefault.jpg", "YouTube's thumbnail may be hotlinked"
    assert "poster" not in lessons[0], "a Pixabay poster is never hotlinked; the player shows the first frame"
    assert [asset["kind"] for asset in assets] == ["video"] * 3 and assets[0]["credit"]["provider"] == "pixabay"
    assert pixabay.calls[0] == ("Flat washes Lesson", "seed") and len(pixabay.calls) == 3
    assert "3 seeded video(s)" in notes[0]["message"]
    # the kit reads the credits by URL, apart from the photo credits
    raw = json.loads((EXAMPLES / "app-outlines" / "media-library.json").read_text())
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    theme = {"style": "dashboard", "colorScheme": "light-dark", "density": "comfortable"}
    spec = app_frontend_spec(backend, outline, theme, contract).spec
    spec["assets"] = [*(spec.get("assets") or []), *assets]
    normalized = validate_frontend_spec_data(spec)
    assert normalized.report.valid, [issue.message for issue in normalized.report.errors]
    data = app_data(plan_frontend(normalized.normalized, contract), normalized.normalized, contract)
    assert data["videoCredits"]["https://cdn.pixabay.com/video/p1.mp4"]["name"] == "Sea Films"
    assert data["videoCredits"]["https://www.youtube.com/watch?v=v1"]["title"] == "Talk v1"
    assert data["photoCredits"] == {}


def test_without_a_provider_the_seeds_keep_the_samples():
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / "media-library.json").read_text())).normalized
    assets, notes = asyncio.run(stock_seed_videos(backend, _search(None, None)))
    lessons = next(seed for seed in backend["seed"] if seed["entity"] == "Lesson")["records"]
    assert assets == [] and lessons[0]["video"] == "lesson/video/shared/seed/1.mp4"
    assert "keep the sample video" in notes[0]["message"]
