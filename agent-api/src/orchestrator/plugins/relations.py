"""Many-to-many relations as a plugin (Story 10.11): a route set per link model, from templates.

`GET /<parents>/{id}/<children>` lists the related records as `{id, label}` summaries, one query per page;
`POST /<parents>/{id}/<children>` (`{<child>Id}`) adds one (404 for an unknown parent, 400 `REFERENCE_NOT_FOUND` for an
unknown child, 409 `DUPLICATE` when already related); `DELETE /<parents>/{id}/<children>/{<child>Id}` removes it. The
link model (composite primary key, both foreign keys `ON DELETE CASCADE`) is planned and written with the other models.
"""

import re
from typing import Any

from src.modules.shared.domain.backend_spec.naming import to_pascal, to_snake

from .base import Plugin


def _lower(name: str) -> str:
    return f"{name[:1].lower()}{name[1:]}"


def _base(plan: dict[str, Any], entity: str, table: str) -> str:
    """Where an entity's records live in the API: its list route, else its table."""
    module = next((m for m in plan["modules"] if m.get("entity") == entity and not m.get("plugin")), None)
    for op in (module or {}).get("operations", []):
        if op.get("action") == "list" and "{" not in op["path"]:
            return op["path"]
    return f"/{table.replace('_', '-')}"


class RelationsPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="relations")

    def applies(self, spec: dict[str, Any]) -> bool:
        return any(rel.get("type") in ("many-to-many", "one-to-one") for rel in spec.get("relationships", []))

    def plan(self, plan: dict[str, Any], spec: dict[str, Any]) -> None:
        models = {m["entity"]: m for m in plan["models"] if m.get("entity")}
        relations = []
        for link in (m for m in plan["models"] if m.get("linkFor")):
            parent, child = models[link["linkFrom"]], models[link["linkTo"]]
            left, right = link["columns"]
            parent_pk = next(c for c in parent["columns"] if c["primaryKey"])
            child_pk = next(c for c in child["columns"] if c["primaryKey"])
            segment = _base(plan, child["entity"], child["table"]).rstrip("/").rsplit("/", 1)[-1]
            path = f"{_base(plan, parent['entity'], parent['table']).rstrip('/')}/{{id}}/{segment}"
            name = f"{to_snake(parent['entity'])}_{to_snake(segment)}"
            child_list = next(
                (
                    op["operationId"]
                    for m in plan["modules"]
                    if m.get("entity") == child["entity"]
                    for op in m["operations"]
                    if op.get("action") == "list"
                ),
                None,
            )
            relation = {
                "name": name,
                "relationship": link["linkFor"],
                "link": link["class"],
                "parent": parent["entity"],
                "parentModel": parent["class"],
                "parentPk": parent_pk["attr"],
                "parentPkType": parent_pk["pythonType"],
                "leftAttr": left["attr"],
                "rightAttr": right["attr"],
                "child": child["entity"],
                "childModel": child["class"],
                "childPk": child_pk["attr"],
                "childPkType": child_pk["pythonType"],
                "childField": right["field"],
                "childLabel": (child.get("label") or {}).get("attr") or child_pk["attr"],
                "childLabelField": (child.get("label") or {}).get("apiName"),
                "childList": child_list,
                "path": path,
                "itemPath": f"{path}/{{{right['field']}}}",
                "ops": {
                    "list": f"{_lower(parent['entity'])}.list{to_pascal(segment.replace('-', '_'))}",
                    "add": f"{_lower(parent['entity'])}.add{child['entity']}",
                    "remove": f"{_lower(parent['entity'])}.remove{child['entity']}",
                },
                "secured": bool(plan.get("auth")),
            }
            relations.append(relation)
            plan["modules"].append(_module(relation))
            plan["routers"]["order"].append(f"{name}_router")
        plan["relations"] = relations
        plan["unresolved"] = [
            entry
            for entry in plan["unresolved"]
            if not (entry["kind"] == "relationships" or "many-to-many" in str(entry.get("message", "")))
        ]

    def contract(self, contract: dict[str, Any], plan: dict[str, Any], spec: dict[str, Any]) -> None:
        meta = contract["x-bga"]
        _one_to_one(contract, plan)
        error = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
        for relation in plan.get("relations", []):
            parents = meta["fixtures"].get(relation["parent"]) or []
            children = meta["fixtures"].get(relation["child"]) or []
            parent_key = next(
                c["apiName"]
                for m in plan["models"]
                if m.get("entity") == relation["parent"]
                for c in m["columns"]
                if c["primaryKey"]
            )
            child_key = next(
                c["apiName"]
                for m in plan["models"]
                if m.get("entity") == relation["child"]
                for c in m["columns"]
                if c["primaryKey"]
            )
            left_field = next(
                c["field"]
                for m in plan["models"]
                if m.get("class") == relation["link"]
                for c in m["columns"]
                if c["attr"] == relation["leftAttr"]
            )
            links = (
                [
                    {left_field: parents[i][parent_key], relation["childField"]: children[i % len(children)][child_key]}
                    for i in range(min(len(parents), 3))
                ]
                if children
                else []
            )
            meta["fixtures"][relation["link"].removesuffix("Model")] = links  # the mocks and the seed hold them
            summary = {
                "type": "object",
                "properties": {"id": {"type": "string"}, "label": {"type": ["string", "null"]}},
                "required": ["id", "label"],
            }
            page = {
                "type": "object",
                "required": ["items", "total", "limit", "offset"],
                "properties": {
                    "items": {"type": "array", "items": summary},
                    "total": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            }
            body = {
                "type": "object",
                "required": [relation["childField"]],
                "properties": {
                    relation["childField"]: {
                        "type": "string",
                        "x-bga": {
                            "source": "reference",
                            "many": True,
                            "ref": {
                                "entity": relation["child"],
                                "listOperation": relation["childList"],
                                "labelField": relation["childLabelField"],
                            },
                        },
                    }
                },
            }
            linked = links[0] if links else None
            first_parent = parents[0][parent_key] if parents else None
            unknown = "00000000-0000-4000-8000-0000000000ff"

            def operation(
                op_id, summary_text, status, scenarios, errors, response=None, request=None, relation=relation
            ):
                out = {
                    "operationId": op_id,
                    "summary": summary_text,
                    "tags": [relation["name"]],
                    "responses": {
                        str(status): {
                            "description": summary_text,
                            **({"content": {"application/json": {"schema": response}}} if response else {}),
                        },
                        **{str(e["status"]): {"description": e["code"], **error} for e in errors},
                    },
                    "x-bga": {
                        "entity": relation["child"],
                        "action": None,
                        "module": relation["name"],
                        "plugin": "relations",
                        "mock": "sample",
                        "errors": errors,
                        "scenarios": [s for s in scenarios if s],
                    },
                }
                if request:
                    out["requestBody"] = {"required": True, "content": {"application/json": {"schema": request}}}
                if relation["secured"]:
                    out["security"] = [{"bearerAuth": []}]
                    out["x-bga"]["auth"] = "jwt"
                return out

            not_found = {"status": 404, "code": "NOT_FOUND", "message": f"{relation['parent']} not found"}
            contract["paths"][relation["path"]] = {
                "get": operation(
                    relation["ops"]["list"],
                    f"The {relation['parent']}'s {relation['child']} records",
                    200,
                    [
                        first_parent and {"name": "success", "params": {"id": first_parent}, "expect": {"status": 200}},
                        {
                            "name": "unknown id",
                            "params": {"id": unknown},
                            "expect": {"status": 404, "code": "NOT_FOUND"},
                        },
                    ],
                    [not_found],
                    response=page,
                ),
                "post": operation(
                    relation["ops"]["add"],
                    f"Relate a {relation['child']}",
                    201,
                    [
                        linked
                        and {
                            "name": "already related",
                            "params": {"id": linked[left_field]},
                            "body": {relation["childField"]: linked[relation["childField"]]},
                            "expect": {"status": 409, "code": "DUPLICATE"},
                        },
                        first_parent
                        and {
                            "name": f"unknown {relation['childField']}",
                            "params": {"id": first_parent},
                            "body": {relation["childField"]: unknown},
                            "expect": {"status": 400, "code": "REFERENCE_NOT_FOUND"},
                        },
                    ],
                    [
                        not_found,
                        {
                            "status": 400,
                            "code": "REFERENCE_NOT_FOUND",
                            "message": f"{relation['child']} not found",
                            "fields": [relation["childField"]],
                        },
                        {
                            "status": 409,
                            "code": "DUPLICATE",
                            "message": "Already related",
                            "fields": [relation["childField"]],
                        },
                    ],
                    response=summary,
                    request=body,
                ),
            }
            contract["paths"][relation["itemPath"]] = {
                "delete": operation(
                    relation["ops"]["remove"],
                    f"Unrelate a {relation['child']}",
                    204,
                    [
                        first_parent
                        and {
                            "name": "not related",
                            "params": {"id": first_parent, relation["childField"]: unknown},
                            "expect": {"status": 404, "code": "NOT_FOUND"},
                        }
                    ],
                    [{"status": 404, "code": "NOT_FOUND", "message": "Not related"}],
                ),
            }
            # Story 22.7: the path parameters (and the list's page), as every other operation declares them
            for path in (relation["path"], relation["itemPath"]):
                names = re.findall(r"\{(\w+)\}", path)
                for method, found in contract["paths"][path].items():
                    found["parameters"] = [
                        {"name": name, "in": "path", "required": True, "schema": {"type": "string"}} for name in names
                    ]
                    if method == "get":
                        found["parameters"] += [
                            {"name": "limit", "in": "query", "required": False,
                             "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
                            {"name": "offset", "in": "query", "required": False,
                             "schema": {"type": "integer", "minimum": 0, "default": 0}},
                        ]  # fmt: skip
            info = meta["entities"].get(relation["parent"])
            if info is not None:
                info.setdefault("links", []).append(
                    {
                        "entity": relation["child"],
                        "list": relation["ops"]["list"],
                        "add": relation["ops"]["add"],
                        "remove": relation["ops"]["remove"],
                        "fixtures": relation["link"].removesuffix("Model"),
                    }
                )

    def files(self, plan: dict[str, Any] | None) -> dict[str, str]:
        files = super().files(plan)
        for relation in (plan or {}).get("relations", []):
            module = f"src/modules/{relation['name']}"
            files[f"{module}/__init__.py"] = ""
            files[f"{module}/presenter/__init__.py"] = (
                f'from .router import {relation["name"]}_router\n\n__all__ = ["{relation["name"]}_router"]\n'
            )
            files[f"{module}/presenter/router.py"] = _router(relation)
            files[f"tests/modules/{relation['name']}/__init__.py"] = ""
            files[f"tests/modules/{relation['name']}/test_{relation['name']}_api.py"] = _tests(plan, relation)
        return files

    def engine_note(self, plan: dict[str, Any]) -> str:
        return (
            "Relations (Story 10.11): many-to-many links have their own routes (list, add, remove) through the link "
            "model; a one-to-one child appears in its parent's response as a summary."
        )


def _repoint(
    meta: dict[str, Any], plan: dict[str, Any], entity: str, removed: dict[str, Any], kept: list[dict[str, Any]]
) -> None:
    """The fixtures pointing at a removed row (a quiz's submissions) go too, and theirs after them: the seed must insert
    (found on a learning draft: a submission's quiz was the one-to-one child removed here, and the seed failed on its
    foreign key). They are dropped rather than pointed elsewhere, which could fill the pair a `uniqueTogether` rule's
    success scenario keeps free (the mocks then answered its create with 409)."""
    model = next((m for m in plan["models"] if m.get("entity") == entity), None)
    if model is None:
        return
    pk = next(c["apiName"] for c in model["columns"] if c["primaryKey"])
    gone = removed.get(pk)
    for other in plan["models"]:
        for column in other["columns"]:
            fk = column.get("foreignKey") or {}
            if fk.get("references", "").partition(".")[0] != model["table"] or not other.get("entity"):
                continue
            rows = meta["fixtures"].get(other["entity"]) or []
            for row in [r for r in rows if r.get(column["apiName"]) == gone]:
                rows.remove(row)
                _repoint(meta, plan, other["entity"], row, rows)


def _one_to_one(contract: dict[str, Any], plan: dict[str, Any]) -> None:
    """A one-to-one child's fixtures leave one parent free, its create succeeds there, and a second child of a parent
    that has one is a scenario (409 CONFLICT, the unique foreign key)."""
    from ..integration.contract import contract_operations

    meta = contract["x-bga"]
    operations = contract_operations(contract)
    for parent in (m for m in plan["models"] if m.get("children")):
        parent_pk = next(c["apiName"] for c in parent["columns"] if c["primaryKey"])
        parents = meta["fixtures"].get(parent["entity"]) or []
        for child in parent["children"]:
            rows = meta["fixtures"].get(child["entity"]) or []
            if not rows or not parents:
                continue
            if len(rows) >= len(parents) and len(rows) > 1:
                removed = rows.pop()  # the last parent keeps no child, so a create has somewhere to go
                _repoint(meta, plan, child["entity"], removed, rows)
            taken = {row.get(child["field"]) for row in rows}
            free = next((p[parent_pk] for p in parents if p[parent_pk] not in taken), None)
            create = next(
                (
                    found["operation"]
                    for found in operations.values()
                    if (found["operation"].get("x-bga") or {}).get("entity") == child["entity"]
                    and (found["operation"].get("x-bga") or {}).get("action") == "create"
                ),
                None,
            )
            scenarios = ((create or {}).get("x-bga") or {}).get("scenarios") or []
            success = next((x for x in scenarios if x["name"] == "success" and isinstance(x.get("body"), dict)), None)
            if success is None or free is None:
                continue
            before = success["body"].get(child["field"])
            for scenario in scenarios:  # every create built from the success's body goes to the free parent too
                body = scenario.get("body")
                if isinstance(body, dict) and child["field"] in body and body[child["field"]] == before:
                    body[child["field"]] = free
            scenarios.append(
                {
                    "name": f"second {_lower(child['entity'])}",
                    "params": success["params"],
                    "body": {**success["body"], child["field"]: rows[0][child["field"]]},
                    "expect": {"status": 409, "code": "CONFLICT"},
                    **({"user": success["user"]} if success.get("user") else {}),  # as the success: the role may create
                }
            )


def _module(relation: dict[str, Any]) -> dict[str, Any]:
    auth = {"auth": "jwt", "policy": None} if relation["secured"] else None

    def op(op_id, method, path, handler, status, errors):
        entry = {
            "operationId": op_id,
            "type": "plugin",
            "action": None,
            "method": method,
            "path": path,
            "handler": handler,
            "status": status,
            "transactional": method != "GET",
            "errors": [{"status": s, "exception": None, "code": c} for s, c in errors],
        }
        if auth:
            entry["auth"] = auth
        return entry

    child = to_snake(relation["child"])
    return {
        "name": relation["name"],
        "entity": None,
        "plugin": "relations",
        "port": {"interface": None, "dep": None, "methods": []},
        "usecases": [],
        "dtoFiles": [],
        "router": {
            "variable": f"{relation['name']}_router",
            "file": f"src/modules/{relation['name']}/presenter/router.py",
            "prefix": "",
            "tag": relation["name"],
        },
        "operations": [
            op(relation["ops"]["list"], "GET", relation["path"], f"list_{child}s", 200, [(404, "NOT_FOUND")]),
            op(
                relation["ops"]["add"],
                "POST",
                relation["path"],
                f"add_{child}",
                201,
                [(404, "NOT_FOUND"), (400, "REFERENCE_NOT_FOUND"), (409, "DUPLICATE")],
            ),
            op(relation["ops"]["remove"], "DELETE", relation["itemPath"], f"remove_{child}", 204, [(404, "NOT_FOUND")]),
        ],
        "recordActions": [],
        "testFile": None,
        "tests": [],
    }


def _router(relation: dict[str, Any]) -> str:
    child, link, parent = relation["childModel"], relation["link"], relation["parentModel"]
    child_snake = to_snake(relation["child"])
    user = "_user: CurrentUserDep, " if relation["secured"] else ""
    field = relation["childField"]
    return (
        f'"""{relation["parent"]} ↔ {relation["child"]} (Story 10.11): list, relate and unrelate, through '
        f'{link}."""\n\n'
        "import uuid\nfrom typing import Annotated\n\n"
        "from fastapi import APIRouter, Path, Query, Response\n"
        "from pydantic import BaseModel, ConfigDict\nfrom pydantic.alias_generators import to_camel\n"
        "from sqlalchemy.exc import IntegrityError\nfrom sqlmodel import col, func, select\n\n"
        "from src.libs.database.session import SessionDep\n"
        "from src.libs.exceptions import BadRequestException, ConflictException, ErrorCode, NotFoundException\n"
        + ("from src.libs.security import CurrentUserDep\n" if relation["secured"] else "")
        + f"from src.modules.shared.infrastructure.models import {', '.join(sorted({child, link, parent}))}\n\n"
        f'{relation["name"]}_router = APIRouter(tags=["{relation["name"]}"])\n\n'
        'ERROR = {"description": "Error envelope: {error: {code, message, details}}"}\n'
        f'ChildId = Annotated[{relation["childPkType"]}, Path(alias="{field}")]\n\n\n'
        "class Camel(BaseModel):\n    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)\n\n\n"
        f"class RelateDto(Camel):\n    {relation['rightAttr']}: {relation['childPkType']}\n\n\n"
        f"class SummaryDto(Camel):\n    id: {relation['childPkType']}\n    label: str | None\n\n\n"
        "class SummaryPageDto(Camel):\n    items: list[SummaryDto]\n    total: int\n    limit: int\n    offset: "
        "int\n\n\n"
        f"def _parent(session: SessionDep, parent_id: {relation['parentPkType']}) -> {parent}:\n"
        f"    found = session.get({parent}, parent_id)\n"
        "    if found is None:\n"
        f'        raise NotFoundException("{relation["parent"]} not found", details={{"id": str(parent_id)}})\n'
        "    return found\n\n\n"
        f"def _summary(row: {child}) -> SummaryDto:\n"
        f"    label = row.{relation['childLabel']}\n"
        f"    return SummaryDto(id=row.{relation['childPk']}, label=None if label is None else str(label))\n\n\n"
        f'@{relation["name"]}_router.get(\n    "{relation["path"]}",\n    operation_id="{relation["ops"]["list"]}",\n'
        "    response_model=SummaryPageDto,\n    responses={404: ERROR},\n)\n"
        f"def list_{child_snake}s(\n    id: {relation['parentPkType']},\n    {user}session: SessionDep,\n"
        "    limit: int = Query(default=20, ge=1, le=100),\n    offset: int = Query(default=0, ge=0),\n"
        ") -> SummaryPageDto:\n"
        '    """One query for the page (and one for the total)."""\n'
        "    _parent(session, id)\n"
        f"    related = select({child}).join({link}, col({link}.{relation['rightAttr']}) == "
        f"col({child}.{relation['childPk']}))\n"
        f"    related = related.where(col({link}.{relation['leftAttr']}) == id)\n"
        "    total = session.exec(select(func.count()).select_from(related.subquery())).one()\n"
        f"    rows = "
        f"session.exec(related.order_by(col({child}.{relation['childLabel']})).offset(offset).limit(limit)).all()\n"
        "    return SummaryPageDto(items=[_summary(row) for row in rows], total=total, limit=limit, "
        "offset=offset)\n\n\n"
        f'@{relation["name"]}_router.post(\n    "{relation["path"]}",\n    operation_id="{relation["ops"]["add"]}",\n'
        "    response_model=SummaryDto,\n    status_code=201,\n    responses={400: ERROR, 404: ERROR, 409: ERROR},\n)\n"
        f"def add_{child_snake}(id: {relation['parentPkType']}, body: RelateDto, {user}session: SessionDep) -> "
        f"SummaryDto:\n"
        "    _parent(session, id)\n"
        f"    row = session.get({child}, body.{relation['rightAttr']})\n"
        "    if row is None:\n"
        "        raise BadRequestException(\n"
        f'            "{relation["child"]} not found", ErrorCode.REFERENCE_NOT_FOUND, details={{"fields": '
        f'["{field}"]}}\n'
        "        )\n"
        f"    session.add({link}({relation['leftAttr']}=id, {relation['rightAttr']}=body.{relation['rightAttr']}))\n"
        "    try:\n        session.commit()\n    except IntegrityError as exc:\n        session.rollback()\n"
        f'        raise ConflictException("Already related", ErrorCode.DUPLICATE, details={{"fields": '
        f'["{field}"]}}) from exc\n'
        "    return _summary(row)\n\n\n"
        f'@{relation["name"]}_router.delete(\n    "{relation["itemPath"]}",\n    '
        f'operation_id="{relation["ops"]["remove"]}",\n'
        "    status_code=204,\n    responses={404: ERROR},\n)\n"
        f"def remove_{child_snake}(id: {relation['parentPkType']}, child_id: ChildId, {user}session: "
        f"SessionDep) -> Response:\n"
        f"    found = session.get({link}, ({'id'}, child_id))\n"
        "    if found is None:\n"
        '        raise NotFoundException("Not related", details={"id": str(child_id)})\n'
        "    session.delete(found)\n    session.commit()\n"
        "    return Response(status_code=204)\n"
    )


def _tests(plan: dict[str, Any], relation: dict[str, Any]) -> str:
    """The relation's template tests; the records are seeded with the CRUD tests' own helpers."""
    from ..backend.codegen import _Tests

    module = next(m for m in plan["modules"] if m.get("entity") == relation["parent"] and not m.get("plugin"))
    seeder = _Tests(plan, {}, module)
    models = {m["entity"]: m for m in plan["models"] if m.get("entity")}
    parent_seed, child_seed = seeder.seed(models[relation["parent"]]), seeder.seed(models[relation["child"]])
    seeder.imports.add("sqlalchemy", "text")
    helpers = "\n\n".join(text for text in seeder.helpers.values() if text)
    signed_in = ""
    if relation["secured"]:
        seeder.imports.add("pytest").add("tests.auth", "sign_in")
        signed_in = (
            "@pytest.fixture(autouse=True)\ndef _signed_in(client):\n"
            '    client.headers["Authorization"] = f"Bearer {sign_in(client)}"\n    yield\n'
            '    client.headers.pop("Authorization", None)\n\n\n'
        )
    path = relation["path"].replace("{id}", "{parent.id}")
    field = relation["childField"]
    parent_table = models[relation["parent"]]["table"]
    link_table = next(m["table"] for m in plan["models"] if m.get("class") == relation["link"])
    return (
        '"""Generated by the Fullstack Generation Agent (Story 10.11, the relations plugin)."""\n\n'
        + seeder.imports.render()
        + "\nSEQUENCE = count(1)\n\n\n"
        + signed_in
        + helpers
        + "\n\n\ndef _links() -> int:\n"
        '    engine = create_engine(os.environ["DB_URL"])\n'
        "    with Session(engine) as session:\n"
        f'        count = session.connection().execute(text("SELECT count(*) FROM {link_table}")).scalar_one()\n'
        "    engine.dispose()\n    return count\n\n\n"
        f"def test_a_{to_snake(relation['child'])}_is_related_listed_and_unrelated(client):\n"
        f"    parent, child = {parent_seed}(), {child_seed}()\n\n"
        f'    added = client.post(f"{path}", json={{"{field}": str(child.{relation["childPk"]})}})\n'
        "    assert added.status_code == 201, added.text\n"
        f'    page = client.get(f"{path}").json()\n'
        f'    assert page["total"] == 1 and page["items"][0]["id"] == str(child.{relation["childPk"]})\n'
        f'    assert client.delete(f"{path}/{{child.{relation["childPk"]}}}").status_code == 204\n'
        f'    assert client.get(f"{path}").json()["total"] == 0\n'
        f'    assert client.delete(f"{path}/{{child.{relation["childPk"]}}}").status_code == 404\n\n\n'
        "def test_relating_twice_is_409_and_an_unknown_record_is_refused(client):\n"
        f"    parent, child = {parent_seed}(), {child_seed}()\n"
        f'    body = {{"{field}": str(child.{relation["childPk"]})}}\n'
        f'    assert client.post(f"{path}", json=body).status_code == 201\n\n'
        f'    again = client.post(f"{path}", json=body)\n\n'
        '    assert again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE"\n'
        f'    unknown = client.post(f"{path}", json={{"{field}": "00000000-0000-4000-8000-0000000000ff"}})\n'
        '    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "REFERENCE_NOT_FOUND"\n\n\n'
        "def test_deleting_the_parent_removes_its_links(client):\n"
        f"    parent, child = {parent_seed}(), {child_seed}()\n"
        f'    client.post(f"{path}", json={{"{field}": str(child.{relation["childPk"]})}})\n'
        "    assert _links() == 1\n\n"
        '    engine = create_engine(os.environ["DB_URL"])\n'
        "    with Session(engine) as session:\n"
        f'        session.connection().execute(text("DELETE FROM {parent_table} WHERE id = :id"), {{"id": '
        f"parent.id}})\n"
        "        session.commit()\n"
        "    engine.dispose()\n\n"
        "    assert _links() == 0  # ON DELETE CASCADE\n"
    )
