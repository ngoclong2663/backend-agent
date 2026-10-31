"""Component context pack generation (Story 18.9).

Builds a single compact Markdown file (.bga/context.md, < 25 KB) in the component scratch copy containing
the data APIs, UI primitives, example section, and relevant mocks needed by custom components so the
engine does not spend dozens of turns discovering them sequentially.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.configs import get_logger

logger = get_logger(__name__)

MAX_PACK_BYTES = 25 * 1024
DEFAULT_MAX_LINES = 80


def extract_exports(text: str, max_lines: int = DEFAULT_MAX_LINES) -> str:
    """Extraction rule (Story 18.9):

    A file under ~80 lines goes in whole; a longer one contributes its export declarations with their
    leading doc comment.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    exported_names: set[str] = set()
    for block in re.finditer(r"export\s+\{([^}]+)\}", text):
        for item in block.group(1).split(","):
            cleaned = item.strip()
            if cleaned:
                if " as " in cleaned:
                    cleaned = cleaned.split(" as ")[0].strip()
                exported_names.add(cleaned)

    output_chunks: list[str] = []
    i = 0
    total = len(lines)
    while i < total:
        comment_lines: list[str] = []
        while i < total and (
            lines[i].strip().startswith("//") or lines[i].strip().startswith("/*") or lines[i].strip().startswith("*")
        ):
            comment_lines.append(lines[i])
            if "*/" in lines[i]:
                i += 1
                break
            i += 1
        if i >= total:
            break
        line = lines[i]

        is_direct_export = line.startswith("export ")
        is_exported_sym = any(
            line.startswith(f"function {name}")
            or line.startswith(f"const {name}")
            or line.startswith(f"type {name}")
            or line.startswith(f"interface {name}")
            for name in exported_names
        )

        if is_direct_export or is_exported_sym:
            decl_lines = list(comment_lines)
            if "type " in line or "interface " in line:
                depth = 0
                started = False
                while i < total:
                    l_str = lines[i]
                    decl_lines.append(l_str)
                    depth += l_str.count("{") - l_str.count("}")
                    if "{" in l_str:
                        started = True
                    if (started and depth <= 0) or (not started and ";" in l_str):
                        i += 1
                        break
                    i += 1
                output_chunks.append("\n".join(decl_lines))
                continue
            elif "export {" in line:
                while i < total:
                    decl_lines.append(lines[i])
                    if "}" in lines[i]:
                        i += 1
                        break
                    i += 1
                output_chunks.append("\n".join(decl_lines))
                continue
            else:
                paren_depth = 0
                started_paren = False
                while i < total:
                    l_str = lines[i]
                    paren_depth += l_str.count("(") - l_str.count(")")
                    if "(" in l_str:
                        started_paren = True
                    if started_paren and paren_depth == 0 and "{" in l_str:
                        before_brace = l_str[: l_str.rfind("{")].rstrip()
                        if before_brace:
                            decl_lines.append(before_brace)
                        i += 1
                        break
                    decl_lines.append(l_str)
                    i += 1
                output_chunks.append("\n".join(decl_lines))
                continue
        i += 1

    return "\n\n".join(output_chunks)


def _read_file_or_empty(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _extract_asset_ids(project: Path) -> list[str]:
    registry_file = project / "src" / "assets" / "index.ts"
    if not registry_file.is_file():
        return []
    content = registry_file.read_text(encoding="utf-8", errors="replace")
    # Matches keys like "hero": { or 'hero': {
    return sorted(set(re.findall(r'["\']([a-z0-9-]+)["\']\s*:\s*\{', content)))


def _extract_bindings_summary(bindings_file: Path) -> str:
    if not bindings_file.is_file():
        return ""
    text = bindings_file.read_text(encoding="utf-8", errors="replace")
    if len(text.splitlines()) <= DEFAULT_MAX_LINES:
        return text

    # Extract operation IDs known to bindings.ts
    op_ids = sorted(set(re.findall(r'["\']([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)["\']\s*:', text)))
    summary_lines = [
        "// Operations known to bindings.ts:",
        f"// {', '.join(op_ids)}" if op_ids else "// (no operations)",
        "",
    ]
    # Extract useOperationMutation and useOperationQuery
    extracted = extract_exports(text, max_lines=0)
    summary_lines.append(extracted)
    return "\n".join(summary_lines)


def component_context(project: Path, component: dict[str, Any], sample_props: dict[str, Any]) -> str:
    """Builds a Markdown context pack from the files in the scratch copy `project`."""
    name = component.get("name", "CustomComponent")
    sections: list[str] = [
        f"# Context Pack for `{name}`\n\n"
        "Read `.bga/context.md` first: it has the APIs, types, primitives and an example you need. "
        "Read another file only if the pack lacks something.\n"
    ]

    # 1. Data API
    data_api_parts: list[str] = ["## Data API\n"]

    site_ts = project / "src" / "components" / "renderer" / "site.ts"
    if site_ts.is_file():
        extracted = extract_exports(_read_file_or_empty(site_ts))
        data_api_parts.append(f"### `src/components/renderer/site.ts`\n```typescript\n{extracted}\n```\n")

    use_records = project / "src" / "components" / "renderer" / "use-section-records.ts"
    if use_records.is_file():
        extracted = extract_exports(_read_file_or_empty(use_records))
        data_api_parts.append(
            f"### `src/components/renderer/use-section-records.ts`\n```typescript\n{extracted}\n```\n"
        )

    bindings_ts = project / "src" / "components" / "renderer" / "bindings.ts"
    if bindings_ts.is_file():
        data_api_parts.append(
            f"### `src/components/renderer/bindings.ts`\n```typescript\n{_extract_bindings_summary(bindings_ts)}\n```\n"
        )

    format_ts = project / "src" / "components" / "sections" / "format.ts"
    if format_ts.is_file():
        extracted = extract_exports(_read_file_or_empty(format_ts))
        data_api_parts.append(f"### `src/components/sections/format.ts`\n```typescript\n{extracted}\n```\n")

    query_state = project / "src" / "components" / "sections" / "QueryState.tsx"
    if query_state.is_file():
        extracted = extract_exports(_read_file_or_empty(query_state))
        data_api_parts.append(f"### `src/components/sections/QueryState.tsx`\n```typescript\n{extracted}\n```\n")

    asset_image = project / "src" / "components" / "assets" / "AssetImage.tsx"
    if asset_image.is_file():
        asset_ids = _extract_asset_ids(project)
        asset_ids_note = f"\n// Available asset ids: {', '.join(asset_ids)}\n" if asset_ids else ""
        extracted = extract_exports(_read_file_or_empty(asset_image))
        data_api_parts.append(
            f"### `src/components/assets/AssetImage.tsx`\n```typescript\n{extracted}{asset_ids_note}\n```\n"
        )

    sections.append("\n".join(data_api_parts))

    # 2. UI primitives
    ui_parts: list[str] = ["## UI Primitives\n"]
    uses = component.get("uses") or []
    ui_dir = project / "src" / "components" / "ui"
    if uses:
        for use_name in uses:
            ui_file = ui_dir / f"{use_name}.tsx"
            if ui_file.is_file():
                extracted = extract_exports(ui_file.read_text(encoding="utf-8", errors="replace"))
                ui_parts.append(f"### `src/components/ui/{use_name}.tsx`\n```typescript\n{extracted}\n```\n")
            else:
                ui_parts.append(f"### `src/components/ui/{use_name}.tsx`\n(primitive not found)\n\n")
    else:
        # names only when uses is empty
        if ui_dir.is_dir():
            primitives = sorted(p.stem for p in ui_dir.glob("*.tsx"))
            ui_parts.append(f"Available UI primitives (names only): {', '.join(primitives)}\n\n")
        else:
            ui_parts.append("Available UI primitives: (none)\n\n")

    sections.append("\n".join(ui_parts))

    # 3. One example: CardGrid.tsx
    card_grid = project / "src" / "components" / "sections" / "CardGrid.tsx"
    if card_grid.is_file():
        sections.append(
            f"## Example Section Pattern\n\n### `src/components/sections/CardGrid.tsx`\n```typescript\n"
            f"{card_grid.read_text(encoding='utf-8', errors='replace')}\n```\n"
        )

    # 4. Mocks & Fixtures
    fixtures_file = project / "src" / "mocks" / "fixtures.json"
    if fixtures_file.is_file():
        try:
            fixtures_data = json.loads(fixtures_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            fixtures_data = {}

        mock_parts: list[str] = ["## Mock API & Fixtures\n"]
        # Operation IDs known to mock setup
        operations_file = project / "src" / "mocks" / "operations.json"
        if operations_file.is_file():
            try:
                ops_data = json.loads(operations_file.read_text(encoding="utf-8", errors="replace"))
                mock_parts.append(f"Known mock operation ids: {', '.join(sorted(ops_data.keys()))}\n")
            except Exception:
                pass

        binding = sample_props.get("binding") or {}
        op_id = binding.get("operationId")
        matched_entity: str | None = None
        if op_id and isinstance(op_id, str):
            prefix = op_id.split(".")[0]
            # Match entity in fixtures
            if prefix in fixtures_data:
                matched_entity = prefix
            else:
                for k in fixtures_data:
                    if k.lower() in prefix.lower() or prefix.lower() in k.lower():
                        matched_entity = k
                        break

        if matched_entity and fixtures_data.get(matched_entity):
            first_record = fixtures_data[matched_entity][0]
            mock_parts.append(
                f"First fixture record for binding entity `{matched_entity}`:\n"
                f"```json\n{json.dumps(first_record, indent=2)}\n```\n"
            )
        elif fixtures_data:
            # Include first record for first available entity
            ent = next(iter(fixtures_data.keys()))
            rec = fixtures_data[ent][0] if fixtures_data[ent] else {}
            mock_parts.append(f"Sample fixture record (`{ent}`):\n```json\n{json.dumps(rec, indent=2)}\n```\n")

        sections.append("\n".join(mock_parts))

    result = "\n".join(sections)
    size_bytes = len(result.encode("utf-8"))
    if size_bytes > MAX_PACK_BYTES:
        logger.warning(
            "component context pack exceeds %d bytes (got %d bytes) for component %s",
            MAX_PACK_BYTES,
            size_bytes,
            name,
        )

    return result
