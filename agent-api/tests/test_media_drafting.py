"""Epic 29 (Story 29.5): drafting picks media fields: a `file` field that is really a video, an audio file or
subtitles (by its accepted types or its name) becomes that type, with a note; the answer schema lists the types."""

import json
from pathlib import Path

from src.orchestrator.drafting.answer_schema import app_answer_schema
from src.orchestrator.drafting.app import fix_backend_defaults, media_kind_of


def test_the_answer_schema_lists_the_media_types():
    schema = app_answer_schema("backend-spec.json", "app-outline.json", "notes.json", design=True)
    field = schema["$defs"]["FieldDef"]["properties"]["type"]
    assert {"video", "audio", "subtitles", "image", "file"} <= set(field["enum"])


def test_a_file_field_becomes_its_media_kind_by_accept_or_name():
    assert media_kind_of({"name": "attachment", "type": "file", "accept": ["video/mp4", "video/webm"]}) == "video"
    assert media_kind_of({"name": "attachment", "type": "file", "accept": ["audio/*"]}) == "audio"
    assert media_kind_of({"name": "attachment", "type": "file", "accept": ["application/pdf"]}) is None
    assert media_kind_of({"name": "attachment", "type": "file", "accept": ["video/mp4", "application/zip"]}) is None
    assert media_kind_of({"name": "introClip", "type": "file"}) == "video"
    assert media_kind_of({"name": "recording", "type": "file"}) == "audio"
    assert media_kind_of({"name": "captionsFile", "type": "file"}) == "subtitles"
    assert media_kind_of({"name": "contract", "type": "file"}) is None


def test_fix_backend_defaults_rewrites_the_media_files_with_notes(tmp_path: Path):
    spec = {
        "specVersion": "1.0",
        "project": {"name": "Clips"},
        "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlalchemy", "migration": "alembic"},
        "entities": [
            {
                "name": "Clip",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True},
                    {"name": "title", "type": "string", "required": True},
                    {"name": "video", "type": "file", "accept": ["video/*"]},
                    {"name": "transcript", "type": "file"},
                    {"name": "contract", "type": "file", "accept": ["application/pdf"]},
                ],
            },
            {
                "name": "Episode",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True},
                    {"name": "recording", "type": "file"},
                    {"name": "cover", "type": "image"},
                ],
            },
        ],
        "operations": [],
    }
    (tmp_path / "backend-spec.json").write_text(json.dumps(spec))
    notes = fix_backend_defaults(tmp_path, "backend-spec.json")
    fixed = json.loads((tmp_path / "backend-spec.json").read_text())
    clip = {f["name"]: f for f in fixed["entities"][0]["fields"]}
    assert clip["video"]["type"] == "video" and "accept" not in clip["video"]
    assert clip["transcript"]["type"] == "subtitles"
    assert clip["contract"]["type"] == "file"
    episode = {f["name"]: f for f in fixed["entities"][1]["fields"]}
    assert episode["recording"]["type"] == "audio"
    messages = [note["message"] for note in notes]
    assert "Clip.video: a file people watch is `video`" in messages
    assert "Clip.transcript: a file people read along is `subtitles`" in messages
    assert "Episode.recording: a file people listen to is `audio`" in messages
    assert any("Clip has a video but no image field" in message for message in messages)
    assert not any("Episode has a video" in message for message in messages)
    # a draft without media: unchanged, no note of this kind
    plain = {**spec, "entities": [spec["entities"][0] | {"fields": spec["entities"][0]["fields"][:2]}]}
    (tmp_path / "plain.json").write_text(json.dumps(plain))
    assert not any("is `" in note["message"] for note in fix_backend_defaults(tmp_path, "plain.json"))
