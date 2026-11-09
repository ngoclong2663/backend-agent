"""Epic 25: who may see and do what, correct by default (Stories 25.2–25.5), on synthetic specs that cover the
shapes (a person's record, an assigned worker, staff creating for a person, reference data), not one domain."""

import copy

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.drafting.access import owner_from_request, person_roles, secure_access
from src.orchestrator.integration.contract import build_fixtures
from src.orchestrator.plugins import extended_spec

STACK = {"framework": "fastapi", "database": "postgresql", "orm": "sqlalchemy", "migration": "alembic"}


def _crud(entity: str, path: str, policies: dict[str, str | None]) -> list[dict]:
    stem = entity[:1].lower() + entity[1:]
    shapes = {
        "create": ("POST", path),
        "get": ("GET", f"{path}/{{id}}"),
        "list": ("GET", path),
        "update": ("PATCH", f"{path}/{{id}}"),
        "delete": ("DELETE", f"{path}/{{id}}"),
    }
    out = []
    for action, policy in policies.items():
        method, route = shapes[action]
        op = {"operationId": f"{stem}.{action}", "type": "crud", "action": action, "entity": entity}
        op |= {"method": method, "path": route}
        if policy:
            op["policy"] = policy
        out.append(op)
    return out


def spec(created_by: str = "staff") -> dict:
    """Members own cases; staff manage them; a worker is assigned to a case; catalog items are reference data."""
    policies = [
        {"name": "staffOnly", "type": "role", "roles": ["staff"]},
        {"name": "memberOnly", "type": "role", "roles": ["member"]},
        {"name": "workerOnly", "type": "role", "roles": ["worker"]},
        {"name": "creators", "type": "role", "roles": [created_by]},
    ]
    actions = [
        ("accept", "memberOnly"),
        ("assign", "staffOnly"),
        ("finish", "workerOnly"),
    ]
    return {
        "specVersion": "1.0",
        "project": {"name": "Cases", "description": "A synthetic app with records that belong to people"},
        "stack": STACK,
        "auth": {"type": "jwt", "roles": ["member", "staff", "worker"]},
        "policies": policies,
        "entities": [
            {
                "name": "Case",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True},
                    {"name": "title", "type": "string", "required": True},
                    {"name": "memberId", "type": "uuid", "required": True},
                    {"name": "workerId", "type": "uuid"},
                    {"name": "status", "type": "enum", "values": ["OPEN", "ACCEPTED", "DONE"], "default": "OPEN"},
                    {"name": "createdAt", "type": "datetime", "default": "now"},
                ],
            },
            {
                "name": "CatalogItem",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True},
                    {"name": "name", "type": "string", "required": True, "unique": True},
                ],
            },
        ],
        "rules": [
            {
                "id": "caseFlow",
                "kind": "transition",
                "entity": "Case",
                "params": {"field": "status", "transitions": {"OPEN": ["ACCEPTED"], "ACCEPTED": ["DONE"]}},
            }
        ],
        "operations": [
            *_crud("Case", "/cases", {"create": "creators", "get": None, "list": None, "update": "staffOnly"}),
            *[
                {
                    "operationId": f"case.{name}",
                    "type": "custom",
                    "method": "POST",
                    "path": f"/cases/{{id}}/{name}",
                    "policy": policy,
                    "rules": ["caseFlow"],
                }
                for name, policy in actions
            ],
            {
                "operationId": "case.countByStatus",
                "type": "aggregate",
                "entity": "Case",
                "method": "GET",
                "path": "/cases/aggregate/count-by-status",
                "aggregate": {"fn": "count", "groupBy": "status"},
            },
            *_crud("CatalogItem", "/catalog-items", {"create": "staffOnly", "get": None, "list": None}),
        ],
    }


def _ops(data: dict) -> dict:
    return {op["operationId"]: op for op in data["operations"]}


def _policy(data: dict, op_id: str) -> dict:
    name = _ops(data)[op_id].get("policy")
    return next((p for p in data["policies"] if p["name"] == name), {}) if name else {}


def test_a_persons_records_are_private_and_staff_read_them():
    data = spec()
    notes = secure_access(data)
    assert validate_spec_data(data).report.valid
    listing = _policy(data, "case.list")
    assert listing == {"name": listing["name"], "type": "ownership", "ownerField": "memberId", "bypassRoles": ["staff"]}
    reading = _policy(data, "case.get")
    assert reading["ownerField"] == "memberId" and set(reading["bypassRoles"]) == {"staff", "worker"}, (
        "an assigned worker opens a record by id; lists stay private"
    )
    assert _policy(data, "case.countByStatus") == {
        "name": "caseStaffFigures",
        "type": "role",
        "roles": ["staff"],
    }, "figures over private records are the staff's"
    assert "policy" not in _ops(data)["catalogItem.list"], "reference data stays public"
    assert any("private to its member" in note["message"] for note in notes)


def test_each_action_belongs_to_its_role():
    data = spec()
    secure_access(data)
    accept = _policy(data, "case.accept")
    assert accept["type"] == "ownership" and accept["ownerField"] == "memberId" and accept["bypassRoles"] == []
    finish = _policy(data, "case.finish")
    assert finish["type"] == "ownership" and finish["ownerField"] == "workerId" and finish["bypassRoles"] == []
    assert _ops(data)["case.assign"]["policy"] == "staffOnly", "a staff action stays the staff role's"


def test_an_owner_action_with_a_staff_bypass_loses_the_bypass():
    data = spec()
    data["policies"].append({"name": "own", "type": "ownership", "ownerField": "memberId", "bypassRoles": ["staff"]})
    for op in data["operations"]:
        if op["operationId"] in ("case.get", "case.list", "case.accept"):
            op["policy"] = "own"
    secure_access(data)
    assert _ops(data)["case.get"]["policy"] == "own"
    assert _policy(data, "case.accept")["bypassRoles"] == []


def test_a_status_with_a_flow_changes_only_through_its_actions():
    data = spec()
    notes = secure_access(data)
    update = _ops(data)["case.update"]
    assert update["request"]["entity"] == "Case"
    assert "status" not in update["request"]["fields"] and "title" in update["request"]["fields"]
    assert "caseFlow" not in (update.get("rules") or [])
    assert any("'status' changes only through its actions" in note["message"] for note in notes)


def test_staff_creating_for_a_person_name_the_person():
    data = spec(created_by="staff")
    notes = secure_access(data)
    assert validate_spec_data(data).report.valid
    assert owner_from_request(copy.deepcopy(data), "Case")
    user = next(entity for entity in data["entities"] if entity["name"] == "User")
    assert {field["name"] for field in user["fields"]} >= {"id", "email", "role"}
    assert {"user.list", "user.get"} <= set(_ops(data))
    assert _policy(data, "user.list")["roles"] == ["staff"], "the user directory is for those who create"
    assert any(r["from"] == "User" and r["foreignKey"] == "memberId" for r in data["relationships"])
    assert any("create it for a member" in note["message"] for note in notes)


def test_a_person_creating_their_own_record_stays_the_owner():
    data = spec(created_by="member")
    notes = secure_access(data)
    assert validate_spec_data(data).report.valid
    assert not owner_from_request(copy.deepcopy(data), "Case")
    assert not any("create it for" in note["message"] for note in notes)
    links = {r["foreignKey"] for r in data["relationships"] if r["from"] == "User"}
    assert links == {"workerId"}, "only the assignee is picked in a form; the owner is the signed-in member"
    assert _policy(data, "user.list")["roles"] == ["staff"], "the staff pick the worker"


def test_without_sign_in_or_people_nothing_changes():
    data = spec()
    data.pop("auth")
    before = copy.deepcopy(data)
    assert secure_access(data) == [] and data == before
    plain = spec()
    plain["entities"][0]["fields"] = [f for f in plain["entities"][0]["fields"] if not f["name"].endswith("Id")]
    plain["operations"] = [op for op in plain["operations"] if not op["operationId"].startswith("case.")]
    assert secure_access(plain) == []


def test_person_fields_name_their_roles():
    data = spec()
    secure_access(data)
    assert person_roles(data) == {("Case", "memberId"): ["member"], ("Case", "workerId"): ["worker"]}


def test_the_seed_gives_each_demo_user_of_a_person_role_records_of_their_own():
    """Story 25.5: person fields name demo users of their role; a second demo user per person role."""
    data = spec(created_by="member")
    secure_access(data)
    normalized = validate_spec_data(data).normalized
    records, _ = build_fixtures(extended_spec(normalized), build_plan(normalized))
    users = {row["id"]: row for row in records["User"]}
    logins = sorted(row["email"] for row in users.values())
    assert "demo-member-2@example.com" in logins and "demo-worker-2@example.com" in logins
    owners = {users[row["memberId"]]["role"] for row in records["Case"]}
    workers = {users[row["workerId"]]["role"] for row in records["Case"] if row.get("workerId")}
    assert owners == {"member"} and workers <= {"worker"}
    members = {users[row["memberId"]]["email"] for row in records["Case"]}
    assert len(members) == 2, "both demo members own records"


def test_the_secured_spec_plans_and_builds_its_contract():
    """The directory and the access policies go through the planner and the contract (a real run found a pagination
    the contract could not read)."""
    from src.orchestrator.integration.contract import build_contract

    for created_by in ("staff", "member"):
        data = spec(created_by=created_by)
        secure_access(data)
        normalized = validate_spec_data(data).normalized
        contract = build_contract(normalized, build_plan(normalized))
        ops = {op["operationId"] for methods in contract["paths"].values() for op in methods.values()}
        assert {"user.list", "user.get", "case.accept", "case.finish"} <= ops
        create = contract["paths"]["/cases"]["post"]
        schema = create["requestBody"]["content"]["application/json"]["schema"]
        name = schema["$ref"].rsplit("/", 1)[1]
        member = contract["components"]["schemas"][name]["properties"]["memberId"]
        source = (member.get("x-bga") or {}).get("source")
        assert source == ("reference" if created_by == "staff" else "currentUser") or (
            created_by == "member" and "memberId" not in contract["components"]["schemas"][name]["properties"]
        )


def test_pagination_true_on_a_custom_list_means_the_default_limits():
    """Story 25.1 (a real agy draft): `"pagination": true` on a custom GET list crashed the contract."""
    from src.orchestrator.integration.contract import build_contract

    data = spec(created_by="member")
    data["operations"].append(
        {
            "operationId": "case.listMine",
            "type": "custom",
            "entity": "Case",
            "method": "GET",
            "path": "/cases/mine",
            "pagination": True,
            "response": {"entity": "Case", "type": "array"},
        }  # fmt: skip
    )
    normalized = validate_spec_data(data).normalized
    mine = next(op for op in normalized["operations"] if op["operationId"] == "case.listMine")
    assert mine["pagination"] == {"defaultLimit": 20, "maxLimit": 100}
    contract = build_contract(normalized, build_plan(normalized))  # no crash on the paginated custom list
    assert contract["paths"]["/cases/mine"]["get"]["operationId"] == "case.listMine"


def test_records_a_staff_role_makes_for_everyone_stay_readable_by_the_other_roles():
    """gen_01M6Z75NJYKSXNF4JGQPZ4XYF8 (2026-11-09, Ember Kitchen): courses name their instructor; the rule made them
    private to that instructor, so learners opened an empty course list. A record whose person field names the role
    that creates it is made for the other roles: they read every record, the owner alone writes it."""
    data = {
        "specVersion": "1.0",
        "project": {"name": "Courses", "description": "Instructors publish courses that learners browse"},
        "stack": STACK,
        "auth": {"type": "jwt", "roles": ["learner", "instructor"]},
        "policies": [{"name": "instructorsOnly", "type": "role", "roles": ["instructor"]}],
        "entities": [
            {
                "name": "Course",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True},
                    {"name": "title", "type": "string", "required": True},
                    {"name": "instructorId", "type": "uuid", "required": True},
                ],
            }
        ],
        "operations": _crud(
            "Course",
            "/courses",
            {
                "create": "instructorsOnly",
                "get": None,
                "list": None,
                "update": "instructorsOnly",
                "delete": "instructorsOnly",
            },
        ),
    }
    secure_access(data)
    assert validate_spec_data(data).report.valid
    listing = _policy(data, "course.list")
    assert listing["type"] == "ownership" and listing["ownerField"] == "instructorId"
    assert listing["bypassRoles"] == ["learner"], "learners read every course"
    assert _policy(data, "course.get")["bypassRoles"] == ["learner"]
    assert _policy(data, "course.update") == {"name": "instructorsOnly", "type": "role", "roles": ["instructor"]}
