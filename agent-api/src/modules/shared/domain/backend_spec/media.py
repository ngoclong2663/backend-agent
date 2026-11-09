"""Media fields (Epic 29, Story 29.1): `video`, `audio` and `subtitles` are file fields (an object key in the column, a
signed `<field>Url` in the response, Story 10.5) whose defaults are what browsers play as they are (D2): no format
that needs transcoding. `accept` may narrow a kind's types, never widen them.

Subtitles have two shapes, both found by code (D3): a `subtitles` field on the media record (one track), or a child
entity with a `subtitles` field and a language field (one track per language). `media_tracks` finds them for the
contract (`x-bga.storage.tracks`), the fixtures and the kit's players.
"""

import re
from typing import Any

FILE_KINDS = ("file", "image", "video", "audio", "subtitles")
MEDIA_KINDS = ("video", "audio", "subtitles")
IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"]
# What browsers play natively (D2); SubRip is converted to WebVTT in the browser (Story 29.3)
PLAYABLE: dict[str, list[str]] = {
    "video": ["video/mp4", "video/webm"],
    "audio": ["audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm"],
    "subtitles": ["text/vtt", "application/x-subrip"],
}
DEFAULT_ACCEPT: dict[str, list[str]] = {"file": [], "image": IMAGE_TYPES, **PLAYABLE}
MB = 1024 * 1024
DEFAULT_MAX_SIZE: dict[str, int] = {
    "file": 10 * MB,
    "image": 5 * MB,
    "video": 200 * MB,  # D7: one request each; multipart uploads are a later story
    "audio": 50 * MB,
    "subtitles": 1 * MB,
}
# The sample of each kind (Story 29.2, `templates/samples/`): the fixtures' keys end in it, the seeds upload it
SAMPLE_EXTENSION: dict[str, str] = {"file": "pdf", "image": "png", "video": "mp4", "audio": "mp3", "subtitles": "vtt"}
SAMPLE_CONTENT_TYPE: dict[str, str] = {
    "file": "application/pdf",
    "image": "image/png",
    "video": "video/mp4",
    "audio": "audio/mpeg",
    "subtitles": "text/vtt",
}
# content type → the sample file of that type (none: a 1×1 PNG stands in, as the smoke check always did)
SAMPLE_FILES: dict[str, str] = {
    "video/mp4": "sample.mp4",
    "video/webm": "sample.webm",
    "audio/mpeg": "sample.mp3",
    "audio/ogg": "sample.ogg",
    "text/vtt": "sample.en.vtt",
    "application/x-subrip": "sample.en.srt",
    "image/jpeg": "sample-poster.jpg",
    "image/png": "placeholder.png",
}
SAMPLE_LANGUAGES = ("en", "ja")  # the subtitle tracks the samples come in
LANGUAGE_FIELDS = ("language", "lang", "locale", "languagecode", "langcode")
LABEL_FIELDS = ("label", "title", "name")
_LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")


def is_file_kind(kind: str | None) -> bool:
    return kind in FILE_KINDS


def is_media_kind(kind: str | None) -> bool:
    return kind in MEDIA_KINDS


def playable_problem(kind: str, mime: str) -> str | None:
    """Why an `accept` entry is refused on a media field: outside the kind's playable set (D2)."""
    allowed = PLAYABLE.get(kind)
    if allowed is None or mime in allowed:
        return None
    return f"'{mime}' is not a type browsers play as {kind}; allowed: {', '.join(allowed)}"


def default_accept(kind: str) -> list[str]:
    return list(DEFAULT_ACCEPT.get(kind, []))


def default_max_size(kind: str) -> int:
    return DEFAULT_MAX_SIZE.get(kind, DEFAULT_MAX_SIZE["file"])


def sample_content_type(kind: str, accept: list[str] | None) -> str:
    """The content type the scenarios, tests and seeds use for a field: the first accepted type a sample exists for,
    else the kind's default (an `image/*` pattern reads as PNG)."""
    for mime in accept or []:
        if mime in SAMPLE_FILES:
            return mime
    for mime in accept or []:
        if mime.endswith("/*"):
            return SAMPLE_CONTENT_TYPE.get(kind) or mime.replace("/*", "/png")
    if accept and kind == "file":
        return accept[0]
    return SAMPLE_CONTENT_TYPE.get(kind, "application/pdf")


def _language_field(fields: list[dict[str, Any]]) -> str | None:
    for field in fields:
        if field.get("name", "").lower() in LANGUAGE_FIELDS and field.get("type") in ("string", "enum"):
            return field["name"]
    for field in fields:
        values = field.get("values") or []
        if field.get("type") == "enum" and values and all(_LANGUAGE_CODE.match(str(v)) for v in values):
            return field["name"]
    return None


def _label_field(fields: list[dict[str, Any]], language: str | None) -> str | None:
    for field in fields:
        named = field.get("name", "").lower() in LABEL_FIELDS
        if named and field.get("type") == "string" and field["name"] != language:
            return field["name"]
    return None


def _children(spec: dict[str, Any], parent: str) -> list[tuple[str, str]]:
    """(child entity, its foreign key to `parent`) from the relationships, else from a `<parent>Id` field."""
    out: list[tuple[str, str]] = []
    for rel in spec.get("relationships") or []:
        kind = rel.get("type")
        if kind == "one-to-many" and rel.get("from") == parent and rel.get("to"):
            out.append((rel["to"], rel.get("foreignKey") or f"{parent[:1].lower()}{parent[1:]}Id"))
        elif kind == "many-to-one" and rel.get("to") == parent and rel.get("from"):
            out.append((rel["from"], rel.get("foreignKey") or f"{parent[:1].lower()}{parent[1:]}Id"))
    known = {child for child, _ in out}
    key = f"{parent[:1].lower()}{parent[1:]}Id"
    for entity in spec.get("entities") or []:
        if entity["name"] != parent and entity["name"] not in known:
            if any(f.get("name") == key for f in entity.get("fields") or []):
                out.append((entity["name"], key))
    return out


def media_tracks(spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """`Entity.mediaField` → its subtitle tracks (D3): the same record's `subtitles` fields (`shape: field`) and the
    child entities with a `subtitles` field (`shape: child`, with their foreign key, language and label fields)."""
    entities = {entity["name"]: entity for entity in spec.get("entities") or []}
    out: dict[str, list[dict[str, Any]]] = {}
    for name, entity in entities.items():
        fields = entity.get("fields") or []
        media = [f["name"] for f in fields if f.get("type") in ("video", "audio")]
        if not media:
            continue
        tracks: list[dict[str, Any]] = []
        for field in fields:
            if field.get("type") == "subtitles":
                tracks.append({"shape": "field", "entity": name, "field": field["name"]})
        for child, fk in _children(spec, name):
            child_fields = entities.get(child, {}).get("fields") or []
            subtitle = next((f["name"] for f in child_fields if f.get("type") == "subtitles"), None)
            if not subtitle:
                continue
            language = _language_field(child_fields)
            tracks.append(
                {
                    "shape": "child",
                    "entity": child,
                    "field": subtitle,
                    "parent": fk,
                    "language": language,
                    "label": _label_field(child_fields, language),
                }
            )
        if tracks:
            for field in media:
                out[f"{name}.{field}"] = tracks
    return out


def track_children(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The child entities that are subtitle tracks (one fixture row per sample language), by entity name."""
    out: dict[str, dict[str, Any]] = {}
    for tracks in media_tracks(spec).values():
        for track in tracks:
            if track["shape"] == "child":
                out[track["entity"]] = track
    return out
