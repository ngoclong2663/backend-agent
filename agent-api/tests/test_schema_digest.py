"""Tests for compact schema digests (Story 18.9)."""

import os
from pathlib import Path

from src.modules.shared.domain.backend_spec import spec_json_schema
from src.modules.shared.domain.frontend_spec import frontend_spec_json_schema
from src.modules.shared.domain.schema_digest import schema_digest

FIXTURES = Path(__file__).parent / "fixtures" / "schema-digests"


def test_schema_digest_backend_spec_snapshot():
    schema = spec_json_schema()
    digest = schema_digest(schema, "BackendSpec")
    snapshot = FIXTURES / "backend-spec.digest.md"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(digest)
    assert digest == snapshot.read_text(), "BackendSpec digest changed: review, then rerun with UPDATE_SNAPSHOTS=1"


def test_schema_digest_frontend_spec_snapshot():
    schema = frontend_spec_json_schema()
    digest = schema_digest(schema, "FrontendSpec")
    snapshot = FIXTURES / "frontend-spec.digest.md"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(digest)
    assert digest == snapshot.read_text(), "FrontendSpec digest changed: review, then rerun with UPDATE_SNAPSHOTS=1"


def test_schema_digest_all_defs_and_required_fields_present():
    """Every $defs entry and every required field must appear in the digest."""
    for schema, title in [(spec_json_schema(), "BackendSpec"), (frontend_spec_json_schema(), "FrontendSpec")]:
        digest = schema_digest(schema, title)
        defs = schema.get("$defs", {})
        for name, def_schema in defs.items():
            assert f"type {name} =" in digest, f"Missing definition for {name} in {title}"
            required = def_schema.get("required", [])
            for field in required:
                # Required field must appear as 'field:' and not 'field?:'
                assert f"{field}:" in digest, f"Required field {field} not found as required in {name} ({title})"


def test_schema_digest_size_limits():
    """FrontendSpec digest must be <= 15 KB (Story 18.9 target)."""
    fs_digest = schema_digest(frontend_spec_json_schema(), "FrontendSpec")
    bs_digest = schema_digest(spec_json_schema(), "BackendSpec")
    fs_size = len(fs_digest.encode("utf-8"))
    bs_size = len(bs_digest.encode("utf-8"))

    assert fs_size <= 15 * 1024, f"FrontendSpec digest is {fs_size} bytes, exceeding 15 KB limit"
    assert bs_size <= 15 * 1024, f"BackendSpec digest is {bs_size} bytes, exceeding 15 KB limit"
