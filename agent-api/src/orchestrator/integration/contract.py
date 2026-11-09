"""API contract, contract first (Story 12.3): normalized BackendSpec + plan → OpenAPI 3.1. No LLM.

Every planned operation with its exact operationId, method and path; request and response schemas from the plan's
columns (camelCase API names); the list envelope `{items,total,limit,offset}`; the error envelope per planned
error status; pagination, filter, sort and search query parameters; examples from the spec's `seed[]`, or
synthesized from the field types. The same spec always gives a byte-identical document (`dump_contract`).

`x-bga.fixtures` holds one record set per entity (ids and foreign keys consistent across entities); the frontend
mock layer (Epic 13) serves exactly these records.

Story 10.0b, the integration contract: a frontend reads what it needs and implements no rule. Each request property
says where its value comes from (`x-bga.source`; a foreign key also `x-bga.ref`: the parent, its list and detail
operations, its label field); record responses carry a `{id, label}` summary per parent and `allowedActions`; each
operation lists its errors (`x-bga.errors`); `x-bga.entities` is the same per entity, for the mocks.
"""

import hashlib
import json
import re
import uuid
from typing import Any

from src.modules.shared.domain.backend_spec.media import SAMPLE_EXTENSION, SAMPLE_LANGUAGES, track_children
from src.modules.shared.domain.backend_spec.naming import to_snake

from ..backend.planner import build_plan

CONTRACT_VERSION = "1"
OPENAPI_VERSION = "3.1.0"
EXAMPLE_NAMESPACE = uuid.UUID("6f1c2b8e-7d3a-4f0e-9c55-12b0e5a7c0de")
SYNTHESIZED_RECORDS = 3
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"  # Story 10.0b scenarios: an id no fixture has
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
_PATH_PARAM = re.compile(r"\{([^}]+)\}")

_BASE_TYPES: dict[str, dict[str, Any]] = {
    "uuid": {"type": "string", "format": "uuid"},
    "string": {"type": "string"},
    "text": {"type": "string"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    # Pydantic serializes Decimal as a string and accepts both: the contract allows either.
    "decimal": {"type": ["number", "string"], "format": "decimal"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "json": {},
}


def field_schema(column: dict[str, Any], nullable: bool | None = None) -> dict[str, Any]:
    """JSON Schema of one plan column (or a column-shaped field). `nullable` overrides the column's own."""
    if column["type"] == "enum":
        values = list(column["enum"]["values"] if "enum" in column else column.get("values") or [])
        schema: dict[str, Any] = {"type": "string", "enum": values}
    else:
        schema = json.loads(json.dumps(_BASE_TYPES[column["type"]]))
    if column["type"] in ("string", "text") and column.get("maxLength"):
        schema["maxLength"] = column["maxLength"]
    if column["type"] in ("integer", "float", "decimal"):
        if column.get("min") is not None:
            schema["minimum"] = column["min"]
        if column.get("max") is not None:
            schema["maximum"] = column["max"]
    is_nullable = column.get("nullable") if nullable is None else nullable
    if is_nullable and "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        schema["type"] = [*types, "null"]
        if "enum" in schema:
            schema["enum"] = [*schema["enum"], None]
    return schema


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _writable(column: dict[str, Any]) -> bool:
    """Columns a client sends: not generated ids, not `now` timestamps, never a secret (a password hash, 10.2), not
    what the server takes from the signed-in user (an owner, 10.3)."""
    default = column.get("default") or {}
    return (
        not default.get("factory")
        and not default.get("autoincrement")
        and not column.get("secret")
        and column.get("source") != "currentUser"
    )


def _request_columns(model: dict[str, Any], spec_op: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = (spec_op.get("request") or {}).get("fields")
    return [
        column for column in model["columns"] if _writable(column) and (allowed is None or column["apiName"] in allowed)
    ]


def _properties_columns(properties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """BackendSpec payload `properties` (FieldDefs) in the shape of plan columns."""
    return [
        {
            **prop,
            "apiName": prop["name"],
            "nullable": prop.get("nullable", not prop.get("required")),
            "default": {"value": prop["default"]} if prop.get("default") is not None else None,
        }
        for prop in properties
    ]


def _required(column: dict[str, Any]) -> bool:
    return not column.get("nullable") and not column.get("default")


def _fresh(column: dict[str, Any], value: Any) -> Any:
    """A value for a unique column that no fixture has (Story 10.0b's create scenario)."""
    if column["type"] in ("integer", "float", "decimal"):
        return 900001 if column["type"] == "integer" else 900001.5
    if column["type"] == "uuid":  # an id no fixture has, still an id (never "Scenario <id>"), the same every build
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bga-scenario:{value}"))
    if isinstance(value, str) and "@" in value:
        return "scenario@example.com"
    if isinstance(value, str):
        text = f"Scenario {value}"
        return text[: column["maxLength"]] if column.get("maxLength") else text
    return value


def _public(record: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """A fixture row without its secret columns (a password hash, Story 10.2)."""
    secret = {column["apiName"] for column in model["columns"] if column.get("secret")}
    return {key: value for key, value in record.items() if key not in secret} if secret else record


def summary_name(entity: str) -> str:
    return f"{entity}Summary"


def present(record: dict[str, Any], model: dict[str, Any], by_entity: dict[str, list[dict[str, Any]]],
            actions: list[str]) -> dict[str, Any]:  # fmt: skip
    """A fixture row as the API answers it: plus a `{id, label}` summary per reference and `allowedActions`."""
    out = dict(record)
    for reference in model.get("references", []):
        value = record.get(reference["field"])
        parents = by_entity.get(reference["entity"]) or []
        parent = next((row for row in parents if row.get(reference["primaryKeyField"]) == value), None)
        out[reference["apiName"]] = (
            None if value is None else {"id": value, "label": (parent or {}).get(reference["labelField"])}
        )
    own = next((c["apiName"] for c in model["columns"] if c["primaryKey"]), "id")
    for child in model.get("children", []):  # Story 10.11: a one-to-one child, or None
        row = next((r for r in by_entity.get(child["entity"]) or [] if r.get(child["field"]) == record.get(own)), None)
        out[child["apiName"]] = (
            None if row is None else {"id": row.get(child["primaryKeyField"]), "label": row.get(child["labelField"])}
        )
    out["allowedActions"] = list(actions)
    return out


# -- examples ----------------------------------------------------------------------------------------------------


def _synthesize(column: dict[str, Any], entity: str, index: int, slug: str) -> Any:
    name, kind = column["apiName"], column["type"]
    if kind == "uuid":
        return str(uuid.uuid5(EXAMPLE_NAMESPACE, f"{slug}:{entity}:{name}:{index}"))
    if kind == "string":
        lower = name.lower()
        if "email" in lower:
            value = f"user{index + 1}@example.com"
        elif lower.endswith("url"):
            value = f"https://example.com/{to_snake(entity)}/{index + 1}.jpg"
        else:
            value = f"{entity} {to_snake(name).replace('_', ' ')} {index + 1}"
        return value[: column["maxLength"]] if column.get("maxLength") else value
    if kind == "text":
        return f"Example {to_snake(name).replace('_', ' ')} of {entity} {index + 1}."
    if kind in ("integer", "float", "decimal"):
        low = column.get("min")
        value: float = (low if low is not None else 1) + index
        if kind != "integer":
            value = round(value + 8.99, 2)
        if column.get("max") is not None:
            value = min(value, column["max"])
        return int(value) if kind == "integer" else value
    if kind == "boolean":
        return index % 2 == 0
    if kind == "date":
        return f"2026-01-{index + 1:02d}"
    if kind == "datetime":
        return f"2026-01-{index + 1:02d}T09:00:00Z"
    if kind == "enum":
        # Payload properties (custom operations) carry `values` themselves; entity columns carry an `enum` entry.
        values = list(column["enum"]["values"] if "enum" in column else column.get("values") or [])
        return values[index % len(values)] if values else None
    return {}


def build_fixtures(spec: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    """One record set per entity: the spec's seed rows (completed), else synthesized rows. Returns the records
    by entity and the entities whose records came from the seed."""
    slug = spec["project"].get("slug") or "project"
    models = [model for model in plan["models"] if model.get("entity")]
    by_table = {model["table"]: model for model in models}
    seeds: dict[str, list[dict[str, Any]]] = {}
    for seed in spec.get("seed", []):
        seeds.setdefault(seed["entity"], []).extend(seed["records"])

    records: dict[str, list[dict[str, Any]]] = {}
    tracks = track_children(spec)  # Epic 29 (Story 29.2): a subtitle track entity gets one row per sample language
    for model in models:  # pass 1: own values and primary keys
        entity = model["entity"]
        rows = [dict(row) for row in seeds.get(entity, [])] or [{} for _ in range(SYNTHESIZED_RECORDS)]
        if entity not in seeds and entity in tracks:
            rows = _track_rows(model, tracks[entity])
        seeded = entity in seeds
        for index, row in enumerate(rows):
            for column in model["columns"]:
                name = column["apiName"]
                if name in row or column.get("foreignKey"):
                    continue
                default = column.get("default") or {}
                if column["primaryKey"]:
                    row[name] = index + 1 if column["type"] == "integer" else _synthesize(column, entity, index, slug)
                elif default.get("factory"):
                    row[name] = _synthesize(column, entity, 0 if seeded else index, slug)
                elif "value" in default and (seeded or column["type"] != "enum"):
                    row[name] = default["value"]
                elif seeded and column["nullable"]:
                    row[name] = None
                else:
                    row[name] = _synthesize(column, entity, index, slug)
        records[entity] = rows
    # Story 25.5: a person field (an owner, an assigned worker) names demo users of its role, so every demo user of
    # that role has records of their own (and the second one others the first cannot reach)
    from ..drafting.access import person_roles

    person = person_roles(spec)
    user_entity = ((spec.get("auth") or {}).get("userEntity") or "User") if spec.get("auth") else None
    for model in models:  # pass 2: foreign keys point at the parent's records
        dangling: dict[str, dict[str, Any]] = {}  # field → a seeded key no parent record has → the one it now names
        for index, row in enumerate(records[model["entity"]]):
            for column in model["columns"]:
                fk = column.get("foreignKey")
                if not fk:
                    continue
                name = column["apiName"]
                table, _, _ = fk["references"].partition(".")
                parent = by_table.get(table)
                parent_rows = records.get(parent["entity"]) if parent else None
                roles = person.get((model["entity"], name))
                if roles and parent_rows and parent and parent["entity"] == user_entity:
                    parent_rows = [r for r in parent_rows if r.get("role") in roles] or parent_rows
                pk = next(c["apiName"] for c in parent["columns"] if c["primaryKey"]) if parent_rows else None
                if name in row:
                    # A seed row's own key names a parent record, or (a drafted id such as an owner the demo users
                    # replaced) is mapped onto one: the same key to the same record, so the seed can be inserted.
                    value = row[name]
                    if value is None or not parent_rows or str(value) in {str(r.get(pk)) for r in parent_rows}:
                        continue
                    mapped = dangling.setdefault(name, {})
                    if str(value) not in mapped:
                        mapped[str(value)] = parent_rows[len(mapped) % len(parent_rows)][pk]
                    row[name] = mapped[str(value)]
                elif parent_rows and model["entity"] in tracks and tracks[model["entity"]].get("parent") == name:
                    row[name] = parent_rows[0][pk]  # Epic 29: every sample track on the first media record
                elif parent_rows:
                    row[name] = parent_rows[index % len(parent_rows)][pk]
                else:
                    row[name] = None
    for model in models:  # a `uniqueTogether` rule (Story 10.10): no two synthesized rows share the fields' values
        if model["entity"] in seeds:
            continue  # the spec's own seed rows are inserted as written (a duplicate there is the spec's to fix)
        for rule in spec.get("rules", []):
            if rule.get("kind") != "uniqueTogether" or rule.get("entity") != model["entity"]:
                continue
            fields = list((rule.get("params") or {}).get("fields") or [])
            if not fields:
                continue
            options: dict[str, list[Any]] = {}  # a foreign key among the fields → the parent keys it may take
            for column in model["columns"]:
                fk = column.get("foreignKey")
                if column["apiName"] not in fields or not fk:
                    continue
                parent = by_table.get(fk["references"].partition(".")[0])
                parent_rows = records.get(parent["entity"]) if parent else None
                roles = person.get((model["entity"], column["apiName"]))
                if roles and parent_rows and parent and parent["entity"] == user_entity:
                    parent_rows = [r for r in parent_rows if r.get("role") in roles] or parent_rows
                if parent_rows:
                    pk = next(c["apiName"] for c in parent["columns"] if c["primaryKey"])
                    options[column["apiName"]] = [r[pk] for r in parent_rows]
            kept: list[dict[str, Any]] = []
            seen: set[tuple] = set()
            for row in records[model["entity"]]:
                key = tuple(str(row.get(f)) for f in fields)
                if key in seen:  # re-point one foreign key at another parent, else drop the row
                    for field, values in options.items():
                        for value in values:
                            trial = {**row, field: value}
                            trial_key = tuple(str(trial.get(f)) for f in fields)
                            if trial_key not in seen:
                                row, key = trial, trial_key
                                break
                        if key not in seen:
                            break
                if key in seen:
                    continue
                seen.add(key)
                kept.append(row)
            # leave at least one pair free: the evaluation's and the smoke check's first create must not collide
            # (gen_01M6Z75NJYKSXNF4JGQPZ4XYF8: the seed filled every learner × lesson pair, so "mark watched" was 409)
            capacity = 1
            for field in fields:
                capacity *= len(options.get(field) or [1])
            if options and len(kept) >= capacity > 1:
                kept = kept[: capacity - 1]
            records[model["entity"]] = kept
    for model in models:  # Story 10.5: a file field holds an object key under its prefix, per owner when there is one
        owner = next((c["apiName"] for c in model["columns"] if c.get("source") == "currentUser"), None)
        language = (tracks.get(model["entity"]) or {}).get("language")
        for column in (c for c in model["columns"] if c.get("file")):
            extension = SAMPLE_EXTENSION.get(column["file"]["kind"], "pdf")  # Epic 29: the kind's sample
            for index, row in enumerate(records[model["entity"]]):
                if column["apiName"] in seeds_given(seeds, model["entity"], index):
                    continue
                folder = row.get(owner) if owner else "shared"
                # a subtitle track's key names its language, so the seed uploads that language's sample
                lang = ""
                if column["file"]["kind"] == "subtitles":
                    lang = f".{row.get(language) if language and row.get(language) else SAMPLE_LANGUAGES[0]}"
                row[column["apiName"]] = f"{column['file']['prefix']}/{folder}/seed/{index + 1}{lang}.{extension}"
    for model in models:  # column order, so documents diff cleanly
        order = [column["apiName"] for column in model["columns"]]
        records[model["entity"]] = [
            {name: row[name] for name in order if name in row} for row in records[model["entity"]]
        ]
    return records, set(seeds)


def _track_rows(model: dict[str, Any], track: dict[str, Any]) -> list[dict[str, Any]]:
    """Epic 29: the synthesized rows of a subtitle track entity: one per sample language (the language field's own
    enum values when it has them, else the samples' languages), parents filled in pass 2."""
    language = track.get("language")
    column = next((c for c in model["columns"] if c["apiName"] == language), None) if language else None
    values = list(((column or {}).get("enum") or {}).get("values") or []) if column else []
    languages = [v for v in values if str(v).lower()[:2] in SAMPLE_LANGUAGES] or list(SAMPLE_LANGUAGES)
    if values and not any(str(v).lower()[:2] in SAMPLE_LANGUAGES for v in values):
        languages = values[: len(SAMPLE_LANGUAGES)]
    return [({language: value} if language else {}) for value in languages[: len(SAMPLE_LANGUAGES)]]


def seeds_given(seeds: dict[str, list[dict[str, Any]]], entity: str, index: int) -> set[str]:
    """The fields the spec's own seed row gives (kept as they are)."""
    rows = seeds.get(entity) or []
    return set(rows[index]) if index < len(rows) else set()


def _examples(value: Any, seeded: bool) -> dict[str, Any]:
    return {"seed" if seeded else "synthesized": {"value": value}}


# -- operations --------------------------------------------------------------------------------------------------


def _parameters(op: dict[str, Any], model: dict[str, Any] | None) -> list[dict[str, Any]]:
    by_api = {column["apiName"]: column for column in model["columns"]} if model else {}
    primary = next((c for c in model["columns"] if c["primaryKey"]), None) if model else None
    names = _PATH_PARAM.findall(op["path"])
    parameters = []
    for position, name in enumerate(names):
        column = by_api.get(name)
        if column is None and position == len(names) - 1 and op.get("action") in ("get", "update", "delete"):
            column = primary
        schema = field_schema(column, nullable=False) if column else {"type": "string"}
        parameters.append({"name": name, "in": "path", "required": True, "schema": schema})
    has_query = bool(op.get("filters") or op.get("pagination") or op.get("sort") or op.get("search"))
    if op.get("action") != "list" and not has_query:
        return parameters
    pagination = op.get("pagination")
    if pagination:
        parameters.append(
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": pagination["maxLimit"],
                    "default": pagination["defaultLimit"],
                },
            }
        )
        parameters.append(
            {
                "name": "offset",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "minimum": 0, "default": 0},
            }
        )
    for flt in op.get("filters", []):
        if flt.get("in") == "path":  # already the path parameter of that name
            continue
        schema = field_schema(by_api[flt["param"]], nullable=False)
        schema.pop("default", None)
        parameters.append({"name": flt["param"], "in": "query", "required": False, "schema": schema})
    if op.get("sort"):
        values = [value for item in op["sort"] for value in (item["param"], f"-{item['param']}")]
        parameters.append(
            {"name": "sort", "in": "query", "required": False, "schema": {"type": "string", "enum": values}}
        )
    for rng in op.get("ranges", []):  # Story 23.4: inclusive bounds on a date
        kind = "date" if rng["type"] == "date" else "date-time"
        for suffix, word in (("From", "on or after"), ("To", "on or before")):
            parameters.append(
                {
                    "name": f"{rng['param']}{suffix}",
                    "in": "query",
                    "required": False,
                    "description": f"Records whose {rng['param']} is {word} this",
                    "schema": {"type": "string", "format": kind},
                }
            )
    if op.get("search"):
        fields = ", ".join(item["param"] for item in op["search"])
        parameters.append(
            {
                "name": "q",
                "in": "query",
                "required": False,
                "description": f"Case-insensitive match on {fields}",
                "schema": {"type": "string"},
            }
        )
    return parameters


def _mock_plan(
    op: dict[str, Any],
    spec_op: dict[str, Any],
    model: dict[str, Any] | None,
    entity: str,
    models: dict[str, Any],
) -> str:
    """Computes the mock plan for a custom operation (Story 19.5)."""
    method = op.get("method", "GET").upper()
    path = op.get("path", "")
    path_params = _PATH_PARAM.findall(path)
    primary = next((c for c in model["columns"] if c["primaryKey"]), None) if model else None
    pk_names = {"id"}
    if primary:
        pk_names.add(primary["apiName"])
    if entity:
        pk_names.add(f"{entity[0].lower() + entity[1:]}Id")
        pk_names.add(f"{to_snake(entity)}_id")
        pk_names.add(f"{entity.lower()}Id")
    has_id = any(p in pk_names for p in path_params)

    spec_resp = spec_op.get("response") or {}
    has_props = bool(spec_resp.get("properties"))
    resp_entity = spec_resp.get("entity")
    is_entity = bool(not has_props and resp_entity and (resp_entity == entity or resp_entity in models))
    is_array = bool(
        spec_resp.get("cardinality") == "many"
        or spec_resp.get("type") == "array"
        or op.get("pagination")
        or spec_op.get("pagination")
    )

    if method == "GET":
        if has_id and is_entity and not is_array:
            return "record"
        if is_entity:
            return "records"
    elif method in ("POST", "PUT", "PATCH"):
        if has_id and is_entity:
            return "merge"
        if method == "POST" and not has_id and is_entity:
            return "create"
    return "sample"


def _error_responses(op: dict[str, Any]) -> dict[str, Any]:
    by_status: dict[int, list[str]] = {}
    for error in op.get("errors", []):
        codes = by_status.setdefault(error["status"], [])
        if error["code"] not in codes:
            codes.append(error["code"])
    return {
        str(status): {
            "description": " | ".join(codes),
            "content": {"application/json": {"schema": {"$ref": ERROR_SCHEMA}}},
        }
        for status, codes in sorted(by_status.items())
    }


def _secure(operation: dict[str, Any], op: dict[str, Any]) -> None:
    """The planned operation's auth on its contract operation: a signed-in one (`auth: jwt`) is `bearerAuth` (the
    auth plugin adds its 401); a public read with only a visibility rule (Story 23.9) takes no token."""
    auth = op.get("auth") or {}
    if auth.get("auth"):
        operation["x-bga"]["auth"] = auth["auth"]
    if auth.get("policy"):
        operation["x-bga"]["policy"] = auth["policy"]
    if auth.get("auth"):
        operation["security"] = [{"bearerAuth": []}]


class _Builder:
    def __init__(self, spec: dict[str, Any], plan: dict[str, Any]):
        self.spec = spec
        self.plan = plan
        self.schemas: dict[str, Any] = {
            "ErrorResponse": _object(
                {
                    "error": _object(
                        {"code": {"type": "string"}, "message": {"type": "string"}, "details": {}},
                        ["code", "message"],
                    )
                },
                ["error"],
            )
        }
        self.models = {model["entity"]: model for model in plan["models"] if model.get("entity")}
        self.spec_ops = {op["operationId"]: op for op in spec.get("operations", [])}
        self.fixtures, self.seeded = build_fixtures(spec, plan)
        # Story 10.0b: entities whose response DTO the templates write carry summaries and `allowedActions`
        self.modules = {module["entity"]: module for module in plan["modules"]}
        self.presented = {
            module["entity"]
            for module in plan["modules"]
            if {"create", "get", "list", "update"} & {op.get("action") for op in module["operations"]}
        }

    def actions(self, entity: str) -> list[str]:
        return list((self.modules.get(entity) or {}).get("recordActions") or [])

    def example(self, entity: str, record: dict[str, Any]) -> dict[str, Any]:
        """A fixture row as the API answers it (10.0b), for entities the templates present."""
        if entity not in self.presented:
            return _public(record, self.models[entity])
        return present(_public(record, self.models[entity]), self.models[entity], self.fixtures, self.actions(entity))

    def operation_ids(self, entity: str, action: str) -> str | None:
        module = self.modules.get(entity) or {}
        return next((op["operationId"] for op in module.get("operations", []) if op.get("action") == action), None)

    def reference_of(self, column: dict[str, Any]) -> dict[str, Any] | None:
        fk = column.get("foreignKey")
        if not fk:
            return None
        table = fk["references"].partition(".")[0]
        parent = next((model for model in self.models.values() if model["table"] == table), None)
        if parent is None:
            return None
        return {
            "entity": parent["entity"],
            "listOperation": self.operation_ids(parent["entity"], "list"),
            "detailOperation": self.operation_ids(parent["entity"], "get"),
            "labelField": (parent.get("label") or {}).get("apiName"),
        }

    def entity_schema(self, entity: str) -> str:
        name = f"{entity}Response"
        if name not in self.schemas:
            model = self.models[entity]
            properties = {c["apiName"]: field_schema(c) for c in model["columns"] if not c.get("secret")}
            if entity in self.presented:
                for reference in [*model.get("references", []), *model.get("children", [])]:  # 10.11: children too
                    ref = {"$ref": self.summary_schema(reference["entity"])}
                    properties[reference["apiName"]] = {"anyOf": [ref, {"type": "null"}]}
                actions = {"type": "string"}
                if self.actions(entity):
                    actions["enum"] = self.actions(entity)
                properties["allowedActions"] = {"type": "array", "items": actions}
            self.schemas[name] = _object(properties, list(properties))
        return f"#/components/schemas/{name}"

    def summary_schema(self, entity: str) -> str:
        name = summary_name(entity)
        if name not in self.schemas:
            model = self.models[entity]
            primary = next(column for column in model["columns"] if column["primaryKey"])
            self.schemas[name] = _object(
                {"id": field_schema(primary, nullable=False), "label": {"type": ["string", "null"]}}, ["id", "label"]
            )
        return f"#/components/schemas/{name}"

    def request_schema(self, name: str, columns: list[dict[str, Any]], partial: bool) -> str:
        properties = {}
        for column in columns:
            schema = field_schema(column)
            default = (column.get("default") or {}).get("value")
            if default is not None:
                schema["default"] = default
            reference = self.reference_of(column)
            schema["x-bga"] = {"source": "reference", "ref": reference} if reference else {"source": "input"}
            properties[column["apiName"]] = schema
        required = [] if partial else [column["apiName"] for column in columns if _required(column)]
        self.schemas[name] = _object(properties, required)
        return f"#/components/schemas/{name}"

    def _sample_response(self, spec_op: dict[str, Any], entity: str, status: int) -> Any:
        if status == 204:
            return None
        spec_resp = spec_op.get("response") or {}
        resp_entity = spec_resp.get("entity")
        if resp_entity and self.fixtures.get(resp_entity):
            return self.fixtures[resp_entity][0]
        if spec_resp.get("properties"):
            slug = self.spec["project"].get("slug") or "project"
            columns = _properties_columns(spec_resp["properties"])
            rows = [{c["apiName"]: _synthesize(c, entity or "Result", i, slug) for c in columns} for i in range(3)]
            return rows if spec_resp.get("type") == "array" else rows[0]
        return {"ok": True}

    def _aggregate_operation(self, module: dict[str, Any], op: dict[str, Any], spec_op: dict[str, Any]) -> dict:
        """Epic 21: `{"value": n}`, or grouped `[{"key", "value"}, …]`; the mock computes it from the fixtures."""
        aggregate = dict(spec_op.get("aggregate") or {})
        value = _object({"value": {"type": "number"}}, ["value"])
        grouped = bool(aggregate.get("groupBy"))
        schema = (
            {
                "type": "array",
                "items": _object({"key": {"type": "string"}, "value": {"type": "number"}}, ["key", "value"]),
            }
            if grouped
            else value
        )
        description = f"{aggregate.get('fn', 'count')} of {module['entity']}" + (
            " by " + aggregate["groupBy"] if grouped else ""
        )
        operation = {
            "operationId": op["operationId"],
            "summary": op.get("summary") or spec_op.get("summary") or description,
            "tags": [module["name"]],
            "x-bga": {
                "entity": module["entity"],
                "action": "aggregate",
                "module": module["name"],
                "mock": "aggregate",
                "aggregate": aggregate,
            },
            "responses": {"200": {"description": description, "content": {"application/json": {"schema": schema}}}},
        }
        # gen_01M6RNS949KSV5QKARTS1ENA46 (2026-11-06): a figure for some roles only (Story 23.9) is signed in, as the
        # app has it; without this the frontend showed it to every visitor and the live API answered 401
        _secure(operation, op)
        return operation

    def operation(self, module: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
        entity = module["entity"]
        model = self.models.get(entity)
        spec_op = self.spec_ops.get(op["operationId"], {})
        if spec_op.get("type") == "aggregate":
            return self._aggregate_operation(module, op, spec_op)
        action = op.get("action")
        records = self.fixtures.get(entity, [])
        seeded = entity in self.seeded
        bga_action = action or ("list" if (spec_op.get("response") or {}).get("type") == "array" else None)
        operation: dict[str, Any] = {
            "operationId": op["operationId"],
            "summary": op.get("summary") or spec_op.get("summary") or f"{action or 'custom'} {entity}",
            "tags": [module["name"]],
            "x-bga": {"entity": entity, "action": bga_action, "module": module["name"]},
        }
        _secure(operation, op)
        mock_plan = None
        if action is None:
            mock_plan = _mock_plan(op, spec_op, model, entity, self.models)
            operation["x-bga"]["mock"] = mock_plan
            if mock_plan == "records" and not bga_action:
                operation["x-bga"]["action"] = "list"
            elif mock_plan == "record" and not bga_action:
                operation["x-bga"]["action"] = "get"
        if op.get("ranges"):  # Story 23.4: what a calendar asks for, and what the mocks apply
            operation["x-bga"]["ranges"] = [
                {"field": rng["param"], "from": f"{rng['param']}From", "to": f"{rng['param']}To"}
                for rng in op["ranges"]
            ]
        if spec_op.get("description"):
            operation["description"] = spec_op["description"]
        parameters = _parameters(op, model)
        if parameters:
            operation["parameters"] = parameters

        request_columns: list[dict[str, Any]] | None = None
        if action in ("create", "update") and model:
            request_columns = _request_columns(model, spec_op)
        elif action is None and (spec_op.get("request") or {}).get("properties"):
            request_columns = _properties_columns(spec_op["request"]["properties"])
        elif action is None and (spec_op.get("request") or {}).get("entity") in self.models:
            request_columns = _request_columns(self.models[spec_op["request"]["entity"]], spec_op)
        if request_columns is not None:
            name = (op.get("requestDto") or f"{op['handler'].title().replace('_', '')}Request").removesuffix("Dto")
            ref = self.request_schema(name, request_columns, partial=action == "update")
            content: dict[str, Any] = {"schema": {"$ref": ref}}
            if records and action in ("create", "update"):
                names = {column["apiName"] for column in request_columns}
                content["examples"] = _examples({k: v for k, v in records[0].items() if k in names}, seeded)
            operation["requestBody"] = {"required": True, "content": {"application/json": content}}

        status = str(op["status"])
        responses: dict[str, Any] = {}
        if op["status"] == 204:
            responses[status] = {"description": "No content"}
        elif (action == "list" or (action is None and mock_plan == "records" and spec_op.get("pagination"))) and model:
            # a custom paginated list has no planned list DTO (Story 25.1, a real agy draft): named from its handler
            list_name = (op.get("responseDto") or f"{op['handler'].title().replace('_', '')}Response").removesuffix(
                "Dto"
            )
            self.schemas[list_name] = _object(
                {
                    "items": {"type": "array", "items": {"$ref": self.entity_schema(entity)}},
                    "total": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
                ["items", "total", "limit", "offset"],
            )
            limit = (op.get("pagination") or {}).get("defaultLimit", len(records))
            items = [self.example(entity, record) for record in records[:limit]]
            example = {"items": items, "total": len(records), "limit": limit, "offset": 0}
            responses[status] = {
                "description": f"Page of {entity} records",
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{list_name}"},
                        "examples": _examples(example, seeded),
                    }
                },
            }
        elif action is None and mock_plan == "records" and not spec_op.get("pagination"):
            response_entity = (spec_op.get("response") or {}).get("entity") or entity
            if response_entity in self.models:
                schema = {"type": "array", "items": {"$ref": self.entity_schema(response_entity)}}
                body: dict[str, Any] = {"schema": schema}
                if self.fixtures.get(response_entity):
                    rows = [self.example(response_entity, row) for row in self.fixtures[response_entity]]
                    body["examples"] = _examples(rows, response_entity in self.seeded)
                responses[status] = {
                    "description": f"List of {response_entity} records",
                    "content": {"application/json": body},
                }
            else:
                responses[status] = {
                    "description": "Result",
                    "content": {"application/json": {"schema": {"type": "array"}}},
                }
        else:
            response_entity = (spec_op.get("response") or {}).get("entity") or (entity if action else None)
            if response_entity in self.models:
                body = {"schema": {"$ref": self.entity_schema(response_entity)}}
                if self.fixtures.get(response_entity):
                    row = self.example(response_entity, self.fixtures[response_entity][0])
                    body["examples"] = _examples(row, response_entity in self.seeded)
                responses[status] = {"description": f"The {response_entity}", "content": {"application/json": body}}
            elif (spec_op.get("response") or {}).get("properties"):
                columns = _properties_columns(spec_op["response"]["properties"])
                schema = _object({c["apiName"]: field_schema(c) for c in columns}, [c["apiName"] for c in columns])
                if spec_op["response"].get("type") == "array":
                    schema = {"type": "array", "items": schema}
                responses[status] = {"description": "Result", "content": {"application/json": {"schema": schema}}}
            else:
                responses[status] = {"description": "Result", "content": {"application/json": {"schema": {}}}}
        if action is None and mock_plan == "sample":
            sample = self._sample_response(spec_op, entity, op["status"])
            operation["x-bga"]["sample"] = sample
            if sample is not None and status in responses and "content" in responses[status]:
                responses[status]["content"]["application/json"]["examples"] = _examples(sample, False)
        responses.update(_error_responses(op))
        operation["responses"] = responses
        if op.get("errors"):
            operation["x-bga"]["errors"] = self.errors(op, model)
        scenarios = self.scenarios(op, model, request_columns or [])
        if scenarios:
            operation["x-bga"]["scenarios"] = scenarios
        return operation

    def scenarios(
        self, op: dict[str, Any], model: dict[str, Any] | None, request_columns: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Story 10.0b: calls with the answer they must get, from the fixtures (the seeded database): the success, an
        unknown id, a missing required field, a duplicate unique value, an unknown reference. Validation runs them
        against the backend; the mocks and the live app answer them the same way (Epic 22)."""
        action = op.get("action")
        records = self.fixtures.get((model or {}).get("entity") or "") or []
        if model is None or action is None or not records:
            return []
        primary = next(column for column in model["columns"] if column["primaryKey"])
        first = records[0]
        names = _PATH_PARAM.findall(op["path"])
        own = names[-1] if action in ("get", "update", "delete") and names else None
        params: dict[str, Any] = {}
        for name in names:
            if name == own:
                params[name] = first[primary["apiName"]]
            elif name in first:
                params[name] = first[name]
            else:
                return []  # a path this record set cannot fill
        unknown = {**params, own: UNKNOWN_ID if primary["type"] == "uuid" else 999999} if own else None
        unique = [column for column in model["columns"] if column["unique"] and not column["primaryKey"]]
        out: list[dict[str, Any]] = []

        def add(name: str, expect: int, code: str | None = None, path: dict | None = None, body: Any = None) -> None:
            scenario: dict[str, Any] = {"name": name, "params": path if path is not None else params}
            if body is not None:
                scenario["body"] = body
            scenario["expect"] = {"status": expect, **({"code": code} if code else {})}
            out.append(scenario)

        if action in ("list", "get"):
            add("success", op["status"])
        if own:
            add("unknown id", 404, "NOT_FOUND", unknown, {} if action == "update" else None)
        if action == "create":
            body = {c["apiName"]: first[c["apiName"]] for c in request_columns if c["apiName"] in first}
            for column in unique:  # fresh values, so the success is not a duplicate of the seed
                if column["apiName"] in body:
                    body[column["apiName"]] = _fresh(column, body[column["apiName"]])
            add("success", op["status"], body=body)
            required = next((column for column in request_columns if _required(column)), None)
            if required is not None:
                missing = {key: value for key, value in body.items() if key != required["apiName"]}
                add("missing required field", 422, "VALIDATION_ERROR", body=missing)
            for column in unique:
                if column["apiName"] in body:
                    duplicate = {**body, column["apiName"]: first[column["apiName"]]}
                    add(f"duplicate {column['apiName']}", 409, "CONFLICT", body=duplicate)
            for column in request_columns:
                if column.get("foreignKey") and column["type"] == "uuid" and column["apiName"] in body:
                    dangling = {**body, column["apiName"]: UNKNOWN_ID}
                    add(f"unknown {column['apiName']}", 400, "REFERENCE_NOT_FOUND", body=dangling)
        if action == "update":
            plain = next(
                (c for c in request_columns if not c["unique"] and not c.get("foreignKey") and c["apiName"] in first),
                None,
            )
            add("success", op["status"], body={plain["apiName"]: first[plain["apiName"]]} if plain else {})
            if unique and len(records) > 1:
                column = unique[0]
                duplicate = {column["apiName"]: records[1][column["apiName"]]}
                add(f"duplicate {column['apiName']}", 409, "CONFLICT", body=duplicate)
        return out

    def errors(self, op: dict[str, Any], model: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Story 10.0b: what the operation answers besides success, with the fields a frontend marks."""
        from ..backend.codegen import conflict_message

        entity = (model or {}).get("entity") or "Record"
        columns = (model or {}).get("columns") or []
        out = []
        for error in op["errors"]:
            fields: list[str] = []
            if error["code"] == "CONFLICT":
                fields = [column["apiName"] for column in columns if column["unique"] and not column["primaryKey"]]
                message = conflict_message(model) if model else "The record conflicts with an existing record"
            elif error["code"] == "REFERENCE_NOT_FOUND":
                fields = [column["apiName"] for column in columns if column.get("foreignKey") and _writable(column)]
                message = "A referenced record does not exist"
            elif error["code"] == "NOT_FOUND":
                message = f"{entity} not found"
            elif error["code"] == "VALIDATION_ERROR":
                message = "Some values are not valid (each one in `details`, by field)"
            elif error["code"] == "FORBIDDEN":
                message = "You may not do this"
            else:
                message = error["code"].replace("_", " ").capitalize()
            entry = {"status": error["status"], "code": error["code"], "message": message}
            if fields:
                entry["fields"] = fields
            if entry not in out:
                out.append(entry)
        return out

    def build(self) -> dict[str, Any]:
        paths: dict[str, dict[str, Any]] = {}
        for module in self.plan["modules"]:
            if module.get("plugin"):  # Story 10.1: a plugin writes its own module's operations (`Plugin.contract`)
                continue
            for op in module["operations"]:
                paths.setdefault(op["path"], {})[op["method"].lower()] = self.operation(module, op)
        project = self.spec["project"]
        canonical = json.dumps(self.spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        info: dict[str, Any] = {"title": project["name"], "version": "1.0.0"}
        if project.get("description"):
            info["description"] = project["description"]
        return {
            "openapi": OPENAPI_VERSION,
            "info": info,
            "paths": paths,
            "components": {"schemas": self.schemas},
            "x-bga": {
                "contractVersion": CONTRACT_VERSION,
                "planVersion": self.plan["planVersion"],
                "specSha256": hashlib.sha256(canonical.encode()).hexdigest(),
                "fixtures": self.fixtures,
                "entities": self.entities(),
            },
        }

    def entities(self) -> dict[str, Any]:
        """Story 10.0b: per presented entity, what the mocks add to a record: summaries and `allowedActions`."""
        out: dict[str, Any] = {}
        for entity, model in sorted(self.models.items()):  # entities no module presents: only their secrets
            secret = [column["apiName"] for column in model["columns"] if column.get("secret")]
            if entity not in self.presented and secret:
                out[entity] = {"secretFields": secret}
        for entity in sorted(self.presented):
            model = self.models[entity]
            secret = [column["apiName"] for column in model["columns"] if column.get("secret")]
            out[entity] = {
                **({"secretFields": secret} if secret else {}),
                "primaryKey": next(column["apiName"] for column in model["columns"] if column["primaryKey"]),
                "labelField": (model.get("label") or {}).get("apiName"),
                "references": [
                    {key: reference[key] for key in ("field", "apiName", "entity", "labelField")}
                    for reference in model.get("references", [])
                ],
                **(
                    {
                        "children": [
                            {key: child[key] for key in ("field", "apiName", "entity", "labelField", "primaryKeyField")}
                            for child in model["children"]
                        ]
                    }
                    if model.get("children")
                    else {}
                ),
                "allowedActions": self.actions(entity),
            }
        return out


def build_contract(spec: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """`spec` is the normalized BackendSpec; `plan` defaults to `build_plan(spec)` (also deterministic)."""
    from ..plugins import extended_spec, plan_plugins

    spec = extended_spec(spec)  # Story 10.2: the plugins' entities and seed records, as the plan has them
    plan = plan or build_plan(spec)
    contract = _Builder(spec, plan).build()
    for plugin in plan_plugins(plan):  # Story 10.1: the plugins' operations, errors and scenarios
        plugin.contract(contract, plan, spec)
    return contract


def dump_contract(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def presented_record(contract: dict[str, Any], entity: str | None, record: dict[str, Any]) -> dict[str, Any]:
    """A fixture row as the API answers it, from the contract alone (`x-bga.entities`, Story 10.0b): what the mocks
    and a live backend return for that record."""
    meta = contract.get("x-bga") or {}
    info = (meta.get("entities") or {}).get(entity or "")
    if info is None:
        return dict(record)
    fixtures = meta.get("fixtures") or {}
    out = {key: value for key, value in record.items() if key not in set(info.get("secretFields") or [])}
    if "allowedActions" not in info:  # not presented: only its secrets dropped
        return out
    for reference in info["references"]:
        value = record.get(reference["field"])
        key = ((meta.get("entities") or {}).get(reference["entity"]) or {}).get("primaryKey", "id")
        parent = next((row for row in fixtures.get(reference["entity"]) or [] if row.get(key) == value), None)
        label = (parent or {}).get(reference["labelField"]) if reference["labelField"] else None
        out[reference["apiName"]] = None if value is None else {"id": value, "label": label}
    own = record.get(info.get("primaryKey") or "id")
    for child in info.get("children") or []:  # Story 10.11: a one-to-one child
        row = next((r for r in fixtures.get(child["entity"]) or [] if r.get(child["field"]) == own), None)
        out[child["apiName"]] = (
            None if row is None else {"id": row.get(child["primaryKeyField"]), "label": row.get(child["labelField"])}
        )
    out["allowedActions"] = list(info["allowedActions"])
    return out


def contract_operations(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """operationId → {method, path, operation}."""
    found = {}
    for path, item in contract.get("paths", {}).items():
        for method, operation in item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                found[operation["operationId"]] = {"method": method.upper(), "path": path, "operation": operation}
    return found


def resolve(document: dict[str, Any], schema: Any) -> Any:
    """Follows local `$ref`s (`#/components/...`) until a schema without one."""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 20:
        node: Any = document
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema, seen = node, seen + 1
    return schema
