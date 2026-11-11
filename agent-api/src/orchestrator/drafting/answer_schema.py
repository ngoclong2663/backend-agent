"""The JSON Schema an API engine's draft answer must follow (Story 22.8, structured output).

The Gemini API engine sends it as `generationConfig.responseJsonSchema`, so the model can only answer with valid
JSON in the expected shape: the three files of an app draft, each with its keys, types, enums and required fields, and
rule params typed per rule kind (a `scope` is a list, never one string). It cannot check what refers to what (a field
that does not exist, a policy no operation names): the validator still does, and `repair_spec` stays the last resort.

The schema keeps the keywords Gemini's structured output documents (type, properties, required, items, enum, anyOf,
$ref / $defs, additionalProperties, minItems, maxItems, minimum, maximum, description, title); the others (pattern,
default, length limits, `const`) are dropped or rewritten, because the validator checks them anyway.
"""

import copy
from functools import cache
from typing import Any

from src.modules.shared.domain.backend_spec import spec_json_schema
from src.modules.shared.domain.frontend_spec.app import outline_schema

KEPT = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "anyOf",
        "$ref",
        "additionalProperties",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "description",
        "title",
        "format",
    }
)
FORMATS = frozenset({"date-time", "date", "time"})

NAMES = {"type": "array", "items": {"type": "string"}}
WHERE = {
    "type": "object",
    "description": "Which records count: {field: value} or {field: {ne | in | notIn: value}}",
}
# What each rule kind's `params` hold (the validator's `_check_*` read the same keys).
RULE_PARAMS: dict[str, tuple[dict[str, Any], list[str]]] = {
    "transition": (
        {
            "field": {"type": "string", "description": "The enum field whose value moves"},
            "transitions": {
                "type": "object",
                "description": "Each state → the states it may move to",
                "additionalProperties": NAMES,
            },
        },
        ["field", "transitions"],
    ),
    "immutableAfter": (
        {"field": {"type": "string"}, "states": {**NAMES, "description": "Once in one of them, no change"}},
        ["field", "states"],
    ),
    "ownerOnly": ({"ownerField": {"type": "string"}}, ["ownerField"]),
    "sumEquals": (
        {
            "field": {"type": "string"},
            "items": {"type": "string", "description": "The child entity whose rows add up"},
            "itemField": {"type": "string"},
            "quantityField": {"type": "string"},
        },
        ["field", "items", "itemField"],
    ),
    "custom": (
        {
            "code": {"type": "string", "description": "UPPER_SNAKE_CASE"},
            "status": {"type": "integer", "enum": [400, 403, 404, 409, 422]},
            "field": {"type": "string"},
        },
        [],
    ),
    "capacity": (
        {
            "parent": {"type": "string", "description": "The foreign key of the parent that has the limit"},
            "capacityField": {"type": "string", "description": "The parent's integer field"},
            "where": WHERE,
        },
        ["parent", "capacityField"],
    ),
    "noOverlap": (
        {
            "start": {"type": "string"},
            "end": {"type": "string"},
            "scope": {**NAMES, "description": "Fields whose equal values may not overlap (e.g. the pitch)"},
            "where": WHERE,
        },
        ["start", "end"],
    ),
    "uniqueTogether": ({"fields": {**NAMES, "minItems": 2}, "where": WHERE}, ["fields"]),
}

NOTE = {
    "type": "object",
    "properties": {
        "spec": {"type": "string", "enum": ["backend", "frontend"]},
        "path": {"type": "string", "description": "A JSON pointer into that file"},
        "message": {"type": "string"},
    },
    "required": ["spec", "path", "message"],
}
NOTES = {
    "type": "object",
    "properties": {"assumptions": {"type": "array", "items": NOTE}, "unresolved": {"type": "array", "items": NOTE}},
    "required": ["assumptions", "unresolved"],
}


def _clean(node: Any) -> Any:
    """The schema with only the keywords structured output documents; `const` becomes a one-value `enum`."""
    if isinstance(node, list):
        return [_clean(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "const":
            out["enum"] = [value]
        elif key in ("properties", "$defs"):
            out[key] = {name: _clean(item) for name, item in value.items()}
        elif key == "format":
            if value in FORMATS:
                out[key] = value
        elif key in KEPT:
            out[key] = _clean(value)
    if "oneOf" in node:  # pydantic writes discriminated unions so; structured output knows anyOf
        out["anyOf"] = _clean(node["oneOf"])
    return out


def _relocate(schema: dict[str, Any], prefix: str, taken: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`schema`'s body and its `$defs`, renamed `<prefix><Name>` where a name is already taken, refs rewritten."""
    defs = schema.get("$defs") or {}
    renames = {name: (f"{prefix}{name}" if name in taken else name) for name in defs}

    def rewrite(node: Any) -> Any:
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {key: rewrite(value) for key, value in node.items() if key != "$defs"}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            out["$ref"] = f"#/$defs/{renames.get(ref.removeprefix('#/$defs/'), ref.removeprefix('#/$defs/'))}"
        return out

    return rewrite(schema), {renames[name]: rewrite(body) for name, body in defs.items()}


def _typed_rules(defs: dict[str, Any]) -> None:
    """`Rule` as one variant per kind, each with its own `params` (Story 22.8: `scope` was written as a string)."""
    rule = defs.get("Rule")
    if not isinstance(rule, dict):
        return
    base = {key: value for key, value in (rule.get("properties") or {}).items() if key not in ("kind", "params")}
    variants = []
    for kind, (params, required) in RULE_PARAMS.items():
        variants.append(
            {
                "type": "object",
                "properties": {
                    **base,
                    "kind": {"type": "string", "enum": [kind]},
                    "params": {"type": "object", "properties": params, "required": required},
                },
                "required": ["id", "kind", "entity", "params", *(["description"] if kind == "custom" else [])],
            }
        )
    defs["Rule"] = {"anyOf": variants}


@cache
def _app_answer_schema(design: bool, domain: bool = False) -> dict[str, Any]:
    backend, backend_defs = _relocate(spec_json_schema(), "", set())
    # Epic 33: the features block is code's (merged after the draft), never the model's to write
    backend.get("properties", {}).pop("features", None)
    # An app is built from its data: the spec's defaults (`[]`) would let an answer of only `project` and `stack`
    # pass, and generation then has nothing to draw. An app draft names at least one entity and one operation.
    for key in ("entities", "operations"):
        backend["properties"][key]["minItems"] = 1
    backend["required"] = [*backend.get("required", []), "entities", "operations"]
    for name in ("FeatureAttachment", "FeatureComputedField"):
        backend_defs.pop(name, None)
    outline, outline_defs = _relocate(outline_schema(design, domain), "Outline", set(backend_defs))
    defs = {**backend_defs, **outline_defs}
    _typed_rules(defs)
    defs |= {"BackendSpec": backend, "AppOutline": outline, "DraftNotes": NOTES}
    files = {
        "backend-spec.json": {"$ref": "#/$defs/BackendSpec"},
        "app-outline.json": {"$ref": "#/$defs/AppOutline"},
        "notes.json": {"$ref": "#/$defs/DraftNotes"},
    }
    schema = {
        "type": "object",
        "properties": {
            "files": {
                "type": "object",
                "properties": files,
                "required": list(files),
                "additionalProperties": False,
            },
            "message": {"type": "string", "description": "One line on what you decided"},
        },
        "required": ["files", "message"],
        "$defs": defs,
    }
    return _clean(schema)


def app_answer_schema(
    backend_file: str, outline_file: str, notes_file: str, design: bool = False, domain: bool = False
) -> dict[str, Any]:
    """The answer of a `draft_app` step: `{"files": {<backend>, <outline>, <notes>}, "message"}` (a copy). `design`
    (Epic 23, `draft_app@v3`): the outline's design brief and areas too; `domain` (Epic 33): the outline's domain."""
    schema = copy.deepcopy(_app_answer_schema(design, domain))
    files = schema["properties"]["files"]
    names = {"backend-spec.json": backend_file, "app-outline.json": outline_file, "notes.json": notes_file}
    files["properties"] = {names[name]: body for name, body in files["properties"].items()}
    files["required"] = [names[name] for name in files["required"]]
    return schema
