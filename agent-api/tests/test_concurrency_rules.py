"""Concurrency rules (Story 10.10): capacity under a parent's row lock, noOverlap as an exclusion constraint,
uniqueTogether as a (partial) unique index; their errors by constraint name, concurrent template tests, scenarios."""

import json
from pathlib import Path

from src.orchestrator.backend.codegen import database_files, module_files, module_tests
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.integration.contract import build_contract, contract_operations
from tests.generation_helpers import normalized


def _crud(entity: str, plural: str) -> list[dict]:
    lower = entity[:1].lower() + entity[1:]
    return [
        {"operationId": f"{lower}.create", "type": "crud", "action": "create", "entity": entity, "method": "POST",
         "path": f"/{plural}"},
        {"operationId": f"{lower}.get", "type": "crud", "action": "get", "entity": entity, "method": "GET",
         "path": f"/{plural}/{{id}}"},
        {"operationId": f"{lower}.list", "type": "crud", "action": "list", "entity": entity, "method": "GET",
         "path": f"/{plural}"},
        {"operationId": f"{lower}.update", "type": "crud", "action": "update", "entity": entity, "method": "PATCH",
         "path": f"/{plural}/{{id}}"},
    ]  # fmt: skip


def booking_spec(tmp_path: Path) -> dict:
    """Workshops with seats, rooms, bookings: a workshop's active bookings fit its capacity, a room's active bookings
    never overlap, one active booking per attendee and workshop."""
    uuid_pk = {"name": "id", "type": "uuid", "primary": True}
    raw = {
        "specVersion": "1.0",
        "project": {"name": "Workshop Bookings"},
        "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlmodel", "migration": "alembic"},
        "entities": [
            {"name": "Workshop", "fields": [uuid_pk, {"name": "name", "type": "string", "required": True,
                                                       "maxLength": 120},
                                             {"name": "capacity", "type": "integer", "required": True, "min": 1}]},
            {"name": "Room", "fields": [uuid_pk, {"name": "name", "type": "string", "required": True,
                                                   "maxLength": 80}]},
            {"name": "Booking", "fields": [
                uuid_pk,
                {"name": "workshopId", "type": "uuid", "required": True},
                {"name": "roomId", "type": "uuid", "required": True},
                {"name": "attendeeEmail", "type": "string", "required": True, "maxLength": 255},
                {"name": "startsAt", "type": "datetime", "required": True},
                {"name": "endsAt", "type": "datetime", "required": True},
                {"name": "status", "type": "enum", "values": ["ACTIVE", "CANCELLED"], "default": "ACTIVE"}]},
        ],
        "relationships": [
            {"name": "workshopBookings", "type": "one-to-many", "from": "Workshop", "to": "Booking",
             "onDelete": "CASCADE"},
            {"name": "roomBookings", "type": "one-to-many", "from": "Room", "to": "Booking", "onDelete": "CASCADE"},
        ],
        "operations": [*_crud("Workshop", "workshops"), *_crud("Room", "rooms"), *_crud("Booking", "bookings")],
        "rules": [
            {"id": "seatLimit", "kind": "capacity", "entity": "Booking",
             "params": {"parent": "workshopId", "capacityField": "capacity", "where": {"status": {"ne": "CANCELLED"}}}},
            {"id": "roomFree", "kind": "noOverlap", "entity": "Booking",
             "params": {"start": "startsAt", "end": "endsAt", "scope": ["roomId"],
                        "where": {"status": {"ne": "CANCELLED"}}}},
            {"id": "oncePerWorkshop", "kind": "uniqueTogether", "entity": "Booking",
             "params": {"fields": ["workshopId", "attendeeEmail"], "where": {"status": {"ne": "CANCELLED"}}}},
        ],
    }  # fmt: skip
    (tmp_path / "booking-spec.json").write_text(json.dumps(raw))
    return normalized(tmp_path / "booking-spec.json")


def _bookings(plan: dict) -> dict:
    return next(module for module in plan["modules"] if module["name"] == "bookings")


def test_the_three_kinds_are_planned_as_a_lock_a_constraint_and_an_index(tmp_path):
    spec = booking_spec(tmp_path)
    plan = build_plan(spec)
    assert plan["unresolved"] == [] and {"name": "rules", "version": "1"} in plan["plugins"]
    booking = next(m for m in plan["models"] if m["entity"] == "Booking")
    assert set(booking["constraintErrors"]) == {"ex_bookings_room_free", "uq_bookings_once_per_workshop"}
    model = database_files(plan)["src/modules/shared/infrastructure/models/booking_model.py"]
    assert (
        'ExcludeConstraint((column("room_id"), "="), (func.tstzrange(column("starts_at"), column("ends_at"), "[)"),'
        in model
    )
    assert "where=text(\"status <> 'CANCELLED'\")" in model
    assert 'Index("uq_bookings_once_per_workshop", "workshop_id", "attendee_email", unique=True' in model
    files = module_files(plan, spec, _bookings(plan))
    create = files["src/modules/bookings/usecases/create_booking_usecase.py"]
    assert "taken, capacity = self.booking_repo.workshop_taken(dto.workshop_id)" in create
    assert "ErrorCode.CAPACITY_REACHED" in create
    repository = files["src/modules/bookings/infrastructure/persistence/booking_repository.py"]
    assert ".with_for_update()" in repository and "!= BookingStatus.CANCELLED" in repository
    assert '"ex_bookings_room_free": {"code": ErrorCode.OVERLAP' in repository
    for relative, source in files.items():
        compile(source, relative, "exec")


def test_each_kind_has_a_concurrent_template_test(tmp_path):
    spec = booking_spec(tmp_path)
    plan = build_plan(spec)
    tests = module_tests(plan, spec, _bookings(plan))["tests/modules/bookings/test_booking_api.py"]
    for name in ("seat_limit", "room_free", "once_per_workshop"):
        assert f"def test_create_booking__{name}_concurrent(client):" in tests
    assert "with ThreadPoolExecutor(2) as pool:" in tests and "assert statuses == [201, 409]" in tests
    assert "parent = _seed_workshop(capacity=1)" in tests
    compile(tests, "tests", "exec")


def test_the_contract_carries_their_errors_and_scenarios_that_do_not_collide(tmp_path):
    spec = booking_spec(tmp_path)
    contract = build_contract(spec)
    create = contract_operations(contract)["booking.create"]["operation"]["x-bga"]
    codes = {(e["code"], tuple(e.get("fields", []))) for e in create["errors"]}
    assert ("CAPACITY_REACHED", ("workshopId",)) in codes and ("OVERLAP", ("roomId", "startsAt", "endsAt")) in codes
    names = [s["name"] for s in create["scenarios"]]
    assert names[-3:] == ["workshop full", "overlap", "duplicate"]
    success = next(s for s in create["scenarios"] if s["name"] == "success")
    full = next(s for s in create["scenarios"] if s["name"] == "workshop full")
    assert success["body"]["workshopId"] != full["body"]["workshopId"]
    rows = contract["x-bga"]["fixtures"]["Booking"]
    assert all(row["endsAt"] > row["startsAt"] for row in rows)  # real ranges, so a record can be overlapped


def test_concurrency_rules_are_validated():
    from src.modules.shared.domain.backend_spec.validator import validate_spec_data

    raw = json.loads(
        (tmp := Path(__file__).resolve().parents[2] / "examples" / "specs" / "two-entity.json").read_text()
    )
    raw["rules"] = [
        {"id": "a", "kind": "capacity", "entity": "Task", "params": {"parent": "title", "capacityField": "x"}},
        {"id": "b", "kind": "noOverlap", "entity": "Task", "params": {"start": "title", "end": "dueDate"}},
        {"id": "c", "kind": "uniqueTogether", "entity": "Task", "params": {"fields": ["title"],
                                                                             "where": {"status": {"ne": "LOST"}}}},
    ]  # fmt: skip
    assert tmp.name == "two-entity.json"
    paths = {issue.path for issue in validate_spec_data(raw).report.errors}
    assert {"/rules/0/params/parent", "/rules/1/params/start", "/rules/2/params/fields",
            "/rules/2/params/where/status"} <= paths  # fmt: skip


def test_a_status_rule_next_to_a_concurrency_rule_on_one_operation(tmp_path):
    """Story 22.8 (the soccer draft on Antigravity): a booking's status flow and its no-overlap rule both guard
    `booking.update`; the contract used to crash (`KeyError: 'path'`) adding the transition's scenarios."""
    booking_spec(tmp_path)
    raw = json.loads((tmp_path / "booking-spec.json").read_text())
    raw["entities"][2]["fields"][-1]["values"] = ["PENDING", "ACTIVE", "CANCELLED"]
    raw["entities"][2]["fields"][-1]["default"] = "PENDING"
    raw["rules"].append(
        {"id": "bookingFlow", "kind": "transition", "entity": "Booking",
         "params": {"field": "status", "transitions": {"PENDING": ["ACTIVE", "CANCELLED"], "ACTIVE": ["CANCELLED"]}}}
    )  # fmt: skip
    next(op for op in raw["operations"] if op["operationId"] == "booking.update")["rules"] = ["bookingFlow"]
    (tmp_path / "booking-spec.json").write_text(json.dumps(raw))
    spec = normalized(tmp_path / "booking-spec.json")
    update = contract_operations(build_contract(spec))["booking.update"]["operation"]["x-bga"]
    codes = {error["code"] for error in update["errors"]}
    assert {"INVALID_TRANSITION", "OVERLAP"} <= codes, codes
    assert any("transition" in scenario["name"] for scenario in update["scenarios"]), [
        s["name"] for s in update["scenarios"]
    ]


def test_a_pair_with_the_signed_in_owner_is_checked_for_the_scenarios_user(tmp_path):
    """Lumen (2026-11-06): `uniqueTogether (ownerId, seriesId)` where the server sets `ownerId` from the signed-in
    user. The success must favourite a series its user has not, and the duplicate repeats a pair of that user's own,
    without the read-only owner in the body."""
    uuid_pk = {"name": "id", "type": "uuid", "primary": True}
    raw = {
        "specVersion": "1.0",
        "project": {"name": "Photo Series"},
        "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlmodel", "migration": "alembic"},
        "entities": [
            {"name": "Series", "fields": [uuid_pk, {"name": "title", "type": "string", "required": True,
                                                     "maxLength": 120}]},
            {"name": "Favourite", "fields": [uuid_pk, {"name": "ownerId", "type": "uuid", "required": True},
                                              {"name": "seriesId", "type": "uuid", "required": True}]},
        ],
        "relationships": [{"name": "seriesFavourites", "type": "one-to-many", "from": "Series", "to": "Favourite",
                           "foreignKey": "seriesId", "onDelete": "CASCADE"}],
        "auth": {"type": "jwt", "userEntity": "User", "loginField": "email", "roles": ["client", "photographer"]},
        "policies": [{"name": "ownFavourites", "type": "ownership", "ownerField": "ownerId",
                      "bypassRoles": ["photographer"]}],
        "operations": [
            *_crud("Series", "series"),
            {"operationId": "favourite.list", "type": "crud", "action": "list", "entity": "Favourite",
             "method": "GET", "path": "/favourites", "auth": "jwt", "policy": "ownFavourites"},
            {"operationId": "favourite.create", "type": "crud", "action": "create", "entity": "Favourite",
             "method": "POST", "path": "/favourites", "auth": "jwt", "rules": ["oncePerSeries"]},
        ],
        "rules": [{"id": "oncePerSeries", "kind": "uniqueTogether", "entity": "Favourite",
                   "params": {"fields": ["ownerId", "seriesId"]}}],
    }  # fmt: skip
    (tmp_path / "favourites.json").write_text(json.dumps(raw))
    spec = normalized(tmp_path / "favourites.json")
    plan = build_plan(spec)
    contract = build_contract(spec, plan)
    meta = contract["x-bga"]
    create = contract_operations(contract)["favourite.create"]["operation"]["x-bga"]
    scenarios = {s["name"]: s for s in create["scenarios"]}
    users = {row["email"]: row["id"] for row in meta["fixtures"]["User"]}
    pairs = {(row["ownerId"], row["seriesId"]) for row in meta["fixtures"]["Favourite"]}

    def caller(scenario):
        return users[scenario.get("user") or plan["auth"]["demoUsers"][0]["login"]]

    success, duplicate = scenarios["success"], scenarios["duplicate"]
    first = meta["fixtures"]["Favourite"][0]
    assert first["ownerId"] == caller(success), "the trap: row 0 (the body's source) is the success user's own pair"
    assert (caller(success), success["body"]["seriesId"]) not in pairs, "the success is no duplicate"
    assert (caller(duplicate), duplicate["body"]["seriesId"]) in pairs, "the duplicate is one of the user's own"
    assert "ownerId" not in duplicate["body"], "the server sets the owner"


def test_synthesized_fixtures_respect_a_unique_together_rule():
    """gen_01M6Z6HKT859PCNTAGVK2WEY4Z (2026-11-09, Ember Kitchen): a learner marks a lesson watched once
    (`uniqueTogether` lessonId + learnerId); the synthesized Progress rows cycled two lessons and two demo learners
    over three rows, so the seed hit the rule's unique index and the smoke calls could not run."""
    import json
    from pathlib import Path

    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.integration.contract import build_fixtures

    spec = validate_spec_data(
        json.loads((Path(__file__).parent / "fixtures" / "specs" / "ember-kitchen-2.json").read_text())
    ).normalized
    rule = next(r for r in spec["rules"] if r["kind"] == "uniqueTogether" and r["entity"] == "Progress")
    fields = rule["params"]["fields"]
    fixtures, _ = build_fixtures(spec, build_plan(spec))
    keys = [tuple(str(row[f]) for f in fields) for row in fixtures["Progress"]]
    assert len(keys) == len(set(keys)) and len(keys) >= 2, keys
    assert all(row["learnerId"] and row["lessonId"] for row in fixtures["Progress"])
    learners = {row["learnerId"] for row in fixtures["Progress"]}
    lessons = {row["lessonId"] for row in fixtures["Progress"]}
    assert len(keys) < len(learners) * len(lessons) or len(keys) == 1, "one learner × lesson pair is left free"


def test_a_unique_together_rule_with_a_text_field_keeps_every_distinct_fixture(tmp_path):
    """The free-pair trim counts pairs only over foreign keys: `workshopId` + `attendeeEmail` has no finite set, so
    three distinct bookings stay (trimming to two left no open record for the overlap and duplicate scenarios)."""
    from src.orchestrator.integration.contract import build_fixtures

    spec = booking_spec(tmp_path)
    fixtures, _ = build_fixtures(spec, build_plan(spec))
    assert len(fixtures["Booking"]) == 3


def test_a_unique_together_rule_on_a_pair_the_entity_already_declares_unique_reuses_its_constraint():
    """gen_01M6Z81Z2TM5SFN3ZMD05TPW56 (2026-11-09, Lantern Audio): `uniqueConstraints` and a `uniqueTogether` rule on
    the same two fields gave the model two identical constraints; Alembic's check then reported one as new and every
    generation carried a migration warning. The rule answers through the entity's own constraint."""
    import copy
    import json
    from pathlib import Path

    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan

    raw = json.loads((Path(__file__).parent / "fixtures" / "specs" / "lantern-audio-m2m.json").read_text())
    link = next(e for e in raw["entities"] if e["name"] == "EpisodeGuest")
    link["uniqueConstraints"] = [["episodeId", "guestId"]]
    spec = validate_spec_data(raw).normalized
    plan = build_plan(spec)
    model = next(m for m in plan["models"] if m.get("entity") == "EpisodeGuest")
    assert model["uniqueConstraints"] == [["episode_id", "guest_id"]]
    assert not [a for a in model.get("tableArgs") or [] if "UniqueConstraint" in a["code"]], "no second constraint"
    assert "uq_episode_guests_episode_id_guest_id" in model["constraintErrors"], "the rule's 409 maps to the entity's"
    plain = build_plan(
        validate_spec_data(
            copy.deepcopy(
                json.loads((Path(__file__).parent / "fixtures" / "specs" / "lantern-audio-m2m.json").read_text())
            )
        ).normalized
    )
    model = next(m for m in plain["models"] if m.get("entity") == "EpisodeGuest")
    assert [a for a in model.get("tableArgs") or [] if "UniqueConstraint" in a["code"]], (
        "without one, the rule adds its own"
    )


def test_a_read_only_module_with_a_unique_together_rule_starts():
    """gen_01M6Z9E38WE8XQHJ50MKTBEM78 (2026-11-09, TikTok Lite): `VideoInteraction` had a `uniqueTogether` rule but
    only a list operation, so its repository got the `CONSTRAINT_ERRORS` table (which names `ErrorCode`) without the
    import that only a writing repository adds; the app failed at import with `NameError: ErrorCode` in a
    generator-owned file, which the engine may not repair. A read-only repository has no table to consult."""
    from src.modules.shared.domain.backend_spec import validate_spec_data

    raw = json.loads((Path(__file__).parent / "fixtures" / "specs" / "tiktok-lite.json").read_text())
    spec = validate_spec_data(raw).normalized
    plan = build_plan(spec)
    module = next(m for m in plan["modules"] if m["name"] == "video_interactions")
    files = module_files(plan, spec, module)
    repository = next(code for path, code in files.items() if path.endswith("video_interaction_repository.py"))
    assert "CONSTRAINT_ERRORS" not in repository and "ErrorCode" not in repository
    for path, code in files.items():
        if path.endswith(".py"):
            compile(code, path, "exec")
    # the generated files only name what they import
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        for path, code in files.items():
            target = Path(tmp) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code)
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "F821", "--no-cache", tmp],
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0, result.stdout
