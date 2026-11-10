"""Epic 33 (Stories 33.7-33.12): the five domains built on their reference drafts, as if the model had named them,
and judged by their UX tasks (the baseline drafts recorded with today's kit, Story 33.1)."""

import json

import pytest

from scripts.domain_report import TASKS, replanned
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.orchestrator.frontend.app.domain_tasks import judge

# what each domain answers on its baseline draft; drivers' customer tracking needs a customer role, which that draft
# doesn't have (the domain offers the area; Story 33.11's real draft)
EXPECTED = {
    "socials": set(),
    "news": set(),
    "learning": set(),
    "drivers": {"track-delivery"},
    "iot": set(),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_domain_answers_its_tasks(name):
    spec = replanned(name, domain=name)
    assert validate_frontend_spec_data(spec).report.valid
    assert spec["app"]["domain"]["name"] == name
    results = judge(spec, json.loads((TASKS / f"{name}.json").read_text())["tasks"])
    assert {r["id"] for r in results if not r["passed"]} == EXPECTED[name], [r for r in results if not r["passed"]]


def _sections(spec, component):
    return [(page["route"], s) for page in spec["pages"] for s in page["sections"] if s["component"] == component]


def test_the_learning_home_resumes_with_progress():
    spec = replanned("learning", domain="learning")
    route, resume = _sections(spec, "AppResume")[0]
    assert route == "/" and resume["content"]["resume"] == {
        "state": "myEnrollmentId",
        "recordPage": "courses-id",
        "done": "myCompletedCount",
        "total": "lessonCount",
    }
    lesson = next(p for p in spec["pages"] if p["route"] == "/lessons/[id]")
    complete = next(a for a in lesson["sections"][0]["content"]["actions"] if a["id"] == "complete")
    assert complete["body"] == {"lessonId": "$route.id", "courseId": "$record.courseId"}


def test_a_driver_goes_online_and_delivers_with_a_photo_and_the_delivery_shows_its_steps():
    spec = replanned("drivers", domain="drivers")
    assert [route for route, _ in _sections(spec, "AppPresence")] == ["/driver"]
    timeline = _sections(spec, "AppTimeline")[0][1]
    assert timeline["content"]["timeline"]["states"][0] == "offered"
    form = next(f for f in spec["forms"] if f["id"] == "driver_delivery_completeDelivery")
    assert [f["name"] for f in form["fields"] if f.get("upload")] == ["proofPhoto"]


def test_the_operators_overview_charts_every_measure():
    spec = replanned("iot", domain="iot")
    route, chart = _sections(spec, "AppChart")[0]
    assert route == "/" and chart["content"]["chart"]["time"] == "recordedAt"
    assert {s["field"] for s in chart["content"]["chart"]["series"]} >= {"temperature", "humidity", "co2"}
    device = [r for r, s in _sections(spec, "AppChart") if r.endswith("/devices/[id]")]
    assert device, "a device's page charts its own readings"
