"""Sample videos in drafts (Epic 31, Stories 31.3 and 31.4): a site's `video` assets drafted as a search (`source:
"search"`, a `query` and a `place`) and an app's seeded `video` fields become real videos with their credits, through
the providers in the place's order (the epic's table). One search per distinct phrase (cached), a handful per draft
(D4); with nothing found the place falls back as today, with a note.

Nothing is downloaded: a YouTube hit is an embed (its id), a Pixabay hit a hotlinked MP4 file; a Pixabay poster is the
one thing stored (its images may not be hotlinked), as a public file of the site or a seeded image of the app.
"""

from typing import Any

from .pixabay import PixabayVideos
from .port import IVideoProvider, Place, VideoHit, VideoUnavailable

MAX_SEARCHES = 8  # per draft, across places (D4: a handful)
WATCH_URL = "https://www.youtube.com/watch?v={id}"


def _note(path: str, message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": path, "message": message, "suggestion": None}


class VideoSearch:
    """The searches of one draft: the budget, the phrases already asked (any provider), the ids already used."""

    def __init__(self, providers_for, language: str = "en", budget: int = MAX_SEARCHES):
        self.providers_for = providers_for  # Place -> list[IVideoProvider]
        self.language = language
        self.budget = budget
        self.searches = 0
        self.used: set[str] = set()
        self.reasons: list[str] = []

    async def find(self, phrase: str, place: Place) -> VideoHit | None:
        providers: list[IVideoProvider] = self.providers_for(place)
        if not providers:
            self.reasons.append("no video provider is on")
            return None
        for provider in providers:
            if self.searches >= self.budget:
                self.reasons.append(f"at most {self.budget} video searches per draft")
                return None
            try:
                self.searches += 1
                hits = await provider.search(phrase, place=place, language=self.language)
            except VideoUnavailable as exc:
                self.reasons.append(f"{provider.name}: {exc.reason}")
                continue
            for hit in hits:
                key = f"{hit.provider}:{hit.id}"
                if key not in self.used:
                    self.used.add(key)
                    return hit
            self.reasons.append(f"{provider.name}: every result for '{phrase}' is already used")
        return None


async def poster_file(hit: VideoHit, providers: list[IVideoProvider]) -> bytes | None:
    """A Pixabay hit's poster, downloaded into the cache (YouTube's thumbnails may be hotlinked)."""
    if hit.provider != "pixabay":
        return None
    provider = next((p for p in providers if isinstance(p, PixabayVideos)), None)
    return await provider.poster_bytes(hit) if provider else None


async def stock_site_videos(
    assets: list[dict[str, Any]], search: VideoSearch, posters: dict[str, bytes] | None = None
) -> list[dict[str, Any]]:
    """Each `video` asset drafted as a search (in place): it gains `video` (provider, id or file, title, poster, size)
    and `credit`, and its source becomes the provider's. A Pixabay poster's bytes go into `posters` (asset id →
    JPEG) for the site's `public/assets/`. Returns notes."""
    found, missed = [], []
    for asset in assets:
        if asset.get("kind") != "video" or asset.get("source") != "search":
            continue
        place: Place = "background" if asset.get("place") == "background" else "watch"
        phrase = str(asset.get("query") or asset.get("alt") or asset["id"].replace("-", " "))
        hit = await search.find(phrase, place)
        if hit is None:
            asset["source"] = "placeholder"
            missed.append(f"{asset['id']} ({'; '.join(search.reasons[-2:]) or 'no result'})")
            continue
        asset["source"] = hit.provider
        asset["video"] = hit.asset_fields()
        asset["credit"] = hit.credit_fields()
        asset.setdefault("alt", hit.title or phrase)
        if posters is not None and hit.provider == "pixabay":
            data = await poster_file(hit, search.providers_for(place))
            if data:
                posters[asset["id"]] = data
                asset["video"]["poster"] = f"/assets/{asset['id']}-poster.jpg"
            else:
                asset["video"].pop("poster", None)
        found.append(f"{asset['id']} ({hit.provider})")
    notes = []
    if found:
        notes.append(_note("/assets", f"Sample videos, credited on the page: {', '.join(found)}"))
    if missed:
        notes.append(_note("/assets", f"No video found, shown as placeholders: {'; '.join(missed)}"))
    return notes


def _label(record: dict[str, Any], fields: list[str]) -> str:
    for name in ("name", "title", "label", *fields):
        value = record.get(name)
        if isinstance(value, str) and value.strip() and not value.startswith(("http", "/")):
            return value.strip()
    return ""


async def stock_seed_videos(
    backend: dict[str, Any], search: VideoSearch, posters: dict[str, bytes] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """An app's seeded records with `video` fields (in place): each value becomes a video found from the record's
    label (one search per distinct label, the rest reuse results): a Pixabay file link (played by the kit's player),
    else a YouTube watch link (the kit's facade). The record's empty image field gets the poster. Returns the videos
    as FrontendSpec assets (their credits, for the kit) and notes."""
    videos = {
        entity["name"]: [field["name"] for field in entity.get("fields") or [] if field.get("type") == "video"]
        for entity in backend.get("entities") or []
    }
    images = {
        entity["name"]: [field["name"] for field in entity.get("fields") or [] if field.get("type") == "image"]
        for entity in backend.get("entities") or []
    }
    texts = {
        entity["name"]: [f["name"] for f in entity.get("fields") or [] if f.get("type") in ("string", "text")]
        for entity in backend.get("entities") or []
    }
    by_label: dict[str, VideoHit | None] = {}
    assets: list[dict[str, Any]] = []
    found, kept = 0, 0
    for seed in backend.get("seed") or []:
        entity = seed.get("entity")
        for field in videos.get(entity) or []:
            for index, record in enumerate(seed.get("records") or []):
                label = _label(record, texts.get(entity) or [])
                phrase = f"{label} {entity}".strip() if label else str(entity)
                if phrase not in by_label:
                    by_label[phrase] = await search.find(phrase, "seed")
                hit = by_label[phrase]
                if hit is None:
                    kept += 1
                    continue
                url = hit.url if hit.provider == "pixabay" else WATCH_URL.format(id=hit.id)
                record[field] = url
                found += 1
                asset = {
                    "id": f"seed-video-{len(assets) + 1}",
                    "kind": "video",
                    "alt": hit.title or phrase,
                    "source": url,
                    "video": hit.asset_fields(),
                    "credit": hit.credit_fields(),
                }
                poster_field = next((f for f in images.get(entity) or [] if not record.get(f)), None)
                if poster_field and hit.provider == "youtube" and hit.poster:
                    record[poster_field] = hit.poster  # YouTube's thumbnail may be hotlinked
                elif poster_field and hit.provider == "pixabay" and posters is not None:
                    # a Pixabay poster is never hotlinked: kept for a caller that ships files (sites); apps' players
                    # show the first frame instead
                    data = await poster_file(hit, search.providers_for("seed"))
                    if data:
                        posters[f"{entity}-{index}-{field}"] = data
                assets.append(asset)
    notes = []
    if found:
        notes.append(_note("/assets", f"{found} seeded video(s) from the providers, credited where they play"))
    if kept:
        reason = "; ".join(dict.fromkeys(search.reasons[-3:])) or "no result"
        notes.append(_note("/assets", f"{kept} seeded video field(s) keep the sample video ({reason})"))
    return assets, notes
