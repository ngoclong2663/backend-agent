"""Epic 15: site images. 15.1 asset sources, validation, planning and the registry; 15.2 drawings."""

import copy
import json
import os
from pathlib import Path

import pytest

from src.engines.fake_engine import GOLDEN_ASSETS, FakeEngine, FakeStep, demo_scenario
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.modules.shared.domain.frontend_spec.assets import lucide_icons
from src.orchestrator.asset_registry import assets_ts
from src.orchestrator.frontend_planner import plan_frontend
from src.orchestrator.svg_assets import check_component, check_svg, svg_to_tsx
from tests.generation_helpers import EXAMPLES
from workflow_helpers import cli_invocations, events, node_runs, run_job

FIXTURES = Path(__file__).parent / "fixtures"
LANDING = json.loads((EXAMPLES / "frontend-specs" / "static-landing.json").read_text())


def _issues(assets: list[dict]) -> list[tuple[str, str]]:
    spec = copy.deepcopy(LANDING)
    spec["assets"] += assets
    report = validate_frontend_spec_data(spec).report
    return [(issue.code, issue.path) for issue in report.errors + report.warnings]


# -- 15.1 sources and checks -------------------------------------------------------------------------------------------


def test_every_source_kind_validates():
    assets = [
        {"id": "logo", "kind": "logo", "source": "upload:upl_01J8ABCDEF", "alt": "Northwind"},
        {"id": "dots", "kind": "pattern", "source": "generate", "decorative": True},
        {"id": "mail", "kind": "icon", "source": "lucide:Mail", "decorative": True},
        {"id": "office", "source": "https://cdn.example.com/office.jpg", "alt": "Our office"},
    ]
    assert _issues(assets) == []
    assert "Mail" in lucide_icons() and len(lucide_icons()) > 1000


@pytest.mark.parametrize(
    ("asset", "code", "path"),
    [
        ({"id": "x", "source": "placeholder"}, "FE_ASSET_ALT_REQUIRED", "/assets/3/alt"),
        ({"id": "x", "alt": "X", "source": "http://example.com/x.png"}, "FE_INSECURE_URL", "/assets/3/source"),
        ({"id": "x", "alt": "X", "source": "data:image/png;base64,AA"}, "FE_INSECURE_URL", "/assets/3/source"),
        ({"id": "x", "alt": "X", "source": "somewhere"}, "FE_UNSUPPORTED_ASSET_SOURCE", "/assets/3/source"),
        (
            {"id": "x", "kind": "video", "alt": "X", "source": "generate"},
            "FE_UNSUPPORTED_ASSET_SOURCE",
            "/assets/3/source",
        ),
        (
            {"id": "x", "kind": "icon", "alt": "X", "source": "generate"},
            "FE_UNSUPPORTED_ASSET_SOURCE",
            "/assets/3/source",
        ),
        ({"id": "x", "kind": "icon", "alt": "X", "source": "lucide:NoSuchIcon"}, "FE_UNKNOWN_ICON", "/assets/3/source"),
        ({"id": "x", "kind": "icon", "alt": "X", "source": "lucide:mail"}, "FE_UNKNOWN_ICON", "/assets/3/source"),
        ({"id": "x", "alt": "X", "source": "upload:../etc"}, "FE_UNKNOWN_UPLOAD", "/assets/3/source"),
    ],
)
def test_asset_issues_have_stable_codes(asset, code, path):
    assert (code, path) in _issues([asset])


def test_too_many_generated_assets_is_a_warning():
    many = [{"id": f"g{i}", "kind": "illustration", "source": "generate", "alt": f"G {i}"} for i in range(12)]
    spec = copy.deepcopy(LANDING)
    spec["assets"] += many
    report = validate_frontend_spec_data(spec).report
    assert report.valid and [w.code for w in report.warnings] == ["FE_TOO_MANY_GENERATED_ASSETS"]


def test_an_empty_state_image_must_be_a_declared_asset():
    spec = json.loads((EXAMPLES / "frontend-specs" / "project-tracker-dynamic.json").read_text())
    spec["pages"][0]["sections"][0]["states"]["emptyImage"] = "asset:missing"
    report = validate_frontend_spec_data(spec).report
    assert ("FE_UNKNOWN_ASSET", "/pages/0/sections/0/states/emptyImage") in [(e.code, e.path) for e in report.errors]


# -- 15.1 plan and registry --------------------------------------------------------------------------------------------


def _plan(spec: dict) -> dict:
    result = validate_frontend_spec_data(spec)
    assert result.report.valid, result.report
    return plan_frontend(result.normalized)


def test_the_plan_lists_each_asset_with_its_render_mode_file_and_routes():
    spec = copy.deepcopy(LANDING)
    spec["layout"]["header"]["logo"] = "asset:logo"
    spec["assets"] += [
        {"id": "logo", "kind": "logo", "source": "upload:upl_01J8ABCDEF", "alt": "Northwind"},
        {"id": "mail", "kind": "icon", "source": "lucide:Mail", "decorative": True},
    ]
    assets = {asset["id"]: asset for asset in _plan(spec)["assets"]}
    assert assets["hero"]["render"] == "svg-component" and assets["hero"]["routes"] == ["/"]
    assert assets["hero"]["file"] == "src/assets/svg/hero.svg"
    assert assets["hero"]["component"] == "src/components/assets/generated/HeroAsset.tsx"
    assert assets["work-1"]["prompt"].startswith("Bakery packaging") and assets["work-1"]["aspectRatio"] == "16:9"
    assert assets["work-2"]["render"] == "placeholder" and assets["work-2"]["routes"] == ["/work"]
    assert assets["logo"]["render"] == "public-file" and assets["logo"]["upload"] == "upl_01J8ABCDEF"
    assert len(assets["logo"]["routes"]) == 5, "the header logo shows on every page"
    assert (assets["mail"]["render"], assets["mail"]["icon"], assets["mail"]["routes"]) == ("icon", "Mail", [])


def test_the_registry_renders_undrawn_svgs_as_placeholders_and_imports_drawn_ones():
    plan = _plan(copy.deepcopy(LANDING))
    text = assets_ts(plan)
    snapshot = FIXTURES / "assets-registry.ts"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.write_text(text)
    assert text == snapshot.read_text(), "registry changed: review, then rerun with UPDATE_SNAPSHOTS=1"
    assert '"hero": { mode: "placeholder"' in text and "generated/" not in text
    plan["assets"][0]["drawn"] = True
    drawn = assets_ts(plan)
    assert 'import HeroAsset from "@/components/assets/generated/HeroAsset";' in drawn
    assert (
        '"hero": { mode: "svg-component", aspectRatio: "16:9", alt: "Studio desk with sketches", component: HeroAsset }'
        in drawn
    )


# -- 15.2 drawings -----------------------------------------------------------------------------------------------------

OPTIONS = {"engine": "fake", "deployPreview": False}


@pytest.fixture
def auth(login):
    return {"Authorization": f"Bearer {login('user@test.local', 'userpass')}"}


def _submit(client, auth: dict, spec: dict) -> str:
    response = client.post("/api/v1/generations", json={"mode": "static", "frontendSpec": spec, "options": OPTIONS},
                           headers=auth)  # fmt: skip
    assert response.status_code == 202, response.text
    return response.json()["generationId"]


def _node(generation_id: str, name: str):
    return next(run for run in node_runs(generation_id) if run.node == name)


def test_a_drawing_becomes_a_themed_accessible_component():
    svg = (GOLDEN_ASSETS / "work-1.svg").read_text()
    asset = {"id": "work-1", "alt": "Bakehouse packaging", "file": "src/assets/svg/work-1.svg"}
    tsx = svg_to_tsx(svg, asset, "Work1Asset")
    snapshot = FIXTURES / "assets" / "Work1Asset.tsx"
    snapshot.parent.mkdir(exist_ok=True)
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.write_text(tsx)
    assert tsx == snapshot.read_text(), "conversion changed: review, then rerun with UPDATE_SNAPSHOTS=1"
    assert 'role="img" aria-label="Bakehouse packaging"' in tsx and '<title>{"Bakehouse packaging"}</title>' in tsx
    assert 'stopColor="var(--secondary)"' in tsx and 'strokeWidth="4"' in tsx and "stroke-width" not in tsx
    assert 'id="work-1-shade"' in tsx and 'fill="url(#work-1-shade)"' in tsx, "ids are prefixed with the asset id"
    assert check_component(tsx) == []
    decorative = svg_to_tsx(svg, {**asset, "decorative": True}, "Work1Asset")
    assert 'aria-hidden="true"' in decorative and "<title>" not in decorative


def test_the_converter_drops_what_the_safe_rule_forbids():
    hostile = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1600 900">'
        '<script>alert(1)</script><rect width="10" height="10" onclick="x()" fill="var(--primary)" />'
        '<use xlink:href="https://example.com/a.svg#i" /><foreignObject><div /></foreignObject></svg>'
    )
    tsx = svg_to_tsx(hostile, {"id": "x", "alt": "X"}, "XAsset")
    assert "script" not in tsx and "onClick" not in tsx and "onclick" not in tsx
    assert "example.com" not in tsx and "foreignObject" not in tsx and 'fill="var(--primary)"' in tsx


def test_the_static_landing_draws_its_illustrations_once_then_from_the_cache(client, auth, tmp_path):
    first = _submit(client, auth, LANDING)
    assert run_job(tmp_path, first, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED"
    node = _node(first, "generate_assets")
    assert node.summary == {"assets": 2, "drawn": 2, "cacheHits": 0, "engineCalls": 2}
    assert [call.purpose for call in cli_invocations(first)] == ["generate_assets", "generate_assets"]
    frontend = tmp_path / first / "frontend"
    assert (frontend / "src/assets/svg/hero.svg").read_text() == (GOLDEN_ASSETS / "hero.svg").read_text()
    registry = (frontend / "src/assets/index.ts").read_text()
    assert 'import HeroAsset from "@/components/assets/generated/HeroAsset";' in registry
    assert '"work-2": { mode: "placeholder"' in registry
    assert (frontend / "src/components/assets/generated/Work1Asset.tsx").is_file()
    owned = json.loads((frontend / ".bga/owned.json").read_text())
    assert {"src/assets/svg/hero.svg", "src/components/assets/generated/HeroAsset.tsx", "src/assets/index.ts"} <= set(
        owned
    )
    ready = [e.payload for e in events(first) if e.type == "frontend.asset.ready"]
    assert sorted((p["id"], p["cached"]) for p in ready) == [("hero", False), ("work-1", False)]

    second = _submit(client, auth, LANDING)
    assert run_job(tmp_path, second, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED"
    assert _node(second, "generate_assets").summary == {"assets": 2, "drawn": 2, "cacheHits": 2, "engineCalls": 0}
    assert cli_invocations(second) == []


def test_only_the_requested_drawings_come_back(client, auth, tmp_path):
    hero = (GOLDEN_ASSETS / "hero.svg").read_text()
    step = FakeStep(write={"src/assets/svg/hero.svg": hero, "src/app/page.tsx": "export default 1;\n"})
    scenario = {**demo_scenario(0), "generate_assets": [step]}
    generation_id = _submit(client, auth, LANDING)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario)) == "COMPLETED"
    out_of_scope = [e.payload["files"] for e in events(generation_id) if e.type == "frontend.asset.out_of_scope"]
    assert any("src/app/page.tsx" in files for files in out_of_scope)
    home = (tmp_path / generation_id / "frontend" / "src/app/page.tsx").read_text()
    assert "export default 1;" not in home, "the engine's write outside the request is discarded"
    assert _node(generation_id, "generate_assets").summary["drawn"] == 1, "work-1 was not drawn: placeholder"
    missing = [e.payload["id"] for e in events(generation_id) if e.type == "frontend.asset.missing"]
    assert missing == ["work-1"]


def test_a_site_without_generated_assets_skips_the_step(client, auth, tmp_path):
    spec = copy.deepcopy(LANDING)
    for asset in spec["assets"]:
        asset.update(source="placeholder")
    generation_id = _submit(client, auth, spec)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED"
    node = _node(generation_id, "generate_assets")
    assert node.status == "skipped" and cli_invocations(generation_id) == []


def test_golden_drawings_pass_every_check():
    for path in GOLDEN_ASSETS.glob("*.svg"):
        ratio = "4:3" if path.stem == "empty-projects" else "16:9"
        assert check_svg(path.read_text(), ratio) == [], path.name


# -- 15.3 checks and fallback ------------------------------------------------------------------------------------------

GOOD = (GOLDEN_ASSETS / "hero.svg").read_text()
LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">]>'
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900"><g>&lol2;</g></svg>'
)


def _with(body: str, view_box: str = "0 0 1600 900") -> str:
    namespaces = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
    return f'<svg {namespaces} viewBox="{view_box}">{body}</svg>'


@pytest.mark.parametrize(
    ("svg", "rule", "fragment"),
    [
        (_with("<script>alert(1)</script>"), "safe", "<script>"),
        (_with('<rect width="1" height="1" onload="x()" fill="none" />'), "safe", "onload"),
        (_with('<use xlink:href="https://example.com/a.svg#i" />'), "safe", "links outside"),
        (_with('<image href="data:image/png;base64,AAAA" />'), "safe", "<image>"),
        (_with('<rect width="1" height="1" fill="url(https://example.com/x)" />'), "safe", "points outside"),
        (_with('<rect width="1" height="1" style="fill:url(https://example.com/x)" />'), "safe", "points outside"),
        (LAUGHS, "safe", "DTDs and entities"),
        (_with(f'<path d="M0 0 {"L1 1 " * 1_000_000}" fill="none" />'), "valid", "KB"),
        (_with('<rect width="1" height="1" fill="#ff0000" />'), "theme", "#ff0000"),
        (_with('<rect width="1" height="1" style="stroke:rgb(1,2,3)" />'), "theme", "rgb(1,2,3)"),
        (_with("", "0 0 100 100"), "valid", "aspect ratio"),
        (_with("<foreignObject><div /></foreignObject>"), "safe", "foreignObject"),
    ],
)
def test_hostile_drawings_are_caught_with_their_rule(svg, rule, fragment):
    issues = check_svg(svg, "16:9")
    assert any(issue.rule == rule and fragment in issue.message for issue in issues), issues


def test_uploaded_svgs_skip_the_theme_rule():
    hex_only = _with('<rect width="1" height="1" fill="#ff0000" />')
    assert check_svg(hex_only, None, theme=False) == [] and check_svg(GOOD, "16:9") == []


def test_an_unsafe_drawing_is_repaired_once_then_falls_back_and_the_job_warns(client, auth, tmp_path):
    scenario = {**demo_scenario(0), "generate_assets": [FakeStep(unsafe_assets=True)]}
    generation_id = _submit(client, auth, LANDING)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario)) == "COMPLETED_WITH_WARNINGS"
    nodes = [run.node for run in node_runs(generation_id)]
    assert nodes.count("validate_frontend") == 2 and nodes.count("repair_frontend") == 1
    fallbacks = sorted(e.payload["id"] for e in events(generation_id) if e.type == "frontend.asset.fallback")
    assert fallbacks == ["hero", "work-1"]
    frontend = tmp_path / generation_id / "frontend"
    assert (
        not (frontend / "src/assets/svg/hero.svg").exists()
        and "generated/" not in (frontend / "src/assets/index.ts").read_text()
    )
    plan = json.loads((frontend / ".bga/frontend-plan.json").read_text())
    hero = next(asset for asset in plan["assets"] if asset["id"] == "hero")
    assert hero["fallback"].startswith("safe: ") and hero["repairs"] == 1
    from workflow_helpers import generation

    assert generation(generation_id).error_summary.startswith("Images shown as placeholders: hero (safe:")
    first = _node(generation_id, "validate_frontend")
    assert "assets" in first.summary["failedChecks"]


def test_a_repaired_drawing_is_used(client, auth, tmp_path):
    fixed = {f"src/assets/svg/{name}.svg": (GOLDEN_ASSETS / f"{name}.svg").read_text() for name in ("hero", "work-1")}
    scenario = {
        **demo_scenario(0),
        "generate_assets": [FakeStep(unsafe_assets=True)],
        "repair_frontend": [FakeStep(write=fixed)],
    }
    generation_id = _submit(client, auth, LANDING)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, scenario)) == "COMPLETED"
    frontend = tmp_path / generation_id / "frontend"
    assert (
        'import HeroAsset from "@/components/assets/generated/HeroAsset";'
        in (frontend / "src/assets/index.ts").read_text()
    )
    assert _node(generation_id, "repair_frontend").summary["assetsRepaired"] == ["hero", "work-1"]
    assert not [e for e in events(generation_id) if e.type == "frontend.asset.fallback"]


# -- 15.4 uploads and links --------------------------------------------------------------------------------------------


def _png(size=(64, 48), exif: bool = False) -> bytes:
    import io

    from PIL import Image

    image = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCam"  # Make
        data[0x8825] = {2: (51.0, 30.0, 0.0)}  # GPS latitude
        image.save(out, format="JPEG", exif=data.tobytes())
    else:
        image.save(out, format="PNG")
    return out.getvalue()


def _upload(client, auth, name: str, data: bytes):
    return client.post("/api/v1/uploads", files={"file": (name, data)}, headers=auth)


def test_an_upload_is_sniffed_cleaned_and_kept_once(client, auth):
    from PIL import Image

    response = _upload(client, auth, "photo.jpg", _png(exif=True))
    assert response.status_code == 201, response.text
    upload = response.json()
    assert upload["mime"] == "image/jpeg" and (upload["width"], upload["height"]) == (64, 48)
    assert upload["source"] == f"upload:{upload['uploadId']}"
    content = client.get(f"/api/v1/uploads/{upload['uploadId']}/content", headers=auth)
    assert content.status_code == 200 and content.headers["content-type"] == "image/jpeg"
    import io

    assert not Image.open(io.BytesIO(content.content)).getexif(), "EXIF and GPS are stripped"
    again = _upload(client, auth, "copy.jpg", _png(exif=True))
    assert again.status_code == 200 and again.json()["uploadId"] == upload["uploadId"]
    listed = client.get("/api/v1/uploads", headers=auth).json()
    assert [u["uploadId"] for u in listed["uploads"]] == [upload["uploadId"]] and listed["usedBytes"] == upload["bytes"]


def test_large_images_are_shrunk_and_svgs_checked(client, auth):
    big = _upload(client, auth, "wide.png", _png(size=(4000, 1000))).json()
    assert (big["width"], big["height"]) == (2560, 640)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<rect width="200" height="100" fill="#123456"/></svg>'
    )
    logo = _upload(client, auth, "logo.svg", svg.encode())
    assert logo.status_code == 201 and (logo.json()["mime"], logo.json()["width"]) == ("image/svg+xml", 200)
    unsafe = _upload(
        client, auth, "x.svg", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>'
    )
    assert unsafe.status_code == 422 and unsafe.json()["error"]["code"] == "UPLOAD_UNSAFE"


def test_the_type_comes_from_the_content(client, auth):
    fake = _upload(client, auth, "image.png", b"<!doctype html><html><script>alert(1)</script></html>")
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "UPLOAD_TYPE_UNSUPPORTED"
    renamed = _upload(client, auth, "notes.txt", _png())
    assert renamed.status_code == 201 and renamed.json()["mime"] == "image/png"


def test_upload_limits(client, auth, monkeypatch):
    from src.configs import config

    monkeypatch.setattr(config, "upload_max_mb", 0)
    too_big = _upload(client, auth, "a.png", _png())
    assert too_big.status_code == 413 and too_big.json()["error"]["details"]["limitMb"] == 0
    monkeypatch.setattr(config, "upload_max_mb", 5)
    monkeypatch.setattr(config, "upload_quota_mb", 0)
    over = _upload(client, auth, "b.png", _png(size=(10, 10)))
    assert over.status_code == 413 and over.json()["error"]["code"] == "UPLOAD_QUOTA_EXCEEDED"


def test_other_users_uploads_are_not_found(client, auth, login):
    upload = _upload(client, auth, "a.png", _png()).json()
    other = {"Authorization": f"Bearer {login('other@test.local', 'otherpass')}"}
    assert client.get(f"/api/v1/uploads/{upload['uploadId']}/content", headers=other).status_code == 404
    assert client.delete(f"/api/v1/uploads/{upload['uploadId']}", headers=other).status_code == 404
    spec = copy.deepcopy(LANDING)
    spec["assets"].append({"id": "logo", "kind": "logo", "source": upload["source"], "alt": "Logo"})
    refused = client.post("/api/v1/generations", json={"mode": "static", "frontendSpec": spec, "options": OPTIONS},
                          headers=other)  # fmt: skip
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0] == {
        "code": "FE_UNKNOWN_UPLOAD", "path": "/assets/3/source",
        "message": f"'{upload['source']}' is not one of your uploads",
        "severity": "error",
    }  # fmt: skip
    assert client.delete(f"/api/v1/uploads/{upload['uploadId']}", headers=auth).status_code == 204


def test_an_uploaded_logo_and_a_linked_image_reach_the_site(client, auth, tmp_path):
    upload = _upload(client, auth, "logo.png", _png(size=(120, 120))).json()
    spec = copy.deepcopy(LANDING)
    spec["layout"]["header"]["logo"] = "asset:logo"
    spec["assets"] += [
        {"id": "logo", "kind": "logo", "source": upload["source"], "alt": "Northwind"},
        {"id": "office", "source": "https://cdn.example.com/office.jpg", "alt": "Our office"},
    ]
    spec["pages"][4]["sections"].append(
        {"id": "office", "component": "Gallery", "content": {"items": [{"image": "asset:office", "title": "Office"}]}}
    )
    generation_id = _submit(client, auth, spec)
    assert run_job(tmp_path, generation_id, engine=FakeEngine(tmp_path, demo_scenario(0))) == "COMPLETED"
    frontend = tmp_path / generation_id / "frontend"
    assert (frontend / "public/assets/logo.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    registry = (frontend / "src/assets/index.ts").read_text()
    assert (
        '"logo": { mode: "public-file", aspectRatio: "1:1", alt: "Northwind", src: "/assets/logo.png", '
        "width: 120, height: 120 }" in registry
    )
    assert (
        '"office": { mode: "remote", aspectRatio: "16:9", alt: "Our office", '
        'src: "https://cdn.example.com/office.jpg" }' in registry
    )
    assert "- `office`: https://cdn.example.com/office.jpg" in (frontend / "README.md").read_text()
    assert _node(generation_id, "scaffold_frontend").summary["uploads"] == 1
    owned = json.loads((frontend / ".bga/owned.json").read_text())
    assert "public/assets/logo.png" in owned


def test_unused_old_uploads_are_pruned(client, auth):
    from datetime import UTC, datetime, timedelta

    from src.orchestrator.store import JobStore

    kept = _upload(client, auth, "kept.png", _png(size=(11, 11))).json()
    dropped = _upload(client, auth, "dropped.png", _png(size=(12, 12))).json()
    spec = copy.deepcopy(LANDING)
    spec["assets"].append({"id": "logo", "kind": "logo", "source": kept["source"], "alt": "Logo"})
    _submit(client, auth, spec)  # a saved FrontendSpec now uses `kept`
    assert JobStore().prune_uploads(datetime.now(UTC) + timedelta(days=1)) >= 1
    ids = [u["uploadId"] for u in client.get("/api/v1/uploads", headers=auth).json()["uploads"]]
    assert kept["uploadId"] in ids and dropped["uploadId"] not in ids
