"""An app whose BackendSpec has no data: the draft's schema asks for it, the pair check refuses it, and the API
client the generator writes for an empty contract still type-checks (2026-11-11: a drafted media app came with only
`project` and `stack`, and `queries.ts` imported from a `query-keys.ts` that was not a module)."""

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.orchestrator.checks.consistency import check_consistency, check_spec_pair
from src.orchestrator.drafting.answer_schema import app_answer_schema
from src.orchestrator.frontend.codegen import operations_ts, queries_ts, query_keys_ts
from src.orchestrator.integration.contract import build_contract

EMPTY = {
    "specVersion": "1.0",
    "project": {"name": "Lesson Library"},
    "stack": {"framework": "fastapi", "database": "postgresql", "orm": "sqlmodel", "migration": "alembic"},
}
APP = {"specVersion": "1.0", "project": {"name": "Lesson Library", "mode": "dynamic", "flow": "app"}, "pages": []}


def _empty_backend() -> dict:
    result = validate_spec_data(EMPTY)
    assert result.normalized is not None  # a backend with no data is a valid BackendSpec on its own
    return result.normalized


def test_empty_contract_writes_modules_without_empty_imports():
    contract = build_contract(_empty_backend())
    keys = query_keys_ts(contract)
    assert "export {};" in keys
    queries = queries_ts(contract)
    assert "import {\n}" not in queries
    assert '"./query-keys"' not in queries and '"./operations"' not in queries
    assert "import { request }" in operations_ts(contract)  # already a module through its import


def test_pair_check_refuses_an_app_without_data():
    backend = _empty_backend()
    issues = [issue for issue in check_spec_pair(APP, backend) if issue.code == "FE_APP_FLOW"]
    assert len(issues) == 1 and issues[0].backend_path == "/entities"
    assert issues[0].severity == "error"


def test_pair_check_leaves_static_sites_and_frontend_only_checks_alone():
    backend = _empty_backend()
    static = {**APP, "project": {"name": "Lesson Library", "mode": "static"}}
    assert not [i for i in check_spec_pair(static, backend) if i.code == "FE_APP_FLOW"]
    assert not [i for i in check_consistency(APP, build_contract(backend)) if i.code == "FE_APP_FLOW"]


def test_app_answer_schema_requires_entities_and_operations():
    schema = app_answer_schema("b.json", "o.json", "n.json", design=True)
    backend = schema["$defs"]["BackendSpec"]
    assert {"entities", "operations"} <= set(backend["required"])
    assert backend["properties"]["entities"]["minItems"] == 1
    assert backend["properties"]["operations"]["minItems"] == 1
