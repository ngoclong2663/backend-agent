"""Product patterns (Epic 32, Story 32.2): the `pattern` kind in the design registry, each area's kind and pattern.
`back-office` is the planner as it always was (the golden screens snapshots in `test_app_screens.py` hold it)."""

import json

import pytest

from scripts.app_design_report import golden_app
from src.modules.shared.domain.frontend_spec.design_registry import DesignPluginDescriptor, registry
from src.orchestrator.frontend.app.patterns import (
    app_areas,
    area_kind,
    area_pattern,
    area_patterns,
    contract_roles,
    manages,
)
from src.orchestrator.frontend.app.plan import plan_app

PATTERN = {
    "kind": "pattern",
    "name": "feed",
    "label": "Feed",
    "choose": "People scroll and react.",
    "archetypes": ["feed"],
    "menu": ["main", "mine"],
    "children": {"interaction": "inline", "contribution": "sheet", "part": "tab"},
}


def test_a_pattern_descriptor_places_every_shape_and_serves_one_archetype():
    assert DesignPluginDescriptor.model_validate(PATTERN).children["contribution"] == "sheet"
    for broken in (
        {**PATTERN, "children": {"interaction": "inline", "part": "tab"}},  # a shape without a place
        {**PATTERN, "children": {**PATTERN["children"], "part": "drawer"}},  # not a placement
        {**PATTERN, "menu": []},
        {**PATTERN, "menu": ["main", "everything"]},
        {**PATTERN, "never": ["tables"]},
        {**PATTERN, "checks": ["looks-nice"]},
        {**PATTERN, "archetypes": ["feed", "catalogue"]},  # one archetype, its own name
    ):
        with pytest.raises(ValueError):
            DesignPluginDescriptor.model_validate(broken)
    with pytest.raises(ValueError):  # the pattern fields are a pattern's
        DesignPluginDescriptor.model_validate(
            {"kind": "home", "name": "x", "label": "X", "choose": "x", "dispatch": False, "menu": ["main"]}
        )


def test_the_registry_ships_back_office_ready_and_the_first_patterns_as_drafts():
    patterns = registry().plugins["pattern"]
    assert patterns["back-office"].status == "ready"
    assert patterns["back-office"].menu == ["every"] and set(patterns["back-office"].children.values()) == {"tab"}
    for name in ("feed", "storefront"):  # ready in Stories 32.5 and 32.6
        assert patterns[name].status == "draft"
    assert area_pattern("feed").name == "back-office", "a draft pattern is never followed"
    assert area_pattern("workspace").name == "back-office", "an archetype without a pattern"


def test_staff_who_manage_the_main_entity_are_a_back_office_whatever_the_look():
    """Story 32.1's finding: the clinic's front desk was `booking` like the patients' area. The front desk manages the
    appointments (staff), the patients do not; a producer-only app is the producer's back-office."""
    spec, backend, contract = golden_app("clinic-bookings")
    kinds = {k: v["kind"] for k, v in area_patterns(spec, contract).items()}
    assert kinds == {"patient": "booking", "front-desk": "back-office"}
    spec, _, contract = golden_app("lantern-audio")
    assert {v["kind"] for v in area_patterns(spec, contract).values()} == {"back-office"}
    spec, _, contract = golden_app("news-feed")  # members and editors in one area: members do not manage posts
    assert manages(contract, "Post", ["editor"]) and not manages(contract, "Post", ["member", "editor"])
    assert area_patterns(spec, contract) == {"app": {"kind": "feed", "pattern": "back-office"}}


def test_an_area_without_an_archetype_or_a_main_entity_is_a_back_office():
    spec = {"app": {"design": {}}}
    area = app_areas(spec, ["member"])[0]
    assert (area["archetype"], area["main"]) == ("back-office", None)
    assert area_kind(None, ["member"], None, {"paths": {}, "x-bga": {}}) == "back-office"


def test_the_plan_records_each_areas_kind_and_pattern():
    spec, _, contract = golden_app("plant-shop")
    from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data

    normalized = validate_frontend_spec_data(spec).normalized
    patterns = plan_app(normalized, contract)["app"]["patterns"]
    assert patterns == {
        "storefront": {"kind": "storefront", "pattern": "back-office"},
        "management": {"kind": "back-office", "pattern": "back-office"},
    }
    assert contract_roles(contract) == ["shopper", "owner"]
    json.dumps(patterns)  # it goes into the plan artifact
