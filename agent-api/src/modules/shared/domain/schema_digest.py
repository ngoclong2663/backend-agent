"""Compact schema digests for drafting (Story 18.9).

Generates TypeScript-like type definitions from JSON Schema's $defs so models can read the spec
structure in one small file (~15 KB) instead of paging through hundreds of schema chunks.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _first_sentence(desc: str | None) -> str:
    if not desc:
        return ""
    cleaned = " ".join(desc.strip().split())
    # Match up to period followed by space or end of string
    m = re.search(r"^(.*?\.)(?:\s|$)", cleaned)
    if m:
        return m.group(1)
    return cleaned


def _resolve_type(prop: dict[str, Any]) -> str:
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]
    if "enum" in prop:
        return " | ".join(json.dumps(v) for v in prop["enum"])
    for ukey in ("anyOf", "oneOf"):
        if ukey in prop:
            types = [_resolve_type(sub) for sub in prop[ukey]]
            seen: set[str] = set()
            dedup = [t for t in types if not (t in seen or seen.add(t))]
            return " | ".join(dedup)
    if "allOf" in prop:
        types = [_resolve_type(sub) for sub in prop["allOf"]]
        return " & ".join(types)
    t = prop.get("type")
    if t == "array":
        sub = _resolve_type(prop.get("items", {}))
        if " | " in sub or " & " in sub:
            return f"({sub})[]"
        return f"{sub}[]"
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "object" or "properties" in prop:
        if "additionalProperties" in prop and isinstance(prop["additionalProperties"], dict):
            val_t = _resolve_type(prop["additionalProperties"])
            return f"Record<string, {val_t}>"
        if not prop.get("properties"):
            return "Record<string, unknown>"
        fields = []
        req = set(prop.get("required", []))
        for k, v in prop.get("properties", {}).items():
            opt = "" if k in req else "?"
            fields.append(f"{k}{opt}: {_resolve_type(v)}")
        return "{ " + "; ".join(fields) + " }"
    return "unknown"


def schema_digest(json_schema: dict[str, Any], title: str) -> str:
    """Writes TypeScript-like types from the JSON Schema's $defs and root schema.

    Enums become string unions, arrays become T[], oneOf/anyOf become unions, and the first sentence
    of each description appears as a // comment. Numeric limits and patterns are omitted.
    """
    blocks = [f"# {title} Schema Digest\n"]
    defs = json_schema.get("$defs", {})
    all_types: dict[str, dict[str, Any]] = {}
    if "properties" in json_schema and title not in defs:
        all_types[title] = json_schema
    all_types.update(defs)

    for name, s in all_types.items():
        desc = _first_sentence(s.get("description"))
        if desc:
            blocks.append(f"// {desc}")
        props = s.get("properties", {})
        req = set(s.get("required", []))
        if not props:
            t_str = _resolve_type(s)
            blocks.append(f"type {name} = {t_str};\n")
            continue
        lines = [f"type {name} = {{"]
        for pk, pv in props.items():
            pdesc = _first_sentence(pv.get("description"))
            if pdesc:
                lines.append(f"  // {pdesc}")
            opt = "" if pk in req else "?"
            lines.append(f"  {pk}{opt}: {_resolve_type(pv)};")
        lines.append("};\n")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
