"""Frontend ↔ contract consistency (Story 12.5): a dynamic job is rejected before any engine time is spent when
its FrontendSpec asks for data the backend will never provide.

Every section binding and form names a contract operation; binding params are that operation's parameters with
values of the right type; displayed fields exist in the response; form fields exist in the request with
compatible types and cover what the contract requires. Each issue points at the FrontendSpec (`path`) and, where
it can, at the BackendSpec (`backend_path`), so the UI can mark either editor.
"""

import copy
import re
from collections.abc import Iterator
from typing import Any

from src.modules.shared.domain.backend_spec import Severity, SpecIssue
from src.modules.shared.domain.frontend_spec import FrontendIssueCode, page_id, route_params
from src.modules.shared.domain.frontend_spec.app import is_app_spec
from src.orchestrator.integration.contract import build_contract, contract_operations, resolve

C = FrontendIssueCode
_VARIABLE = re.compile(r"^\$(route|query|record)\.[A-Za-z][A-Za-z0-9_]*$")
_ASSET_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")  # FrontendSpec SLUG
# Sections that pass each shown record to their actions (`$record.<field>`)
RECORD_SECTIONS = frozenset({"DataTable", "CardGrid", "List", "DetailView"})
LIST_SECTIONS = RECORD_SECTIONS - {"DetailView"}
# FrontendSpec form field type → the JSON type and format it submits
FORM_TYPES: dict[str, tuple[str, str | None]] = {
    "string": ("string", None),
    "text": ("string", None),
    "email": ("string", None),
    "url": ("string", None),
    "tel": ("string", None),
    "password": ("string", None),
    "enum": ("string", None),
    "integer": ("integer", None),
    "number": ("number", None),
    "decimal": ("number", None),
    "boolean": ("boolean", None),
    "date": ("string", "date"),
    "datetime": ("string", "date-time"),
}


def _sections(sections: list[dict[str, Any]], path: str) -> Iterator[tuple[dict[str, Any], str]]:
    """Every section with its JSON path, layout nodes' children included (Story 17.1)."""
    for index, section in enumerate(sections):
        yield section, f"{path}/{index}"
        yield from _sections(section.get("children") or [], f"{path}/{index}/children")


def _types(schema: dict[str, Any]) -> set[str]:
    kind = schema.get("type")
    if kind is None:
        return {"any"}
    return {t for t in (kind if isinstance(kind, list) else [kind]) if t != "null"}


def _value_fits(value: Any, schema: dict[str, Any]) -> str | None:
    """Why a literal value does not fit a parameter schema, or None."""
    if isinstance(value, str) and _VARIABLE.match(value):
        return None
    types = _types(schema)
    if "any" in types:
        return None
    checks = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if not any(checks.get(kind, False) for kind in types):
        return f"{value!r} is not {' | '.join(sorted(types))}"
    enum = [item for item in schema.get("enum") or [] if item is not None]
    if enum and value not in enum:
        return f"{value!r} is not one of {', '.join(map(str, enum))}"
    if isinstance(value, int | float) and not isinstance(value, bool):
        if schema.get("minimum") is not None and value < schema["minimum"]:
            return f"{value} is below the minimum {schema['minimum']}"
        if schema.get("maximum") is not None and value > schema["maximum"]:
            return f"{value} is above the maximum {schema['maximum']}"
    return None


def _response_record(contract: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """The record schema a binding displays: the list's item schema, or the response body."""
    responses = operation.get("responses") or {}
    success = next((r for s, r in sorted(responses.items()) if s.startswith("2")), {})
    schema = resolve(contract, (success.get("content") or {}).get("application/json", {}).get("schema", {}))
    if schema.get("type") == "array" and "items" in schema:
        return resolve(contract, schema["items"])
    items = (schema.get("properties") or {}).get("items")
    if isinstance(items, dict) and items.get("type") == "array":
        return resolve(contract, items.get("items", {}))
    return schema


class _Checker:
    def __init__(self, frontend: dict[str, Any], contract: dict[str, Any], backend: dict[str, Any] | None):
        self.frontend = frontend
        self.contract = contract
        self.operations = contract_operations(contract)
        self.issues: list[SpecIssue] = []
        self.has_backend = backend is not None
        self.backend = backend or {}
        self.op_index = {op["operationId"]: i for i, op in enumerate(self.backend.get("operations", []))}
        self.entity_index = {entity["name"]: i for i, entity in enumerate(self.backend.get("entities", []))}
        self.field_index = {
            (entity["name"], field["name"]): j
            for entity in self.backend.get("entities", [])
            for j, field in enumerate(entity["fields"])
        }

    def add(
        self,
        code: FrontendIssueCode,
        path: str,
        message: str,
        backend_path: str | None = None,
        hint=None,
        warning: bool = False,
    ):
        self.issues.append(
            SpecIssue(
                code=code,
                path=path,
                message=message,
                hint=hint,
                backend_path=backend_path,
                severity=Severity.WARNING if warning else Severity.ERROR,
            )
        )

    def undeclared(self, operation_id: str, side: str) -> str | None:
        """A hint for a custom operation whose `request` / `response` the BackendSpec does not declare: its fields
        exist only in the description, so the contract has none."""
        index = self.op_index.get(operation_id)
        spec_op = self.backend["operations"][index] if index is not None else {}
        payload = spec_op.get(side) or {}
        if spec_op.get("type") != "custom" or payload.get("properties") or payload.get("entity"):
            return None
        return (
            f'\'{operation_id}\' is a custom operation that declares no {side}: add "{side}": {{"properties": '
            f'[{{"name", "type"}}, ...]}} (or {{"entity": "<Entity>"}}) to {self.op_pointer(operation_id)} '
            "in the BackendSpec"
        )

    def op_pointer(self, operation_id: str) -> str:
        index = self.op_index.get(operation_id)
        return f"/operations/{index}" if index is not None else "/operations"

    def field_pointer(self, operation_id: str, field: str | None = None) -> str | None:
        entity = (self.operations[operation_id]["operation"].get("x-bga") or {}).get("entity")
        index = self.op_index.get(operation_id)
        custom = index is not None and self.backend["operations"][index].get("type") == "custom"
        if entity not in self.entity_index or custom:  # a custom operation declares its own request and response
            return self.op_pointer(operation_id)
        if field is not None and (entity, field) in self.field_index:
            return f"/entities/{self.entity_index[entity]}/fields/{self.field_index[(entity, field)]}"
        return f"/entities/{self.entity_index[entity]}/fields"

    def lookup(self, operation_id: str, path: str) -> dict[str, Any] | None:
        found = self.operations.get(operation_id)
        if found is None:
            known = ", ".join(sorted(self.operations)[:20])
            self.add(
                C.CONTRACT_UNKNOWN_OPERATION,
                path,
                f"Operation '{operation_id}' is not in the API contract",
                backend_path="/operations",
                hint=f"Contract operations: {known}",
            )
        return found

    def parameters(self, operation_id: str, given: dict[str, Any], path: str) -> None:
        operation = self.operations[operation_id]["operation"]
        params = {p["name"]: p for p in operation.get("parameters") or []}
        for name, value in given.items():
            parameter = params.get(name)
            if parameter is None:
                self.add(
                    C.CONTRACT_PARAM_MISMATCH,
                    f"{path}/{name}",
                    f"'{operation_id}' has no parameter '{name}'",
                    backend_path=self.op_pointer(operation_id),
                    hint=f"Parameters: {', '.join(params) or '(none)'}",
                )
                continue
            problem = _value_fits(value, resolve(self.contract, parameter.get("schema") or {}))
            if problem:
                self.add(
                    C.CONTRACT_PARAM_MISMATCH,
                    f"{path}/{name}",
                    f"{parameter['in']} parameter '{name}' of '{operation_id}': {problem}",
                    backend_path=self.op_pointer(operation_id),
                )
        for name, parameter in params.items():
            if parameter.get("required") and name not in given:
                self.add(
                    C.CONTRACT_PARAM_MISMATCH,
                    path,
                    f"'{operation_id}' needs the {parameter['in']} parameter '{name}'",
                    backend_path=self.op_pointer(operation_id),
                    hint=f'e.g. "{name}": "$route.{name}"',
                )

    def response_record(self, operation_id: str) -> dict[str, Any]:
        return _response_record(self.contract, self.operations[operation_id]["operation"])

    def bindings(self) -> None:
        for p_index, page in enumerate(self.frontend.get("pages", [])):
            for section, section_path in _sections(page.get("sections", []), f"/pages/{p_index}/sections"):
                content = section.get("content") or {}
                # 1. Section actions (DataTable, CardGrid, List, DetailView, ActionBar)
                for a_index, action in enumerate(content.get("actions") or []):
                    action_path = f"{section_path}/content/actions/{a_index}"
                    kind = action.get("kind", "link")
                    if kind == "link":
                        target_page = action.get("page")
                        if target_page:
                            pages = self.frontend.get("pages", [])
                            known_pages = {p.get("id") or page_id(p.get("route") or "") for p in pages} | {
                                p.get("route") for p in pages
                            }
                            if target_page not in known_pages:
                                self.add(
                                    C.FE_UNKNOWN_PAGE,
                                    f"{action_path}/page",
                                    f"Action '{action.get('id', a_index)}' links to unknown page '{target_page}'",
                                )
                    elif kind == "mutation":
                        op_id = action.get("operationId")
                        if not op_id:
                            self.add(
                                C.CONTRACT_UNKNOWN_OPERATION,
                                f"{action_path}/operationId",
                                "Mutation action requires 'operationId'",
                            )
                            continue
                        found_act = self.lookup(op_id, f"{action_path}/operationId")
                        if found_act is None:
                            continue
                        if found_act["method"] == "GET":
                            self.add(
                                C.CONTRACT_METHOD_MISMATCH,
                                f"{action_path}/operationId",
                                f"Mutation actions call mutating operations; '{op_id}' is GET",
                                backend_path=self.op_pointer(op_id),
                            )
                        if found_act["method"] == "DELETE" and not action.get("confirm"):
                            self.add(
                                C.CONTRACT_PARAM_MISMATCH,
                                f"{action_path}/confirm",
                                f"Delete action '{action.get('id', a_index)}' requires 'confirm'",
                                backend_path=self.op_pointer(op_id),
                            )
                        self.parameters(op_id, action.get("params") or {}, f"{action_path}/params")
                        if action.get("body"):
                            body_content = (
                                (found_act["operation"].get("requestBody") or {})
                                .get("content", {})
                                .get("application/json", {})
                            )
                            body_schema = resolve(self.contract, body_content.get("schema") or {})
                            props = body_schema.get("properties") or {}
                            for k, v in action["body"].items():
                                if k not in props:
                                    self.add(
                                        C.CONTRACT_FIELD_MISSING,
                                        f"{action_path}/body/{k}",
                                        f"The request of '{op_id}' has no field '{k}'",
                                        backend_path=self.op_pointer(op_id),
                                        hint=self.undeclared(op_id, "request"),
                                    )
                                else:
                                    prob = _value_fits(v, resolve(self.contract, props[k]))
                                    if prob:
                                        self.add(
                                            C.CONTRACT_FIELD_TYPE_MISMATCH,
                                            f"{action_path}/body/{k}",
                                            f"Action body field '{k}': {prob}",
                                            backend_path=self.op_pointer(op_id),
                                        )

                # 2. Stats items data binding
                if section.get("component") == "Stats":
                    for i_index, item in enumerate(content.get("items") or []):
                        stat_data = item.get("data")
                        if stat_data:
                            stat_op = stat_data.get("operationId")
                            if stat_op:
                                found_stat = self.lookup(
                                    stat_op, f"{section_path}/content/items/{i_index}/data/operationId"
                                )
                                if found_stat:
                                    if found_stat["method"] != "GET":
                                        self.add(
                                            C.CONTRACT_METHOD_MISMATCH,
                                            f"{section_path}/content/items/{i_index}/data/operationId",
                                            f"Stats read data; '{stat_op}' is {found_stat['method']} "
                                            f"{found_stat['path']}",
                                            backend_path=self.op_pointer(stat_op),
                                        )
                                    val = stat_data.get("value", "count")
                                    if val != "count":
                                        stat_record = self.response_record(stat_op)
                                        stat_props = stat_record.get("properties") or {}
                                        if val not in stat_props:
                                            self.add(
                                                C.CONTRACT_FIELD_MISSING,
                                                f"{section_path}/content/items/{i_index}/data/value",
                                                f"The response of '{stat_op}' has no field '{val}'",
                                                backend_path=self.op_pointer(stat_op),
                                                hint=self.undeclared(stat_op, "response"),
                                            )

                # 3. Section data binding
                data = section.get("data") or {}
                operation_id = data.get("operationId")
                if operation_id is None:
                    continue
                path = f"{section_path}/data"
                found = self.lookup(operation_id, f"{path}/operationId")
                if found is None:
                    continue
                if found["method"] != "GET":
                    self.add(
                        C.CONTRACT_METHOD_MISMATCH,
                        f"{path}/operationId",
                        f"Sections read data; '{operation_id}' is {found['method']} {found['path']} (use a form)",
                        backend_path=self.op_pointer(operation_id),
                    )
                    continue
                self.parameters(operation_id, data.get("params") or {}, f"{path}/params")
                if (
                    section.get("component") in LIST_SECTIONS
                    and (found["operation"].get("x-bga") or {}).get("action") != "list"
                ):
                    # The renderer draws these from a list; one record would send the whole site to the engine.
                    self.add(
                        C.CONTRACT_SHAPE_MISMATCH,
                        f"{path}/operationId",
                        f"{section['component']} shows a list; '{operation_id}' returns one record",
                        backend_path=self.op_pointer(operation_id),
                        hint=(
                            "Bind a list operation, or declare the custom operation's response as a list: "
                            '"response": {"type": "array", "properties": [...]} (or "entity")'
                        ),
                    )
                record = self.response_record(operation_id)
                properties = record.get("properties") or {}
                for f_index, field in enumerate(data.get("fields") or []):
                    if field not in properties:
                        self.add(
                            C.CONTRACT_FIELD_MISSING,
                            f"{path}/fields/{f_index}",
                            f"The response of '{operation_id}' has no field '{field}'",
                            backend_path=self.field_pointer(operation_id),
                            hint=self.undeclared(operation_id, "response") or f"Fields: {', '.join(properties)}",
                        )

                # 4. List controls (search, filters, sort)
                controls = content.get("controls")
                if controls:
                    op_query_params = {
                        p["name"]: p for p in found["operation"].get("parameters") or [] if p.get("in") == "query"
                    }
                    if controls.get("search") and "q" not in op_query_params and "search" not in op_query_params:
                        self.add(
                            C.CONTRACT_PARAM_MISMATCH,
                            f"{section_path}/content/controls/search",
                            f"'{operation_id}' does not declare a search parameter ('q')",
                            backend_path=self.op_pointer(operation_id),
                        )
                    for f_idx, flt in enumerate(controls.get("filters") or []):
                        if flt not in op_query_params:
                            self.add(
                                C.CONTRACT_PARAM_MISMATCH,
                                f"{section_path}/content/controls/filters/{f_idx}",
                                f"'{operation_id}' has no query parameter '{flt}'",
                                backend_path=self.op_pointer(operation_id),
                            )
                    if controls.get("sort"):
                        sort_param = op_query_params.get("sort")
                        allowed_sort: set[str] = set()
                        if sort_param:
                            sort_schema = resolve(self.contract, sort_param.get("schema") or {})
                            allowed_sort = set(sort_schema.get("enum") or [])
                        for s_idx, s in enumerate(controls.get("sort") or []):
                            bare_s = s.removeprefix("-").removesuffix(":asc").removesuffix(":desc")
                            valid = bool(
                                sort_param
                                and (
                                    not allowed_sort
                                    or s in allowed_sort
                                    or bare_s in allowed_sort
                                    or f"{bare_s}:asc" in allowed_sort
                                    or f"-{bare_s}" in allowed_sort
                                )
                            )
                            if not valid:
                                self.add(
                                    C.CONTRACT_PARAM_MISMATCH,
                                    f"{section_path}/content/controls/sort/{s_idx}",
                                    f"Sort field '{s}' is not allowed by '{operation_id}'",
                                    backend_path=self.op_pointer(operation_id),
                                )

    def forms(self) -> None:
        for f_index, form in enumerate(self.frontend.get("forms", [])):
            path = f"/forms/{f_index}"
            load = form.get("load")
            if load:
                load_op_id = load.get("operationId")
                if load_op_id:
                    found_load = self.lookup(load_op_id, f"{path}/load/operationId")
                    if found_load:
                        if found_load["method"] != "GET":
                            self.add(
                                C.CONTRACT_METHOD_MISMATCH,
                                f"{path}/load/operationId",
                                f"Form load reads data; '{load_op_id}' is {found_load['method']} {found_load['path']}",
                                backend_path=self.op_pointer(load_op_id),
                            )
                        else:
                            self.parameters(load_op_id, load.get("params") or {}, f"{path}/load/params")
                            load_record = self.response_record(load_op_id)
                            load_props = load_record.get("properties") or {}
                            for i, field in enumerate(form.get("fields", [])):
                                fname = field.get("name")
                                if fname and fname not in load_props:
                                    self.add(
                                        C.CONTRACT_FIELD_MISSING,
                                        f"{path}/fields/{i}/name",
                                        f"The response of '{load_op_id}' has no field '{fname}'",
                                        backend_path=self.field_pointer(load_op_id),
                                        hint=self.undeclared(load_op_id, "response")
                                        or f"Fields: {', '.join(load_props)}",
                                    )

            operation_id = form.get("operationId")
            if operation_id is None:
                continue
            found = self.lookup(operation_id, f"{path}/operationId")
            if found is None:
                continue
            if found["method"] == "GET":
                self.add(
                    C.CONTRACT_METHOD_MISMATCH,
                    f"{path}/operationId",
                    f"Forms submit data; '{operation_id}' is GET {found['path']}",
                    backend_path=self.op_pointer(operation_id),
                )
                continue
            self.parameters(operation_id, form.get("params") or {}, f"{path}/params")
            body = (found["operation"].get("requestBody") or {}).get("content", {}).get("application/json", {})
            schema = resolve(self.contract, body.get("schema", {}))
            properties, required = schema.get("properties") or {}, set(schema.get("required") or [])
            collected = set()
            for i, field in enumerate(form.get("fields", [])):
                name, field_path = field["name"], f"{path}/fields/{i}"
                collected.add(name)
                contract_field = properties.get(name)
                if contract_field is None:
                    self.add(
                        C.CONTRACT_FIELD_MISSING,
                        f"{field_path}/name",
                        f"The request of '{operation_id}' has no field '{name}'",
                        backend_path=self.field_pointer(operation_id),
                        hint=self.undeclared(operation_id, "request")
                        or f"Fields: {', '.join(properties) or '(no body)'}",
                    )
                    continue
                self.form_field(
                    operation_id, field, resolve(self.contract, contract_field), name in required, field_path
                )
                self.field_source(operation_id, field, contract_field, field_path)
            for name in sorted(required - collected):
                self.add(
                    C.CONTRACT_FIELD_MISSING,
                    f"{path}/fields",
                    f"'{operation_id}' requires '{name}', which the form does not collect",
                    backend_path=self.field_pointer(operation_id, name),
                    hint="Add a field (hidden with a fixed or $route value if the user should not type it)",
                )

    def field_source(self, operation_id: str, field: dict, contract_field: dict, path: str) -> None:
        """Story 10.0b: a visible field for a reference asks the user to type a record's id (`x-bga.source`). An app's
        field picks the record by name (`reference`, Story 22.6); without one it is an error in an app, a warning in the
        legacy flow (which has no picker)."""
        meta = contract_field.get("x-bga") or {}
        if meta.get("source") != "reference" or field.get("hidden") or field.get("value") is not None:
            return
        if field.get("reference"):
            return
        entity = (meta.get("ref") or {}).get("entity") or "record"
        self.add(
            C.FE_FIELD_SOURCE,
            path,
            f"Form field '{field['name']}' asks the user to type a {entity} id",
            backend_path=self.field_pointer(operation_id, field["name"]),
            hint=f'Show the form on the {entity}\'s page and take it from the route (hidden, value "$route.id"), '
            "or let the user pick it by name (an app field's `reference`)",
            warning=not is_app_spec(self.frontend),
        )

    def form_field(self, operation_id: str, field: dict, schema: dict, required: bool, path: str) -> None:
        kind, form_format = FORM_TYPES[field.get("type", "string")]
        types = _types(schema)
        backend_path = self.field_pointer(operation_id, field["name"])
        fits = "any" in types or kind in types or (kind == "integer" and "number" in types)
        if not fits:
            self.add(
                C.CONTRACT_FIELD_TYPE_MISMATCH,
                f"{path}/type",
                f"Form field '{field['name']}' submits {kind}; the contract expects {' | '.join(sorted(types))}",
                backend_path=backend_path,
            )
            return
        contract_format = schema.get("format")
        if contract_format in ("date", "date-time") and form_format != contract_format:
            expected = "date" if contract_format == "date" else "datetime"
            self.add(
                C.CONTRACT_FIELD_TYPE_MISMATCH,
                f"{path}/type",
                f"Form field '{field['name']}' should be type '{expected}' (the contract expects {contract_format})",
                backend_path=backend_path,
            )
        enum = [value for value in schema.get("enum") or [] if value is not None]
        if enum and not field.get("hidden"):
            values = field.get("values") or []
            if field.get("type") != "enum":
                self.add(
                    C.CONTRACT_FIELD_TYPE_MISMATCH,
                    f"{path}/type",
                    f"Form field '{field['name']}' must be an enum of {', '.join(enum)}",
                    backend_path=backend_path,
                )
            elif set(values) - set(enum):
                self.add(
                    C.CONTRACT_FIELD_TYPE_MISMATCH,
                    f"{path}/values",
                    f"Values {', '.join(sorted(set(values) - set(enum)))} are not allowed by the contract",
                    backend_path=backend_path,
                )
        if required and not field.get("required") and field.get("value") is None:
            self.add(
                C.CONTRACT_FIELD_TYPE_MISMATCH,
                f"{path}/required",
                f"'{field['name']}' is required by '{operation_id}'; mark the form field required",
                backend_path=backend_path,
            )

    def seed_assets(self) -> None:
        if not self.backend:
            return
        assets = {a.get("id") for a in self.frontend.get("assets", []) if isinstance(a, dict)}
        seed = self.backend.get("seed") or []
        if isinstance(seed, list):
            for s_index, entry in enumerate(seed):
                if not isinstance(entry, dict):
                    continue
                records = entry.get("records") or []
                if not isinstance(records, list):
                    continue
                for r_index, record in enumerate(records):
                    if not isinstance(record, dict):
                        continue
                    for field_name, value in record.items():
                        if isinstance(value, str) and value.startswith("asset:"):
                            asset_id = value[len("asset:") :]
                            if asset_id not in assets:
                                self.add(
                                    C.FE_UNKNOWN_ASSET,
                                    "/assets",
                                    f"Seed record references unknown asset '{asset_id}'",
                                    backend_path=f"/seed/{s_index}/records/{r_index}/{field_name}",
                                    warning=True,
                                )
        elif isinstance(seed, dict):
            for entity_name, records in seed.items():
                if not isinstance(records, list):
                    continue
                for r_index, record in enumerate(records):
                    if not isinstance(record, dict):
                        continue
                    for field_name, value in record.items():
                        if isinstance(value, str) and value.startswith("asset:"):
                            asset_id = value[len("asset:") :]
                            if asset_id not in assets:
                                self.add(
                                    C.FE_UNKNOWN_ASSET,
                                    "/assets",
                                    f"Seed record references unknown asset '{asset_id}'",
                                    backend_path=f"/seed/{entity_name}/{r_index}/{field_name}",
                                    warning=True,
                                )

    def app_data(self) -> None:
        """An app (`project.flow: "app"`) is drawn from its BackendSpec's records: with none there is nothing to
        show, and generation would write an empty API client."""
        if not self.has_backend or (self.frontend.get("project") or {}).get("flow") != "app":
            return
        if not self.backend.get("entities") or not self.backend.get("operations"):
            self.add(
                C.FE_APP_FLOW,
                "/app",
                "The app has no data: its BackendSpec declares no entities or no operations",
                backend_path="/entities" if not self.backend.get("entities") else "/operations",
            )

    def coverage(self) -> None:
        from src.modules.shared.domain.frontend_spec import uncovered_operations

        uncovered = uncovered_operations(self.frontend, self.contract)
        for op_id in uncovered:
            self.add(
                C.FE_OPERATION_UNUSED,
                "/pages",
                f"API operation '{op_id}' is uncovered: not referenced in the frontend",
                warning=True,
                backend_path=self.op_pointer(op_id) if op_id in self.operations else None,
            )


def check_consistency(
    frontend: dict[str, Any], contract: dict[str, Any], backend: dict[str, Any] | None = None
) -> list[SpecIssue]:
    """`frontend` and `backend` are the normalized specs; `contract` comes from `build_contract(backend)`."""
    checker = _Checker(frontend, contract, backend)
    checker.app_data()
    checker.bindings()
    checker.forms()
    checker.seed_assets()
    checker.coverage()
    return checker.issues


def check_spec_pair(frontend: dict[str, Any], backend: dict[str, Any]) -> list[SpecIssue]:
    """Both normalized specs: builds the contract the backend lane would get and checks the frontend against it."""
    return check_consistency(frontend, build_contract(backend), backend)


def _note(path: str, message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": path, "message": message, "suggestion": None}


def _name_tokens(name: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)]


def closest_field(name: str, available: list[str]) -> str | None:
    """The response field a misnamed one most likely means (`totalValue` → `totalStockValue`): the same name in
    another case or separator, then one whose words contain the other's, then a close spelling. None when nothing
    is close, or two fields are equally close."""
    import difflib

    words = _name_tokens(name)
    scored: list[tuple[float, str]] = []
    for candidate in available:
        other = _name_tokens(candidate)
        if words and words == other:
            score = 1.0
        elif words and other and (set(words) <= set(other) or set(other) <= set(words)):
            score = 0.9 - 0.01 * abs(len(words) - len(other))
        else:
            score = difflib.SequenceMatcher(None, name.lower(), candidate.lower()).ratio()
            if score < 0.75:
                continue
        scored.append((score, candidate))
    scored.sort(reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def _heal_response_fields(
    data: dict[str, Any], operation_id: str, properties: list[str], path: str, notes: list[dict[str, Any]]
) -> None:
    """Section `data.fields` the response does not have: renamed to the closest response field, else dropped."""
    fields = data.get("fields")
    if not isinstance(fields, list):
        return
    healed: list[Any] = []
    for index, field in enumerate(fields):
        if not isinstance(field, str) or field in properties:
            healed.append(field)
            continue
        match = closest_field(field, [p for p in properties if p not in fields and p not in healed])
        if match is not None:
            healed.append(match)
            notes.append(
                _note(f"{path}/fields/{index}", f"Field '{field}' is '{match}' in the response of '{operation_id}'.")
            )
        else:
            notes.append(
                _note(
                    f"{path}/fields/{index}",
                    f"Field '{field}' is not in the response of '{operation_id}' ({', '.join(properties)}); dropped.",
                )
            )
    if healed:
        data["fields"] = healed
    else:
        del data["fields"]


def _fill_path_params(
    target: dict[str, Any],
    operation_id: str,
    operation: dict[str, Any],
    path: str,
    route: set[str],
    record: set[str] | None,
    notes: list[dict[str, Any]],
) -> None:
    """Fills the missing required path parameters of `target["params"]`. Inside a record context (`record` is the
    record's fields) from the record: `$record.<p>`, or the record's `id` for the operation's last path parameter;
    otherwise from the page route when it has the parameter. Anything else is left for the check, with a note."""
    names = [
        p["name"]
        for p in operation.get("parameters") or []
        if p.get("in") == "path" and p.get("required", True) and p.get("name")
    ]
    params = target.get("params") if isinstance(target.get("params"), dict) else {}
    for index, name in enumerate(names):
        if name in params:
            continue
        value = None
        if record is not None:
            if name in record:
                value = f"$record.{name}"
            elif (name == "id" or index == len(names) - 1) and ("id" in record or not record):
                value = "$record.id"
        if value is None and name in route:
            value = f"$route.{name}"
        if value is None:
            notes.append(
                _note(
                    f"{path}/params",
                    f"Could not fill the path parameter '{name}' of '{operation_id}': there is no record here and "
                    f"the page route has no '[{name}]'; set it by hand.",
                )
            )
            continue
        params[name] = value
        target["params"] = params
        if value == "$record.id" and name != "id":
            notes.append(
                _note(
                    f"{path}/params/{name}",
                    f"Assumed the path parameter '{name}' of '{operation_id}' is the record's id.",
                )
            )


def _form_routes(pages: list[Any]) -> dict[str, set[str]]:
    """Form id → the route parameters every page showing the form has."""
    routes: dict[str, set[str]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        params = set(route_params(page.get("route") or ""))
        for section, _ in _sections(page.get("sections") or [], ""):
            form_id = section.get("form") if isinstance(section, dict) else None
            if isinstance(form_id, str):
                routes[form_id] = routes[form_id] & params if form_id in routes else set(params)
    return routes


def _form_route_values(pages: list[Any]) -> dict[str, list[dict[str, str]]]:
    """Form id → per page showing it, what its route gives: `{operationId: "$route.<p>"}` for each section bound
    to one record by a route parameter (`deck.get` with `{"id": "$route.id"}`), plus `{"$<p>": ...}` per parameter."""
    values: dict[str, list[dict[str, str]]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        given = {f"${name}": f"$route.{name}" for name in route_params(page.get("route") or "")}
        forms = []
        for section, _ in _sections(page.get("sections") or [], ""):
            if not isinstance(section, dict):
                continue
            data = section.get("data") if isinstance(section.get("data"), dict) else {}
            route_values = [
                v for v in (data.get("params") or {}).values() if isinstance(v, str) and v.startswith("$route.")
            ]
            if data.get("operationId") and len(route_values) == 1:
                given[data["operationId"]] = route_values[0]
            if isinstance(section.get("form"), str):
                forms.append(section["form"])
        for form_id in forms:
            values.setdefault(form_id, []).append(given)
    return values


def _route_sources(
    form: dict[str, Any], f_idx: int, props: dict[str, Any], pages: list[dict[str, str]], notes: list[dict[str, Any]]
) -> None:
    """Story 10.0b: a visible reference field on a page that already shows the parent (its detail bound to a route
    parameter, or a route parameter of the field's name) is hidden and takes that parameter."""
    if not pages:
        return
    for fld_idx, field in enumerate(form.get("fields") or []):
        if not isinstance(field, dict) or field.get("hidden") or field.get("value") is not None:
            continue
        meta = (props.get(field.get("name")) or {}).get("x-bga") or {}
        if meta.get("source") != "reference":
            continue
        detail = (meta.get("ref") or {}).get("detailOperation")
        found = {page.get(detail or "") or page.get(f"${field['name']}") for page in pages}
        if len(found) != 1 or None in found:
            continue  # not every page showing the form knows the parent
        value = found.pop()
        field["hidden"], field["value"] = True, value
        notes.append(
            _note(
                f"/forms/{f_idx}/fields/{fld_idx}",
                f"Field '{field['name']}' of form '{form.get('id')}' now takes the {meta['ref']['entity']} from the "
                f"page ({value}) instead of asking for its id.",
            )
        )


def reconcile_spec_pair(
    frontend: dict[str, Any], backend: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Auto-heals FrontendSpec inconsistencies against the BackendSpec contract:
    - Clears dangling/unknown or invalid operationIds on forms so they become client-only forms
    - Prunes form fields not in request schema, or adds hidden defaults for missing required fields
    - Clears unknown load.operationId on forms
    - Converts mutation actions with unknown operations to link actions; points links to unknown pages at the
      first page
    - Fills missing path parameters from the record (row/card actions) or the page route, when either has them
    - Adds confirmation prompt to DELETE actions if missing
    - Clears unknown operationIds from section data bindings or stats items
    - Renames section data fields and stats values the response lacks to its closest field (else drops them)
    - Prunes unsupported section controls (search/filter/sort)
    - Declares placeholder assets for seed records that reference undeclared (valid) asset ids
    Works on a copy and never changes the BackendSpec (it is already stored and seeds the backend). Every change
    is reported in the notes. Returns (healed_frontend, notes).
    """
    if not isinstance(frontend, dict) or not isinstance(backend, dict):
        return frontend, []

    try:
        contract = build_contract(backend)
    except Exception:
        return frontend, []

    frontend = copy.deepcopy(frontend)
    ops = contract_operations(contract)
    notes: list[dict[str, Any]] = []
    pages = frontend.get("pages") if isinstance(frontend.get("pages"), list) else []
    form_routes = _form_routes(pages)
    form_values = _form_route_values(pages)

    # 1. Forms
    forms = frontend.get("forms")
    if isinstance(forms, list):
        for f_idx, form in enumerate(forms):
            if not isinstance(form, dict):
                continue
            f_id = form.get("id") or f"form-{f_idx}"
            route = form_routes.get(form.get("id"), set())
            op_id = form.get("operationId")
            if op_id:
                if op_id not in ops:
                    form["operationId"] = None
                    notes.append(
                        _note(
                            f"/forms/{f_idx}/operationId",
                            f"Operation '{op_id}' is not in the API contract; "
                            f"cleared form '{f_id}' to client-only submission.",
                        )
                    )
                elif ops[op_id]["method"] == "GET":
                    form["operationId"] = None
                    notes.append(
                        _note(
                            f"/forms/{f_idx}/operationId",
                            f"Operation '{op_id}' is GET; cleared form '{f_id}' to client-only submission.",
                        )
                    )
                else:
                    found_op = ops[op_id]
                    _fill_path_params(form, op_id, found_op["operation"], f"/forms/{f_idx}", route, None, notes)

                    body_content = (
                        (found_op["operation"].get("requestBody") or {}).get("content", {}).get("application/json", {})
                    )
                    schema = resolve(contract, body_content.get("schema") or {})
                    props = schema.get("properties") or {}
                    required = set(schema.get("required") or [])

                    if props and isinstance(form.get("fields"), list):
                        valid_fields = []
                        for fld_idx, fld in enumerate(form["fields"]):
                            if isinstance(fld, dict):
                                fname = fld.get("name")
                                if fname in props:
                                    valid_fields.append(fld)
                                else:
                                    notes.append(
                                        _note(
                                            f"/forms/{f_idx}/fields/{fld_idx}",
                                            f"Field '{fname}' of form '{f_id}' is not in the request of '{op_id}'; "
                                            "removed (the user can no longer enter it).",
                                        )
                                    )
                        form["fields"] = valid_fields

                    _route_sources(form, f_idx, props, form_values.get(form.get("id"), []), notes)
                    existing_names = {f.get("name") for f in form.get("fields") or [] if isinstance(f, dict)}
                    for req_name in sorted(required - existing_names):
                        prop_schema = resolve(contract, props.get(req_name) or {})
                        types = _types(prop_schema)
                        field_type = "string"
                        val: Any = ""
                        if "integer" in types or "number" in types:
                            field_type = "integer"
                            val = 0
                        elif "boolean" in types:
                            field_type = "boolean"
                            val = False
                        form.setdefault("fields", []).append(
                            {
                                "name": req_name,
                                "type": field_type,
                                "hidden": True,
                                "value": val,
                            }
                        )
                        notes.append(
                            _note(
                                f"/forms/{f_idx}/fields",
                                f"Added the required field '{req_name}' of '{op_id}' to form '{f_id}' as a hidden "
                                f"field that always submits {val!r}; make it visible or set its value.",
                            )
                        )

            load = form.get("load")
            if isinstance(load, dict):
                load_op = load.get("operationId")
                if load_op and (load_op not in ops or ops[load_op]["method"] != "GET"):
                    del form["load"]
                    notes.append(
                        _note(
                            f"/forms/{f_idx}/load",
                            f"Invalid load operationId '{load_op}' removed from form '{f_id}'.",
                        )
                    )
                elif load_op and load_op in ops:
                    _fill_path_params(
                        load, load_op, ops[load_op]["operation"], f"/forms/{f_idx}/load", route, None, notes
                    )

    # 2. Pages and sections
    # Links name pages by id (the route's id when a page has none); a link given as a route is pointed at its id.
    page_ids = {p["route"]: p.get("id") or page_id(p["route"]) for p in pages if isinstance(p, dict) and p.get("route")}
    known_pages: set[str] = set(page_ids.values())
    first_page: str = next(iter(page_ids.values()), "home")

    def _page_target(target: Any) -> Any:
        return page_ids.get(target, target) if isinstance(target, str) else target

    for p_idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        route = set(route_params(page.get("route") or ""))
        for sec, sec_path in _sections(page.get("sections") or [], f"/pages/{p_idx}/sections"):
            if not isinstance(sec, dict):
                continue
            data = sec.get("data")
            # Row/card actions of a section showing records can read `$record` (the renderer passes the record).
            record: set[str] | None = None
            if sec.get("component") in RECORD_SECTIONS and isinstance(data, dict):
                data_op = data.get("operationId")
                if data_op in ops and ops[data_op]["method"] == "GET":
                    record = set(_response_record(contract, ops[data_op]["operation"]).get("properties") or {})
                elif data.get("collection"):
                    record = set()
            content = sec.get("content")
            if isinstance(content, dict):
                # Actions
                actions = content.get("actions")
                if isinstance(actions, list):
                    for a_idx, action in enumerate(actions):
                        if not isinstance(action, dict):
                            continue
                        action_path = f"{sec_path}/content/actions/{a_idx}"
                        a_id = action.get("id") or a_idx
                        if action.get("kind") == "link":
                            if "page" in action:
                                action["page"] = _page_target(action["page"])
                            target_page = action.get("page")
                            if target_page and target_page not in known_pages:
                                action["page"] = first_page
                                notes.append(
                                    _note(
                                        f"{action_path}/page",
                                        f"Link action '{a_id}' pointed at unknown page '{target_page}'; "
                                        f"it now links to '{first_page}'.",
                                    )
                                )
                        elif action.get("kind") == "mutation":
                            act_op = action.get("operationId")
                            if not act_op or act_op not in ops or ops[act_op]["method"] == "GET":
                                target_page = _page_target(action.get("page"))
                                if not target_page or target_page not in known_pages:
                                    target_page = first_page
                                action["kind"] = "link"
                                action["page"] = target_page
                                action.pop("operationId", None)
                                action.pop("body", None)
                                action.pop("params", None)
                                reason = (
                                    "has no operation"
                                    if not act_op
                                    else f"calls '{act_op}', which is GET"
                                    if act_op in ops
                                    else f"calls '{act_op}', which is not in the API contract"
                                )
                                notes.append(
                                    _note(
                                        action_path,
                                        f"Mutation action '{a_id}' {reason}; converted to a link to "
                                        f"'{target_page}' (it no longer changes data).",
                                    )
                                )
                            else:
                                if ops[act_op]["method"] == "DELETE" and not action.get("confirm"):
                                    action["confirm"] = "Are you sure you want to proceed?"
                                _fill_path_params(
                                    action, act_op, ops[act_op]["operation"], action_path, route, record, notes
                                )
                # Stats
                if sec.get("component") == "Stats" and isinstance(content.get("items"), list):
                    for i_idx, item in enumerate(content["items"]):
                        if isinstance(item, dict) and isinstance(item.get("data"), dict):
                            stat_op = item["data"].get("operationId")
                            if stat_op and (stat_op not in ops or ops[stat_op]["method"] != "GET"):
                                del item["data"]
                                notes.append(
                                    _note(
                                        f"{sec_path}/content/items/{i_idx}/data",
                                        f"Stats item invalid operation '{stat_op}' removed.",
                                    )
                                )
                            elif stat_op and item["data"].get("value", "count") != "count":
                                value = item["data"]["value"]
                                stat_props = list(
                                    _response_record(contract, ops[stat_op]["operation"]).get("properties") or {}
                                )
                                if value not in stat_props:
                                    match = closest_field(value, stat_props)
                                    stat_path = f"{sec_path}/content/items/{i_idx}/data"
                                    if match is not None:
                                        item["data"]["value"] = match
                                        notes.append(
                                            _note(
                                                f"{stat_path}/value",
                                                f"Stats value '{value}' is '{match}' in the response of '{stat_op}'.",
                                            )
                                        )
                                    else:
                                        del item["data"]
                                        notes.append(
                                            _note(
                                                stat_path,
                                                f"Stats item reads '{value}', which '{stat_op}' does not return; "
                                                "its data binding was removed.",
                                            )
                                        )

            # Section data binding
            if isinstance(data, dict):
                sec_op = data.get("operationId")
                if sec_op:
                    if sec_op not in ops or ops[sec_op]["method"] != "GET":
                        del sec["data"]
                        notes.append(
                            _note(
                                f"{sec_path}/data",
                                f"Section data binding with invalid operation '{sec_op}' removed.",
                            )
                        )
                    else:
                        _fill_path_params(
                            data, sec_op, ops[sec_op]["operation"], f"{sec_path}/data", route, None, notes
                        )
                        _heal_response_fields(
                            data,
                            sec_op,
                            list(_response_record(contract, ops[sec_op]["operation"]).get("properties") or {}),
                            f"{sec_path}/data",
                            notes,
                        )

                        if isinstance(content, dict) and isinstance(content.get("controls"), dict):
                            controls = content["controls"]
                            op_params = {
                                p["name"]: p
                                for p in ops[sec_op]["operation"].get("parameters") or []
                                if p.get("in") == "query"
                            }
                            if controls.get("search") and "q" not in op_params and "search" not in op_params:
                                controls["search"] = False
                            if isinstance(controls.get("filters"), list):
                                controls["filters"] = [f for f in controls["filters"] if f in op_params]
                            if controls.get("sort") and "sort" not in op_params:
                                controls["sort"] = []

    # 3. Seed asset references: declare the missing (valid) asset ids as placeholders. The BackendSpec is left
    # alone: an id that is not a valid asset id stays a consistency warning (the site shows a placeholder).
    existing_asset_ids = {
        a.get("id") for a in frontend.get("assets", []) if isinstance(a, dict) and isinstance(a.get("id"), str)
    }
    seed = backend.get("seed")

    def _declare_seed_assets(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, str) and v.startswith("asset:"):
                    aid = v[len("asset:") :]
                    if aid in existing_asset_ids:
                        continue
                    existing_asset_ids.add(aid)
                    if not _ASSET_ID.match(aid):
                        notes.append(
                            _note(
                                "/assets",
                                f"Seed records reference '{v}', which is not a valid asset id; fix the BackendSpec "
                                "seed (the site shows a placeholder for it).",
                            )
                        )
                        continue
                    kind = "logo" if "logo" in aid else "icon" if "icon" in aid else "image"
                    frontend.setdefault("assets", []).append(
                        {"id": aid, "kind": kind, "source": "placeholder", "alt": aid.replace("-", " ").title()}
                    )
                    notes.append(_note(f"/assets/{aid}", f"Added missing asset '{aid}' referenced by seed records."))
                else:
                    _declare_seed_assets(v)
        elif isinstance(obj, list):
            for item in obj:
                _declare_seed_assets(item)

    if seed:
        _declare_seed_assets(seed)

    return frontend, notes
