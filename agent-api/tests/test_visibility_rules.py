"""Visibility rules (Story 23.9): "learners see only published courses" is a backend rule. Lists narrow, a hidden
record is 404, the entity's figures are for the other roles, and the contract, the scenarios and the template tests
carry it. Learnly (Story 23.0's real draft) had the sentence in its requirement and no rule for it."""

import ast
import copy
import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.codegen import module_files, module_tests
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.integration.contract import build_contract

EXAMPLES = Path(__file__).parents[2] / "examples"
RULE = {"name": "publishedOnly", "type": "visibility", "entity": "Course", "roles": ["learner"],
        "where": {"status": "published"}}  # fmt: skip


def _learnly(rule: dict | None = RULE) -> dict:
    spec = json.loads((EXAMPLES / "specs" / "learning-platform.json").read_text())
    if rule:
        spec["policies"].append(copy.deepcopy(rule))
    return spec


def _built(spec: dict):
    normalized = validate_spec_data(spec).normalized
    plan = build_plan(normalized)
    module = next(m for m in plan["modules"] if m.get("entity") == "Course")
    return normalized, plan, module


def test_a_rule_names_an_entity_and_values_it_has():
    assert validate_spec_data(_learnly()).report.valid
    for bad, message in (
        ({**RULE, "entity": "Ghost"}, "needs a known entity"),
        ({**RULE, "where": {"status": "archived"}}, "'archived' is not a value of Course.status"),
        ({**RULE, "where": {"nowhere": 1}}, "has no field 'nowhere'"),
        ({**RULE, "roles": ["guest"]}, "Role 'guest' is not declared"),
    ):
        errors = [issue.message for issue in validate_spec_data(_learnly(bad)).report.errors]
        assert any(message in error for error in errors), (bad, errors)
    named = _learnly()
    next(op for op in named["operations"] if op["operationId"] == "course.list")["policy"] = "publishedOnly"
    assert any("applies to its entity's reads by itself" in i.message for i in validate_spec_data(named).report.errors)


def test_lists_and_reads_check_who_is_asking():
    spec, plan, module = _built(_learnly())
    ops = {op["operationId"]: op for op in module["operations"]}
    for op_id in ("course.list", "course.get"):
        rule = ops[op_id]["auth"]["visibility"]
        assert rule["roles"] == ["learner"] and rule["where"] == [
            {"field": "status", "attr": "status", "value": "published"}
        ]
    files = module_files(plan, spec, module) | module_tests(plan, spec, module)
    joined = "\n".join(files.values())
    assert 'visible_only = True if current_user is None or current_user.role in ("learner",) else None' in joined
    assert (
        "if (current_user is None or current_user.role in (\"learner\",)) and not (course.status == 'published'):"
        in joined
    )
    assert "col(CourseModel.status) == 'published'" in joined
    assert "OptionalUserDep" in joined, "a public read takes the signed-in user, if any"
    for path, text in files.items():
        if path.endswith(".py") and text.strip():
            ast.parse(text)
    cases = {test["case"] for test in module["tests"]}
    assert {"hidden_record", "visible_only"} <= cases
    tests = next(text for path, text in files.items() if path.startswith("tests/") and "hidden_record" in text)
    assert "status='draft'" in tests and "status='published'" in tests


def test_the_figures_are_for_the_roles_that_see_everything():
    spec, plan, module = _built(_learnly())
    aggregate = next(op for op in module["operations"] if op["operationId"] == "course.countWhereStatusPublished")
    assert aggregate["auth"]["roles"] == ["manager"]
    router = next(text for path, text in module_files(plan, spec, module).items() if path.endswith("router.py"))
    handler = router.split(f"async def {aggregate['handler']}(", 1)[1].split("):", 1)[0]
    assert 'require_roles("manager")' in handler, "the route itself refuses a learner (it ignored policies before)"


def test_the_contract_carries_the_rule_and_a_404_scenario():
    spec, plan, _ = _built(_learnly())
    contract = build_contract(spec, plan)
    get = contract["paths"]["/courses/{id}"]["get"]
    assert get["x-bga"]["visibility"] == {
        "policy": "publishedOnly",
        "roles": ["learner"],
        "where": {"status": "published"},
    }
    assert contract["x-bga"]["entities"]["Course"]["visibility"]["where"] == {"status": "published"}
    hidden = [s for s in get["x-bga"]["scenarios"] if s["name"] == "a record this role may not see"]
    assert hidden and hidden[0]["expect"] == {"status": 404, "code": "NOT_FOUND"}
    assert hidden[0]["user"].startswith("demo-learner")


def test_a_public_read_with_a_rule_takes_no_token():
    """gen_01M6RJ17148HNE5MWEK0QKDZKA (2026-11-06): the rule made the public reads `bearerAuth` in the contract, so it
    expected a 401 the app (an optional user) never answers, and the frontend put the pages behind sign-in."""
    spec, plan, _ = _built(_learnly())
    contract = build_contract(spec, plan)
    for path in ("/courses", "/courses/{id}"):
        read = contract["paths"][path]["get"]
        assert "security" not in read and "401" not in read["responses"], path
        assert not any(s["name"] == "no token" for s in read["x-bga"]["scenarios"]), path
    assert contract["paths"]["/courses"]["post"]["security"] == [{"bearerAuth": []}]


def test_a_figure_for_some_roles_is_signed_in_in_the_contract():
    """gen_01M6RNS949KSV5QKARTS1ENA46 (2026-11-06): the guarded counts had no `bearerAuth`, so the frontend showed
    them to every visitor and the live API answered 401."""
    spec, plan, module = _built(_learnly())
    contract = build_contract(spec, plan)
    aggregate = next(op for op in module["operations"] if op["operationId"] == "course.countWhereStatusPublished")
    path = next(
        p for p, item in contract["paths"].items() if item.get("get", {}).get("operationId") == aggregate["operationId"]
    )
    read = contract["paths"][path]["get"]
    assert read["security"] == [{"bearerAuth": []}] and "401" in read["responses"]
    assert read["x-bga"]["action"] == "aggregate"


def test_without_a_rule_nothing_changes():
    spec, plan, module = _built(_learnly(None))
    joined = "\n".join(module_files(plan, spec, module).values())
    assert "visible_only" not in joined
    assert not any("visibility" in (op.get("auth") or {}) for op in module["operations"])


# -- 2026-11-09: two real drafts (Epic 30's final check) whose mocks broke the contract's scenarios -------------------

SPECS = Path(__file__).parent / "fixtures" / "specs"


def _scenarios(name: str, operation_id: str) -> tuple[list[dict], dict]:
    spec = validate_spec_data(json.loads((SPECS / name).read_text())).normalized
    contract = build_contract(spec, build_plan(spec))
    for item in contract["paths"].values():
        for op in item.values():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return op["x-bga"]["scenarios"], contract
    raise AssertionError(operation_id)


def test_the_no_token_scenario_of_a_secured_read_with_a_rule_stays_unauthenticated():
    """gen_01M6Z63NYZ0EFVPZG0YJK659R8 (Ember Kitchen): learners see only published lessons, every read is signed in;
    the rule's scenario pass made the auth plugin's "no token" call run as an instructor, so the mock answered 200
    where the contract expects 401."""
    scenarios, _ = _scenarios("ember-kitchen.json", "lesson.get")
    no_token = next(s for s in scenarios if s["name"] == "no token")
    assert no_token["auth"] is False and "user" not in no_token and no_token["expect"]["status"] == 401
    success = next(s for s in scenarios if s["name"] == "success")
    assert success["auth"] is True and success["user"].startswith("demo-instructor"), "a user who sees drafts"


def test_a_public_read_with_a_rule_reads_a_visible_record_in_its_success_scenario():
    """gen_01M6Z63RXKVZN823Y6RY74CNYV (Lantern Audio): anyone reads published episodes, drafts are never public; the
    success scenario pointed at the first seeded episode, a draft, so the signed-out mock answered 404."""
    scenarios, contract = _scenarios("lantern-audio.json", "episode.get")
    success = next(s for s in scenarios if s["name"] == "success")
    episodes = {str(row["id"]): row for row in contract["x-bga"]["fixtures"]["Episode"]}
    assert episodes[str(success["params"]["id"])]["status"] == "published"
    assert not success.get("auth") and not success.get("user"), "a public read stays signed out"
    assert not any(s["name"] == "no token" for s in scenarios)
