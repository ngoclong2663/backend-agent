"""Every seeded foreign key points at a seeded row. Found on a real learning draft (2026-11-10): the relations plugin
left a one-to-one child out of the fixtures for the create scenario while a quiz submission still pointed at that quiz,
so the seed failed with a ForeignKeyViolation and no smoke call could run."""

import json
from pathlib import Path

import pytest

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.integration.contract import build_contract

DRAFTS = sorted((Path(__file__).parent / "fixtures" / "drafts").glob("domain-*-v10"))


def dangling(contract: dict, plan: dict) -> list[tuple[str, str, str]]:
    fixtures = contract["x-bga"]["fixtures"]
    by_table = {m["table"]: m for m in plan["models"]}
    out = []
    for model in plan["models"]:
        for column in model["columns"]:
            parent = by_table.get(((column.get("foreignKey") or {}).get("references") or "").partition(".")[0])
            if not parent or not parent.get("entity") or not model.get("entity"):
                continue
            pk = next(c["apiName"] for c in parent["columns"] if c["primaryKey"])
            ids = {str(row.get(pk)) for row in fixtures.get(parent["entity"]) or []}
            for row in fixtures.get(model["entity"]) or []:
                value = row.get(column["apiName"])
                if value is not None and str(value) not in ids:
                    out.append((model["entity"], column["apiName"], str(value)))
    return out


@pytest.mark.parametrize("folder", DRAFTS, ids=lambda f: f.name)
def test_every_seeded_key_points_at_a_seeded_row(folder):
    spec = validate_spec_data(json.loads((folder / "backend-spec.json").read_text())).normalized
    plan = build_plan(spec)
    assert dangling(build_contract(spec, plan), plan) == []


def test_a_unique_pairs_success_scenario_still_finds_its_pair_free():
    """The learning draft's quiz submission (one per quiz and learner): dropping the one-to-one child's dependents must
    not fill the pair the create's success scenario uses (the mocks answered it 409 when they were re-pointed)."""
    folder = next(f for f in DRAFTS if f.name == "domain-learning-v10")
    spec = validate_spec_data(json.loads((folder / "backend-spec.json").read_text())).normalized
    plan = build_plan(spec)
    contract = build_contract(spec, plan)
    fixtures = contract["x-bga"]["fixtures"]
    create = contract["paths"]["/quiz-submissions"]["post"]
    success = next(s for s in create["x-bga"]["scenarios"] if s["name"] == "success")
    users = {row.get("email"): row["id"] for row in fixtures["User"]}
    learner = users.get(success.get("user"))
    pairs = {(row["quizId"], row["learnerId"]) for row in fixtures["QuizSubmission"]}
    assert (success["body"]["quizId"], learner) not in pairs
    assert dangling(contract, plan) == []


@pytest.mark.parametrize("folder", DRAFTS, ids=lambda f: f.name)
def test_a_unique_key_takes_each_parent_once(folder):
    """The courier draft's availability (one per driver): three rows over two demo drivers repeated a unique key and
    the seed failed with a UniqueViolation (gen_01M723BPHN5PC2FR99EGAQWCXA)."""
    spec = validate_spec_data(json.loads((folder / "backend-spec.json").read_text())).normalized
    plan = build_plan(spec)
    fixtures = build_contract(spec, plan)["x-bga"]["fixtures"]
    for model in plan["models"]:
        for column in model["columns"]:
            if column.get("unique") and not column["primaryKey"] and model.get("entity"):
                values = [row.get(column["apiName"]) for row in fixtures.get(model["entity"]) or []]
                values = [v for v in values if v is not None]
                assert len(values) == len(set(map(str, values))), (model["entity"], column["apiName"])


def test_the_proof_photo_is_the_deliverys_own_photo_field():
    from src.orchestrator.drafting.domains import role_field

    spec = json.loads((DRAFTS[0].parent / "domain-drivers-v10" / "backend-spec.json").read_text())
    fields = [f["name"] for e in spec["entities"] if e["name"] == "Delivery" for f in e["fields"]]
    found = role_field(spec, "Delivery", "photo")
    assert found in fields or found == "proofPhoto"
    assert "doorPhoto" not in fields or found == "doorPhoto"
