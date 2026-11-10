"""Fixes found on Epic 33's real generations (2026-11-10), each on the real drafted spec."""

import json
from pathlib import Path

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.codegen import module_files
from src.orchestrator.backend.planner import build_plan

DRAFTS = Path(__file__).parent / "fixtures" / "drafts"


def _files(name: str, entity: str) -> dict[str, str]:
    spec = validate_spec_data(json.loads((DRAFTS / name / "backend-spec.json").read_text())).normalized
    plan = build_plan(spec)
    return module_files(plan, spec, next(m for m in plan["modules"] if m["entity"] == entity))


def test_an_update_whose_body_has_no_status_does_not_check_its_transition():
    """The news draft's article status moves only through its actions, so the update's DTO has no `status`; the rules
    plugin still checked `dto.status`, and every update answered 500 (gen_01M7219E7W5WGVQ9D0GRSA5XWM)."""
    update = _files("domain-news-v10", "Article")["src/modules/articles/usecases/update_article_usecase.py"]
    assert "dto.status" not in update


def test_computed_fields_are_required_in_the_response_dto():
    """The contract always returns them; with defaults the app's OpenAPI marked them optional (the openapi check)."""
    dto = _files("domain-news-v10", "Article")["src/modules/articles/presenter/dtos/article_response_dto.py"]
    assert "comment_count: int\n" in dto and "my_save_id: uuid.UUID | None\n" in dto
