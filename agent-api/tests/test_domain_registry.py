"""Epic 33 (Story 33.3): the domain, type and feature plugin kinds."""

import json
from pathlib import Path

import pytest

from src.modules.shared.domain.domains.registry import DomainRegistry, DomainRegistryError, registry

FEATURE = {
    "name": "reactions",
    "label": "Reactions",
    "status": "ready",
    "attachesTo": "content",
    "choose": "People like or save a record and see that they did.",
}
DOMAIN = {
    "name": "socials",
    "label": "Socials",
    "status": "ready",
    "choose": "A community where members post and react.",
    "words": ["community", "followers"],
    "roles": {"content": {"label": "Post", "words": ["post", "clip"], "needs": ["media", "author"]}},
    "areas": [{"id": "members", "label": "Members", "people": ["member"], "pattern": "feed", "main": "content"}],
    "features": {"required": [{"feature": "reactions", "on": "content"}]},
}
TYPE = {
    "name": "short-video-feed",
    "label": "Short-video feed",
    "status": "ready",
    "choose": "One video per screen.",
    "areas": {"members": {"pages": [{"id": "feed", "title": "Feed", "route": "/", "menu": True}], "home": "feed"}},
}


def _write(root: Path, rel: str, data: dict) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _templates(tmp_path: Path, domain=DOMAIN, feature=FEATURE, kind=TYPE) -> Path:
    _write(tmp_path, f"features/{feature['name']}/feature.json", feature)
    _write(tmp_path, f"domains/{domain['name']}/domain.json", domain)
    _write(tmp_path, f"domains/{domain['name']}/types/{kind['name']}/type.json", kind)
    return tmp_path


def test_the_three_kinds_load_and_link(tmp_path):
    reg = DomainRegistry(_templates(tmp_path), strict=True)
    assert [d.name for d in reg.ready_domains()] == ["socials"]
    assert [t.name for t in reg.ready_types("socials")] == ["short-video-feed"]
    assert reg.feature("reactions").attaches_to == "content"
    assert reg.domain("socials").roles["content"].needs == ["media", "author"]


def test_a_domain_naming_a_missing_feature_is_left_out(tmp_path):
    domain = {**DOMAIN, "features": {"required": [{"feature": "comments", "on": "content"}]}}
    reg = DomainRegistry(_templates(tmp_path, domain=domain))
    assert reg.domains == {} and "feature 'comments' is missing" in reg.problems[0]
    with pytest.raises(DomainRegistryError):
        DomainRegistry(tmp_path, strict=True)


def test_a_feature_on_an_unknown_role_and_a_type_on_an_unknown_area_are_left_out(tmp_path):
    domain = {**DOMAIN, "features": {"required": [{"feature": "reactions", "on": "lesson"}]}}
    assert DomainRegistry(_templates(tmp_path, domain=domain)).domains == {}
    kind = {**TYPE, "areas": {"drivers": TYPE["areas"]["members"]}}
    reg = DomainRegistry(_templates(tmp_path / "b", kind=kind))
    assert reg.types["socials"] == {} and "unknown area 'drivers'" in reg.problems[0]


def test_drafts_are_offered_only_behind_the_switch(tmp_path, monkeypatch):
    reg = DomainRegistry(_templates(tmp_path, domain={**DOMAIN, "status": "draft"}))
    monkeypatch.delenv("BGA_DESIGN_INCLUDE_DRAFTS", raising=False)
    assert reg.ready_domains() == [] and reg.domain("socials") is None
    monkeypatch.setenv("BGA_DESIGN_INCLUDE_DRAFTS", "1")
    assert reg.domain("socials") is not None


def test_a_folder_must_match_its_name(tmp_path):
    _write(tmp_path, "features/likes/feature.json", FEATURE)
    reg = DomainRegistry(tmp_path)
    assert reg.features == {} and "does not match its folder" in reg.problems[0]


def test_the_shipped_plugins_load_strictly():
    """Every folder under templates/domains and templates/features is valid (no hand-written list of names)."""
    reg = DomainRegistry(strict=True)
    assert reg.problems == []
    assert registry().domains.keys() == reg.domains.keys()
