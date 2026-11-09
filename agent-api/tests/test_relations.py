"""Relations from templates (Story 10.11): many-to-many through a link model with routes to list, add and remove the
related records, and one-to-one with the child's summary in the parent's response."""

import json
from pathlib import Path

from src.orchestrator.backend.codegen import database_files, database_gaps, module_files, module_tests
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.integration.contract import build_contract, contract_operations
from src.orchestrator.plugins.app import plugin_files
from tests.generation_helpers import normalized


def _crud(entity: str, plural: str, delete: bool = True) -> list[dict]:
    lower = entity[:1].lower() + entity[1:]
    ops = [
        {"operationId": f"{lower}.create", "type": "crud", "action": "create", "entity": entity, "method": "POST",
         "path": f"/{plural}"},
        {"operationId": f"{lower}.get", "type": "crud", "action": "get", "entity": entity, "method": "GET",
         "path": f"/{plural}/{{id}}"},
        {"operationId": f"{lower}.list", "type": "crud", "action": "list", "entity": entity, "method": "GET",
         "path": f"/{plural}"},
    ]  # fmt: skip
    if delete:
        ops.append({"operationId": f"{lower}.delete", "type": "crud", "action": "delete", "entity": entity,
                    "method": "DELETE", "path": f"/{plural}/{{id}}"})  # fmt: skip
    return ops


def relations_spec(tmp_path: Path) -> dict:
    """Projects have members (many-to-many); a member has one profile (one-to-one)."""
    pk = {"name": "id", "type": "uuid", "primary": True}
    raw = {
        "specVersion": "1.0",
        "project": {"name": "Team Projects"},
        "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlmodel", "migration": "alembic"},
        "entities": [
            {"name": "Project", "fields": [pk, {"name": "name", "type": "string", "required": True, "maxLength": 120}]},
            {"name": "Member", "fields": [pk, {"name": "name", "type": "string", "required": True, "maxLength": 120}]},
            {"name": "Profile", "fields": [pk, {"name": "memberId", "type": "uuid", "required": True},
                                            {"name": "bio", "type": "string", "required": True, "maxLength": 500}]},
        ],
        "relationships": [
            {"name": "projectMembers", "type": "many-to-many", "from": "Project", "to": "Member"},
            {"name": "memberProfile", "type": "one-to-one", "from": "Member", "to": "Profile", "onDelete": "CASCADE"},
        ],
        "operations": [*_crud("Project", "projects"), *_crud("Member", "members"), *_crud("Profile", "profiles")],
    }  # fmt: skip
    (tmp_path / "relations-spec.json").write_text(json.dumps(raw))
    return normalized(tmp_path / "relations-spec.json")


def test_both_kinds_are_templated_models_with_no_database_gap(tmp_path):
    plan = build_plan(relations_spec(tmp_path))
    assert database_gaps(plan) == [] and plan["unresolved"] == []
    files = database_files(plan)
    link = files["src/modules/shared/infrastructure/models/project_member_link_model.py"]
    assert 'project_id: uuid.UUID = Field(primary_key=True, foreign_key="projects.id", ondelete="CASCADE")' in link
    project = files["src/modules/shared/infrastructure/models/project_model.py"]
    assert 'Relationship(back_populates="projects", link_model=ProjectMemberLinkModel)' in project
    member = files["src/modules/shared/infrastructure/models/member_model.py"]
    assert (
        'profile: "ProfileModel" = Relationship(back_populates="member", sa_relationship_kwargs={"uselist": False})'
        in member
    )
    assert "member_entity" in "".join(files) and "project_member_link_entity" not in "".join(files)  # no link entity
    for relative, source in files.items():
        compile(source, relative, "exec")


def test_a_one_to_one_child_is_a_summary_in_its_parents_response(tmp_path):
    spec = relations_spec(tmp_path)
    plan = build_plan(spec)
    members = next(m for m in plan["modules"] if m["name"] == "members")
    files = module_files(plan, spec, members)
    dto = files["src/modules/members/presenter/dtos/member_response_dto.py"]
    assert "profile: ProfileSummaryDto | None" in dto and '"profile": refs.get("profile", {}).get(entity.id)' in dto
    repository = files["src/modules/members/infrastructure/persistence/member_repository.py"]
    assert "where(col(ProfileModel.member_id).in_(own_ids))" in repository
    contract = build_contract(spec, plan)
    assert contract["components"]["schemas"]["MemberResponse"]["properties"]["profile"]["anyOf"][1] == {"type": "null"}
    profile_create = contract_operations(contract)["profile.create"]["operation"]["x-bga"]["scenarios"]
    assert profile_create[-1]["name"] == "second profile" and profile_create[-1]["expect"]["code"] == "CONFLICT"


def test_many_to_many_routes_tests_fixtures_and_scenarios(tmp_path):
    spec = relations_spec(tmp_path)
    plan = build_plan(spec)
    [relation] = plan["relations"]
    assert relation["path"] == "/projects/{id}/members" and relation["itemPath"] == "/projects/{id}/members/{memberId}"
    files = plugin_files(plan)
    router = files["src/modules/project_members/presenter/router.py"]
    assert 'raise ConflictException("Already related", ErrorCode.DUPLICATE' in router
    assert "session.get(ProjectMemberLinkModel, (id, child_id))" in router
    tests = files["tests/modules/project_members/test_project_members_api.py"]
    for name in (
        "test_a_member_is_related_listed_and_unrelated",
        "test_relating_twice_is_409_and_an_unknown_record_is_refused",
        "test_deleting_the_parent_removes_its_links",
    ):
        assert f"def {name}(client):" in tests
    for relative, source in files.items():
        if relative.endswith(".py"):
            compile(source, relative, "exec")
    contract = build_contract(spec, plan)
    assert len(contract["x-bga"]["fixtures"]["ProjectMemberLink"]) == 3
    body = contract["components"]["schemas"]
    add = contract_operations(contract)["project.addMember"]["operation"]
    prop = add["requestBody"]["content"]["application/json"]["schema"]["properties"]["memberId"]
    assert prop["x-bga"]["source"] == "reference" and prop["x-bga"]["many"] is True and body
    assert [s["name"] for s in add["x-bga"]["scenarios"]] == ["already related", "unknown memberId"]
    assert contract["x-bga"]["entities"]["Project"]["links"][0]["add"] == "project.addMember"


def test_the_crud_tests_still_seed_and_compile(tmp_path):
    spec = relations_spec(tmp_path)
    plan = build_plan(spec)
    for module in (m for m in plan["modules"] if not m.get("plugin")):
        for relative, source in module_tests(plan, spec, module).items():
            compile(source, relative, "exec")


def test_a_many_to_many_already_modelled_by_a_join_entity_adds_no_link():
    """gen_01M6Z75RG2H8YD1JT4XNZ5AMPP (2026-11-09, Lantern Audio): the draft had an `EpisodeGuest` entity (a child of
    Episode and of Guest) and a many-to-many Episode–Guest; the plugin's link routes landed in the entity's module
    and the app could not start (`episode_guests_router` missing). The join entity is the relationship."""
    import json
    from pathlib import Path

    from src.modules.shared.domain.backend_spec import validate_spec_data

    spec = validate_spec_data(
        json.loads((Path(__file__).parent / "fixtures" / "specs" / "lantern-audio-m2m.json").read_text())
    ).normalized
    assert any(rel["type"] == "many-to-many" for rel in spec["relationships"])
    plan = build_plan(spec)
    assert all(model.get("entity") for model in plan["models"]), "no link model"
    assert not plan.get("relations") and not any(m.get("plugin") == "relations" for m in plan["modules"])
    names = [m["name"] for m in plan["modules"]]
    assert len(names) == len(set(names)) and "episode_guests" in names
    assert all(not entry.get("kind") == "relationships" for entry in plan["unresolved"])
