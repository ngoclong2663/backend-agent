"""Epic 29 (Stories 29.1, 29.2, 29.4): `video`, `audio` and `subtitles` fields through the schema, the planner, the
storage plugin, the contract's fixtures and scenarios, the seeds' sample objects, the design brief and `app.json`."""

import base64
import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.backend_spec.media import PLAYABLE, media_tracks, sample_content_type
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.frontend.app.design import complete_design
from src.orchestrator.frontend.app.files import app_data
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.codegen import mock_plugins
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.frontend.scaffold import scaffold_frontend
from src.orchestrator.integration.contract import build_contract, contract_operations
from src.orchestrator.packaging import seed_artifact
from src.orchestrator.samples import SAMPLES_DIR, sample_bytes, storage_objects

EXAMPLES = Path(__file__).parents[2] / "examples"


def _media_spec() -> dict:
    return json.loads((EXAMPLES / "specs" / "media-library.json").read_text())


def _planned():
    backend = validate_spec_data(_media_spec()).normalized
    raw = json.loads((EXAMPLES / "app-outlines" / "media-library.json").read_text())
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    theme = {"style": "dashboard", "colorScheme": "light-dark", "density": "comfortable"}
    spec = validate_frontend_spec_data(app_frontend_spec(backend, outline, theme, contract).spec).normalized
    return backend, spec, contract


# -- 29.1 ---------------------------------------------------------------------------------------------------------


def test_media_fields_validate_and_get_playable_defaults():
    result = validate_spec_data(_media_spec())
    assert result.report.valid, [issue.message for issue in result.report.errors]
    plan = build_plan(result.normalized)
    fields = {f["name"]: f for f in plan["storage"]["fields"]}
    assert fields["Lesson.video"]["kind"] == "video" and fields["Lesson.video"]["accept"] == PLAYABLE["video"]
    assert fields["Lesson.video"]["maxSize"] == 200 * 1024 * 1024
    assert (
        fields["Episode.audio"]["maxSize"] == 50 * 1024 * 1024
        and fields["Episode.audio"]["accept"] == PLAYABLE["audio"]
    )
    assert fields["Caption.file"]["kind"] == "subtitles" and fields["Caption.file"]["maxSize"] == 1024 * 1024
    assert fields["Course.cover"]["kind"] == "image" and fields["Course.cover"]["maxSize"] == 5 * 1024 * 1024
    assert fields["Lesson.video"]["prefix"] == "lesson/video"


def test_an_accept_outside_the_playable_set_is_refused_with_the_allowed_list():
    raw = _media_spec()
    lesson = next(e for e in raw["entities"] if e["name"] == "Lesson")
    next(f for f in lesson["fields"] if f["name"] == "video")["accept"] = ["video/mp4", "video/x-msvideo"]
    report = validate_spec_data(raw).report
    [issue] = [i for i in report.errors if i.path.endswith("/accept/1")]
    assert "not a type browsers play as video" in issue.message and "video/mp4, video/webm" in (issue.hint or "")
    next(f for f in lesson["fields"] if f["name"] == "video")["accept"] = ["video/webm"]  # narrowing is fine
    assert validate_spec_data(raw).report.valid


def test_the_storage_plugin_speaks_each_kinds_type():
    backend = validate_spec_data(_media_spec()).normalized
    contract = build_contract(backend, build_plan(backend))
    ops = {op_id: found["operation"] for op_id, found in contract_operations(contract).items()}
    presign = ops["files.presign"]["x-bga"]["scenarios"]
    assert presign[0]["body"]["contentType"] == "image/png"  # the first field (Course.cover)
    assert sample_content_type("video", PLAYABLE["video"]) == "video/mp4"
    assert sample_content_type("audio", ["audio/ogg"]) == "audio/ogg"
    assert sample_content_type("subtitles", None) == "text/vtt"
    assert sample_content_type("image", ["image/*"]) == "image/png"
    objects = {item["key"]: item["contentType"] for item in contract["x-bga"]["storage"]["objects"]}
    assert objects["lesson/video/shared/seed/1.mp4"] == "video/mp4"
    assert objects["episode/audio/shared/seed/1.mp3"] == "audio/mpeg"
    assert objects["caption/file/shared/seed/1.en.vtt"] == "text/vtt"
    assert objects["caption/file/shared/seed/2.ja.vtt"] == "text/vtt"
    assert ops["lesson.create"]["x-bga"]["scenarios"][0]["body"]["video"] == "lesson/video/shared/seed/1.mp4"
    upload = contract["components"]["schemas"]["CreateLessonRequest"]["properties"]["video"]["x-bga"]["upload"]
    assert upload["kind"] == "video" and upload["accept"] == PLAYABLE["video"]
    assert {"field": "video", "urlField": "videoUrl", "kind": "video"} in contract["x-bga"]["entities"]["Lesson"][
        "fileFields"
    ]


def test_subtitle_tracks_are_found_in_both_shapes():
    backend = validate_spec_data(_media_spec()).normalized
    tracks = media_tracks(backend)
    assert tracks["Lesson.video"] == [
        {
            "shape": "child",
            "entity": "Caption",
            "field": "file",
            "parent": "lessonId",
            "language": "language",
            "label": "label",
        }
    ]
    assert tracks["Episode.audio"] == [{"shape": "field", "entity": "Episode", "field": "transcript"}]
    contract = build_contract(backend, build_plan(backend))
    assert contract["x-bga"]["storage"]["tracks"] == tracks
    # a child without a language field: one track, no language
    raw = _media_spec()
    caption = next(e for e in raw["entities"] if e["name"] == "Caption")
    caption["fields"] = [f for f in caption["fields"] if f["name"] != "language"]
    for op in raw["operations"]:
        if op["entity"] == "Caption":
            op["filters"] = [f for f in op.get("filters", []) if f != "language"]
            if op.get("request"):
                op["request"]["fields"] = [f for f in op["request"]["fields"] if f != "language"]
    found = media_tracks(validate_spec_data(raw).normalized)["Lesson.video"][0]
    assert found["language"] is None and found["label"] == "label"


def test_read_urls_carry_the_files_type():
    library = (
        Path(__file__).parents[1] / "templates/plugins/storage/backend/files/src/libs/storage/s3_storage.py"
    ).read_text()
    assert 'params["ResponseContentType"] = content_type' in library and '"vtt": "text/vtt"' in library


# -- 29.2 ---------------------------------------------------------------------------------------------------------


def test_the_fixtures_give_tracks_one_row_per_sample_language():
    backend = validate_spec_data(_media_spec()).normalized
    contract = build_contract(backend, build_plan(backend))
    captions = contract["x-bga"]["fixtures"]["Caption"]
    assert [(row["language"], row["file"]) for row in captions] == [
        ("en", "caption/file/shared/seed/1.en.vtt"),
        ("ja", "caption/file/shared/seed/2.ja.vtt"),
    ]
    first_lesson = contract["x-bga"]["fixtures"]["Lesson"][0]["id"]
    assert all(row["lessonId"] == first_lesson for row in captions), "both languages on one lesson"
    episodes = contract["x-bga"]["fixtures"]["Episode"]
    assert episodes[0]["audio"] == "episode/audio/shared/seed/1.mp3"
    assert episodes[0]["transcript"] == "episode/transcript/shared/seed/1.en.vtt"


def test_the_samples_exist_are_small_and_are_what_the_seeds_upload():
    for name in (
        "sample.mp4",
        "sample.webm",
        "sample.mp3",
        "sample.ogg",
        "sample-poster.jpg",
        "sample.en.vtt",
        "sample.ja.vtt",
        "sample.en.srt",
    ):
        path = SAMPLES_DIR / name
        assert path.is_file() and path.stat().st_size < 400 * 1024, name
    assert sample_bytes("video/mp4")[4:8] == b"ftyp"
    assert sample_bytes("text/vtt", "ja").startswith(b"WEBVTT") and "サンプル".encode() in sample_bytes(
        "text/vtt", "ja"
    )
    assert sample_bytes("application/x-nothing").startswith(b"\x89PNG")
    backend = validate_spec_data(_media_spec()).normalized
    plan = build_plan(backend)
    contract = build_contract(backend, plan)
    objects = {item["key"]: item for item in storage_objects(contract)}
    ja = objects["caption/file/shared/seed/2.ja.vtt"]
    assert base64.b64decode(ja["data"]).startswith(b"WEBVTT") and "サンプル".encode() in base64.b64decode(ja["data"])
    assert base64.b64decode(objects["lesson/video/shared/seed/1.mp4"]["data"])[4:8] == b"ftyp"
    seed = seed_artifact(contract, plan)
    assert isinstance(seed, dict) and seed["rows"] and len(seed["objects"]) == len(objects)
    plain = json.loads((EXAMPLES / "specs" / "two-entity.json").read_text())
    plain_backend = validate_spec_data(plain).normalized
    assert isinstance(
        seed_artifact(build_contract(plain_backend, build_plan(plain_backend)), build_plan(plain_backend)), list
    )


def test_the_mocks_know_each_fields_kind_and_the_app_ships_the_samples(tmp_path):
    backend, spec, contract = _planned()
    plugins = mock_plugins(contract)
    assert plugins["storage"]["fields"]["Lesson.video"]["kind"] == "video"
    assert plugins["storage"]["tracks"]["Lesson.video"][0]["entity"] == "Caption"
    plan = plan_frontend(spec, contract)
    assert plan["app"]["media"] is True
    scaffold_frontend(tmp_path / "frontend", plan, spec, contract)
    assert (tmp_path / "frontend/public/samples/sample.mp4").is_file()
    assert (tmp_path / "frontend/public/samples/sample.ja.vtt").is_file()
    assert not (tmp_path / "frontend/public/samples/README.md").exists()
    assert (tmp_path / "frontend/src/components/plugins/storage/VideoPlayer.tsx").is_file()
    registry = (tmp_path / "frontend/src/components/app/plugins.ts").read_text()
    assert 'export { UploadField, FileValue, ListeningBar } from "@/components/plugins/storage";' in registry


def test_an_app_without_media_ships_no_samples(tmp_path):
    raw = json.loads((EXAMPLES / "specs" / "workshop-bookings.json").read_text())
    backend = validate_spec_data(raw).normalized
    outline_raw = json.loads((EXAMPLES / "app-outlines" / "workshop-bookings.json").read_text())
    outline, _ = complete_outline(outline_raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    theme = {"style": "dashboard", "colorScheme": "light-dark", "density": "comfortable"}
    spec = validate_frontend_spec_data(app_frontend_spec(backend, outline, theme, contract).spec).normalized
    plan = plan_frontend(spec, contract)
    assert plan["app"]["media"] is False
    scaffold_frontend(tmp_path / "frontend", plan, spec, contract)
    assert not (tmp_path / "frontend/public/samples").exists()


# -- 29.4 ---------------------------------------------------------------------------------------------------------


def test_app_json_carries_the_tracks_the_media_kinds_and_the_duration_role():
    backend, spec, contract = _planned()
    data = app_data(plan_frontend(spec, contract), spec, contract)
    assert data["media"] == {"video": True, "audio": True, "subtitles": True}
    [track] = data["entities"]["Lesson"]["tracks"]["video"]
    assert track["shape"] == "child" and track["listOperation"] == "caption.list" and track["parent"] == "lessonId"
    assert data["entities"]["Episode"]["tracks"]["audio"] == [
        {"shape": "field", "entity": "Episode", "field": "transcript"}
    ]
    assert data["entities"]["Lesson"]["fields"]["video"] == {"type": "video", "urlField": "videoUrl"}
    lesson = data["design"]["entities"]["Lesson"]
    assert lesson["roles"]["media"] == "video" and lesson["roles"]["duration"] == "durationSeconds"
    assert lesson["detailView"] == "media"
    assert data["design"]["entities"]["Episode"]["roles"]["duration"] == "durationMinutes"


def test_the_brief_takes_a_video_as_media_and_defaults_its_detail_to_the_player():
    backend = validate_spec_data(_media_spec()).normalized
    design, _, replaced = complete_design(
        {"archetype": "catalogue", "mainEntity": "Lesson", "entities": {}}, [], backend
    )
    lesson = design["entities"]["Lesson"]
    assert lesson["roles"]["media"] == "video" and lesson["roles"]["duration"] == "durationSeconds"
    assert lesson["detailView"] == "watch" and lesson["view"] == "media-grid"  # Story 30.5: a watch page (Up next)
    assert design["entities"]["Episode"]["roles"]["media"] == "audio"
    # a non-number field cannot be the duration; a text field cannot be the media
    design, _, replaced = complete_design(
        {
            "archetype": "catalogue",
            "mainEntity": "Lesson",
            "entities": {"Lesson": {"roles": {"duration": "title", "media": "description"}}},
        },
        [],
        backend,
    )
    assert any("duration 'title' left out" in line for line in replaced)
    assert any("media 'description' left out" in line for line in replaced)
    assert design["entities"]["Lesson"]["roles"]["media"] == "video"
