"""Story 29.2: the sample files the generated apps' seeds upload (the smoke check's database, the previews'), so a
media field has something to play before anyone uploads. The files are ours (`templates/samples/`, CC0, made by
`make sample-media`); a content type without a sample gets the 1×1 PNG the smoke check always uploaded."""

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.modules.shared.domain.backend_spec.media import SAMPLE_FILES

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "templates" / "samples"
PNG_HEX = (
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@lru_cache
def sample_bytes(content_type: str, language: str | None = None) -> bytes:
    """The sample of a content type (a subtitle track in `language` when the samples have it), else the PNG."""
    name = SAMPLE_FILES.get(content_type)
    if name and language and content_type in ("text/vtt", "application/x-subrip"):
        candidate = SAMPLES_DIR / name.replace(".en.", f".{language}.")
        if candidate.is_file():
            return candidate.read_bytes()
    path = SAMPLES_DIR / name if name else None
    if path is not None and path.is_file():
        return path.read_bytes()
    return bytes.fromhex(PNG_HEX)


def _language_of(key: str) -> str | None:
    """`…/seed/1.ja.vtt` → `ja`."""
    name = key.rsplit("/", 1)[-1]
    parts = name.split(".")
    return parts[-2] if len(parts) >= 3 else None


def storage_objects(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """The contract's seeded objects (`x-bga.storage.objects`) with the bytes to upload, base64 encoded."""
    objects = ((contract.get("x-bga") or {}).get("storage") or {}).get("objects") or []
    return [
        {
            **item,
            "data": base64.b64encode(sample_bytes(item["contentType"], _language_of(item["key"]))).decode(),
        }
        for item in objects
    ]


def has_media(contract: dict[str, Any] | None) -> bool:
    """Whether the app has a video, audio or subtitles field (the kit then ships the samples, Story 29.2)."""
    meta = (contract or {}).get("x-bga") or {}
    return any(
        (file.get("kind") in ("video", "audio", "subtitles"))
        for info in (meta.get("entities") or {}).values()
        for file in info.get("fileFields") or []
    )
