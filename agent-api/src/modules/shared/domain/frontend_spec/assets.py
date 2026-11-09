"""Asset sources (Stories 15.1, 19.1): how each FrontendSpec asset is rendered, and the facts the validator checks.

placeholder        a themed panel (no file)
generate           an SVG drawn by the code engine (15.2) → a React component; until drawn, a placeholder
photo              an AI photograph (19.2) → public/assets/<id>.webp; until made, a placeholder
upload:<id>        a file the user uploaded (15.4) → public/assets/<id>.<ext>
lucide:<Name>      a lucide-react icon from the pinned base
https://…          a remote image (never fetched by the sandbox)
search             a video to find at draft time (Epic 31; `query`, `place`) → youtube | pixabay once found
youtube            a YouTube video, embedded in its player on play (`video.id`)
pixabay            a Pixabay video file, played by our own <video> (`video.url`, a stored poster)
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

RenderMode = Literal[
    "svg-component", "public-file", "remote", "icon", "placeholder", "photo", "video-embed", "video-file"
]
VIDEO_SOURCES = frozenset({"search", "youtube", "pixabay"})  # Epic 31: `kind: video` only

# The base's lucide-react icon names, written by scripts/frontend-base.sh next to the base's lock file.
LUCIDE_ICONS_FILE = Path(__file__).resolve().parents[5] / "templates" / "nextjs_base" / "lucide-icons.txt"
SVG_KINDS = frozenset({"illustration", "pattern", "logo", "image"})  # what the engine can draw (15.2)
DEFAULT_ASPECT = {"illustration": "16:9", "image": "16:9", "pattern": "1:1", "logo": "1:1", "icon": "1:1"}
MAX_GENERATED_ASSETS = 12  # FRONTEND_MAX_GENERATED_ASSETS default; above it the validator warns
MAX_PHOTOS = 8  # FRONTEND_MAX_PHOTOS default; above it the validator warns
UPLOAD_ID = re.compile(r"^upl_[A-Za-z0-9]{6,40}$")
ICON_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")


@lru_cache
def lucide_icons(path: Path = LUCIDE_ICONS_FILE) -> frozenset[str]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return frozenset()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def source_kind(source: str) -> str:
    """placeholder | generate | photo | search | youtube | pixabay | upload | lucide | https | insecure | unknown."""
    if source in ("placeholder", "generate", "photo") or source in VIDEO_SOURCES:
        return source
    if source.startswith("upload:"):
        return "upload"
    if source.startswith("lucide:"):
        return "lucide"
    if source.startswith("https://"):
        return "https"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", source):
        return "insecure"
    return "unknown"


def render_mode(asset: dict) -> RenderMode:
    return {
        "generate": "svg-component",
        "photo": "photo",
        "upload": "public-file",
        "https": "remote",
        "lucide": "icon",
        "youtube": "video-embed",
        "pixabay": "video-file",
    }.get(source_kind(asset.get("source") or "placeholder"), "placeholder")  # type: ignore[return-value]


def aspect_ratio(asset: dict) -> str:
    return asset.get("aspectRatio") or DEFAULT_ASPECT.get(asset.get("kind") or "image", "16:9")
