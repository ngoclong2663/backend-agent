"""Epic 33 (Story 33.4): features merged into a real draft (the socials reference requirement, recorded 2026-11-10)."""

import copy
import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.drafting.access import secure_access
from src.orchestrator.drafting.features import attach
from src.orchestrator.integration.contract import build_contract

DRAFT = Path(__file__).parent / "fixtures" / "drafts" / "domain-socials" / "backend-spec.json"
BOTH = [{"feature": "comments", "on": "Clip"}, {"feature": "reactions", "on": "Clip", "options": {"kinds": ["like"]}}]


def _draft() -> dict:
    return json.loads(DRAFT.read_text())


def test_the_features_replace_the_drafted_comment_and_like():
    merged, notes = attach(_draft(), BOTH)
    names = [e["name"] for e in merged["entities"]]
    assert "Comment" not in names and "Like" not in names
    assert {"ClipComment", "ClipReaction"} <= set(names)
    messages = [n["message"] for n in notes]
    assert "'Comment' is now the Comments feature's (ClipComment)" in messages
    assert "'Like' is now the Reactions feature's (ClipReaction)" in messages
    assert not [op for op in merged["operations"] if op["entity"] in ("Comment", "Like")]


def test_the_merged_draft_validates_plans_and_computes():
    merged, _ = attach(_draft(), BOTH)
    result = validate_spec_data(merged)
    assert result.report.valid, [e.message for e in result.report.errors]
    contract = build_contract(result.normalized, build_plan(result.normalized))
    computed = {i["field"]: i for i in contract["x-bga"]["entities"]["Clip"]["computed"]}
    assert computed["likeCount"]["where"] == {"kind": "like"} and computed["myLikeId"]["owner"] == "userId"
    assert computed["commentCount"]["key"] == "clipId"
    replies = next(r for r in result.normalized["relationships"] if r["name"] == "clipCommentReplies")
    assert replies["from"] == replies["to"] == "ClipComment"  # a reply's parent is a comment (Story 33.4's fix)
    attached = {f["feature"]: f for f in result.normalized["features"]}
    assert attached["reactions"]["entities"] == ["ClipReaction"]


def test_each_kind_gets_its_count_and_the_callers_row():
    merged, _ = attach(_draft(), [{"feature": "reactions", "on": "Clip", "options": {"kinds": ["like", "save"]}}])
    fields = [c["field"] for c in merged["features"][0]["computed"]]
    assert fields == ["likeCount", "saveCount", "myLikeId", "mySaveId"]
    kind = next(f for f in merged["entities"][-1]["fields"] if f["name"] == "kind")
    assert kind["values"] == ["like", "save"]


def test_a_missing_target_or_a_clash_is_left_out_with_a_note():
    merged, notes = attach(_draft(), [{"feature": "comments", "on": "Video"}])
    assert "features" not in merged and "'Video' is not an entity" in notes[0]["message"]
    draft = _draft()
    draft["entities"].append(copy.deepcopy(next(e for e in draft["entities"] if e["name"] == "Clip")))
    draft["entities"][-1]["name"] = "ClipComment"
    _, notes = attach(draft, [{"feature": "comments", "on": "Clip"}])
    assert any("'ClipComment' already exists" in n["message"] for n in notes)


def test_the_access_rules_leave_a_features_entities_as_written():
    """Comments stay readable by everyone who reads the clip; only their author edits them."""
    merged, _ = attach(_draft(), BOTH)
    normalized = validate_spec_data(merged).normalized
    secure_access(normalized)
    listing = next(op for op in normalized["operations"] if op["operationId"] == "clipComment.list")
    assert "policy" not in listing
    update = next(op for op in normalized["operations"] if op["operationId"] == "clipComment.update")
    assert update["policy"] == "ownClipComments"
