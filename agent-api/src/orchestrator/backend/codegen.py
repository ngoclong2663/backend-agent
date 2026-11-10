"""Backend CRUD from templates (Story 17.6). No LLM.

The architecture plan (`planner.py`) fixes every name, file, column, operation and test case of a fastapi-skills
backend; for the CRUD parts this module writes them directly, in the shape of the golden projects
(`src/engines/golden/two_entity`, `shop`):

    database   src/modules/shared/domain/entities/<entity>_entity.py (+ enums), .../models/<entity>_model.py,
               both packages' __init__.py and src/modules/__init__.py (models registered for Alembic)
    module     ports/output (interface + Dep re-export), infrastructure/persistence (repository + `I<Name>RepoDep`),
               one use case per operation (+ `Dep`), request / response / list DTOs, the router; src/routers.py
    tests      tests/modules/<module>/test_<entity>_api.py: one test per planned case; records are inserted with
               the ORM, so entities without a create endpoint are testable too

Output is a pure function of (spec, plan): byte-identical between runs. The sandbox's ruff normalizes it once
(`generate_database` / `generate_backend`), after which the files are recorded as generator-owned. What is not CRUD
(custom operations, business rules, auth and policies) is left to the engine: `codegen_gaps` says why per module.
"""

import json
import keyword
import re
from typing import Any

from src.modules.shared.domain.backend_spec.naming import py_name, to_snake

from ..integration.contract import _request_columns, _required, _writable
from ..plugins import plan_plugins
from ..plugins.base import CaseContext, Code, Import
from .pysource import Imports

ENTITIES_PKG = "src/modules/shared/domain/entities"
MODELS_PKG = "src/modules/shared/infrastructure/models"
# Story 10.0b: the `{id, label}` summaries a record shows its parents as, shared by every module
SUMMARIES_FILE = "src/modules/shared/presenter/summaries.py"
SUMMARIES_PKG = "src.modules.shared.presenter.summaries"
CRUD_ACTIONS = ("create", "get", "list", "update", "delete")
RESERVED = {"usecase", "q", "sort", "limit", "offset", "body", "id"}
FOREIGN_KEY_VIOLATION = "23503"
# Repositories define a `list` method: in their class body a later `list[...]` annotation (one the engine adds for a
# custom query) would name that method, so annotations there stay unevaluated.
FUTURE = "from __future__ import annotations\n\n"

# -- what the templates cover ------------------------------------------------------------------------------------------


def database_gaps(plan: dict[str, Any]) -> list[str]:
    """Why the models cannot be generated (empty: they can)."""
    gaps = []  # Story 10.11: one-to-one and many-to-many (their link models) are templated too
    for model in plan["models"]:
        for relation in model.get("relationships", []):
            if relation.get("type") not in ("one-to-many", "one-to-one", "many-to-many", None):
                gaps.append(f"{model['entity']}.{relation['attr']}: {relation.get('type')} relationships")
    return sorted(set(gaps))


def is_crud(op: dict[str, Any]) -> bool:
    return op.get("type") == "crud" and op.get("action") in CRUD_ACTIONS


def codegen_gaps(module: dict[str, Any]) -> list[str]:
    """What the engine still writes in a module (empty: the templates write all of it)."""
    if module.get("plugin"):  # Story 10.1: the plugin's own module
        return []
    gaps = []
    for op in module["operations"]:
        where = op["operationId"]
        if not is_crud(op) and op.get("type") != "aggregate":  # Epic 21: aggregates are templated too
            gaps.append(f"{where}: custom operation")
        if engine_rules(op):  # Story 10.4: the rules plugin writes the predefined kinds
            gaps.append(f"{where}: business rules")
    gaps += [f"job {name}: custom handler" for name in module.get("customJobs") or []]  # Story 10.6
    return gaps


def engine_rules(op: dict[str, Any]) -> list[str]:
    """The operation's rules the engine implements: those no plugin templated (custom rules; every rule without
    the rules plugin)."""
    done = {*(op.get("templatedRules") or []), *(op.get("skippedRules") or [])}  # skipped: ambiguous, not built
    return [rule for rule in op.get("rules") or [] if rule not in done]


# -- helpers -----------------------------------------------------------------------------------------------------------


def _py(value: Any) -> str:
    """A Python literal for a JSON value."""
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _member(value: str) -> str:
    name = re.sub(r"\W+", "_", str(value)).strip("_").upper() or "VALUE"
    if name[0].isdigit() or keyword.iskeyword(name.lower()):
        name = f"V_{name}"
    return name


def _type(column: dict[str, Any], imports: Imports, response: bool = False) -> str:
    kind = column["type"]
    if kind == "enum":
        return column["enum"]["class"]
    if kind == "uuid":
        imports.add("uuid")
        return "uuid.UUID"
    if kind == "decimal":
        if response:
            return "float"
        imports.add("decimal", "Decimal")
        return "Decimal"
    # Always module-qualified: a field named `date` / `datetime` in the same class would shadow a bare annotation
    # for every later field (`due_date: date | None` after `date: date` fails at import).
    if kind == "date":
        imports.add("datetime as dt")
        return "dt.date"
    if kind == "datetime":
        imports.add("datetime as dt")
        return "dt.datetime"
    if kind == "json":
        imports.add("typing", "Any")
        return "dict[str, Any]"
    return {"string": "str", "text": "str", "integer": "int", "float": "float", "boolean": "bool"}[kind]


def _default(column: dict[str, Any]) -> dict[str, Any]:
    return column.get("default") or {}


def _value(column: dict[str, Any], value: Any) -> str:
    if column["type"] == "enum":
        return f"{column['enum']['class']}.{_member(value)}"
    if column["type"] == "decimal":
        return f'Decimal("{value}")'
    return _py(value)


def _enums(model: dict[str, Any]) -> list[str]:
    return sorted({column["enum"]["class"] for column in model["columns"] if column["type"] == "enum"})


def _entity_by_name(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {model["entity"]: model for model in plan["models"]}


def _pk(model: dict[str, Any]) -> dict[str, Any]:
    return next(column for column in model["columns"] if column["primaryKey"])


def _snake(entity: str) -> str:
    return to_snake(entity)


def _label(model: dict[str, Any]) -> str:
    """`ContactMessage` → `contact message` (for messages)."""
    return _snake(model["entity"]).replace("_", " ")


# -- database ----------------------------------------------------------------------------------------------------------


def conflict_message(model: dict[str, Any]) -> str:
    """The message of a unique-field 409 (the repository's `ConflictException`, the contract's `x-bga.errors`)."""
    unique = [column["apiName"] for column in model["columns"] if column["unique"] and not column["primaryKey"]]
    if unique:
        return f"A {_label(model)} with this {' / '.join(unique)} already exists"
    return f"The {_label(model)} conflicts with an existing record"


def entity_file(model: dict[str, Any]) -> str:
    imports = Imports().add("pydantic", "BaseModel")
    body = []
    for name in _enums(model):
        imports.add("enum", "StrEnum")
        values = next(
            c["enum"]["values"] for c in model["columns"] if c["type"] == "enum" and c["enum"]["class"] == name
        )
        members = "".join(f"    {_member(value)} = {_py(value)}\n" for value in values)
        body.append(f"class {name}(StrEnum):\n{members}")
    fields = []
    for column in model["columns"]:
        annotation = _type(column, imports)
        default = _default(column)
        if column["primaryKey"] or "factory" in default or "autoincrement" in default:
            fields.append(f"    {column['attr']}: {annotation} | None = None")
        elif "value" in default:
            optional = " | None" if column["nullable"] else ""
            fields.append(f"    {column['attr']}: {annotation}{optional} = {_value(column, default['value'])}")
        elif column["nullable"]:
            fields.append(f"    {column['attr']}: {annotation} | None = None")
        else:
            fields.append(f"    {column['attr']}: {annotation}")
    body.append(f"class {model['entityClass']}(BaseModel):\n" + "\n".join(fields) + "\n")
    return imports.render() + "\n\n" + "\n\n".join(body)


def _model_field(column: dict[str, Any], model: dict[str, Any], imports: Imports, indexed: bool = False) -> str:
    annotation = _type(column, imports)
    default = _default(column)
    kwargs: list[str] = []
    nullable = column["nullable"] and not column["primaryKey"]
    if column["primaryKey"]:
        if column.get("foreignKey"):  # Story 10.11: a link model's keys are its two references
            pass
        elif column["type"] == "uuid":
            kwargs.append("default_factory=uuid.uuid4")
        elif "autoincrement" in default:
            kwargs.append("default=None")
            annotation += " | None"
        kwargs.append("primary_key=True")
    elif "factory" in default:
        imports.add("datetime as dt")
        factory = "dt.datetime.now(dt.UTC).date()" if column["type"] == "date" else "dt.datetime.now(dt.UTC)"
        kwargs.append(f"default_factory=lambda: {factory}")
    elif "value" in default:
        kwargs.append(f"default={_value(column, default['value'])}")
    elif nullable:
        kwargs.append("default=None")
    foreign = column.get("foreignKey")
    if foreign:
        kwargs.append(f'foreign_key="{foreign["references"]}"')
        kwargs.append(f'ondelete="{foreign["onDelete"]}"')
    if column["type"] == "string" and column.get("maxLength"):
        kwargs.append(f"max_length={column['maxLength']}")
    if column["unique"] and not column["primaryKey"]:
        kwargs.append("unique=True")
    if (column["index"] or foreign or indexed) and not column["primaryKey"] and not column["unique"]:
        kwargs.append("index=True")
    sa_type = {
        "text": "Text",
        "decimal": "Numeric(18, 4)",
        "datetime": "DateTime(timezone=True)",
        "json": "JSONB",
    }.get(column["type"])
    if column["type"] == "enum":
        enum = column["enum"]
        imports.add("sqlalchemy", "Enum as SAEnum")
        sa_type = f'SAEnum({enum["class"]}, name="{enum["dbName"]}", values_callable=lambda e: [m.value for m in e])'
    elif sa_type == "JSONB":
        imports.add("sqlalchemy.dialects.postgresql", "JSONB")
    elif sa_type:
        imports.add("sqlalchemy", sa_type.split("(")[0])
    if sa_type:
        kwargs.append(f"sa_type={sa_type}")
    if nullable:
        annotation += " | None"
    if kwargs == ["default=None"]:
        return f"    {column['attr']}: {annotation} = None"
    if not kwargs:
        return f"    {column['attr']}: {annotation}"
    line = f"    {column['attr']}: {annotation} = Field({', '.join(kwargs)})"
    if len(line) <= 120:
        return line
    inner = "".join(f"        {kwarg},\n" for kwarg in kwargs)
    return f"    {column['attr']}: {annotation} = Field(\n{inner}    )"


def _table_args(model: dict[str, Any], imports: Imports) -> tuple[set[str], str]:
    """The entity's own indexes and unique constraints: a one-column index is the field's `index=True` (named
    `ix_<table>_<column>`, as planned); the others go in `__table_args__`."""
    single = {i["columns"][0] for i in model.get("indexes", []) if len(i["columns"]) == 1 and not i["unique"]}
    args = []
    for index in model.get("indexes", []):
        if len(index["columns"]) == 1 and not index["unique"]:
            continue
        imports.add("sqlalchemy", "Index")
        columns = ", ".join(f'"{column}"' for column in index["columns"])
        args.append(f'Index("{index["name"]}", {columns}' + (", unique=True)" if index["unique"] else ")"))
    for group in model.get("uniqueConstraints", []):
        imports.add("sqlalchemy", "UniqueConstraint")
        columns = ", ".join(f'"{column}"' for column in group)
        args.append(f'UniqueConstraint({columns}, name="uq_{model["table"]}_{"_".join(group)}")')
    for extra in model.get("tableArgs", []):  # Story 10.10: a rule's constraint (exclusion, partial unique index)
        for module, names in extra["imports"]:
            imports.add(module, *names)
        args.append(extra["code"])
    if not args:
        return single, ""
    return single, "    __table_args__ = (\n" + "".join(f"        {arg},\n" for arg in args) + "    )\n"


def model_file(model: dict[str, Any], plan: dict[str, Any]) -> str:
    imports = Imports().add("sqlmodel", "Field", "SQLModel")
    single, table_args = _table_args(model, imports)
    fields = [_model_field(column, model, imports, column["attr"] in single) for column in model["columns"]]
    if _enums(model):
        imports.add("src.modules.shared.domain.entities", *_enums(model))
    relations = []
    referenced = []
    by_link = {m["class"]: m for m in plan["models"] if m.get("linkFor")}
    for relation in model.get("relationships", []):
        imports.add("sqlmodel", "Relationship")
        target = re.findall(r'"(\w+)"', relation["annotation"])[0]
        if target != model["class"]:  # a model never imports itself (a self-relationship)
            referenced.append(target)
        extra = ', passive_deletes="all"' if relation["annotation"].startswith("list[") else ""
        if relation.get("link"):  # Story 10.11: many-to-many through its link model (imported: SQLAlchemy needs it)
            link = by_link[relation["link"]]
            imports.add(f".{link['file'].rsplit('/', 1)[1].removesuffix('.py')}", relation["link"])
            extra = f", link_model={relation['link']}"
        else:
            kwargs = []
            if relation.get("uselist") is False:  # a one-to-one parent: one record, or none
                kwargs.append('"uselist": False')
            if relation.get("foreignKeys"):  # one of several keys to the same model: the one it follows
                kwargs.append(f'"foreign_keys": "[{relation["foreignKeys"]}]"')
            if relation.get("remoteSide"):  # a record's parent of its own kind: the parent's key is the remote side
                kwargs.append(f'"remote_side": "{relation["remoteSide"]}"')
            if kwargs:
                extra = (extra if relation["annotation"].startswith("list[") else "") + (
                    f", sa_relationship_kwargs={{{', '.join(kwargs)}}}"
                )

        relations.append(
            f"    {relation['attr']}: {relation['annotation']} = "
            f'Relationship(back_populates="{relation["backPopulates"]}"{extra})'
        )
    checking = ""
    if referenced:
        imports.add("typing", "TYPE_CHECKING")
        by_class = {m["class"]: m for m in plan["models"]}
        lines = "".join(
            f"    from .{by_class[name]['file'].rsplit('/', 1)[1].removesuffix('.py')} import {name}\n"
            for name in sorted(set(referenced))
        )
        checking = f"if TYPE_CHECKING:\n{lines}\n\n"
    body = "\n".join(fields) + ("\n\n" + "\n".join(relations) if relations else "")
    return (
        imports.render()
        + "\n"
        + checking
        + ("" if checking else "\n")
        + f'class {model["class"]}(SQLModel, table=True):\n    __tablename__ = "{model["table"]}"\n'
        + table_args
        + f"\n{body}\n"
    )


def _exports(names: list[str]) -> str:
    quoted = ", ".join(f'"{name}"' for name in names)
    line = f"__all__ = [{quoted}]\n"
    if len(line) <= 121:
        return line
    return "__all__ = [\n" + "".join(f'    "{name}",\n' for name in names) + "]\n"


def database_files(plan: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {}
    entity_exports: list[tuple[str, str]] = []
    model_exports: list[tuple[str, str]] = []
    for model in plan["models"]:
        files[model["file"]] = model_file(model, plan)
        if not model.get("entity"):  # Story 10.11: a link model has no domain entity
            model_exports.append((model["file"].rsplit("/", 1)[1].removesuffix(".py"), model["class"]))
            continue
        files[model["entityFile"]] = entity_file(model)
        entity_module = model["entityFile"].rsplit("/", 1)[1].removesuffix(".py")
        for name in [model["entityClass"], *_enums(model)]:
            entity_exports.append((entity_module, name))
        model_exports.append((model["file"].rsplit("/", 1)[1].removesuffix(".py"), model["class"]))
    files[f"{ENTITIES_PKG}/__init__.py"] = _package(entity_exports)
    files[f"{MODELS_PKG}/__init__.py"] = _package(model_exports)
    summaries = summaries_file(plan)
    if summaries:
        files["src/modules/shared/presenter/__init__.py"] = ""
        files[SUMMARIES_FILE] = summaries
    classes = sorted(name for _, name in model_exports)
    registry = Imports().add("src.modules.shared.infrastructure.models", *classes).render()
    # Story 10.6: a plugin's own tables (the job queue) are discovered the same way
    extra = "".join(f"import {module}  # noqa: F401\n" for module in plan.get("pluginModels") or [])
    files["src/modules/__init__.py"] = (
        '"""Imports every ORM model so Alembic autogenerate discovers it (fastapi-skills pillar 4)."""\n\n'
        + extra
        + registry
        + "\n"
        + _exports(classes)
    )
    return files


def summary_dto(entity: str) -> str:
    return f"{entity}SummaryDto"


def summaries_file(plan: dict[str, Any]) -> str:
    """Story 10.0b: one `{id, label}` DTO per referenced entity, and the `References` a repository returns."""
    by_entity = _entity_by_name(plan)
    parents = sorted(
        {ref["entity"] for model in plan["models"] for ref in [*(model.get("references") or []),
                                                                *(model.get("children") or [])]}
    )  # fmt: skip
    if not parents:
        return ""
    imports = Imports().add("typing", "Any").add("pydantic", "BaseModel", "ConfigDict")
    imports.add("pydantic.alias_generators", "to_camel")
    classes = []
    for entity in parents:
        pk = _type(_pk(by_entity[entity]), imports, response=True)
        classes.append(
            f"class {summary_dto(entity)}(BaseModel):\n"
            f'    """A {entity} as the records that refer to it show it."""\n\n'
            "    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)\n\n"
            f"    id: {pk}\n    label: str | None\n"
        )
    return (
        '"""Summaries of referenced records (Story 10.0b): `{id, label}`, so a client shows a name, never an id."""\n\n'
        + imports.render()
        + "\n# Labels of referenced records by reference name and id, as a repository's `references()` returns them\n"
        "References = dict[str, dict[Any, Any]]  # a label, or a one-to-one child's {id, label} (Story 10.11)\n\n\n"
        + "\n\n".join(classes)
    )


def _package(exports: list[tuple[str, str]]) -> str:
    by_module: dict[str, list[str]] = {}
    for module, name in exports:
        by_module.setdefault(module, []).append(name)
    lines = []
    for module in sorted(by_module):
        names = sorted(by_module[module], key=lambda name: name.lower())
        line = f"from .{module} import {', '.join(names)}"
        lines.append(
            line if len(line) <= 120 else f"from .{module} import (\n" + "".join(f"    {n},\n" for n in names) + ")"
        )
    return "\n".join(lines) + "\n\n" + _exports(sorted(name for _, name in exports))


# -- modules -----------------------------------------------------------------------------------------------------------


class _Module:
    def __init__(self, plan: dict[str, Any], spec: dict[str, Any], module: dict[str, Any]):
        self.plan = plan
        self.module = module
        self.model = _entity_by_name(plan)[module["entity"]]
        self.name = module["name"]
        self.entity = module["entity"]
        self.snake = _snake(self.entity)
        self.var = py_name(self.snake)  # the entity as a variable (`class_` for `Class`)
        self.entity_class = module["entityClass"]
        self.repo_var = f"{self.snake}_repo"
        self.pk = _pk(self.model)
        self.pkg = f"src.modules.{self.name}"
        self.dir = f"src/modules/{self.name}"
        self.spec_ops = {op["operationId"]: op for op in spec.get("operations", [])}
        self.ops = {op["action"]: op for op in module["operations"] if is_crud(op)}
        # A module may list its records more than once (`GET /tasks`, `GET /projects/{projectId}/tasks`).
        self.lists = [op for op in module["operations"] if is_crud(op) and op["action"] == "list"]
        self.crud_ops = [op for op in self.ops.values() if op["action"] != "list"] + self.lists
        # Epic 21: aggregate operations, by their handler (also their repository method)
        self.aggregates = {op["handler"]: op for op in module["operations"] if op.get("type") == "aggregate"}
        self.has_fk = any(column.get("foreignKey") for column in self.model["columns"])
        # Story 10.1: the plugins' hook contributions (none: the code is exactly what it is without plugins)
        self.plugins = plan_plugins(plan)
        # Story 10.0b: parents shown as summaries, when the repository loads their labels
        self.references = (self.model.get("references") or []) if "references" in module["port"]["methods"] else []
        # Story 10.11: one-to-one children, shown as summaries in this record's response
        self.children = (self.model.get("children") or []) if "references" in module["port"]["methods"] else []
        # Epic 33: fields a feature computes per record (a count, the caller's own row), filled with the references
        self.computed = (self.model.get("computed") or []) if "references" in module["port"]["methods"] else []
        self.shows = bool(self.references or self.children or self.computed)
        self.unique = [column for column in self.model["columns"] if column["unique"] and not column["primaryKey"]]
        # Story 10.3: columns the server fills from the signed-in user on create (`x-bga.source: currentUser`)
        self.from_user = [column for column in self.model["columns"] if column.get("source") == "currentUser"]

    @property
    def pk_type(self) -> str:
        return _type(self.pk, Imports())

    def _pk_imports(self, imports: Imports) -> str:
        return _type(self.pk, imports)

    def request_columns(self, op: dict[str, Any]) -> list[dict[str, Any]]:
        return _request_columns(self.model, self.spec_ops.get(op["operationId"], {}))

    def search(self) -> list[dict[str, Any]]:
        """The repository's search fields: those of every list of the module."""
        fields = {item["attr"]: item for op in self.lists for item in op.get("search") or []}
        return list(fields.values())

    # -- ports & repository ------------------------------------------------------------------------------------

    def port(self) -> str:
        imports = Imports().add("abc", "ABC", "abstractmethod").add(ENTITIES_PKG.replace("/", "."), self.entity_class)
        pk = self._pk_imports(imports) if {"find_by_id", "delete"} & set(self.module["port"]["methods"]) else ""
        entity = self.entity_class
        methods = []
        for method in self.module["port"]["methods"]:
            if method == "create":
                methods.append(f"    def create(self, {self.var}: {entity}) -> {entity}:\n        pass")
            elif method == "find_by_id":
                methods.append(f"    def find_by_id(self, {self.snake}_id: {pk}) -> {entity} | None:\n        pass")
            elif method == "list":
                imports.add("typing", "Any")
                q = "q: str | None, " if self.search() else ""
                scoped = self._scope_params(imports)
                methods.append(
                    "    def list(\n"
                    + self._list_params_line(f"{q}sort: tuple[str, bool] | None, limit: int, offset: int{scoped}")
                    + f"    ) -> tuple[list[{entity}], int]:\n"
                    '        """One page and the total count; `filters` are equality matches on entity attributes."""'
                )
            elif method == "update":
                methods.append(f"    def update(self, {self.var}: {entity}) -> {entity}:\n        pass")
            elif method == "delete":
                methods.append(f"    def delete(self, {self.snake}_id: {pk}) -> None:\n        pass")
            elif method == "references":
                imports.add(SUMMARIES_PKG, "References")
                viewer = ", viewer: Any = None" if self.computed else ""
                if self.computed:
                    imports.add("typing", "Any")
                methods.append(
                    f"    def references(self, records: list[{entity}]{viewer}) -> References:\n"
                    '        """Labels of the records these refer to, one query per reference (Story 10.0b)."""'
                )
            elif method in self.aggregates:
                methods.append(
                    f"    def {method}(self) -> {self._aggregate_returns(self.aggregates[method])}:\n        pass"
                )
        for extra in self._repository_methods():  # Story 10.4: what a plugin's pre-checks ask the repository
            self._imports(imports, extra.port_imports)
            methods.append(f"    def {extra.signature}:\n        pass")
        body = "\n\n".join(f"    @abstractmethod\n{method}" for method in methods)
        return FUTURE + imports.render() + f"\n\nclass {self.module['port']['interface']}(ABC):\n{body}\n"

    def repository(self) -> str:
        port = self.module["port"]
        model = self.module["model"]
        entity = self.entity_class
        imports = (
            Imports()
            .add("typing", "Annotated")
            .add("fastapi", "Depends")
            .add("src.libs.database.session", "SessionDep")
            .add(ENTITIES_PKG.replace("/", "."), entity)
            .add(MODELS_PKG.replace("/", "."), model)
            .add(f"{self.pkg}.ports.output.{port['file'].rsplit('/', 1)[1].removesuffix('.py')}", port["interface"])
        )
        pk = self._pk_imports(imports) if {"find_by_id", "delete"} & set(port["methods"]) else ""
        methods = []
        writes = {"create", "update", "delete"} & set(port["methods"])
        if "create" in port["methods"]:
            methods.append(
                f"    def create(self, {self.var}: {entity}) -> {entity}:\n"
                f"        model = self.__to_model({self.var})\n"
                "        self.session.add(model)\n"
                "        self.__flush()\n"
                "        return self.__to_entity(model)"
            )
        if "find_by_id" in port["methods"]:
            methods.append(
                f"    def find_by_id(self, {self.snake}_id: {pk}) -> {entity} | None:\n"
                f"        model = self.session.get({model}, {self.snake}_id)\n"
                "        return self.__to_entity(model) if model else None"
            )
        if "list" in port["methods"]:
            imports.add("typing", "Any").add("sqlmodel", "col", "func", "select")
            search = self.search()
            q_param = "q: str | None, " if search else ""
            q_block = ""
            if search:
                imports.add("sqlmodel", "or_")
                matches = "".join(
                    f"                    col({model}.{item['attr']}).ilike(pattern),\n" for item in search
                )
                q_block = (
                    "        if q:\n"
                    '            pattern = f"%{q}%"\n'
                    "            query = query.where(\n                or_(\n"
                    f"{matches}                )\n            )\n"
                )
            scope = "".join(
                f"        if {item.param} is not None:\n"
                f"            query = query.where({item.condition.format(model=model)})\n"
                for item in self._repository_filters()
            )
            params = f"{q_param}sort: tuple[str, bool] | None, limit: int, offset: int{self._scope_params(imports)}"
            methods.append(
                "    def list(\n" + self._list_params_line(params) + f"    ) -> tuple[list[{entity}], int]:\n"
                f"        query = select({model})\n"
                + (
                    self._bounded_filters(model)
                    if self._ranged()
                    else "        for attribute, value in filters.items():\n"
                    f"            query = query.where(col(getattr({model}, attribute)) == value)\n"
                )
                + scope
                + q_block
                + "        total = self.session.exec(select(func.count()).select_from(query.subquery())).one()\n"
                "        if sort:\n"
                f"            column = col(getattr({model}, sort[0]))\n"
                "            query = query.order_by(\n"
                "                column.desc().nulls_last() if sort[1] else column.asc().nulls_last()\n"
                "            )\n"
                f"        query = query.order_by(col({model}.{self.pk['attr']}))\n"
                "        models = self.session.exec(query.offset(offset).limit(limit)).all()\n"
                "        return [self.__to_entity(model) for model in models], total"
            )
        if "update" in port["methods"]:
            methods.append(
                f"    def update(self, {self.var}: {entity}) -> {entity}:\n"
                f"        model = self.session.get({model}, {self.var}.{self.pk['attr']})\n"
                f'        for key, value in {self.var}.model_dump(exclude={{"{self.pk["attr"]}"}}).items():\n'
                "            setattr(model, key, value)\n"
                "        self.__flush()\n"
                "        return self.__to_entity(model)"
            )
        if "delete" in port["methods"]:
            methods.append(
                f"    def delete(self, {self.snake}_id: {pk}) -> None:\n"
                f"        model = self.session.get({model}, {self.snake}_id)\n"
                "        if model is not None:\n"
                "            self.session.delete(model)\n"
                "            self.__flush(deleting=True)"
            )
        if "references" in port["methods"]:
            methods.append(self._references_method(imports))
        for method in port["methods"]:  # Epic 21: aggregate queries
            if method in self.aggregates:
                methods.append(self._aggregate_repository_method(self.aggregates[method], imports))
        for extra in self._repository_methods():  # Story 10.4
            self._imports(imports, (*extra.port_imports, *extra.imports))
            methods.append(
                f"    def {extra.signature}:\n" + "".join(f"        {line}\n" for line in extra.body).rstrip("\n")
            )
        if writes:
            imports.add("sqlalchemy.exc", "IntegrityError").add("src.libs.exceptions", "ConflictException")
            label = _label(self.model)
            conflict = f'"{conflict_message(self.model)}"'
            if self.unique:  # Story 10.0b: the fields a client marks
                names = ", ".join(f'"{column["apiName"]}"' for column in self.unique)
                conflict += f', details={{"fields": [{names}]}}'
            fk_branch = ""
            if self.has_fk or "delete" in port["methods"]:
                imports.add("src.libs.exceptions", "BadRequestException", "ErrorCode")
                fks = ", ".join(  # what a client sent (an owner comes from the signed-in user, 10.3)
                    f'"{c["apiName"]}"' for c in self.model["columns"] if c.get("foreignKey") and _writable(c)
                )
                fk_details = f', details={{"fields": [{fks}]}}' if fks else ""
                missing = (
                    "                raise BadRequestException(\n"
                    '                    "A referenced record does not exist",\n'
                    f"                    ErrorCode.REFERENCE_NOT_FOUND{fk_details},\n"
                    "                ) from exc\n"
                )
                fk_branch = (
                    '            if getattr(exc.orig, "pgcode", None) == FOREIGN_KEY_VIOLATION:\n'
                    "                if deleting:\n"
                    "                    raise ConflictException(\n"
                    f'                        "The {label} is still referenced by other records"\n'
                    "                    ) from exc\n" + missing
                )
            named = ""
            if self.model.get("constraintErrors"):  # Story 10.10: a rule's constraint answers its own code
                imports.add("src.libs.exceptions", "ErrorCode")
                named = (
                    '            diag = getattr(exc.orig, "diag", None)\n'
                    '            rule = CONSTRAINT_ERRORS.get(getattr(diag, "constraint_name", None) or "")\n'
                    "            if rule is not None:\n"
                    '                details = {"fields": rule["fields"]}\n'
                    '                raise ConflictException(rule["message"], rule["code"], details=details) from exc\n'
                )
            methods.append(
                "    def __flush(self, deleting: bool = False) -> None:\n"
                "        try:\n"
                "            self.session.flush()\n"
                "        except IntegrityError as exc:\n"
                + named
                + fk_branch
                + (
                    f"            raise ConflictException({conflict}) from exc"
                    if len(f"            raise ConflictException({conflict}) from exc") <= 120
                    else f"            raise ConflictException(\n                {conflict}\n            ) from exc"
                )
            )
        methods.append(
            f"    def __to_entity(self, model: {model}) -> {entity}:\n"
            f"        return {entity}.model_validate(model.model_dump())"
        )
        if "create" in port["methods"]:
            methods.append(
                f"    def __to_model(self, entity: {entity}) -> {model}:\n"
                f"        return {model}(**entity.model_dump(exclude_none=True))"
            )
        constant = (
            f'\nFOREIGN_KEY_VIOLATION = "{FOREIGN_KEY_VIOLATION}"\n'
            if "== FOREIGN_KEY_VIOLATION" in "".join(methods)
            else ""
        )
        if writes and self.model.get("constraintErrors"):  # read by __flush only: a read-only module has none
            entries = "".join(
                f'    "{name}": {{"code": ErrorCode.{rule["code"]}, "message": {json.dumps(rule["message"])}, '
                f'"fields": {json.dumps(rule["fields"])}}},\n'
                for name, rule in self.model["constraintErrors"].items()
            )
            constant += (
                "# Story 10.10: the rules' constraints, by name\n"
                f"CONSTRAINT_ERRORS: dict[str, dict[str, Any]] = {{\n{entries}}}\n"
            )
            imports.add("typing", "Any")
        return (
            FUTURE + imports.render() + constant + f"\n\nclass {port['implementation']}({port['interface']}):\n"
            "    def __init__(self, session: SessionDep):\n"
            "        self.session = session\n\n"
            + "\n\n".join(methods)
            + f"\n\n\n{port['dep']} = Annotated[{port['interface']}, Depends({port['implementation']})]\n"
        )

    def _references_method(self, imports: Imports) -> str:
        """Story 10.0b: one `IN` query per reference for a page of records; labels as strings."""
        imports.add(SUMMARIES_PKG, "References").add("sqlmodel", "col", "select")
        viewer = ", viewer: Any = None" if self.computed else ""
        if self.computed:
            imports.add("typing", "Any")
        lines = [
            f"    def references(self, records: list[{self.entity_class}]{viewer}) -> References:",
            "        found: References = {}",
        ]
        for reference in self.references:
            parent = reference["model"]
            imports.add(MODELS_PKG.replace("/", "."), parent)
            ids = f"{reference['attr']}_ids"
            pk, label = f"{parent}.{reference['primaryKey']}", f"{parent}.{reference['labelAttr']}"
            lines += [
                f"        {ids} = {{record.{reference['column']} for record in records"
                f" if record.{reference['column']} is not None}}",
                f'        found["{reference["attr"]}"] = {{}}',
                f"        if {ids}:",
                f"            query = select(col({pk}), col({label})).where(col({pk}).in_({ids}))",
                f'            found["{reference["attr"]}"] = {{',
                "                key: None if label is None else str(label)"
                " for key, label in self.session.exec(query).all()",
                "            }",
            ]
        if self.children or self.computed:
            lines.append(f"        own_ids = {{record.{self.pk['attr']} for record in records}}")
        for child in self.children:
            model = child["model"]
            imports.add(MODELS_PKG.replace("/", "."), model)
            fk, pk, label = (
                f"{model}.{child['column']}",
                f"{model}.{child['primaryKey']}",
                f"{model}.{child['labelAttr']}",
            )
            lines += [
                f'        found["{child["attr"]}"] = {{}}',
                "        if own_ids:",
                f"            query = select(col({fk}), col({pk}), col({label})).where(col({fk}).in_(own_ids))",
                f'            found["{child["attr"]}"] = {{',
                '                key: {"id": child_id, "label": None if label is None else str(label)}',
                "                for key, child_id, label in self.session.exec(query).all()",
                "            }",
            ]
        lines += self._computed_lines(imports)
        lines.append("        return found")
        return "\n".join(lines)

    def _computed_lines(self, imports: Imports) -> list[str]:
        """Epic 33: a feature's computed fields for a page of records: one grouped count, or the caller's own row."""
        lines: list[str] = []
        for item in self.computed:
            model = item["model"]
            imports.add(MODELS_PKG.replace("/", "."), model)
            key = f"col({model}.{item['key']})"
            ids = "own_ids"
            if item.get("match"):  # rows pointing at one of the record's fields (its creator, its section), as text
                ids = f"{item['attr']}_keys"
                lines.append(
                    f"        {ids} = {{str(record.{item['match']}) for record in records"
                    f" if record.{item['match']} is not None}}"
                )
            where = [f"{key}.in_({ids})"] + [
                f"col({model}.{attr}) == {value!r}" for attr, value in item["where"].items()
            ]
            mine = item["kind"] == "mine" or bool(item.get("owner"))
            if item.get("owner"):
                where.append(f"col({model}.{item['owner']}) == viewer")
            guard = f"        if {ids} and viewer is not None:" if mine else f"        if {ids}:"
            if item["kind"] == "count":
                imports.add("sqlmodel", "func")
                query = f"select({key}, func.count()).where({', '.join(where)}).group_by({key})"
            else:
                query = f"select({key}, col({model}.id)).where({', '.join(where)})"
            text = "str(key)" if item.get("match") else "key"
            lines += [
                f'        found["{item["attr"]}"] = {{}}',
                guard,
                f"            query = {query}",
                f'            found["{item["attr"]}"] = '
                f"{{{text}: value for key, value in self.session.exec(query).all()}}",
            ]
        return lines

    # -- aggregates (Epic 21) ------------------------------------------------------------------------------------

    @staticmethod
    def _grouped(op: dict[str, Any]) -> bool:
        return bool(op["aggregate"].get("groupAttr"))

    def _aggregate_returns(self, op: dict[str, Any]) -> str:
        return "list[tuple[str, float]]" if self._grouped(op) else "float"

    def _aggregate_repository_method(self, op: dict[str, Any], imports: Imports) -> str:
        """`select(func.sum(Model.amount))` with the aggregate's period and filters; grouped: `(key, value)` rows."""
        model = self.module["model"]
        agg = op["aggregate"]
        imports.add("sqlmodel", "col", "func", "select")
        measure = "func.count()" if agg["fn"] == "count" else f"func.{agg['fn']}(col({model}.{agg['attr']}))"
        if agg["fn"] != "count":
            measure = f"func.coalesce({measure}, 0)"
        lines = []
        if self._grouped(op):
            group = f"col({model}.{agg['groupAttr']})"
            lines.append(f"        query = select({group}, {measure}).group_by({group})")
        else:
            lines.append(f"        query = select({measure}).select_from({model})")
        for attr, value in sorted(agg.get("filters", {}).items()):
            lines.append(f"        query = query.where(col({model}.{attr}) == {_value({'type': 'string'}, value)})")
        if agg.get("period") and agg.get("dateAttr"):
            imports.add("datetime as dt")
            start = {
                "day": "now.replace(hour=0, minute=0, second=0, microsecond=0)",
                "week": "now - dt.timedelta(days=7)",
                "month": "now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)",
                "year": "now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)",
            }[agg["period"]]
            lines.append("        now = dt.datetime.now(dt.UTC)")
            lines.append(f"        query = query.where(col({model}.{agg['dateAttr']}) >= {start})")
        if self._grouped(op):
            lines.append("        rows = self.session.exec(query).all()")
            lines.append("        return [(str(key), float(value or 0)) for key, value in rows]")
        else:
            lines.append("        return float(self.session.exec(query).one() or 0)")
        return f"    def {op['handler']}(self) -> {self._aggregate_returns(op)}:\n" + "\n".join(lines)

    def _aggregate_dto(self, op: dict[str, Any]) -> str:
        fields = "    key: str\n    value: float\n" if self._grouped(op) else "    value: float\n"
        return (
            "from pydantic import BaseModel\n\n\n"
            f"class {op['responseDto']}(BaseModel):\n"
            f'    """{op.get("summary") or op["operationId"]} (Epic 21 aggregate)."""\n\n' + fields
        )

    def _aggregate_usecase(self, op: dict[str, Any]) -> str:
        imports = Imports().add(f"{self.pkg}.presenter.dtos", op["responseDto"])
        repo = f"self.{self.repo_var}"
        if self._grouped(op):
            body = (
                f"        rows = {repo}.{op['handler']}()\n"
                f"        return [{op['responseDto']}(key=key, value=value) for key, value in rows]"
            )
            return self._usecase(op, imports, "", body, f"list[{op['responseDto']}]")
        body = f"        return {op['responseDto']}(value={repo}.{op['handler']}())"
        return self._usecase(op, imports, "", body, op["responseDto"])

    # -- DTOs --------------------------------------------------------------------------------------------------

    def _constraints(self, column: dict[str, Any], required: bool) -> list[str]:
        kwargs = []
        if column["type"] in ("string", "text") and required:
            kwargs.append("min_length=1")
        if column["type"] in ("string", "text") and column.get("maxLength"):
            kwargs.append(f"max_length={column['maxLength']}")
        if column["type"] in ("integer", "float", "decimal"):
            if column.get("min") is not None:
                kwargs.append(f"ge={column['min']}")
            if column.get("max") is not None:
                kwargs.append(f"le={column['max']}")
        return kwargs

    def _dto_imports(self, columns: list[dict[str, Any]], imports: Imports) -> None:
        enums = sorted({c["enum"]["class"] for c in columns if c["type"] == "enum"})
        if enums:
            imports.add(ENTITIES_PKG.replace("/", "."), *enums)

    def create_dto(self) -> str:
        op = self.ops["create"]
        columns = self.request_columns(op)
        imports = Imports().add("pydantic", "BaseModel", "ConfigDict").add("pydantic.alias_generators", "to_camel")
        imports.add(ENTITIES_PKG.replace("/", "."), self.entity_class)
        self._dto_imports(columns, imports)
        fields = []
        for column in columns:
            annotation = _type(column, imports)
            required = _required(column)
            kwargs = self._constraints(column, required)
            default = _default(column).get("value")
            if not required:
                annotation += " | None" if column["nullable"] or default is None else ""
                kwargs.insert(0, f"default={_value(column, default) if default is not None else 'None'}")
            if kwargs and kwargs != ["default=None"]:
                imports.add("pydantic", "Field")
                fields.append(f"    {column['attr']}: {annotation} = Field({', '.join(kwargs)})")
            elif kwargs:
                fields.append(f"    {column['attr']}: {annotation} = None")
            else:
                fields.append(f"    {column['attr']}: {annotation}")
        params, values = "", ""
        for column in self.from_user:  # Story 10.3: accepted and ignored; the use case passes the signed-in user's
            imports.add("pydantic", "Field")
            annotation = _type(column, imports)
            fields.append(
                f"    {column['attr']}: {annotation} | None = Field(default=None, exclude=True)  # the signed-in user"
            )
            params += f", {column['attr']}: {annotation}"
            values += f", {column['attr']}={column['attr']}"
        return (
            imports.render() + f"\n\nclass {op['requestDto']}(BaseModel):\n"
            '    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")\n\n'
            + "\n".join(fields)
            + f"\n\n    def to_entity(self{params}) -> {self.entity_class}:\n"
            f"        return {self.entity_class}(**self.model_dump(){values})\n"
        )

    def update_dto(self) -> str:
        op = self.ops["update"]
        columns = self.request_columns(op)
        imports = Imports().add("pydantic", "BaseModel", "ConfigDict").add("pydantic.alias_generators", "to_camel")
        imports.add(ENTITIES_PKG.replace("/", "."), self.entity_class)
        self._dto_imports(columns, imports)
        fields = []
        for column in columns:
            annotation = _type(column, imports) + " | None"
            kwargs = self._constraints(column, _required(column))
            if kwargs:
                imports.add("pydantic", "Field")
                fields.append(f"    {column['attr']}: {annotation} = Field(default=None, {', '.join(kwargs)})")
            else:
                fields.append(f"    {column['attr']}: {annotation} = None")
        return (
            imports.render() + f"\n\nclass {op['requestDto']}(BaseModel):\n"
            '    """PATCH body: only the fields that are sent change."""\n\n'
            '    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")\n\n'
            + "\n".join(fields)
            + f"\n\n    def to_entity(self, current: {self.entity_class}) -> {self.entity_class}:\n"
            "        return current.model_copy(update=self.model_dump(exclude_unset=True))\n"
        )

    @property
    def response_dto(self) -> str:
        return f"{self.entity}ResponseDto"

    @property
    def response_file(self) -> str:
        return f"{self.snake}_response_dto"

    def response_dto_file(self) -> str:
        imports = Imports().add("pydantic", "BaseModel", "ConfigDict").add("pydantic.alias_generators", "to_camel")
        imports.add(ENTITIES_PKG.replace("/", "."), self.entity_class)
        self._dto_imports(self.model["columns"], imports)
        fields = []
        entries = ["**entity.model_dump()"]
        for column in self.model["columns"]:
            if column.get("secret"):  # Story 10.2: a password hash never leaves the backend
                continue
            annotation = _type(column, imports, response=True)
            if column["type"] == "decimal":
                attr = column["attr"]
                entries.append(
                    f'"{attr}": float(entity.{attr})'
                    if not column["nullable"]
                    else f'"{attr}": None if entity.{attr} is None else float(entity.{attr})'
                )
            fields.append(f"    {column['attr']}: {annotation}{' | None' if column['nullable'] else ''}")
        # Story 10.0b: parents as `{id, label}` summaries, and what can be done to the record
        for reference in self.references:
            imports.add(SUMMARIES_PKG, summary_dto(reference["entity"]))
            annotation = f"{summary_dto(reference['entity'])} | None"
            if reference["attr"] != to_snake(reference["apiName"]):  # a Python keyword (`class_`): keep the API name
                imports.add("pydantic", "Field")
                annotation += f' = Field(alias="{reference["apiName"]}")'
            fields.append(f"    {reference['attr']}: {annotation}")
            fk = f"entity.{reference['column']}"
            summary = f'{{"id": {fk}, "label": refs.get("{reference["attr"]}", {{}}).get({fk})}}'
            if reference["nullable"]:
                summary = f"None if {fk} is None else {summary}"
            entries.append(f'"{reference["attr"]}": {summary}')
        for child in self.children:  # Story 10.11: a one-to-one child as a summary, or None
            imports.add(SUMMARIES_PKG, summary_dto(child["entity"]))
            fields.append(f"    {child['attr']}: {summary_dto(child['entity'])} | None")
            entries.append(f'"{child["attr"]}": refs.get("{child["attr"]}", {{}}).get(entity.{self.pk["attr"]})')
        for item in self.computed:  # Epic 33: what a feature computes per record
            pk = f"str(entity.{item['match']})" if item.get("match") else f"entity.{self.pk['attr']}"
            if item["kind"] == "count":
                fields.append(f"    {item['attr']}: int")  # always sent: required, as the contract has it
                entries.append(f'"{item["attr"]}": refs.get("{item["attr"]}", {{}}).get({pk}, 0)')
            else:
                fields.append(f"    {item['attr']}: {_type({'type': item['pkType']}, imports)} | None")
                entries.append(f'"{item["attr"]}": refs.get("{item["attr"]}", {{}}).get({pk})')
        for item in self._response_fields():  # Story 10.1: what plugins add to a record
            self._imports(imports, item.imports)
            fields.append(f"    {item.attr}: {item.annotation}")
            entries.append(f'"{item.attr}": {item.value}')
        fields.append("    allowed_actions: list[str]")
        checks = self._action_checks()
        signature = f"cls, entity: {self.entity_class}"
        refs = ""
        if self.shows:
            imports.add(SUMMARIES_PKG, "References")
            signature += ", references: References | None = None"
            refs = "        refs = references or {}\n"
        narrowing = ""
        if checks:  # Story 10.3: what this caller may do to the record; 10.4: what its state allows
            conditions: dict[str, list[str]] = {}
            for check in checks:
                self._imports(imports, check.imports)
                conditions.setdefault(check.action, []).append(check.condition)
            user = next((check.user_annotation for check in checks if check.user_annotation), None)
            lines = ""
            for action, parts in conditions.items():
                parts = [f"({part})" if " or " in part and len(parts) > 1 else part for part in parts]
                joined = " and ".join(parts)
                line = f'        "{action}": {joined},\n'
                if len(line) > 121:
                    joined = "\n            and ".join(parts)
                    line = f'        "{action}": (\n            {joined}\n        ),\n'
                lines += line
            if user:
                signature += f", user: {user} | None = None"
                entries.append('"allowed_actions": allowed_actions(entity, user)')
                head = f"def allowed_actions(entity: {self.entity_class}, user: {user} | None) -> list[str]:\n"
                doc = (
                    '    """The actions the operations\' policies let `user` take on the record (None: a visitor)."""\n'
                )
            else:
                entries.append('"allowed_actions": allowed_actions(entity)')
                head = f"def allowed_actions(entity: {self.entity_class}) -> list[str]:\n"
                doc = '    """What the rules let anyone do to the record in its state."""\n'
            narrowing = (
                f"\n\n{head}{doc}"
                f"    checks = {{\n{lines}    }}\n"
                "    return [action for action in ALLOWED_ACTIONS if checks.get(action, True)]\n"
            )
        else:
            entries.append('"allowed_actions": list(ALLOWED_ACTIONS)')
        value = "{" + ", ".join(entries) + "}"
        line = f"        return cls.model_validate({value})"
        if len(line) > 120:
            line = (
                "        return cls.model_validate(\n            {\n"
                + "".join(f"                {entry},\n" for entry in entries)
                + "            }\n        )"
            )
        actions = ", ".join(f'"{action}"' for action in self.module.get("recordActions") or [])
        actions = f"({actions},)" if len(self.module.get("recordActions") or []) == 1 else f"({actions})"
        header = f'    def from_entity({signature}) -> "{self.response_dto}":'
        if len(header) > 120:
            header = f'    def from_entity(\n        {signature}\n    ) -> "{self.response_dto}":'
        return (
            imports.render() + "\n# What can be done to a record (Story 10.0b); plugins narrow it by user and state\n"
            f"ALLOWED_ACTIONS: tuple[str, ...] = {actions}\n"
            + narrowing
            + f"\n\nclass {self.response_dto}(BaseModel):\n"
            "    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)\n\n"
            + "\n".join(fields)
            + "\n\n    @classmethod\n"
            f"{header}\n{refs}{line}\n"
        )

    def list_dto(self, op: dict[str, Any]) -> str:
        return (
            "from pydantic import BaseModel, ConfigDict\nfrom pydantic.alias_generators import to_camel\n\n"
            f"from .{self.response_file} import {self.response_dto}\n\n\n"
            f"class {op['responseDto']}(BaseModel):\n"
            "    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)\n\n"
            f"    items: list[{self.response_dto}]\n    total: int\n    limit: int\n    offset: int\n"
        )

    def dto_files(self) -> dict[str, str]:
        files: dict[str, str] = {}
        exports: list[tuple[str, str]] = []
        base = f"{self.dir}/presenter/dtos"
        if {"create", "get", "list", "update"} & set(self.ops):
            files[f"{base}/{self.response_file}.py"] = self.response_dto_file()
            exports.append((self.response_file, self.response_dto))
        for action, builder in (("create", self.create_dto), ("update", self.update_dto)):
            op = self.ops.get(action)
            if op is None:
                continue
            name = op["dtoFile"].removesuffix(".py")
            files[f"{base}/{name}.py"] = builder()
            exports.append((name, op["requestDto"]))
        for op in self.lists:
            name = op["dtoFile"].removesuffix(".py")
            files[f"{base}/{name}.py"] = self.list_dto(op)
            exports.append((name, op["responseDto"]))
        for op in self.aggregates.values():  # Epic 21
            name = op["dtoFile"].removesuffix(".py")
            files[f"{base}/{name}.py"] = self._aggregate_dto(op)
            exports.append((name, op["responseDto"]))
        files[f"{base}/__init__.py"] = _package(exports)
        return files

    # -- use cases -----------------------------------------------------------------------------------------------

    def _usecase(self, op: dict[str, Any], imports: Imports, signature: str, body: str, returns: str) -> str:
        repo = self.module["port"]["dep"]
        imports.add("typing", "Annotated").add("fastapi", "Depends").add(f"{self.pkg}.ports.output", repo)
        decorator = ""
        if op["transactional"]:
            imports.add("src.libs.decorators.transactional_decorator", "Transactional")
            decorator = "    @Transactional\n"
        logger = ""
        if "logger." in body:
            imports.add("src.configs", "get_logger")
            logger = "\nlogger = get_logger(__name__)\n"
        return (
            imports.render() + logger + f"\n\nclass {op['usecase']}:\n"
            f"    def __init__(self, {self.repo_var}: {repo}):\n"
            f"        self.{self.repo_var} = {self.repo_var}\n\n"
            f"{decorator}    async def execute(self{signature}) -> {returns}:\n{body}\n\n\n"
            f"{op['usecaseDep']} = Annotated[{op['usecase']}, Depends({op['usecase']})]\n"
        )

    # -- plugin hooks (Story 10.1) --------------------------------------------------------------------------------

    @staticmethod
    def _imports(imports: Imports, wanted: tuple[Import, ...]) -> None:
        for module, names in wanted:
            imports.add(module, *names)

    def _router_params(self, op: dict[str, Any]) -> list[Any]:
        """Each plugin's route parameters; a later plugin's parameter replaces an earlier one of the same name."""
        params: dict[str, Any] = {}
        for plugin in self.plugins:
            for param in plugin.router_params(self.plan, self.module, op):
                params[param.name] = param
        return list(params.values())

    def _usecase_params(self, op: dict[str, Any], imports: Imports) -> list[tuple[str, str]]:
        """(name, annotation) of what the router passes the use case (after its own arguments)."""
        out = []
        for param in self._router_params(op):
            if param.usecase_annotation:
                self._imports(imports, param.usecase_imports)
                out.append((param.name, param.usecase_annotation))
        return out

    def _code(self, codes: list[Code], imports: Imports) -> str:
        lines = []
        for code in codes:
            self._imports(imports, code.imports)
            lines += [f"        {line}" if line else "" for line in code.lines]
        return "".join(f"{line}\n" for line in lines)

    def _prechecks(self, op: dict[str, Any], record: str | None, imports: Imports) -> str:
        codes = [code for plugin in self.plugins for code in plugin.prechecks(self.plan, self.module, op, record)]
        return self._code(codes, imports)

    def _events(self, op: dict[str, Any], record: str, imports: Imports) -> str:
        codes = [code for plugin in self.plugins for code in plugin.events(self.plan, self.module, op, record)]
        return self._code(codes, imports)

    def _repository_filters(self) -> list[Any]:
        return [item for plugin in self.plugins for item in plugin.repository_filters(self.plan, self.module)]

    def _scope_params(self, imports: Imports) -> str:
        """The repository `list`'s extra parameters, one per plugin filter (Story 10.1)."""
        out = ""
        for item in self._repository_filters():
            self._imports(imports, item.imports)
            out += f", {item.param}: {item.annotation} = None"
        return out

    @staticmethod
    def _list_params_line(params: str) -> str:
        """The repository `list`'s parameters: one line, or one per line past 120 characters (a plugin's filter)."""
        line = f"        self, filters: dict[str, Any], {params}\n"
        if len(line) <= 121:
            return line
        names = ["self", "filters: dict[str, Any]", *re.split(r", (?=\w+: )", params)]
        return "".join(f"        {name},\n" for name in names)

    def _repository_methods(self) -> list[Any]:
        return [item for plugin in self.plugins for item in plugin.repository_methods(self.plan, self.module)]

    def _response_fields(self) -> list[Any]:
        return [item for plugin in self.plugins for item in plugin.response_fields(self.plan, self.module)]

    def _action_checks(self) -> list[Any]:
        return [item for plugin in self.plugins for item in plugin.action_checks(self.plan, self.module)]

    def _caller(self, op: dict[str, Any]) -> str:
        """`, user=<param>` when the record's `allowedActions` depend on the caller and the use case has one."""
        checks = [check for check in self._action_checks() if check.user_annotation]
        names = {param.name for param in self._router_params(op) if param.usecase_annotation}
        return f", user={checks[0].user_param}" if checks and checks[0].user_param in names else ""

    def _viewer(self, op: dict[str, Any]) -> str:
        """Epic 33: `, viewer=<the caller's id>` when a feature computes the caller's own row and the use case knows
        the caller (the policies plugin's `current_user`)."""
        if not any(item["kind"] == "mine" for item in self.computed):
            return ""
        names = {param.name for param in self._router_params(op) if param.usecase_annotation}
        if "current_user" not in names:
            return ""
        return ", viewer=current_user.id if current_user else None"

    def _present(self, var: str, op: dict[str, Any]) -> str:
        """The response for one record; with references, their labels loaded too (Story 10.0b)."""
        user = self._caller(op)
        if not self.shows:
            return f"{self.response_dto}.from_entity({var}{user})"
        viewer = self._viewer(op)
        return f"{self.response_dto}.from_entity({var}, self.{self.repo_var}.references([{var}]{viewer}){user})"

    def _raise_not_found(self) -> str:
        return (
            f'            raise NotFoundException("{self.entity} not found", details={{"id": str({self.snake}_id)}})\n'
        )

    def _not_found(self, var: str) -> str:
        return f"        if {var} is None:\n" + self._raise_not_found()

    def usecase_files(self) -> dict[str, str]:
        files = {}
        dtos = f"{self.pkg}.presenter.dtos"
        repo = f"self.{self.repo_var}"
        log_id = f'extra={{"{self.snake}_id": str({self.var}.{self.pk["attr"]})}}'
        for op in self.crud_ops:
            action = op["action"]
            imports = Imports()
            pk = self._pk_imports(imports) if action in ("get", "update", "delete") else ""
            extra = "".join(f", {name}: {annotation}" for name, annotation in self._usecase_params(op, imports))
            if action == "create":
                imports.add(dtos, op["requestDto"], self.response_dto)
                from_user = ", ".join(column["sourceValue"] for column in self.from_user)
                body = (
                    self._prechecks(op, None, imports)
                    + f"        {self.var} = {repo}.create(dto.to_entity({from_user}))\n"
                    + self._events(op, self.var, imports)
                    + f'        logger.info("{_label(self.model)} created", {log_id})\n'
                    f"        return {self._present(self.var, op)}"
                )
                text = self._usecase(op, imports, f", dto: {op['requestDto']}{extra}", body, self.response_dto)
            elif action == "get":
                imports.add(dtos, self.response_dto).add("src.libs.exceptions", "NotFoundException")
                body = (
                    f"        {self.var} = {repo}.find_by_id({self.snake}_id)\n"
                    + self._not_found(self.var)
                    + self._prechecks(op, self.var, imports)
                    + f"        return {self._present(self.var, op)}"
                )
                text = self._usecase(op, imports, f", {self.snake}_id: {pk}{extra}", body, self.response_dto)
            elif action == "update":
                imports.add(dtos, op["requestDto"], self.response_dto).add("src.libs.exceptions", "NotFoundException")
                body = (
                    f"        current = {repo}.find_by_id({self.snake}_id)\n"
                    + self._not_found("current")
                    + self._prechecks(op, "current", imports)
                    + f"        {self.var} = {repo}.update(dto.to_entity(current))\n"
                    + self._events(op, self.var, imports)
                    + f'        logger.info("{_label(self.model)} updated", {log_id})\n'
                    f"        return {self._present(self.var, op)}"
                )
                signature = f", {self.snake}_id: {pk}, dto: {op['requestDto']}{extra}"
                text = self._usecase(op, imports, signature, body, self.response_dto)
            elif action == "delete":
                imports.add("src.libs.exceptions", "NotFoundException")
                prechecks, events = self._prechecks(op, "existing", imports), self._events(op, "existing", imports)
                load = (  # the record, when a plugin checks it or emits it
                    f"        existing = {repo}.find_by_id({self.snake}_id)\n" + self._not_found("existing")
                    if prechecks or events
                    else f"        if {repo}.find_by_id({self.snake}_id) is None:\n" + self._raise_not_found()
                )
                body = (
                    load
                    + prechecks
                    + f"        {repo}.delete({self.snake}_id)\n"
                    + events
                    + f'        logger.info("{_label(self.model)} deleted", '
                    f'extra={{"{self.snake}_id": str({self.snake}_id)}})'
                )
                text = self._usecase(op, imports, f", {self.snake}_id: {pk}{extra}", body, "None")
            else:
                text = self._list_usecase(op, imports)
            files[f"{self.dir}/usecases/{op['usecaseFile']}"] = text
        for op in self.aggregates.values():  # Epic 21
            files[f"{self.dir}/usecases/{op['usecaseFile']}"] = self._aggregate_usecase(op)
        exports = [
            (op["usecaseFile"].removesuffix(".py"), op["usecaseDep"])
            for op in [*self.crud_ops, *self.aggregates.values()]
        ]
        files[f"{self.dir}/usecases/__init__.py"] = _package(exports)
        return files

    def _ranged(self) -> bool:
        """Story 23.4: a list of this module takes date ranges (its repository reads `__gte` / `__lte` bounds)."""
        return any(op.get("ranges") for op in self.module["operations"])

    @staticmethod
    def _bounded_filters(model: str) -> str:
        return (
            "        for attribute, value in filters.items():\n"
            '            name, _, bound = attribute.partition("__")\n'
            f"            column = col(getattr({model}, name))\n"
            '            if bound == "gte":\n'
            "                query = query.where(column >= value)\n"
            '            elif bound == "lte":\n'
            "                query = query.where(column <= value)\n"
            "            else:\n"
            "                query = query.where(column == value)\n"
        )

    def _filter_params(self, op: dict[str, Any], imports: Imports) -> list[tuple[str, str, dict[str, Any]]]:
        """(variable, annotation, filter) per list filter."""
        by_attr = {column["attr"]: column for column in self.model["columns"]}
        params = []
        for flt in op.get("filters", []):
            column = by_attr[flt["attr"]]
            variable = flt["attr"] if flt["attr"] not in RESERVED else f"{flt['attr']}_filter"
            params.append((variable, _type(column, imports), flt))
        for rng in op.get("ranges", []):  # Story 23.4: two bounds, `<attr>__gte` / `<attr>__lte` in `filters`
            column = by_attr[rng["attr"]]
            for suffix, bound, word in (("From", "gte", "from"), ("To", "lte", "to")):
                bounded = {"param": f"{rng['param']}{suffix}", "attr": f"{rng['attr']}__{bound}"}
                params.append((f"{rng['attr']}_{word}", _type(column, imports), bounded))
        return params

    def _list_usecase(self, op: dict[str, Any], imports: Imports) -> str:
        imports.add(f"{self.pkg}.presenter.dtos", op["responseDto"], self.response_dto)
        params = self._filter_params(op, imports)
        enums = sorted({annotation for _, annotation, _ in params if annotation[0].isupper() and "." not in annotation})
        if enums:
            imports.add(ENTITIES_PKG.replace("/", "."), *enums)
        signature = "".join(f",\n        {variable}: {annotation} | None" for variable, annotation, _ in params)
        search = bool(op.get("search"))
        if search:
            signature += ",\n        q: str | None"
        signature += ",\n        sort: str | None,\n        limit: int,\n        offset: int,"
        passed = self._usecase_params(op, imports)
        signature += "".join(f"\n        {name}: {annotation}," for name, annotation in passed)
        signature += "\n    "
        filters = [
            item
            for item in self._repository_filters()
            if item.operations is None or op["operationId"] in item.operations
        ]
        for item in filters:
            self._imports(imports, item.imports)
        scoped = "".join(f", {item.param}={item.value}" for item in filters)
        user = self._caller(op)
        sort_fields = ", ".join(f'"{item["param"]}": "{item["attr"]}"' for item in op.get("sort", []))
        candidates = ", ".join(f'"{flt["attr"]}": {variable}' for variable, _, flt in params)
        q_arg = ("q, " if search else "None, ") if self.search() else ""
        plural = to_snake(self.name)
        body = (
            self._prechecks(op, None, imports) + f"        candidates = {{{candidates}}}\n"
            "        filters = {key: value for key, value in candidates.items() if value is not None}\n"
            + (
                '        order = (SORT_FIELDS[sort.lstrip("-")], sort.startswith("-")) if sort else None\n'
                if op.get("sort")
                else "        order = None\n"
            )
            + f"        {plural}, total = self.{self.repo_var}.list(filters, {q_arg}order, limit, offset{scoped})\n"
            + (
                f"        references = self.{self.repo_var}.references({plural}{self._viewer(op)})\n"
                if self.shows
                else ""
            )
            + f"        return {op['responseDto']}(\n"
            f"            items=[{self.response_dto}.from_entity(item{', references' if self.shows else ''}{user})"
            f" for item in {plural}],\n"
            "            total=total,\n            limit=limit,\n            offset=offset,\n        )"
        )
        text = self._usecase(op, imports, signature, body, op["responseDto"])
        if op.get("sort"):
            marker = f"\n\nclass {op['usecase']}:"
            text = text.replace(
                marker,
                f"\n# API sort names (camelCase) → entity attributes\nSORT_FIELDS = {{{sort_fields}}}\n{marker}",
                1,
            )
        return text

    # -- router --------------------------------------------------------------------------------------------------

    def router(self) -> str:
        variable = self.module["router"]["variable"]
        imports = Imports().add("fastapi", "APIRouter")
        dtos = f"{self.pkg}.presenter.dtos"
        usecases = f"{self.pkg}.usecases"
        handlers = []
        for op in self.module["operations"]:
            action = op["action"]
            if op.get("type") == "aggregate":  # Epic 21: declared before the `/{id}` routes below
                imports.add(usecases, op["usecaseDep"]).add(dtos, op["responseDto"])
                returns = f"list[{op['responseDto']}]" if self._grouped(op) else op["responseDto"]
                # Story 23.9: a role policy guards the figure (the plugins' dependencies; the use case takes none)
                guards = [param for param in self._router_params(op) if not param.usecase_annotation]
                for param in guards:
                    self._imports(imports, param.imports)
                extra = "".join(f", {param.name}: {param.annotation}" for param in guards)
                signature = f"async def {op['handler']}(usecase: {op['usecaseDep']}{extra}) -> {returns}:"
                if len(signature) > 120:
                    params = [f"usecase: {op['usecaseDep']}", *(f"{p.name}: {p.annotation}" for p in guards)]
                    signature = (
                        f"async def {op['handler']}(\n" + "".join(f"    {p},\n" for p in params) + f") -> {returns}:"
                    )
                handlers.insert(
                    0,
                    f'@{variable}.get("{op["path"]}", operation_id="{op["operationId"]}", response_model={returns})\n'
                    f"{signature}\n"
                    "    return await usecase.execute()\n",
                )
                continue
            if action not in self.ops:
                continue
            imports.add(usecases, op["usecaseDep"])
            responses = ", ".join(f"{status}: ERROR" for status in sorted({e["status"] for e in op["errors"]}))
            decorator_args = [f'"{op["path"]}"', f'operation_id="{op["operationId"]}"']
            path_params = re.findall(r"\{(\w+)\}", op["path"])
            if action == "delete":
                decorator_args.append("status_code=204")
            else:
                response = op["responseDto"]
                imports.add(dtos, response)
                decorator_args.append(f"response_model={response}")
                if op["status"] != 200:
                    decorator_args.append(f"status_code={op['status']}")
            if responses:
                decorator_args.append(f"responses={{{responses}}}")
            if op.get("notes"):  # Story 10.4: what the route does not do (an ambiguous rule), in its OpenAPI
                decorator_args.append(f"description={json.dumps(' '.join(op['notes']), ensure_ascii=False)}")
            params: list[str] = []
            columns = {column["attr"]: column for column in self.model["columns"]}
            scope = {flt["param"]: columns[flt["attr"]] for flt in op.get("filters", []) if flt.get("in") == "path"}
            for name in path_params:
                annotation = _type(scope[name], imports) if name in scope else self._pk_imports(imports)
                params.append(f"{name}: {annotation}")
            args = [name for name in path_params]
            if action in ("create", "update"):
                imports.add(dtos, op["requestDto"])
                params.append(f"body: {op['requestDto']}")
                args.append("body")
            params.insert(0, f"usecase: {op['usecaseDep']}") if action == "list" else params.append(
                f"usecase: {op['usecaseDep']}"
            )
            returns = "None" if action == "delete" else op["responseDto"]
            if action == "list":
                imports.add("fastapi", "Query")
                list_params, args = self._list_params(op, imports)
                params += list_params
            # Story 10.1: the plugins' dependencies (a list's go before its query parameters, which have defaults)
            for index, param in enumerate(self._router_params(op)):
                self._imports(imports, param.imports)
                text = f"{param.name}: {param.annotation}"
                params.insert(1 + index, text) if action == "list" else params.append(text)
                if param.usecase_annotation:
                    args.append(param.name)
            call = f"usecase.execute({', '.join(args)})"
            statement = f"    await {call}" if action == "delete" else f"    return await {call}"
            decorator = f"@{variable}.{op['method'].lower()}({', '.join(decorator_args)})"
            if len(decorator) > 120:
                decorator = (
                    f"@{variable}.{op['method'].lower()}(\n" + "".join(f"    {a},\n" for a in decorator_args) + ")"
                )
            signature = f"async def {op['handler']}({', '.join(params)}) -> {returns}:"
            if len(signature) > 120 or action == "list":
                signature = (
                    f"async def {op['handler']}(\n" + "".join(f"    {p},\n" for p in params) + f") -> {returns}:"
                )
            handlers.append(f"{decorator}\n{signature}\n{statement}\n")
        return (
            imports.render() + f'\n{variable} = APIRouter(tags=["{self.module["router"]["tag"]}"])\n\n'
            'ERROR = {"description": "Error envelope: {error: {code, message, details}}"}\n\n\n' + "\n\n".join(handlers)
        )

    def _list_params(self, op: dict[str, Any], imports: Imports) -> tuple[list[str], list[str]]:
        params, args = [], []
        filters = self._filter_params(op, imports)
        enums = sorted(
            {annotation for _, annotation, _ in filters if annotation[0].isupper() and "." not in annotation}
        )
        if enums:
            imports.add(ENTITIES_PKG.replace("/", "."), *enums)
        for variable, annotation, flt in filters:
            if flt.get("in") == "path":  # the router's path parameter of that name
                args.append(flt["param"])
                continue
            alias = f', alias="{flt["param"]}"' if flt["param"] != variable else ""
            params.append(f"{variable}: {annotation} | None = Query(default=None{alias})")
            args.append(variable)
        if op.get("search"):
            params.append("q: str | None = Query(default=None)")
            args.append("q")
        if op.get("sort"):
            names = "|".join(item["param"] for item in op["sort"])
            params.append(f'sort: str | None = Query(default=None, pattern=r"^-?({names})$")')
        args.append("sort" if op.get("sort") else "None")
        pagination = op.get("pagination")
        if pagination:
            params.append(
                f"limit: int = Query(default={pagination['defaultLimit']}, ge=1, le={pagination['maxLimit']})"
            )
            params.append("offset: int = Query(default=0, ge=0)")
            args += ["limit", "offset"]
        else:
            args += ["1000", "0"]
        return params, args

    def files(self) -> dict[str, str]:
        port = self.module["port"]
        port_module = port["file"].rsplit("/", 1)[1].removesuffix(".py")
        impl_module = port["implementationFile"].rsplit("/", 1)[1].removesuffix(".py")
        router = self.module["router"]["variable"]
        files = {
            f"{self.dir}/__init__.py": "",
            f"{self.dir}/ports/__init__.py": "",
            f"{self.dir}/infrastructure/__init__.py": "",
            port["file"]: self.port(),
            f"{self.dir}/ports/output/__init__.py": (
                f"from .{port_module} import {port['interface']}  # noqa: I001  (must load before the implementation)\n"
                f"from {self.pkg}.infrastructure.persistence import {port['dep']}\n\n"
                + _exports([port["interface"], port["dep"]])
            ),
            port["implementationFile"]: self.repository(),
            f"{self.dir}/infrastructure/persistence/__init__.py": f"from .{impl_module} import {port['dep']}\n\n"
            + _exports([port["dep"]]),
            self.module["router"]["file"]: self.router(),
            f"{self.dir}/presenter/__init__.py": f"from .router import {router}\n\n" + _exports([router]),
        }
        files |= self.dto_files()
        files |= self.usecase_files()
        return files


def module_files(plan: dict[str, Any], spec: dict[str, Any], module: dict[str, Any]) -> dict[str, str]:
    """Every file of one CRUD module (paths relative to the backend project)."""
    return _Module(plan, spec, module).files()


def routers_file(plan: dict[str, Any]) -> str:
    routers = plan["routers"]["order"]
    by_variable = {module["router"]["variable"]: module for module in plan["modules"]}
    imports = Imports().add("src.modules.health.presenter", "health_router")
    for variable in routers:
        if variable in by_variable:
            imports.add(f"src.modules.{by_variable[variable]['name']}.presenter", variable)
    line = f"all_router = [{', '.join(routers)}]\n"
    if len(line) > 120:
        line = "all_router = [\n" + "".join(f"    {name},\n" for name in routers) + "]\n"
    return imports.render() + "\n" + line


# -- tests -------------------------------------------------------------------------------------------------------------


class _Tests:
    """tests/modules/<module>/test_<entity>_api.py for one CRUD module."""

    def __init__(self, plan: dict[str, Any], spec: dict[str, Any], module: dict[str, Any]):
        self.crud = _Module(plan, spec, module)
        self.plan = plan
        self.module = module
        self.models = _entity_by_name(plan)
        self.by_table = {model["table"]: model for model in plan["models"]}
        self.imports = (
            Imports()
            .add("os")
            .add("uuid")
            .add("itertools", "count")
            .add("typing", "Any")
            .add("sqlalchemy", "create_engine")
            .add("sqlmodel", "Session")
        )
        self.helpers: dict[str, str] = {}

    # -- seeding -------------------------------------------------------------------------------------------------

    def _required(self, model: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            column
            for column in model["columns"]
            if not column["primaryKey"] and not column["nullable"] and not _default(column)
        ]

    def _parent(self, column: dict[str, Any]) -> dict[str, Any]:
        return self.by_table[column["foreignKey"]["references"].split(".")[0]]

    def seed(self, model: dict[str, Any]) -> str:
        """The name of `_seed_<entity>(**overrides)`, writing it (and its parents') on first use."""
        name = f"_seed_{_snake(model['entity'])}"
        if name in self.helpers:
            return name
        self.helpers[name] = ""
        self.imports.add(MODELS_PKG.replace("/", "."), model["class"])
        lines = []
        for column in self._required(model):
            if column.get("source") == "currentUser":  # Story 10.3: the signed-in test user owns it, if any
                self.imports.add("tests.auth", "current_user_id")
                parent = self._parent(column)
                fallback = f"{self.seed(parent)}().{_pk(parent)['attr']}"
                lines.append(
                    f'    if "{column["attr"]}" not in values:\n'
                    f'        values["{column["attr"]}"] = current_user_id() or {fallback}\n'
                )
                continue
            if column.get("foreignKey"):
                parent = self._parent(column)
                parent_seed = self.seed(parent)
                lines.append(
                    f'    if "{column["attr"]}" not in values:\n'
                    f'        values["{column["attr"]}"] = {parent_seed}().{_pk(parent)["attr"]}\n'
                )
                continue
            literal = self._literal(column, "n", _label(model).title())
            lines.append(f'    values.setdefault("{column["attr"]}", {literal})\n')
        body = "".join(lines)
        counter = "    n = next(SEQUENCE)\n" if re.search(r"\bn\b", body) else ""
        self.helpers[name] = (
            f"def {name}(**overrides: Any) -> {model['class']}:\n"
            + counter
            + "    values: dict[str, Any] = dict(overrides)\n"
            + body
            + '    engine = create_engine(os.environ["DB_URL"])\n'
            "    with Session(engine) as session:\n"
            f"        model = {model['class']}(**values)\n"
            "        session.add(model)\n"
            "        session.commit()\n"
            "        session.refresh(model)\n"
            "    engine.dispose()\n"
            "    return model\n"
        )
        return name

    def _literal(self, column: dict[str, Any], counter: str, label: str) -> str:
        """A Python expression for a distinct sample value of `column` (using the int variable `counter`)."""
        kind = column["type"]
        if kind in ("string", "text"):
            limit = column.get("maxLength")
            text = f'f"{label} {column["apiName"]} {{{counter}}}"'
            return f"{text}[-{limit}:]" if limit else text
        if kind == "integer":
            low = column.get("min") if column.get("min") is not None else 1
            expression = f"{low} + {counter}"
            return f"min({expression}, {column['max']})" if column.get("max") is not None else expression
        if kind in ("float", "decimal"):
            low = column.get("min") if column.get("min") is not None else 1
            expression = f"{float(low)} + {counter}"
            if column.get("max") is not None:
                expression = f"min({expression}, {float(column['max'])})"
            if kind == "decimal":
                self.imports.add("decimal", "Decimal")
                return f"Decimal(str({expression}))"
            return expression
        if kind == "boolean":
            return f"{counter} % 2 == 1"
        if kind == "date":
            self.imports.add("datetime", "date")
            return f"date(2026, 1, {counter} % 28 + 1)"
        if kind == "datetime":
            self.imports.add("datetime", "UTC", "datetime")
            return f"datetime(2026, 1, {counter} % 28 + 1, 9, 0, tzinfo=UTC)"
        if kind == "enum":
            self.imports.add(ENTITIES_PKG.replace("/", "."), column["enum"]["class"])
            values = column["enum"]["values"]
            return f"list({column['enum']['class']})[{counter} % {len(values)}]"
        if kind == "uuid":
            return "uuid.uuid4()"
        return "{}"

    def _fixed(self, column: dict[str, Any], which: int) -> tuple[str, Any] | None:
        """(Python literal, JSON value) of the `which`-th (0 or 1) of two ordered, distinct values, or None."""
        kind = column["type"]
        if kind in ("string", "text"):
            text = ("Alpha", "Beta")[which]
            return _py(text), text
        if kind == "integer":
            low = column.get("min") if column.get("min") is not None else 1
            value = low + which
            if column.get("max") is not None and value > column["max"]:
                return None
            return repr(value), value
        if kind in ("float", "decimal"):
            low = float(column.get("min") if column.get("min") is not None else 1)
            value = low + which
            if column.get("max") is not None and value > float(column["max"]):
                return None
            if kind == "decimal":
                self.imports.add("decimal", "Decimal")
                return f'Decimal("{value}")', value
            return repr(value), value
        if kind == "boolean":
            return repr(bool(which)), bool(which)
        if kind == "date":
            self.imports.add("datetime", "date")
            return f"date(2026, 1, {which + 1})", f"2026-01-0{which + 1}"
        if kind == "datetime":
            self.imports.add("datetime", "UTC", "datetime")
            return f"datetime(2026, 1, {which + 1}, 9, 0, tzinfo=UTC)", None
        if kind == "enum":
            values = column["enum"]["values"]
            if len(values) < 2:
                return None
            self.imports.add(ENTITIES_PKG.replace("/", "."), column["enum"]["class"])
            return f"{column['enum']['class']}.{_member(values[which])}", values[which]
        return None

    # -- payloads ------------------------------------------------------------------------------------------------

    def payload_helper(self, op: dict[str, Any]) -> str:
        lines = []
        for column in self.crud.request_columns(op):
            if column.get("foreignKey"):
                parent = self._parent(column)
                value = f"str({self.seed(parent)}().{_pk(parent)['attr']})"
            elif column.get("file"):  # Story 10.5: a key the test bucket has, as an upload would leave
                self.imports.add("tests.storage", "uploaded")
                value = f'uploaded("{self.crud.entity}.{column["apiName"]}")'
            else:
                value = self._json_literal(column)
            lines.append(f'        "{column["apiName"]}": {value},\n')
        body = "".join(lines)
        counter = "    n = next(SEQUENCE)\n" if re.search(r"\bn\b", body) else ""
        return f"def _payload() -> dict[str, Any]:\n{counter}    return {{\n{body}    }}\n"

    def _json_literal(self, column: dict[str, Any]) -> str:
        kind = column["type"]
        label = _label(self.crud.model).title()
        if kind in ("string", "text"):
            limit = column.get("maxLength")
            text = f'f"{label} {column["apiName"]} {{n}}"'
            return f"{text}[-{limit}:]" if limit else text
        if kind == "integer":
            low = column.get("min") if column.get("min") is not None else 1
            return f"min({low} + n, {column['max']})" if column.get("max") is not None else f"{low} + n"
        if kind in ("float", "decimal"):
            low = float(column.get("min") if column.get("min") is not None else 1)
            return f"min({low} + n, {float(column['max'])})" if column.get("max") is not None else f"{low} + n"
        if kind == "boolean":
            return "n % 2 == 1"
        if kind == "date":
            return 'f"2026-01-{n % 28 + 1:02d}"'
        if kind == "datetime":
            return 'f"2026-01-{n % 28 + 1:02d}T09:00:00Z"'
        if kind == "enum":
            values = column["enum"]["values"]
            return f"{_py(values)}[n % {len(values)}]"
        if kind == "uuid":
            return "str(uuid.uuid4())"
        return "{}"

    # -- cases ---------------------------------------------------------------------------------------------------

    def _path(self, op: dict[str, Any], record: str) -> str:
        path = op["path"]
        for name in re.findall(r"\{(\w+)\}", path):
            path = path.replace(f"{{{name}}}", f"{{{record}.{self.crud.pk['attr']}}}")
        return f'f"{path}"' if "{" in path else f'"{path}"'

    def _missing_path(self, op: dict[str, Any]) -> str:
        path = op["path"]
        for name in re.findall(r"\{(\w+)\}", path):
            path = path.replace(f"{{{name}}}", "{MISSING}")
        return f'f"{path}"'

    def aggregate_case(self, test: dict[str, Any], op: dict[str, Any]) -> str:
        """Epic 21: the aggregate answers 200 with a number (or grouped numbers) once a record exists."""
        seed = self.seed(self.crud.model)
        shape = (
            '    assert isinstance(body, list) and all({"key", "value"} <= set(row) for row in body)\n'
            if op["aggregate"].get("groupAttr")
            else '    assert isinstance(body["value"], int | float)\n'
        )
        return (
            f"def {test['id']}(client):\n    {seed}()\n\n"
            f'    response = client.get("{op["path"]}")\n\n'
            "    assert response.status_code == 200, response.text\n"
            "    body = response.json()\n" + shape
        )

    def case(self, test: dict[str, Any], op: dict[str, Any]) -> str | None:
        name = test["id"]
        case = test["case"]
        action = op["action"]
        seed = self.seed(self.crud.model)
        pk = self.crud.pk["attr"]
        method = op["method"].lower()
        if action == "create":
            if case == "ok":
                checks = [
                    c["apiName"]
                    for c in self.crud.request_columns(op)
                    if c["type"] not in ("datetime", "float", "decimal")
                ]
                compare = "".join(f'    assert body["{api}"] == payload["{api}"]\n' for api in checks)
                return (
                    f"def {name}(client):\n    payload = _payload()\n\n"
                    f'    response = client.post("{op["path"]}", json=payload)\n\n'
                    "    assert response.status_code == 201, response.text\n"
                    "    body = response.json()\n" + compare
                )
            if case == "invalid":
                body = "{}" if any(_required(c) for c in self.crud.request_columns(op)) else '{"unexpectedField": 1}'
                return (
                    f"def {name}(client):\n"
                    f'    assert client.post("{op["path"]}", json={body}).status_code == 422\n'
                    f'    assert client.post("{op["path"]}", json={{**_payload(), "unexpectedField": 1}})'
                    ".status_code == 422\n"
                )
            if case == "conflict":
                return (
                    f"def {name}(client):\n    payload = _payload()\n"
                    f'    assert client.post("{op["path"]}", json=payload).status_code == 201\n\n'
                    f'    response = client.post("{op["path"]}", json=payload)\n\n'
                    "    assert response.status_code == 409\n"
                    '    assert response.json()["error"]["code"] == "CONFLICT"\n'
                    # Story 10.0b: the fields a client marks
                    + '    assert response.json()["error"]["details"]["fields"] == '
                    + json.dumps([column["apiName"] for column in self.crud.unique])
                    + "\n"
                )
            if case == "bad_reference":
                fks = [c["apiName"] for c in self.crud.request_columns(op) if c.get("foreignKey")]
                if not fks:  # Story 10.3: the only reference is the owner, which the client does not send
                    return None
                changes = ", ".join(f'"{api}": MISSING' for api in fks)
                return (
                    f"def {name}(client):\n"
                    f'    response = client.post("{op["path"]}", json={{**_payload(), {changes}}})\n\n'
                    "    assert response.status_code == 400\n"
                    '    assert response.json()["error"]["code"] == "REFERENCE_NOT_FOUND"\n'
                )
        if action == "get":
            if case == "ok":
                return (
                    f"def {name}(client):\n    record = {seed}()\n\n"
                    f"    response = client.get({self._path(op, 'record')})\n\n"
                    "    assert response.status_code == 200\n"
                    f'    assert response.json()["{self.crud.pk["apiName"]}"] == str(record.{pk})\n'
                )
            if case == "not_found":
                return (
                    f"def {name}(client):\n    response = client.get({self._missing_path(op)})\n\n"
                    "    assert response.status_code == 404\n"
                    '    assert response.json()["error"]["code"] == "NOT_FOUND"\n'
                )
        if action == "list":
            return self._list_case(name, case, op, seed)
        if action == "update":
            if case == "ok":
                change = self._update_change(op)
                if change is None:
                    return None
                api, value, compare = change
                return (
                    f"def {name}(client):\n    record = {seed}()\n\n"
                    f'    response = client.patch({self._path(op, "record")}, json={{"{api}": {value}}})\n\n'
                    "    assert response.status_code == 200, response.text\n"
                    f'    assert response.json()["{api}"] == {compare}\n'
                    f'    assert response.json()["{self.crud.pk["apiName"]}"] == str(record.{pk})\n'
                )
            if case == "not_found":
                missing = self._missing_path(op)
                return f"def {name}(client):\n    assert client.patch({missing}, json={{}}).status_code == 404\n"
            if case == "invalid":
                return (
                    f"def {name}(client):\n    record = {seed}()\n\n"
                    f'    assert client.patch({self._path(op, "record")}, json={{"unexpectedField": 1}})'
                    ".status_code == 422\n"
                )
        if action == "delete":
            if case == "ok":
                get = self.crud.ops.get("get")
                after = f"    assert client.get({self._path(get, 'record')}).status_code == 404\n" if get else ""
                return (
                    f"def {name}(client):\n    record = {seed}()\n\n"
                    f"    assert client.{method}({self._path(op, 'record')}).status_code == 204\n" + after
                )
            if case == "not_found":
                return f"def {name}(client):\n    assert client.delete({self._missing_path(op)}).status_code == 404\n"
        return None

    def _update_change(self, op: dict[str, Any]) -> tuple[str, str, str] | None:
        """(apiName, new value expression, expected response expression) for the PATCH happy path."""
        columns = [c for c in self.crud.request_columns(op) if not c.get("foreignKey")]
        # Story 10.4: a field a rule checks (a state, a total) changes in the rule's own tests
        columns = [c for c in columns if not c.get("ruled")] + [c for c in columns if c.get("ruled")]
        for column in columns:
            fixed = self._fixed(column, 1)
            if fixed is not None and fixed[1] is not None:
                return column["apiName"], _py(fixed[1]), _py(fixed[1])
        fks = [c for c in self.crud.request_columns(op) if c.get("foreignKey")]
        if fks:
            parent = self._parent(fks[0])
            expression = f"str({self.seed(parent)}().{_pk(parent)['attr']})"
            return fks[0]["apiName"], expression, f'response.json()["{fks[0]["apiName"]}"]'
        return None

    def _list_scope(self, op: dict[str, Any]) -> tuple[str, list[str], str]:
        """(setup lines, seed overrides, URL) of a list scoped by its path (`/fields/{fieldId}/reviews`): the test
        seeds every record under one parent and calls the real URL."""
        path, setup, overrides = op["path"], "", []
        for flt in op.get("filters", []):
            if flt.get("in") != "path":
                continue
            column = self._column(flt["attr"])
            variable = f"scope_{column['attr']}"
            if column.get("foreignKey"):
                parent = self._parent(column)
                setup += f"    {variable} = {self.seed(parent)}().{_pk(parent)['attr']}\n"
            else:
                fixed = self._fixed(column, 0)
                if fixed is None or fixed[1] is None:
                    continue
                setup += f"    {variable} = {fixed[0]}\n"
            overrides.append(f"{column['attr']}={variable}")
            path = path.replace(f"{{{flt['param']}}}", f"{{{variable}}}")
        if not setup:
            return "", [], f'"{path}"'
        path = re.sub(r"\{(?!scope_)(\w+)\}", r"{{\1}}", path)
        return setup, overrides, f'f"{path}"'

    def _list_case(self, name: str, case: str, op: dict[str, Any], seed: str) -> str | None:
        setup, overrides, path = self._list_scope(op)

        def call(*extra: str) -> str:
            return f"{seed}({', '.join([*overrides, *extra])})"

        head = f"def {name}(client):\n{setup}"
        pk = self.crud.pk
        ids = f'[item["{pk["apiName"]}"] for item in body["items"]]'
        if case == "ok":
            return (
                f"{head}    first, second = {call()}, {call()}\n\n"
                f"    body = client.get({path}).json()\n\n"
                '    assert body["total"] == 2\n'
                f'    assert {{item["{pk["apiName"]}"] for item in body["items"]}} == '
                f"{{str(first.{pk['attr']}), str(second.{pk['attr']})}}\n"
            )
        if case == "pagination":
            return (
                f"{head}    for _ in range(3):\n        {call()}\n\n"
                f'    page = client.get({path}, params={{"limit": 2, "offset": 2}}).json()\n\n'
                '    assert page["total"] == 3 and page["limit"] == 2 and page["offset"] == 2\n'
                '    assert len(page["items"]) == 1\n'
            )
        if case.startswith("filter_"):
            flt = next(f for f in op.get("filters", []) if f"filter_{to_snake(f['param'])}" == case)
            column = next(c for c in self.crud.model["columns"] if c["attr"] == flt["attr"])
            if flt.get("in") == "path":  # a record under another parent stays out of the list
                high = None if column.get("foreignKey") else self._fixed(column, 1)
                other = f"{column['attr']}={high[0]}" if high else ""
                return (
                    f"{head}    first = {call()}\n    {seed}({other})\n\n"
                    f"    body = client.get({path}).json()\n\n"
                    f"    assert {ids} == [str(first.{pk['attr']})]\n"
                )
            if column.get("foreignKey"):
                return (
                    f"{head}    first = {call()}\n    {call()}\n\n"
                    f'    body = client.get({path}, params={{"{flt["param"]}": str(first.{column["attr"]})}})'
                    ".json()\n\n"
                    f"    assert {ids} == [str(first.{pk['attr']})]\n"
                )
            low, high = self._fixed(column, 0), self._fixed(column, 1)
            if low is None or high is None or low[1] is None:
                return None
            query = _py(low[1]) if column["type"] != "boolean" else _py("true" if low[1] else "false")
            attr = column["attr"]
            return (
                f"{head}    first = {call(f'{attr}={low[0]}')}\n"
                f"    {call(f'{attr}={high[0]}')}\n\n"
                f'    body = client.get({path}, params={{"{flt["param"]}": {query}}}).json()\n\n'
                f"    assert {ids} == [str(first.{pk['attr']})]\n"
            )
        if case.startswith("range_"):  # Story 23.4
            rng = next(r for r in op.get("ranges", []) if f"range_{to_snake(r['param'])}" == case)
            column = next(c for c in self.crud.model["columns"] if c["attr"] == rng["attr"])
            low, high = self._fixed(column, 0), self._fixed(column, 1)
            if low is None or high is None:
                return None
            if column["type"] == "datetime":  # the seeds' times (`_fixed`), as the query sends them
                low, high = (low[0], "2026-01-01T09:00:00Z"), (high[0], "2026-01-02T09:00:00Z")
            attr = column["attr"]
            return (
                f"{head}    early = {call(f'{attr}={low[0]}')}\n"
                f"    late = {call(f'{attr}={high[0]}')}\n\n"
                f'    body = client.get({path}, params={{"{rng["param"]}From": {_py(high[1])}}}).json()\n'
                f"    assert {ids} == [str(late.{pk['attr']})]\n"
                f'    body = client.get({path}, params={{"{rng["param"]}To": {_py(low[1])}}}).json()\n'
                f"    assert {ids} == [str(early.{pk['attr']})]\n"
            )
        if case == "sort":
            item = op["sort"][0]
            column = next(c for c in self.crud.model["columns"] if c["attr"] == item["attr"])
            low, high = self._fixed(column, 0), self._fixed(column, 1)
            if low is None or high is None:
                return (
                    f"{head}"
                    f'    assert client.get({path}, params={{"sort": "{item["param"]}"}}).status_code == 200\n'
                    f'    assert client.get({path}, params={{"sort": "-{item["param"]}"}}).status_code == 200\n'
                )
            ids = f'[entry["{pk["apiName"]}"] for entry in body["items"]]'
            attr = column["attr"]
            return (
                f"{head}"
                f"    high = {call(f'{attr}={high[0]}')}\n"
                f"    low = {call(f'{attr}={low[0]}')}\n"
                f"    expected = [str(low.{pk['attr']}), str(high.{pk['attr']})]\n\n"
                f'    body = client.get({path}, params={{"sort": "{item["param"]}"}}).json()\n'
                f"    assert {ids} == expected\n"
                f'    body = client.get({path}, params={{"sort": "-{item["param"]}"}}).json()\n'
                f"    assert {ids} == expected[::-1]\n"
            )
        if case == "invalid_sort":
            return f'{head}    assert client.get({path}, params={{"sort": "notAField"}}).status_code == 422\n'
        if case == "search":
            item = next(
                (i for i in op["search"] if self._column(i["attr"])["type"] in ("string", "text")), op["search"][0]
            )
            column = self._column(item["attr"])
            if column["type"] not in ("string", "text"):
                return f'{head}    assert client.get({path}, params={{"q": "x"}}).status_code == 200\n'
            match, other = call(f'{column["attr"]}="Needle in a haystack"'), call(f'{column["attr"]}="Something else"')
            return (
                f"{head}"
                f"    match = {match}\n"
                f"    {other}\n\n"
                f'    body = client.get({path}, params={{"q": "needle"}}).json()\n\n'
                f"    assert {ids} == [str(match.{pk['attr']})]\n"
            )
        return None

    def _column(self, attr: str) -> dict[str, Any]:
        return next(c for c in self.crud.model["columns"] if c["attr"] == attr)

    # -- plugin cases (Story 10.3) ----------------------------------------------------------------------------------

    def _code(self, code: Code) -> list[str]:
        for module, names in code.imports:
            self.imports.add(module, *names)
        return list(code.lines)

    def plugin_case(self, test: dict[str, Any], op: dict[str, Any]) -> str | None:
        """A test case a plugin writes (another user's record, a missing role)."""
        own = bool(re.search(r"\{\w+\}", op["path"])) and op["action"] != "list"
        ctx = CaseContext(
            seed=self.seed(self.crud.model),
            record_path=self._path(op, "record") if own else None,
            missing_path=self._missing_path(op) if own else None,
            seed_for=lambda entity: self.seed(self.models[entity]),
        )
        for plugin in self.crud.plugins:
            code = plugin.test_case(self.plan, self.module, op, test, ctx)
            if code is not None:
                return "".join(f"{line}\n" for line in self._code(code))
        return None

    def with_prelude(self, text: str, op: dict[str, Any]) -> str:
        """The plugins' first lines of every test of `op` (sign in with the role it needs)."""
        lines = [
            line
            for plugin in self.crud.plugins
            for line in self._code(plugin.test_prelude(self.plan, self.module, op) or Code(()))
        ]
        if not lines:
            return text
        head, _, rest = text.partition("\n")
        return head + "\n" + "".join(f"    {line}\n" for line in lines) + rest

    def render(self) -> str:
        ops = {op["operationId"]: op for op in self.module["operations"]}
        cases = []
        create = self.crud.ops.get("create")
        payload = self.payload_helper(create) if create else ""
        for test in self.module["tests"]:
            op = ops.get(test["operationId"])
            if op is not None and op.get("type") == "aggregate":  # Epic 21
                cases.append(self.aggregate_case(test, op))
                continue
            if op is None or not is_crud(op):
                continue
            text = self.plugin_case(test, op) or self.case(test, op)
            if text:
                cases.append(self.with_prelude(text, op))
        pk = self.crud.pk
        missing = (
            "str(uuid.uuid4())" if pk["type"] == "uuid" else ("999999999" if pk["type"] == "integer" else '"missing"')
        )
        helpers = [text for text in self.helpers.values() if text]
        setup = []  # Story 10.1: what plugins need around every test (a signed-in client)
        for plugin in self.crud.plugins:
            code = plugin.test_setup(self.plan, self.module)
            if code is not None:
                for module, names in code.imports:
                    self.imports.add(module, *names)
                setup.append("".join(f"{line}\n" for line in code.lines))
        return (
            '"""Generated by the Fullstack Generation Agent from the plan\'s test cases (Story 17.6)."""\n\n'
            + self.imports.render()
            + f"\nMISSING = {missing}\nSEQUENCE = count(1)\n\n\n"
            + "\n\n".join([*setup, *helpers, *([payload] if payload else []), *cases])
        )


def module_tests(plan: dict[str, Any], spec: dict[str, Any], module: dict[str, Any]) -> dict[str, str]:
    """The module's CRUD tests (custom operations' tests are the engine's)."""
    return {module["testFile"]: _Tests(plan, spec, module).render()}
