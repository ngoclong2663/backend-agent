"""Epic 33 (Story 33.4): fields a feature computes per record (`likeCount`, `myLikeId`), end to end without a sandbox:
the plan, the generated repository, DTO and use cases, the contract and the mocks' presentation."""

import ast
import copy

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.codegen import module_files
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.integration.contract import build_contract, presented_record

ID = {"name": "id", "type": "uuid", "primary": True}
SPEC = {
    "specVersion": "1.0",
    "project": {"name": "Loop", "description": "Clips and likes"},
    "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlalchemy", "migration": "alembic"},
    "auth": {"type": "jwt", "userEntity": "User", "loginField": "email", "roles": ["Member"]},
    "entities": [
        {"name": "User", "fields": [ID, {"name": "email", "type": "string", "required": True, "unique": True}]},
        {"name": "Clip", "fields": [ID, {"name": "caption", "type": "string", "required": True}]},
        {
            "name": "ClipReaction",
            "fields": [
                ID,
                {"name": "clipId", "type": "uuid", "required": True},
                {"name": "memberId", "type": "uuid", "required": True},
                {"name": "kind", "type": "enum", "values": ["like", "save"], "required": True},
            ],
        },
    ],
    "relationships": [
        {"name": "clipReactions", "type": "one-to-many", "from": "Clip", "to": "ClipReaction", "onDelete": "CASCADE"},
        {
            "name": "memberReactions",
            "type": "one-to-many",
            "from": "User",
            "to": "ClipReaction",
            "foreignKey": "memberId",
        },
    ],
    "operations": [
        {
            "operationId": "clip.list",
            "type": "crud",
            "action": "list",
            "entity": "Clip",
            "method": "GET",
            "path": "/clips",
            "auth": "jwt",
        },
        {
            "operationId": "clip.get",
            "type": "crud",
            "action": "get",
            "entity": "Clip",
            "method": "GET",
            "path": "/clips/{id}",
            "auth": "jwt",
        },
        {
            "operationId": "clipReaction.create",
            "type": "crud",
            "action": "create",
            "entity": "ClipReaction",
            "method": "POST",
            "path": "/clip-reactions",
            "auth": "jwt",
        },
        {
            "operationId": "clipReaction.delete",
            "type": "crud",
            "action": "delete",
            "entity": "ClipReaction",
            "method": "DELETE",
            "path": "/clip-reactions/{id}",
            "auth": "jwt",
            "policy": "ownReactions",
        },
    ],  # fmt: skip
    "policies": [{"name": "ownReactions", "type": "ownership", "entity": "ClipReaction", "ownerField": "memberId"}],
    "features": [
        {
            "feature": "reactions",
            "on": "Clip",
            "computed": [
                {
                    "field": "likeCount",
                    "kind": "count",
                    "entity": "ClipReaction",
                    "key": "clipId",
                    "where": {"kind": "like"},
                },
                {
                    "field": "myLikeId",
                    "kind": "mine",
                    "entity": "ClipReaction",
                    "key": "clipId",
                    "where": {"kind": "like"},
                    "owner": "memberId",
                },
            ],
        }
    ],  # fmt: skip
}


def _normalized(spec=SPEC):
    result = validate_spec_data(copy.deepcopy(spec))
    assert result.report.valid, [e.message for e in result.report.errors]
    return result.normalized


def test_the_spec_validates_its_features():
    bad = copy.deepcopy(SPEC)
    bad["features"][0]["computed"][1]["owner"] = "authorId"
    bad["features"][0]["computed"][0]["field"] = "caption"
    messages = [e.message for e in validate_spec_data(bad).report.errors]
    assert "Entity 'ClipReaction' has no field 'authorId'" in messages
    assert "'caption' is already a field" in messages
    assert "features" not in _normalized({k: v for k, v in SPEC.items() if k != "features"})


def test_the_generated_code_counts_and_finds_the_callers_row():
    spec = _normalized()
    plan = build_plan(spec)
    clip = next(m for m in plan["modules"] if m["entity"] == "Clip")
    files = module_files(plan, spec, clip)
    for path, text in files.items():
        if path.endswith(".py"):
            ast.parse(text, path)  # every generated file is valid Python
    repo = next(t for p, t in files.items() if p.endswith("persistence/clip_repository.py"))
    assert "def references(self, records: list[ClipEntity], viewer: Any = None) -> References:" in repo
    assert "func.count()" in repo and ".group_by(col(ClipReactionModel.clip_id))" in repo
    assert "col(ClipReactionModel.member_id) == viewer" in repo and "col(ClipReactionModel.kind) == 'like'" in repo
    dto = next(t for p, t in files.items() if p.endswith("dtos/clip_response_dto.py"))
    assert "like_count: int = 0" in dto and "my_like_id: uuid.UUID | None = None" in dto
    usecases = "\n".join(t for p, t in files.items() if "/usecases/" in p)
    assert "viewer=current_user.id if current_user else None" in usecases  # get and list know the caller


def test_the_contract_and_the_mocks_present_the_fields():
    spec = _normalized()
    contract = build_contract(spec)
    response = contract["components"]["schemas"]["ClipResponse"]["properties"]
    assert response["likeCount"]["readOnly"] and response["likeCount"]["x-bga"]["computed"] == "count"
    assert response["myLikeId"]["anyOf"][1] == {"type": "null"}
    info = contract["x-bga"]["entities"]["Clip"]["computed"]
    assert {i["field"]: i["kind"] for i in info} == {"likeCount": "count", "myLikeId": "mine"}
    clip_id = "11111111-1111-4111-8111-111111111111"
    contract["x-bga"]["fixtures"]["ClipReaction"] = [
        {"id": "a", "clipId": clip_id, "memberId": "u1", "kind": "like"},
        {"id": "b", "clipId": clip_id, "memberId": "u2", "kind": "like"},
        {"id": "c", "clipId": clip_id, "memberId": "u2", "kind": "save"},
    ]
    shown = presented_record(contract, "Clip", {"id": clip_id, "caption": "Sourdough"})
    assert shown["likeCount"] == 2 and shown["myLikeId"] is None
