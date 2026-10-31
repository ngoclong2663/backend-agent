"""Tests for component context pack generation (Story 18.9)."""

import os
from pathlib import Path

from src.orchestrator.component_cache import sample_props
from src.orchestrator.context_pack import (
    MAX_PACK_BYTES,
    component_context,
    extract_exports,
)
from src.orchestrator.frontend_renderer import section_props
from src.orchestrator.frontend_scaffold import scaffold_frontend
from tests.test_frontend_scaffold import inputs

FIXTURES = Path(__file__).parent / "fixtures" / "context-packs"


def test_extraction_rule_short_file_whole_long_file_exports_only():
    """Extraction rule (Story 18.9):

    A file under ~80 lines goes in whole; a longer one contributes its export declarations
    with their leading doc comment.
    """
    short_content = (
        "// A short utility file\n"
        "export type TShort = string;\n\n"
        "export function shortHelper() {\n"
        "  return 'hello';\n"
        "}\n"
    )
    # Under 80 lines -> returned in full
    assert extract_exports(short_content, max_lines=80) == short_content

    # Over 80 lines -> only exports and doc comments are retained
    filler = "\n".join(f"const internal_{i} = {i};" for i in range(100))
    long_content = (
        "/**\n * A long component with internal implementation details.\n */\n"
        "export function LongWidget(props: { id: string }) {\n"
        "  return <div>{props.id}</div>;\n"
        "}\n\n" + filler + "\n\n/** Props type for LongWidget */\n"
        "export type LongWidgetProps = {\n  id: string;\n};\n"
    )
    extracted = extract_exports(long_content, max_lines=80)
    assert "internal_50" not in extracted
    assert "LongWidget" in extracted
    assert "LongWidgetProps" in extracted
    assert "A long component with internal implementation details." in extracted
    assert "Props type for LongWidget" in extracted


def test_context_pack_size_warning_when_large(tmp_path, monkeypatch):
    """When a context pack exceeds 25 KB, a warning is logged."""
    component = {"name": "LargeComp", "uses": []}
    sample = {}

    # Create dummy project directory
    (tmp_path / "src" / "components" / "renderer").mkdir(parents=True, exist_ok=True)
    # Put a large file so total size exceeds 25 KB
    large_ts = "// large file\n" + "\n".join(f"export const item_{i} = {i};" for i in range(1000))
    (tmp_path / "src" / "components" / "renderer" / "site.ts").write_text(large_ts)

    warnings: list[str] = []
    monkeypatch.setattr(
        "src.orchestrator.context_pack.logger.warning",
        lambda msg, *args, **kw: warnings.append(msg % args if args else msg),
    )
    pack = component_context(tmp_path, component, sample)

    assert len(pack.encode("utf-8")) > MAX_PACK_BYTES
    assert any("component context pack exceeds" in w for w in warnings)


def test_context_pack_snapshot_golden_dynamic_component(tmp_path):
    """Snapshot test for the context pack of the golden dynamic shop's ProductGrid."""
    spec, contract, plan = inputs("shop-dynamic")
    scaffold_frontend(tmp_path, plan, spec, contract)

    comp = next(c for c in spec["components"] if c["name"] == "ProductGrid")
    # Section props and sample props
    section = next(
        (s for route in plan["routes"] for s in route["sections"] if s.get("component") == "ProductGrid"),
        None,
    )
    props = sample_props(comp.get("propsSchema"))
    if section:
        props |= section_props(plan, spec, contract, section)

    pack = component_context(tmp_path, comp, props)
    assert len(pack.encode("utf-8")) <= MAX_PACK_BYTES

    # Verify key sections are present
    assert "# Context Pack for `ProductGrid`" in pack
    assert "## Data API" in pack
    assert "src/components/renderer/site.ts" in pack
    assert "src/components/renderer/use-section-records.ts" in pack
    assert "src/components/renderer/bindings.ts" in pack
    assert "## UI Primitives" in pack
    assert "src/components/ui/card.tsx" in pack
    assert "## Example Section Pattern" in pack
    assert "src/components/sections/CardGrid.tsx" in pack
    assert "## Mock API & Fixtures" in pack

    snapshot = FIXTURES / "ProductGrid.context.md"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(pack)

    assert pack == snapshot.read_text(), "Context pack changed: review, then rerun with UPDATE_SNAPSHOTS=1"
