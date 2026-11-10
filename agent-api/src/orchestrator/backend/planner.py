"""Deterministic architecture planner (Story 5.1): normalized BackendSpec → fastapi-skills implementation plan.

No LLM. The same spec always yields a byte-identical plan (see `dump_plan`). Generation prompts, the conventions
check, the schema check, the OpenAPI parity check and the test coverage check all read this plan.

Naming: Python attributes and database columns are snake_case; the HTTP API (JSON bodies and query parameters)
keeps the spec's camelCase names through Pydantic aliases.
"""

import json
import re
from typing import Any

from src.modules.shared.domain.backend_spec import media
from src.modules.shared.domain.backend_spec.naming import pluralize, py_name, to_pascal, to_snake

from ..plugins import active_plugins, extended_spec

PLAN_VERSION = "1"
ENTITIES_PKG = "src/modules/shared/domain/entities"
MODELS_PKG = "src/modules/shared/infrastructure/models"
WRITE_ACTIONS = {"create", "update", "delete"}
CRUD_STATUS = {"create": 201, "get": 200, "list": 200, "update": 200, "delete": 204}
# Story 10.0b: the field that names a record, when the spec names none (then: the first required string field)
LABEL_FIELDS = ("name", "title", "label", "email")

# spec field type → (python type, column type as SQLAlchemy/SQLModel spells it)
TYPE_MAP: dict[str, tuple[str, str]] = {
    "uuid": ("uuid.UUID", "Uuid"),
    "string": ("str", "VARCHAR"),
    "text": ("str", "Text"),
    "integer": ("int", "Integer"),
    "float": ("float", "Float"),
    "decimal": ("decimal.Decimal", "Numeric(18, 4)"),
    "boolean": ("bool", "Boolean"),
    "date": ("datetime.date", "Date"),
    "datetime": ("datetime.datetime", "DateTime(timezone=True)"),
    "enum": ("<enum>", "Enum"),
    "json": ("Any", "JSONB"),
    # Story 10.5: an uploaded object's key (the planner makes these `string` columns that carry `file`); Epic 29:
    # the media kinds are file fields too
    "file": ("str", "VARCHAR(512)"),
    "image": ("str", "VARCHAR(512)"),
    "video": ("str", "VARCHAR(512)"),
    "audio": ("str", "VARCHAR(512)"),
    "subtitles": ("str", "VARCHAR(512)"),
}
IMAGE_TYPES = media.IMAGE_TYPES
MAX_FILE_SIZE = media.DEFAULT_MAX_SIZE["file"]
MAX_IMAGE_SIZE = media.DEFAULT_MAX_SIZE["image"]
# Epic 29 (Story 29.1): one table of defaults per file kind: the types browsers play and the largest size
MEDIA_KINDS = {kind: (media.default_accept(kind), media.default_max_size(kind)) for kind in media.FILE_KINDS}


def handler_name(operation_id: str, list_action: bool = False) -> str:
    """`task.create` → `create_task`; `task.list` → `list_tasks`; `admin.task.archive` → `archive_admin_task`."""
    *resource, action = operation_id.split(".")
    subject = "_".join(to_snake(part) for part in resource)
    if list_action:
        head, _, last = subject.rpartition("_")
        subject = f"{head}_{pluralize(last)}" if head else pluralize(last)
    return f"{to_snake(action)}_{subject}"


def _usecase_class(handler: str) -> str:
    return f"{to_pascal(handler)}Usecase"


def _enum_class(entity: str, field: str) -> str:
    return f"{entity}{to_pascal(field)}"


def _column(entity: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
    python_type, column_type = TYPE_MAP[field["type"]]
    attr = py_name(to_snake(field["name"]))
    column: dict[str, Any] = {
        "field": field["name"],
        "attr": attr,
        "apiName": field["name"],
        "type": field["type"],
        "pythonType": python_type,
        "columnType": column_type,
        "nullable": bool(field.get("nullable")),
        "primaryKey": bool(field.get("primary")),
        "unique": bool(field.get("unique")),
        "index": bool(field.get("index")),
    }
    if field["type"] == "enum":
        enum_class = _enum_class(entity["name"], field["name"])
        column["pythonType"] = enum_class
        column["enum"] = {
            "class": enum_class,
            "dbName": f"{to_snake(entity['name'])}_{attr}",
            "values": list(field.get("values") or []),
            "module": f"{ENTITIES_PKG}/{to_snake(entity['name'])}_entity.py",
        }
    if field["type"] in MEDIA_KINDS:  # Story 10.5: a string column holding the object key (Epic 29: media too)
        accept, max_size = MEDIA_KINDS[field["type"]]
        column |= {"type": "string", "maxLength": 512, "columnType": "VARCHAR(512)"}
        column["file"] = {
            "kind": field["type"],
            "accept": list(field.get("accept") or accept),
            "maxSize": field.get("maxSize") or max_size,
            "prefix": f"{to_snake(entity['name'])}/{attr}",  # every key of the field starts with it
        }
    if field.get("maxLength") is not None and "file" not in column:
        column["maxLength"] = field["maxLength"]
        column["columnType"] = f"VARCHAR({field['maxLength']})" if field["type"] == "string" else column_type
    for bound in ("min", "max"):
        if field.get(bound) is not None:
            value = field[bound]
            column[bound] = int(value) if float(value).is_integer() else value
    default = field.get("default")
    if column["primaryKey"] and field["type"] == "uuid":
        column["default"] = {"factory": "uuid.uuid4"}
    elif column["primaryKey"] and field["type"] == "integer":
        column["default"] = {"autoincrement": True}
    elif default == "now" and field["type"] in ("date", "datetime"):
        column["default"] = {"factory": "now (UTC)"}
    elif default is not None:
        column["default"] = {"value": default}
    return column


def _relationships(spec: dict[str, Any]) -> tuple[dict[str, list], list[dict], list[dict]]:
    """Returns (FK columns to add per entity, relationship attributes per model, link models)."""
    by_name = {entity["name"]: entity for entity in spec.get("entities", [])}
    fks: dict[str, list[dict[str, Any]]] = {}
    attributes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    # two entities linked by more than one foreign key (a record's tenant and its contractor, both users): each
    # relationship is named after its key and says which key it follows, else SQLAlchemy cannot map either side
    pairs: dict[tuple[str, str], int] = {}
    for rel in spec.get("relationships", []):
        if rel["type"] in ("one-to-many", "one-to-one"):
            pairs[(rel["from"], rel["to"])] = pairs.get((rel["from"], rel["to"]), 0) + 1
    # a draft with an explicit join entity (a child of both ends) *and* a many-to-many between the ends: the link
    # model's routes would land in the join entity's module and the app could not start. The join entity already
    # models the relationship, so such a many-to-many adds nothing.
    children_of: dict[str, set[str]] = {}
    for rel in spec.get("relationships", []):
        if rel["type"] == "one-to-many":
            children_of.setdefault(rel["to"], set()).add(rel["from"])
    for rel in spec.get("relationships", []):
        if rel["type"] == "many-to-many" and any(
            {rel["from"], rel["to"]} <= parents for parents in children_of.values()
        ):
            continue
        parent, child = by_name[rel["from"]], by_name[rel["to"]]
        parent_pk = next(f for f in parent["fields"] if f.get("primary"))
        parent_attr = py_name(to_snake(rel["from"]))
        child_collection = pluralize(to_snake(rel["to"]))
        if rel["type"] in ("one-to-many", "one-to-one"):
            fk_field = rel["foreignKey"]
            keyed: dict[str, Any] = {}
            remote: dict[str, Any] = {}
            itself = rel["from"] == rel["to"]
            if pairs[(rel["from"], rel["to"])] > 1 or itself:
                stem = to_snake(fk_field).removesuffix("_id") or parent_attr
                parent_attr = py_name(stem)
                child_collection = f"{child_collection}_as_{stem}"
                keyed = {"foreignKeys": f"{rel['to']}Model.{to_snake(fk_field)}"}
            if itself:
                # a record pointing at another of its kind (a comment's parent comment): both sides live on one model,
                # so the many-to-one side names the parent's key as its remote side, else SQLAlchemy can't tell them
                remote = {"remoteSide": f"{rel['from']}Model.{to_snake(parent_pk['name'])}"}
            fks.setdefault(rel["to"], []).append(
                {
                    "field": fk_field,
                    "attr": to_snake(fk_field),
                    "references": f"{parent['table']}.{to_snake(parent_pk['name'])}",
                    "referencesType": parent_pk["type"],
                    "onDelete": rel.get("onDelete") or "RESTRICT",
                    "unique": rel["type"] == "one-to-one",
                }
            )
            many = rel["type"] == "one-to-many"
            attributes.append(
                {
                    "relationship": rel["name"],
                    "type": rel["type"],
                    "parent": {
                        "model": f"{rel['from']}Model",
                        "attr": child_collection if many else py_name(to_snake(rel["to"])),
                        # Story 10.11: a one-to-one parent side is one record (`uselist=False`), possibly none
                        "annotation": f'list["{rel["to"]}Model"]' if many else f'"{rel["to"]}Model"',
                        "backPopulates": parent_attr,
                        **({} if many else {"uselist": False}),
                        **keyed,
                    },
                    "child": {
                        "model": f"{rel['to']}Model",
                        "attr": parent_attr,
                        "annotation": f'"{rel["from"]}Model"',
                        "backPopulates": child_collection if many else py_name(to_snake(rel["to"])),
                        **keyed,
                        **remote,
                    },
                }
            )
        else:
            child_pk = next(f for f in child["fields"] if f.get("primary"))
            link_entity = rel.get("through") or f"{rel['from']}{rel['to']}Link"
            left, right = f"{to_snake(rel['from'])}_id", f"{to_snake(rel['to'])}_id"
            lower = lambda name: f"{name[:1].lower()}{name[1:]}Id"  # noqa: E731 - the link's API names
            links.append(
                {
                    "relationship": rel["name"],
                    "from": rel["from"],
                    "to": rel["to"],
                    "class": f"{link_entity}Model" if not link_entity.endswith("Model") else link_entity,
                    "table": f"{parent['table']}_{child['table']}",
                    "file": f"{MODELS_PKG}/{to_snake(link_entity)}_model.py",
                    "columns": [
                        {
                            "attr": left,
                            "field": lower(rel["from"]),
                            "references": f"{parent['table']}.{to_snake(parent_pk['name'])}",
                            "referencesType": parent_pk["type"],
                            "onDelete": "CASCADE",
                            "primaryKey": True,
                        },
                        {
                            "attr": right,
                            "field": lower(rel["to"]),
                            "references": f"{child['table']}.{to_snake(child_pk['name'])}",
                            "referencesType": child_pk["type"],
                            "onDelete": "CASCADE",
                            "primaryKey": True,
                        },
                    ],
                }
            )
            attributes.append(
                {
                    "relationship": rel["name"],
                    "type": "many-to-many",
                    "link": links[-1]["class"],
                    "parent": {
                        "model": f"{rel['from']}Model",
                        "attr": child_collection,
                        "annotation": f'list["{rel["to"]}Model"]',
                        "backPopulates": pluralize(parent_attr),
                    },
                    "child": {
                        "model": f"{rel['to']}Model",
                        "attr": pluralize(parent_attr),
                        "annotation": f'list["{rel["from"]}Model"]',
                        "backPopulates": child_collection,
                    },
                }
            )
    return fks, attributes, links


def _computed(models: list[dict[str, Any]], spec: dict[str, Any]) -> None:
    """Epic 33: the read-only fields features add to their targets (`likeCount`, `myLikeId`), as model entries the
    repository's `references()` fills per page of records: a grouped count, or the caller's own row id."""
    by_entity = {model["entity"]: model for model in models if model.get("entity")}
    for attached in spec.get("features") or []:
        for computed in attached.get("computed") or []:
            target = by_entity.get(computed.get("target") or attached["on"])
            rows = by_entity.get(computed["entity"])
            if rows is None or target is None:
                continue
            target.setdefault("computed", []).append(
                {
                    "field": computed["field"],
                    "attr": to_snake(computed["field"]),
                    "kind": computed["kind"],
                    "entity": computed["entity"],
                    "model": rows["class"],
                    "key": to_snake(computed["key"]),
                    "keyField": computed["key"],
                    "where": {to_snake(name): value for name, value in (computed.get("where") or {}).items()},
                    "whereFields": dict(computed.get("where") or {}),
                    **(
                        {"owner": to_snake(computed["owner"]), "ownerField": computed["owner"]}
                        if computed.get("owner")
                        else {}
                    ),
                    **(
                        {"match": to_snake(computed["match"]), "matchField": computed["match"]}
                        if computed.get("match")
                        else {}
                    ),
                    "pkType": next(c for c in rows["columns"] if c["primaryKey"])["type"],
                }
            )


def _models(spec: dict[str, Any]) -> list[dict[str, Any]]:
    fks, attributes, links = _relationships(spec)
    models = []
    for entity in spec.get("entities", []):
        columns = [_column(entity, field) for field in entity["fields"]]
        by_attr = {column["attr"]: column for column in columns}
        foreign_keys = []
        for fk in fks.get(entity["name"], []):
            column = by_attr.get(fk["attr"])
            if column is None:  # the spec relies on the implicit foreign key: add the column
                python_type, column_type = TYPE_MAP[fk["referencesType"]]
                column = {
                    "field": fk["field"],
                    "attr": fk["attr"],
                    "apiName": fk["field"],
                    "type": fk["referencesType"],
                    "pythonType": python_type,
                    "columnType": column_type,
                    "nullable": fk["onDelete"] == "SET NULL",
                    "primaryKey": False,
                    "unique": False,
                    "index": True,
                    "implicit": True,
                }
                columns.append(column)
                by_attr[fk["attr"]] = column
            if fk["unique"]:
                column["unique"] = True
            column["foreignKey"] = {"references": fk["references"], "onDelete": fk["onDelete"]}
            foreign_keys.append({"column": fk["attr"], "references": fk["references"], "onDelete": fk["onDelete"]})
        name = to_snake(entity["name"])
        models.append(
            {
                "entity": entity["name"],
                "table": entity["table"],
                "class": f"{entity['name']}Model",
                "file": f"{MODELS_PKG}/{name}_model.py",
                "entityClass": f"{entity['name']}Entity",
                "entityFile": f"{ENTITIES_PKG}/{name}_entity.py",
                "primaryKey": next(c["attr"] for c in columns if c["primaryKey"]),
                "columns": columns,
                "foreignKeys": foreign_keys,
                "indexes": [
                    {
                        "name": index.get("name")
                        or f"ix_{entity['table']}_{'_'.join(to_snake(f) for f in index['fields'])}",
                        "columns": [to_snake(f) for f in index["fields"]],
                        "unique": bool(index.get("unique")),
                    }
                    for index in entity.get("indexes", [])
                ],
                "uniqueConstraints": [[to_snake(f) for f in group] for group in entity.get("uniqueConstraints", [])],
                "enums": [c["enum"] for c in columns if "enum" in c],
                "relationships": [
                    {**side, "relationship": attr["relationship"], "type": attr["type"], "link": attr.get("link")}
                    for attr in attributes
                    for side in (attr["parent"], attr["child"])
                    if side["model"] == f"{entity['name']}Model"
                ],
            }
        )
    for link in links:
        models.append(
            {
                "entity": None,
                "table": link["table"],
                "class": link["class"],
                "file": link["file"],
                "linkFor": link["relationship"],
                "linkFrom": link["from"],
                "linkTo": link["to"],
                "primaryKey": [c["attr"] for c in link["columns"]],
                "columns": [
                    {
                        "attr": c["attr"],
                        "field": c["field"],
                        "apiName": c["field"],
                        "type": c["referencesType"],
                        "pythonType": TYPE_MAP[c["referencesType"]][0],
                        "columnType": TYPE_MAP[c["referencesType"]][1],
                        "nullable": False,
                        "primaryKey": True,
                        "unique": False,
                        "index": False,
                        "foreignKey": {"references": c["references"], "onDelete": c["onDelete"]},
                    }
                    for c in link["columns"]
                ],
                "foreignKeys": [
                    {"column": c["attr"], "references": c["references"], "onDelete": c["onDelete"]}
                    for c in link["columns"]
                ],
                "indexes": [],
                "uniqueConstraints": [],
                "enums": [],
                "relationships": [],
            }
        )
    return models


def _label_column(entity: dict[str, Any], model: dict[str, Any]) -> dict[str, Any] | None:
    """Story 10.0b: the column that names a record (`displayField`, else a usual name, else a required string)."""
    by_api = {column["apiName"]: column for column in model["columns"]}
    if entity.get("displayField") in by_api:
        return by_api[entity["displayField"]]
    named = next((by_api[name] for name in LABEL_FIELDS if name in by_api), None)
    return named or next(
        (
            column
            for column in model["columns"]
            if column["type"] in ("string", "text")
            and not column["nullable"]
            and not column.get("foreignKey")
            and "file" not in column  # an object key names nothing
        ),
        None,
    )


def _references(models: list[dict[str, Any]]) -> None:
    """Story 10.0b: each foreign key to a parent with a label becomes a reference, shown in responses as a summary
    `{id, label}` under the key without its `Id` (`deckId` → `deck`)."""
    by_table = {model["table"]: model for model in models if model.get("entity")}
    for model in models:
        if not model.get("entity"):
            continue
        taken = {column["apiName"] for column in model["columns"]}
        references = []
        for column in model["columns"]:
            fk = column.get("foreignKey")
            parent = by_table.get(fk["references"].partition(".")[0]) if fk else None
            if parent is None or parent.get("label") is None:
                continue
            api = column["apiName"].removesuffix("Id") if column["apiName"].endswith("Id") else ""
            if not api or api in taken:
                api = f"{column['apiName']}Ref"
            taken.add(api)
            references.append(
                {
                    "column": column["attr"],
                    "field": column["apiName"],
                    "apiName": api,
                    "attr": py_name(to_snake(api)),
                    "entity": parent["entity"],
                    "model": parent["class"],
                    "primaryKey": parent["primaryKey"],
                    "primaryKeyField": next(c["apiName"] for c in parent["columns"] if c["primaryKey"]),
                    "labelAttr": parent["label"]["attr"],
                    "labelField": parent["label"]["apiName"],
                    "nullable": column["nullable"],
                }
            )
        model["references"] = references
    for model in models:  # Story 10.11: a one-to-one child, shown in its parent's response as a summary
        if not model.get("entity"):
            continue
        children = []
        taken = {column["apiName"] for column in model["columns"]} | {r["apiName"] for r in model["references"]}
        for child in models:
            if not child.get("entity") or child.get("label") is None:
                continue
            for column in child["columns"]:
                fk = column.get("foreignKey")
                if not fk or not column["unique"] or fk["references"].partition(".")[0] != model["table"]:
                    continue
                api = f"{child['entity'][:1].lower()}{child['entity'][1:]}"
                if api in taken:
                    api = f"{api}Ref"
                taken.add(api)
                children.append({
                    "apiName": api, "attr": py_name(to_snake(api)), "entity": child["entity"], "model": child["class"],
                    "column": column["attr"], "field": column["apiName"], "primaryKey": child["primaryKey"],
                    "primaryKeyField": next(c["apiName"] for c in child["columns"] if c["primaryKey"]),
                    "labelAttr": child["label"]["attr"], "labelField": child["label"]["apiName"],
                })  # fmt: skip
        model["children"] = children


def record_actions(module: dict[str, Any], model: dict[str, Any]) -> list[str]:
    """Story 10.0b: what can be done to one record (`allowedActions`): update, delete, and the custom writes on one
    record (a path parameter that is the record's id: `POST /cards/{cardId}/review`)."""
    entity = module["entity"]
    own_ids = {"id", model["primaryKey"], to_snake(model["primaryKey"]), f"{entity[:1].lower()}{entity[1:]}Id"}
    actions = []
    for op in module["operations"]:
        if op.get("action") in ("update", "delete"):
            actions.append(op["action"])
        elif op["type"] == "custom" and op["method"] != "GET" and own_ids & set(re.findall(r"\{(\w+)\}", op["path"])):
            actions.append(op["operationId"])
    return list(dict.fromkeys(actions))


def _operation(op: dict[str, Any], model: dict[str, Any] | None) -> dict[str, Any]:
    action = op.get("action") if op["type"] == "crud" else None
    handler = handler_name(op["operationId"], list_action=action == "list")
    usecase = _usecase_class(handler)
    planned: dict[str, Any] = {
        "operationId": op["operationId"],
        "type": op["type"],
        "action": action,
        "method": op["method"],
        "path": op["path"],
        "handler": handler,
        "usecase": usecase,
        "usecaseDep": f"{usecase}Dep",
        "usecaseFile": f"{handler}_usecase.py",
        "transactional": action in WRITE_ACTIONS or (action is None and op["method"] != "GET"),
        "status": CRUD_STATUS.get(action or "", 200),
        "errors": [],
    }
    if op.get("summary"):
        planned["summary"] = op["summary"]
    if op["type"] == "aggregate":  # Epic 21: templated like CRUD; the response is a value or grouped values
        by_api = {c["apiName"]: c for c in model["columns"]} if model else {}
        agg = dict(op.get("aggregate") or {})
        planned["aggregate"] = {
            "fn": agg.get("fn", "count"),
            "field": agg.get("field"),
            "attr": by_api.get(agg.get("field") or "", {}).get("attr"),
            "groupBy": agg.get("groupBy"),
            "groupAttr": by_api.get(agg.get("groupBy") or "", {}).get("attr"),
            "period": agg.get("period"),
            "dateAttr": by_api.get(agg.get("dateField") or "", {}).get("attr")
            or next((c["attr"] for c in (model or {}).get("columns", []) if c["type"] in ("date", "datetime")), None),
            "filters": {by_api[k]["attr"]: v for k, v in (agg.get("filters") or {}).items() if k in by_api},
        }
        planned["responseDto"] = f"{to_pascal(handler)}ResponseDto"
        planned["dtoFile"] = f"{handler}_dto.py"
        planned["transactional"] = False
        if op.get("auth") == "jwt" or op.get("policy"):  # Story 23.9: a figure for some roles only (was ignored)
            planned["auth"] = {"auth": "jwt", "policy": op.get("policy")}
        return planned
    entity = model["entity"] if model else None
    if action in ("get", "update", "delete") or (action is None and "{" in op["path"]):
        planned["errors"].append({"status": 404, "exception": "NotFoundException", "code": "NOT_FOUND"})
    if action in ("create", "update"):
        planned["requestDto"] = f"{to_pascal(handler)}RequestDto"
        planned["dtoFile"] = f"{handler}_dto.py"
        if (op.get("request") or {}).get("fields") is not None:  # the fields the body takes (its DTO's), for plugins
            planned["requestFields"] = list(op["request"]["fields"])
        planned["errors"].append({"status": 422, "exception": None, "code": "VALIDATION_ERROR"})
        if model and any(c["unique"] and not c["primaryKey"] for c in model["columns"]):
            planned["errors"].append({"status": 409, "exception": "ConflictException", "code": "CONFLICT"})
        if model and model["foreignKeys"]:
            planned["errors"].append({"status": 400, "exception": "BadRequestException", "code": "REFERENCE_NOT_FOUND"})
    if action in ("create", "get", "update"):
        planned["responseDto"] = f"{entity}ResponseDto"
    if action == "list" or op.get("filters") or op.get("sort") or op.get("search"):
        pagination = op.get("pagination") or None
        if action == "list":
            planned["responseDto"] = f"{to_pascal(handler)}ResponseDto"
            planned["dtoFile"] = f"{handler}_dto.py"
        planned["pagination"] = pagination
        by_api = {c["apiName"]: c for c in model["columns"]} if model else {}
        # A list's path parameter that names a column scopes it (`/fields/{fieldId}/reviews`): a filter bound to the
        # path, never also a query parameter of the same name.
        scope = [name for name in re.findall(r"\{(\w+)\}", op["path"]) if name in by_api] if action == "list" else []
        planned["filters"] = [
            {"param": name, "attr": by_api[name]["attr"], "type": by_api[name]["type"]}
            | ({"in": "path"} if name in scope else {})
            for name in dict.fromkeys([*scope, *op.get("filters", [])])
            if name in by_api
        ]
        planned["sort"] = [
            {"param": name, "attr": by_api[name]["attr"]} for name in op.get("sort", []) if name in by_api
        ]
        planned["search"] = [
            {"param": name, "attr": by_api[name]["attr"]} for name in op.get("search", []) if name in by_api
        ]
        ranges = [
            {"param": name, "attr": by_api[name]["attr"], "type": by_api[name]["type"]}
            for name in op.get("ranges", [])
            if name in by_api and action == "list"
        ]
        if ranges:  # Story 23.4: `<param>From` / `<param>To`, inclusive
            planned["ranges"] = ranges
        if planned["sort"]:
            planned["errors"].append({"status": 422, "exception": None, "code": "VALIDATION_ERROR"})
    if op.get("rules"):
        planned["rules"] = list(op["rules"])
    if op.get("auth") == "jwt" or op.get("policy"):  # a policy needs to know who is calling (Story 10.3)
        planned["auth"] = {"auth": "jwt", "policy": op.get("policy")}
    return planned


def _repository_methods(operations: list[dict[str, Any]]) -> list[str]:
    needed = {"create": ["create"], "get": ["find_by_id"], "list": ["list"], "update": ["find_by_id", "update"]}
    needed["delete"] = ["find_by_id", "delete"]
    methods: list[str] = []
    for op in operations:
        for method in needed.get(op["action"] or "", []):
            if method not in methods:
                methods.append(method)
        if op.get("type") == "aggregate" and op["handler"] not in methods:  # Epic 21: one repository method each
            methods.append(op["handler"])
    return methods


def _tests(module: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []

    def add(op: dict[str, Any], case: str, expect: int, description: str) -> None:
        tests.append(
            {
                "id": f"test_{op['handler']}__{case}",
                "operationId": op["operationId"],
                "case": case,
                "expectStatus": expect,
                "description": description,
            }
        )

    for op in module["operations"]:
        action = op["action"]
        if action == "create":
            add(op, "ok", 201, "valid payload creates the record and returns it")
            add(op, "invalid", 422, "missing required field or wrong type is rejected")
            if any(e["code"] == "CONFLICT" for e in op["errors"]):
                add(op, "conflict", 409, "duplicate value in a unique field is rejected")
            if any(e["code"] == "REFERENCE_NOT_FOUND" for e in op["errors"]):
                add(op, "bad_reference", 400, "a foreign key pointing at a missing record is rejected")
        elif action == "get":
            add(op, "ok", 200, "returns the record")
            add(op, "not_found", 404, "unknown id returns 404 with the error envelope")
        elif action == "list":
            add(op, "ok", 200, "returns {items, total, limit, offset}")
            if op.get("pagination"):
                add(op, "pagination", 200, "limit and offset page through the records; total counts all")
            for flt in op.get("filters", []):
                what = f"{{{flt['param']}}} in the path" if flt.get("in") == "path" else f"?{flt['param']}="
                add(op, f"filter_{to_snake(flt['param'])}", 200, f"{what} returns only matching records")
            for rng in op.get("ranges", []):  # Story 23.4
                what = f"?{rng['param']}From= and ?{rng['param']}To="
                add(op, f"range_{to_snake(rng['param'])}", 200, f"{what} limit the records to a range, inclusive")
            if op.get("sort"):
                add(op, "sort", 200, "?sort=<field> ascending and ?sort=-<field> descending")
                add(op, "invalid_sort", 422, "sorting by an undeclared field is rejected")
            if op.get("search"):
                add(op, "search", 200, "?q= matches the declared search fields")
        elif action == "update":
            add(op, "ok", 200, "partial update changes only the sent fields")
            add(op, "not_found", 404, "unknown id returns 404")
            add(op, "invalid", 422, "wrong type is rejected")
        elif action == "delete":
            add(op, "ok", 204, "deletes the record; a later get returns 404")
            add(op, "not_found", 404, "unknown id returns 404")
        else:
            add(op, "ok", op["status"], "custom operation happy path")
    for test in tests:
        test["module"] = module["name"]
        test["file"] = module["testFile"]
    return tests


def build_plan(spec: dict[str, Any]) -> dict[str, Any]:
    """`spec` is the normalized BackendSpec (validate_spec_text(...).normalized)."""
    spec = extended_spec(spec)  # Story 10.2: what plugins add before planning (the user entity)
    models = _models(spec)
    by_entity = {m["entity"]: m for m in models if m["entity"]}
    for entity in spec.get("entities", []):
        label = _label_column(entity, by_entity[entity["name"]])
        by_entity[entity["name"]]["label"] = {"attr": label["attr"], "apiName": label["apiName"]} if label else None
    _references(models)
    _computed(models, spec)
    modules, unresolved = [], []
    for entity in spec.get("entities", []):
        model = by_entity[entity["name"]]
        name = entity["table"]
        ops = [_operation(op, model) for op in spec.get("operations", []) if op.get("entity") == entity["name"]]
        if not ops:
            continue
        base = f"src/modules/{name}"
        entity_snake = to_snake(entity["name"])
        dto_files = sorted({op["dtoFile"] for op in ops if "dtoFile" in op} | {f"{entity_snake}_response_dto.py"})
        module = {
            "name": name,
            "entity": entity["name"],
            "model": model["class"],
            "entityClass": model["entityClass"],
            "port": {
                "interface": f"I{entity['name']}Repository",
                "dep": f"I{entity['name']}RepoDep",
                "file": f"{base}/ports/output/{entity_snake}_repository.py",
                "implementation": f"{entity['name']}Repository",
                "implementationFile": f"{base}/infrastructure/persistence/{entity_snake}_repository.py",
                "methods": _repository_methods(ops),
            },
            "usecases": [
                {
                    "class": op["usecase"],
                    "dep": op["usecaseDep"],
                    "file": f"{base}/usecases/{op['usecaseFile']}",
                    "operationId": op["operationId"],
                    "transactional": op["transactional"],
                    "raises": sorted({e["exception"] for e in op["errors"] if e["exception"]}),
                }
                for op in ops
            ],
            "dtoFiles": [f"{base}/presenter/dtos/{file}" for file in dto_files],
            "router": {
                "variable": f"{entity_snake}_router",
                "file": f"{base}/presenter/router.py",
                "prefix": "",
                "tag": name,
            },
            "operations": ops,
            "recordActions": [],
            "testFile": f"tests/modules/{name}/test_{entity_snake}_api.py",
        }
        module["recordActions"] = record_actions(module, model)
        # parents' labels, a one-to-one child (10.11), fields a feature computes per record (Epic 33)
        shown = model.get("references") or model.get("children") or model.get("computed")
        if shown and {"create", "get", "list", "update"} & {op.get("action") for op in ops}:
            module["port"]["methods"].append("references")  # Story 10.0b: parents' labels for the responses
        module["tests"] = _tests(module, model)
        modules.append(module)
    for op in spec.get("operations", []):
        if op["type"] == "custom":
            unresolved.append(
                {
                    "kind": "custom_operation",
                    "ref": op["operationId"],
                    "message": "Custom operation: the engine implements it from the description or raises 501",
                }
            )
        if op.get("auth") == "jwt" or op.get("policy"):
            unresolved.append(
                {"kind": "auth", "ref": op["operationId"], "message": "Auth and policies arrive with Epic 10"}
            )
    for key in ("rules", "integrations", "backgroundJobs", "policies"):
        for item in spec.get(key, []):
            unresolved.append(
                {"kind": key, "ref": item.get("id") or item.get("name"), "message": f"`{key}` are not generated yet"}
            )
    if spec.get("auth"):
        unresolved.append({"kind": "auth", "ref": "auth", "message": "JWT auth arrives with Epic 10"})

    plan = {
        "planVersion": PLAN_VERSION,
        "project": {"name": spec["project"]["name"], "slug": spec["project"].get("slug")},
        "architecture": "fastapi-skills-hexagonal",
        "conventions": {
            "pythonNames": "snake_case attributes and columns",
            "apiNames": "camelCase JSON and query parameters (Pydantic alias_generator=to_camel, populate_by_name)",
            "listResponse": {"items": "list", "total": "int", "limit": "int", "offset": "int"},
            "sortParam": "sort=<field> or sort=-<field>; undeclared field → 422",
            "searchParam": "q",
            "errorBody": {"error": {"code": "str", "message": "str", "details": "any"}},
        },
        "models": models,
        "modules": modules,
        "routers": {
            "file": "src/routers.py",
            "variable": "all_router",
            "order": ["health_router", *(m["router"]["variable"] for m in modules)],
        },
        "dependencies": [],
        "tests": [test for module in modules for test in module["tests"]],
        "unresolved": unresolved,
    }
    # Story 10.1: the plugins this spec turns on, in order; each adds to the plan what it needs
    plugins = active_plugins(spec)
    plan["plugins"] = [plugin.manifest() for plugin in plugins]
    for plugin in plugins:
        plugin.plan(plan, spec)
    return plan


def dump_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def planned_operations(plan: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(op["method"], op["path"], op["operationId"]) for m in plan["modules"] for op in m["operations"]}
