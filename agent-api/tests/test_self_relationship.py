"""Epic 33 (Story 33.4): a record pointing at another of its kind (a comment's parent comment, a category's parent).

Before, both sides of such a relationship landed on one model without a remote side, and SQLAlchemy refused to
configure the generated models (every call a 500). The generated models now import and configure.
"""

import importlib
import sys

from sqlalchemy.orm import clear_mappers, configure_mappers

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.backend.codegen import model_file
from src.orchestrator.backend.planner import build_plan

SPEC = {
    "specVersion": "1.0",
    "project": {"name": "Threads", "description": "Posts with threaded remarks"},
    "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlalchemy", "migration": "alembic"},
    "entities": [
        {
            "name": "Zqpost",
            "fields": [{"name": "id", "type": "uuid", "primary": True}, {"name": "title", "type": "string"}],
        },
        {
            "name": "Zqremark",
            "fields": [
                {"name": "id", "type": "uuid", "primary": True},
                {"name": "zqpostId", "type": "uuid", "required": True},
                {"name": "parentId", "type": "uuid"},
                {"name": "text", "type": "text", "required": True},
            ],
        },
    ],
    "relationships": [
        {"name": "postRemarks", "type": "one-to-many", "from": "Zqpost", "to": "Zqremark", "onDelete": "CASCADE"},
        {
            "name": "remarkReplies",
            "type": "one-to-many",
            "from": "Zqremark",
            "to": "Zqremark",
            "foreignKey": "parentId",
            "onDelete": "CASCADE",
        },
    ],
    "operations": [],
}


def test_a_self_relationship_names_both_sides_and_its_remote_side():
    plan = build_plan(validate_spec_data(SPEC).normalized)
    remark = next(m for m in plan["models"] if m["class"] == "ZqremarkModel")
    sides = {r["attr"]: r for r in remark["relationships"]}
    assert sides["parent"]["remoteSide"] == "ZqremarkModel.id"
    assert sides["zqremarks_as_parent"]["annotation"].startswith("list[")
    text = model_file(remark, plan)
    assert '"remote_side": "ZqremarkModel.id"' in text
    assert "import ZqremarkModel" not in text  # a model never imports itself


def test_the_generated_models_configure(tmp_path, monkeypatch):
    plan = build_plan(validate_spec_data(SPEC).normalized)
    package = tmp_path / "zqmodels"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for model in plan["models"]:
        (package / model["file"].rsplit("/", 1)[1]).write_text(model_file(model, plan))
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        for model in plan["models"]:
            importlib.import_module(f"zqmodels.{model['file'].rsplit('/', 1)[1].removesuffix('.py')}")
        configure_mappers()  # raised "both of the same direction ONETOMANY" before the fix
    finally:
        for name in [n for n in sys.modules if n.startswith("zqmodels")]:
            del sys.modules[name]
        from sqlmodel import SQLModel

        for table in [t for t in SQLModel.metadata.tables if t.startswith("zq")]:
            SQLModel.metadata.remove(SQLModel.metadata.tables[table])
        clear_mappers  # noqa: B018 - kept imported for a manual reset; the agent's own mappers stay configured
