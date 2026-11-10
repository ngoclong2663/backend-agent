import json
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from .issues import Severity, SpecIssue, SpecIssueCode, ValidationReport
from .media import PLAYABLE, is_file_kind, is_media_kind, playable_problem
from .naming import table_name, to_snake
from .normalizer import default_foreign_key, normalize_spec, owning_entity
from .registry import SPEC_MODELS
from .schema_v1 import BackendSpecV1, Entity, FieldDef, JobTrigger, Operation, Rule

C = SpecIssueCode
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_ACTION_METHODS = {
    "create": {"POST"},
    "get": {"GET"},
    "list": {"GET"},
    "update": {"PUT", "PATCH"},
    "delete": {"DELETE"},
}
_ITEM_ACTIONS = {"get", "update", "delete"}


@dataclass
class SpecValidationResult:
    report: ValidationReport
    spec: BackendSpecV1 | None = None
    normalized: dict[str, Any] | None = None


def validate_spec_text(raw: str | bytes) -> SpecValidationResult:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        where = f" (line {exc.lineno}, column {exc.colno})" if isinstance(exc, json.JSONDecodeError) else ""
        issue = SpecIssue(code=C.JSON_MALFORMED, path="", message=f"Body is not valid JSON{where}: {exc}")
        return SpecValidationResult(ValidationReport.from_issues([issue], None))
    return validate_spec_data(data)


def validate_spec_data(data: Any) -> SpecValidationResult:
    if not isinstance(data, dict):
        issue = SpecIssue(code=C.SCHEMA_VIOLATION, path="", message="BackendSpec must be a JSON object")
        return SpecValidationResult(ValidationReport.from_issues([issue], None))

    version = data.get("specVersion")
    model = SPEC_MODELS.get(version) if isinstance(version, str) else None
    if model is None:
        issue = SpecIssue(
            code=C.SPEC_VERSION_UNSUPPORTED,
            path="/specVersion",
            message=f"Unsupported specVersion {version!r}",
            hint=f"Supported versions: {', '.join(SPEC_MODELS)}",
        )
        return SpecValidationResult(ValidationReport.from_issues([issue], None))

    try:
        spec = model.model_validate(data)
    except ValidationError as exc:
        issues = [_schema_issue(error) for error in exc.errors()]
        return SpecValidationResult(ValidationReport.from_issues(issues, version))

    issues = _SemanticChecker(spec).run()
    report = ValidationReport.from_issues(issues, version)
    return SpecValidationResult(report, spec, normalize_spec(spec) if report.valid else None)


def _schema_issue(error: dict[str, Any]) -> SpecIssue:
    path = "".join(f"/{part}" for part in error["loc"])
    message = "Unknown property" if error["type"] == "extra_forbidden" else error["msg"]
    return SpecIssue(code=C.SCHEMA_VIOLATION, path=path, message=message)


def _norm_route(path: str) -> str:
    return _PATH_PARAM.sub("{}", path.rstrip("/") or "/")


def value_matches_type(value: Any, field: FieldDef) -> bool:
    """Shared by defaults and seed rows; `None` is handled by callers (nullability)."""
    kind = field.type
    if kind in ("string", "text") or is_file_kind(kind):
        return isinstance(value, str) and (field.max_length is None or len(value) <= field.max_length)
    if kind == "uuid":
        return isinstance(value, str) and _parses(uuid.UUID, value)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool) and _in_range(value, field)
    if kind in ("float", "decimal"):
        return isinstance(value, int | float) and not isinstance(value, bool) and _in_range(value, field)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "date":
        return isinstance(value, str) and (value == "now" or _parses(date.fromisoformat, value))
    if kind == "datetime":
        return isinstance(value, str) and (value == "now" or _parses(datetime.fromisoformat, value))
    if kind == "enum":
        return isinstance(value, str) and value in (field.values or [])
    return True


def _parses(parser, value: str) -> bool:
    try:
        parser(value)
        return True
    except ValueError:
        return False


def _in_range(value: float, field: FieldDef) -> bool:
    return (field.min is None or value >= field.min) and (field.max is None or value <= field.max)


class _SemanticChecker:
    def __init__(self, spec: BackendSpecV1):
        self.spec = spec
        self.issues: list[SpecIssue] = []
        self.entities: dict[str, Entity] = {entity.name: entity for entity in spec.entities}
        self.fields: dict[str, dict[str, FieldDef]] = {
            entity.name: {field.name: field for field in entity.fields} for entity in spec.entities
        }
        self.policies = {policy.name: policy for policy in spec.policies}
        self.rule_ids = {rule.id for rule in spec.rules}

    def run(self) -> list[SpecIssue]:
        self._check_entities()
        self._check_relationships()
        self._check_operations()
        self._check_auth_and_policies()
        self._check_rules()
        self._check_seed()
        self._check_features()
        self._check_bindings()
        self._check_unsupported()
        return self.issues

    def _add(self, code: SpecIssueCode, path: str, message: str, hint: str | None = None, warning: bool = False):
        severity = Severity.WARNING if warning else Severity.ERROR
        self.issues.append(SpecIssue(code=code, path=path, message=message, hint=hint, severity=severity))

    def _entity_ref(self, name: str | None, path: str) -> Entity | None:
        if name is None:
            return None
        entity = self.entities.get(name)
        if entity is None:
            self._add(C.UNKNOWN_ENTITY_REF, path, f"Unknown entity '{name}'", hint=self._known_entities())
        return entity

    def _field_refs(self, entity: Entity | None, names: Iterable[str], path: str) -> None:
        if entity is None:
            return
        for index, name in enumerate(names):
            if name.lstrip("-") not in self.fields[entity.name]:
                self._add(C.UNKNOWN_FIELD_REF, f"{path}/{index}", f"Entity '{entity.name}' has no field '{name}'")

    def _known_entities(self) -> str:
        return f"Known entities: {', '.join(self.entities) or '(none)'}"

    def _check_entities(self) -> None:
        seen_names: dict[str, int] = {}
        seen_tables: dict[str, int] = {}
        for e_index, entity in enumerate(self.spec.entities):
            path = f"/entities/{e_index}"
            keys = ((entity.name.lower(), seen_names, "name"), (self._table(entity), seen_tables, "table"))
            for key, registry, what in keys:
                if key in registry:
                    message = f"Entity {what} '{key}' duplicates /entities/{registry[key]}"
                    self._add(C.DUPLICATE_ENTITY, f"{path}/name", message)
                registry.setdefault(key, e_index)

            primaries = [field for field in entity.fields if field.primary]
            if not primaries:
                self._add(C.PRIMARY_KEY_MISSING, f"{path}/fields", f"Entity '{entity.name}' has no primary key field")
            elif len(primaries) > 1:
                self._add(
                    C.PRIMARY_KEY_MULTIPLE, f"{path}/fields", f"Entity '{entity.name}' has more than one primary key"
                )

            columns: dict[str, int] = {}
            for f_index, field in enumerate(entity.fields):
                f_path = f"{path}/fields/{f_index}"
                column = to_snake(field.name)
                if column in columns:
                    self._add(
                        C.DUPLICATE_FIELD,
                        f"{f_path}/name",
                        f"Field '{field.name}' collides with field #{columns[column]} (column '{column}')",
                    )
                columns.setdefault(column, f_index)
                if field.type == "enum" and not field.values:
                    self._add(C.ENUM_VALUES_MISSING, f"{f_path}/values", f"Enum field '{field.name}' needs 'values'")
                if not is_file_kind(field.type) and (field.accept is not None or field.max_size is not None):
                    key = "accept" if field.accept is not None else "maxSize"
                    self._add(
                        C.SCHEMA_VIOLATION,
                        f"{f_path}/{key}",
                        "'accept' and 'maxSize' are for file, image, video, audio and subtitles fields",
                    )
                for a_index, mime in enumerate(field.accept or []):
                    if not re.fullmatch(r"[a-z]+/([a-z0-9.+-]+|\*)", mime):
                        self._add(C.SCHEMA_VIOLATION, f"{f_path}/accept/{a_index}", f"'{mime}' is not a MIME type")
                    elif is_media_kind(field.type) and (problem := playable_problem(field.type, mime)):
                        # Epic 29 D2: a media field only narrows what browsers play, never asks for transcoding
                        self._add(
                            C.SCHEMA_VIOLATION,
                            f"{f_path}/accept/{a_index}",
                            f"Field '{field.name}': {problem}",
                            hint=f"Use one of: {', '.join(PLAYABLE[field.type])}",
                        )
                if field.default is not None and not value_matches_type(field.default, field):
                    self._add(
                        C.TYPE_DEFAULT_MISMATCH,
                        f"{f_path}/default",
                        f"Default {field.default!r} is not a valid {field.type} for '{field.name}'",
                    )

            for i_index, index in enumerate(entity.indexes):
                self._field_refs(entity, index.fields, f"{path}/indexes/{i_index}/fields")
            for u_index, constraint in enumerate(entity.unique_constraints):
                self._field_refs(entity, constraint, f"{path}/uniqueConstraints/{u_index}")
            if entity.display_field is not None and entity.display_field not in self.fields[entity.name]:
                message = f"Entity '{entity.name}' has no field '{entity.display_field}'"
                self._add(C.UNKNOWN_FIELD_REF, f"{path}/displayField", message)

    def _table(self, entity: Entity) -> str:
        return entity.table or table_name(entity.name)

    def _primary(self, entity: Entity) -> FieldDef | None:
        return next((field for field in entity.fields if field.primary), None)

    def _check_relationships(self) -> None:
        seen: dict[str, int] = {}
        for r_index, rel in enumerate(self.spec.relationships):
            path = f"/relationships/{r_index}"
            if rel.name.lower() in seen:
                self._add(C.DUPLICATE_RELATIONSHIP, f"{path}/name", f"Relationship '{rel.name}' is defined twice")
            seen.setdefault(rel.name.lower(), r_index)

            parent = self._entity_ref(rel.from_, f"{path}/from")
            child = self._entity_ref(rel.to, f"{path}/to")

            if rel.through is not None:
                if rel.type != "many-to-many":
                    self._add(
                        C.MANY_TO_MANY_THROUGH_INVALID, f"{path}/through", "'through' is only valid for many-to-many"
                    )
                elif rel.through in (rel.from_, rel.to):
                    self._add(
                        C.MANY_TO_MANY_THROUGH_INVALID, f"{path}/through", "Join entity must differ from both sides"
                    )
                else:
                    self._entity_ref(rel.through, f"{path}/through")

            if rel.type == "many-to-many":
                if rel.foreign_key is not None:
                    self._add(C.SCHEMA_VIOLATION, f"{path}/foreignKey", "many-to-many uses 'through', not 'foreignKey'")
                continue
            if parent is None or child is None:
                continue
            fk_name = rel.foreign_key or default_foreign_key(parent.name)
            fk_field = self.fields[child.name].get(fk_name)
            if fk_field is None:
                if rel.foreign_key is not None:
                    self._add(
                        C.UNKNOWN_FIELD_REF, f"{path}/foreignKey", f"Entity '{child.name}' has no field '{fk_name}'"
                    )
                continue
            parent_pk = self._primary(parent)
            if parent_pk and fk_field.type != parent_pk.type:
                self._add(
                    C.FOREIGN_KEY_TYPE_MISMATCH,
                    f"{path}/foreignKey",
                    f"'{child.name}.{fk_name}' is {fk_field.type} but '{parent.name}' primary key is {parent_pk.type}",
                )

    def _check_operations(self) -> None:
        ids: dict[str, int] = {}
        routes: dict[tuple[str, str], int] = {}
        for o_index, op in enumerate(self.spec.operations):
            path = f"/operations/{o_index}"
            if op.operation_id in ids:
                self._add(
                    C.DUPLICATE_OPERATION_ID,
                    f"{path}/operationId",
                    f"operationId '{op.operation_id}' duplicates /operations/{ids[op.operation_id]}",
                )
            ids.setdefault(op.operation_id, o_index)

            route = (op.method, _norm_route(op.path))
            if route in routes:
                self._add(
                    C.ROUTE_CONFLICT,
                    f"{path}/path",
                    f"{op.method} {op.path} conflicts with /operations/{routes[route]}",
                    hint="Paths that differ only in parameter names are the same route",
                )
            routes.setdefault(route, o_index)

            entity = self._entity_ref(op.entity, f"{path}/entity")
            if op.type == "crud":
                self._check_crud(op, entity, path)
            elif op.type == "aggregate":
                self._check_aggregate(op, entity, path)
            elif op.entity is None and owning_entity(op, self.spec.entities) is None:
                self._add(
                    C.SCHEMA_VIOLATION,
                    f"{path}/entity",
                    f"Custom operation '{op.operation_id}' needs 'entity': the backend builds every operation in one "
                    "entity's module, so without one it is left out of the backend and the API contract",
                    hint=f"Set it to the entity the operation mostly reads or changes. {self._known_entities()}",
                )
            for key in ("filters", "sort", "search", "ranges"):
                self._field_refs(entity, getattr(op, key), f"{path}/{key}")
            if op.ranges:  # Story 23.4: a range is a list's, on a date
                for r_index, name in enumerate(op.ranges):
                    field = self.fields.get(entity.name, {}).get(name) if entity else None
                    if op.action != "list":
                        self._add(C.SCHEMA_VIOLATION, f"{path}/ranges", "Only a list operation takes 'ranges'")
                        break
                    if field is not None and getattr(field, "type", None) not in ("date", "datetime"):
                        self._add(
                            C.SCHEMA_VIOLATION,
                            f"{path}/ranges/{r_index}",
                            f"A range needs a date or datetime field; '{name}' is a {getattr(field, 'type', '?')}",
                        )
            for key in ("request", "response"):
                self._check_payload(getattr(op, key), f"{path}/{key}")
            for r_index, rule_id in enumerate(op.rules):
                if rule_id not in self.rule_ids:
                    self._add(C.UNKNOWN_RULE_REF, f"{path}/rules/{r_index}", f"Unknown rule '{rule_id}'")

    def _check_aggregate(self, op: Operation, entity: Entity | None, path: str) -> None:
        """Epic 21: an aggregate names its entity, a numeric field (except count), and known group / date fields."""
        if op.entity is None or entity is None:
            self._add(C.SCHEMA_VIOLATION, f"{path}/entity", "aggregate operations require 'entity'")
            return
        if op.aggregate is None:
            self._add(C.SCHEMA_VIOLATION, f"{path}/aggregate", "aggregate operations require 'aggregate'")
            return
        if op.method != "GET":
            self._add(C.SCHEMA_VIOLATION, f"{path}/method", "aggregate operations are GET")
        fields = {field.name: field for field in entity.fields}
        agg = op.aggregate
        if agg.fn != "count":
            if not agg.field:
                self._add(C.SCHEMA_VIOLATION, f"{path}/aggregate/field", f"'{agg.fn}' needs a numeric 'field'")
            elif agg.field not in fields:
                self._add(
                    C.UNKNOWN_FIELD_REF, f"{path}/aggregate/field", f"Entity '{entity.name}' has no field '{agg.field}'"
                )
            elif fields[agg.field].type not in ("integer", "float", "decimal"):
                self._add(
                    C.SCHEMA_VIOLATION,
                    f"{path}/aggregate/field",
                    f"'{agg.fn}' needs a numeric field; '{agg.field}' is {fields[agg.field].type}",
                )
        for key in ("group_by", "date_field"):
            name = getattr(agg, key)
            if name and name not in fields:
                pointer = "groupBy" if key == "group_by" else "dateField"
                self._add(
                    C.UNKNOWN_FIELD_REF, f"{path}/aggregate/{pointer}", f"Entity '{entity.name}' has no field '{name}'"
                )
        if agg.date_field and fields.get(agg.date_field) and fields[agg.date_field].type not in ("date", "datetime"):
            self._add(C.SCHEMA_VIOLATION, f"{path}/aggregate/dateField", f"'{agg.date_field}' is not a date field")
        if agg.period and not agg.date_field and not any(f.type in ("date", "datetime") for f in entity.fields):
            self._add(
                C.SCHEMA_VIOLATION, f"{path}/aggregate/period", f"'{entity.name}' has no date field for the period"
            )
        self._field_refs(entity, list(agg.filters), f"{path}/aggregate/filters")

    def _check_crud(self, op: Operation, entity: Entity | None, path: str) -> None:
        if op.action is None:
            self._add(C.SCHEMA_VIOLATION, f"{path}/action", "crud operations require 'action'")
            return
        if op.entity is None:
            self._add(C.SCHEMA_VIOLATION, f"{path}/entity", "crud operations require 'entity'")
        if op.method not in _ACTION_METHODS[op.action]:
            expected = " or ".join(sorted(_ACTION_METHODS[op.action]))
            self._add(C.METHOD_ACTION_MISMATCH, f"{path}/method", f"'{op.action}' must use {expected}, not {op.method}")

        params = _PATH_PARAM.findall(op.path)
        if len(params) != len(set(params)):
            self._add(C.PATH_PARAM_MISMATCH, f"{path}/path", "Path parameters must be unique")
        if op.action in _ITEM_ACTIONS:
            if not op.path.rstrip("/").endswith("}"):
                self._add(
                    C.PATH_PARAM_MISMATCH,
                    f"{path}/path",
                    f"'{op.action}' needs the record id as the last path segment, e.g. {op.path.rstrip('/')}/{{id}}",
                )
            params = params[:-1]
        if entity is not None:
            for param in params:
                if param not in self.fields[entity.name]:
                    self._add(
                        C.PATH_PARAM_MISMATCH,
                        f"{path}/path",
                        f"Path parameter '{param}' is not a field of '{entity.name}'",
                    )

    def _check_payload(self, payload, path: str) -> None:
        if payload is None:
            return
        entity = self._entity_ref(payload.entity, f"{path}/entity")
        if payload.fields is not None:
            if payload.entity is None:
                self._add(C.SCHEMA_VIOLATION, f"{path}/fields", "'fields' requires 'entity'")
            self._field_refs(entity, payload.fields, f"{path}/fields")
        if payload.entity is None and not payload.properties:
            self._add(C.SCHEMA_VIOLATION, path, "Payload needs 'entity' or 'properties'")

    def _check_auth_and_policies(self) -> None:
        auth = self.spec.auth
        if auth is not None:
            user_entity = self.entities.get(auth.user_entity)
            if user_entity is not None and auth.login_field not in self.fields[user_entity.name]:
                self._add(
                    C.UNKNOWN_FIELD_REF,
                    "/auth/loginField",
                    f"Entity '{auth.user_entity}' has no field '{auth.login_field}'",
                )
        for p_index, policy in enumerate(self.spec.policies):
            if policy.type == "role" and not policy.roles:
                self._add(C.SCHEMA_VIOLATION, f"/policies/{p_index}/roles", "Role policies need at least one role")
            if policy.type == "ownership" and not policy.owner_field:
                self._add(C.SCHEMA_VIOLATION, f"/policies/{p_index}/ownerField", "Ownership policies need 'ownerField'")
            if policy.type == "visibility":  # Story 23.9: which records some roles may see
                self._check_visibility(policy, p_index)
            if auth is not None and auth.roles:
                for key, roles in (("roles", policy.roles), ("bypassRoles", policy.bypass_roles)):
                    for r_index, role in enumerate(roles):
                        if role not in auth.roles:
                            self._add(
                                C.UNKNOWN_ROLE_REF,
                                f"/policies/{p_index}/{key}/{r_index}",
                                f"Role '{role}' is not declared in auth.roles",
                            )

        for o_index, op in enumerate(self.spec.operations):
            path = f"/operations/{o_index}"
            if (op.auth == "jwt" or op.policy) and auth is None:
                self._add(
                    C.AUTH_NOT_CONFIGURED,
                    f"{path}/{'auth' if op.auth == 'jwt' else 'policy'}",
                    f"'{op.operation_id}' requires authentication but the spec has no top-level 'auth'",
                )
            if op.policy is None:
                continue
            policy = self.policies.get(op.policy)
            if policy is None:
                self._add(C.UNKNOWN_POLICY_REF, f"{path}/policy", f"Unknown policy '{op.policy}'")
            elif policy.type == "visibility":
                self._add(
                    C.SCHEMA_VIOLATION,
                    f"{path}/policy",
                    f"Policy '{policy.name}' is a visibility policy: it applies to its entity's reads by itself",
                    hint="Remove 'policy' from the operation; name a role or ownership policy here instead.",
                )
            elif policy.type == "ownership" and policy.owner_field and op.entity in self.fields:
                if policy.owner_field not in self.fields[op.entity]:
                    self._add(
                        C.UNKNOWN_FIELD_REF,
                        f"{path}/policy",
                        f"Policy '{policy.name}' uses ownerField '{policy.owner_field}', missing on '{op.entity}'",
                    )

    def _check_visibility(self, policy: Any, p_index: int) -> None:
        path = f"/policies/{p_index}"
        if not policy.entity or policy.entity not in self.entities:
            self._add(C.UNKNOWN_ENTITY_REF, f"{path}/entity", f"Visibility policy '{policy.name}' needs a known entity")
            return
        if not policy.where:
            self._add(C.SCHEMA_VIOLATION, f"{path}/where", "A visibility policy needs 'where': {field: value}")
        fields = self.fields[policy.entity]
        for name, value in policy.where.items():
            field = fields.get(name)
            if field is None:
                self._add(
                    C.UNKNOWN_FIELD_REF, f"{path}/where/{name}", f"Entity '{policy.entity}' has no field '{name}'"
                )
            elif field.type == "enum" and field.values and value not in field.values:
                self._add(
                    C.SCHEMA_VIOLATION,
                    f"{path}/where/{name}",
                    f"'{value}' is not a value of {policy.entity}.{name}",
                    hint=f"Use one of {', '.join(map(str, field.values))}",
                )
            elif field.type == "boolean" and not isinstance(value, bool):
                self._add(C.SCHEMA_VIOLATION, f"{path}/where/{name}", f"{policy.entity}.{name} takes true or false")

    def _check_rules(self) -> None:
        seen: dict[str, int] = {}
        for r_index, rule in enumerate(self.spec.rules):
            path = f"/rules/{r_index}"
            if rule.id in seen:
                self._add(C.DUPLICATE_RULE_ID, f"{path}/id", f"Rule id '{rule.id}' duplicates /rules/{seen[rule.id]}")
            seen.setdefault(rule.id, r_index)
            entity = self._entity_ref(rule.entity, f"{path}/entity")
            if entity is None:
                continue
            fields = self.fields[entity.name]
            params = rule.params

            if rule.kind == "custom":
                if not rule.description:
                    self._add(C.RULE_PARAMS_INVALID, f"{path}/description", "Custom rules need a 'description'")
                self._check_custom_rule(rule, fields, path)
                continue
            if rule.kind in ("capacity", "noOverlap", "uniqueTogether"):
                self._check_concurrency_rule(rule, fields, path)
                continue
            if rule.kind == "ownerOnly":
                if self.spec.auth is None:
                    self._add(C.AUTH_NOT_CONFIGURED, f"{path}/kind", "ownerOnly rules need top-level 'auth'")
                if params.get("ownerField") not in fields:
                    self._add(
                        C.UNKNOWN_FIELD_REF, f"{path}/params/ownerField", "ownerOnly needs an existing 'ownerField'"
                    )
                continue

            field = fields.get(params.get("field")) if isinstance(params.get("field"), str) else None
            if field is None:
                self._add(C.UNKNOWN_FIELD_REF, f"{path}/params/field", f"'{rule.kind}' needs an existing 'field'")
                continue
            if rule.kind == "transition":
                self._check_transition(field, params.get("transitions"), path)
            elif rule.kind == "immutableAfter":
                states = params.get("states")
                if field.type != "enum" or not isinstance(states, list) or not set(states) <= set(field.values or []):
                    self._add(
                        C.RULE_PARAMS_INVALID,
                        f"{path}/params/states",
                        "'immutableAfter' needs an enum 'field' and 'states' drawn from its values",
                    )
            elif rule.kind == "sumEquals":
                self._check_sum_rule(rule, field, path)

    def _check_where(self, where: Any, fields: dict[str, FieldDef], path: str) -> None:
        """Story 10.10: which records count — `{field: value}`, `{field: {"ne"|"in"|"notIn": …}}`."""
        if where is None:
            return
        if not isinstance(where, dict):
            self._add(C.RULE_PARAMS_INVALID, f"{path}/params/where", "'where' maps fields to values or conditions")
            return
        for name, condition in where.items():
            field = fields.get(name)
            if field is None:
                self._add(C.UNKNOWN_FIELD_REF, f"{path}/params/where/{name}", f"No field '{name}'")
                continue
            if isinstance(condition, dict):
                if len(condition) != 1 or next(iter(condition)) not in ("ne", "in", "notIn"):
                    self._add(C.RULE_PARAMS_INVALID, f"{path}/params/where/{name}", "Use one of ne, in, notIn")
                    continue
                condition = next(iter(condition.values()))
            values = condition if isinstance(condition, list) else [condition]
            if field.type == "enum" and not set(map(str, values)) <= set(field.values or []):
                self._add(C.RULE_PARAMS_INVALID, f"{path}/params/where/{name}", f"Values of '{name}': {field.values}")

    def _check_concurrency_rule(self, rule: Rule, fields: dict[str, FieldDef], path: str) -> None:
        """Story 10.10: capacity (a parent's limit on its children), noOverlap (time ranges), uniqueTogether."""
        params = rule.params
        self._check_where(params.get("where"), fields, path)
        if rule.kind == "capacity":
            parent_fk = params.get("parent")
            rel = next((r for r in self.spec.relationships if r.to == rule.entity and r.type != "many-to-many"
                        and (r.foreign_key or default_foreign_key(r.from_)) == parent_fk), None)  # fmt: skip
            if rel is None:
                self._add(C.RULE_PARAMS_INVALID, f"{path}/params/parent", "'parent' is a foreign key of the entity")
                return
            limit = self.fields[rel.from_].get(params.get("capacityField") or "")
            if limit is None or limit.type != "integer":
                self._add(C.RULE_PARAMS_INVALID, f"{path}/params/capacityField",
                          f"'capacityField' is an integer field of '{rel.from_}'")  # fmt: skip
        elif rule.kind == "noOverlap":
            for key in ("start", "end"):
                field = fields.get(params.get(key) or "")
                if field is None or field.type not in ("date", "datetime"):
                    self._add(C.RULE_PARAMS_INVALID, f"{path}/params/{key}", f"'{key}' is a date or datetime field")
            scope = params.get("scope") or []
            if not isinstance(scope, list):  # one error, not one per letter of a string (Story 22.8)
                self._add(C.RULE_PARAMS_INVALID, f"{path}/params/scope", "'scope' is a list of field names")
                return
            for index, name in enumerate(scope):
                if name not in fields:
                    self._add(C.UNKNOWN_FIELD_REF, f"{path}/params/scope/{index}", f"No field '{name}'")
        else:
            names = params.get("fields")
            if not isinstance(names, list) or len(names) < 2:
                self._add(C.RULE_PARAMS_INVALID, f"{path}/params/fields", "'uniqueTogether' needs two fields or more")
                return
            for index, name in enumerate(names):
                if name not in fields:
                    self._add(C.UNKNOWN_FIELD_REF, f"{path}/params/fields/{index}", f"No field '{name}'")

    def _check_custom_rule(self, rule: Rule, fields: dict[str, FieldDef], path: str) -> None:
        """Story 10.4: what a custom rule answers (`code`, `status`, `field`), all optional."""
        params = rule.params
        if "field" in params and params["field"] not in fields:
            self._add(C.UNKNOWN_FIELD_REF, f"{path}/params/field", f"'{rule.entity}' has no field '{params['field']}'")
        if "status" in params and params["status"] not in (400, 403, 404, 409, 422):
            self._add(C.RULE_PARAMS_INVALID, f"{path}/params/status", "A rule answers 400, 403, 404, 409 or 422")
        code = params.get("code")
        if code is not None and not (isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", code)):
            self._add(C.RULE_PARAMS_INVALID, f"{path}/params/code", "A rule's code is UPPER_SNAKE_CASE")

    def _check_sum_rule(self, rule: Rule, field: FieldDef, path: str) -> None:
        """Story 10.4: `field` equals the sum of `itemField` (times `quantityField`) over the `items` entity's rows
        that reference the record."""
        params = rule.params
        if field.type not in ("integer", "float", "decimal"):
            self._add(C.RULE_PARAMS_INVALID, f"{path}/params/field", "'sumEquals' needs a numeric 'field'")
        items = self.entities.get(params.get("items")) if isinstance(params.get("items"), str) else None
        if items is None:
            self._add(C.UNKNOWN_ENTITY_REF, f"{path}/params/items", "'sumEquals' needs the 'items' entity it adds up")
            return
        if not any(rel.from_ == rule.entity and rel.to == items.name and rel.type != "many-to-many"
                   for rel in self.spec.relationships):  # fmt: skip
            self._add(
                C.RULE_PARAMS_INVALID,
                f"{path}/params/items",
                f"'{items.name}' needs a relationship from '{rule.entity}' (its rows reference the record)",
            )
        for key in ("itemField", "quantityField"):
            name = params.get(key)
            if name is None and key == "quantityField":
                continue
            item_field = self.fields[items.name].get(name) if isinstance(name, str) else None
            if item_field is None or item_field.type not in ("integer", "float", "decimal"):
                self._add(
                    C.RULE_PARAMS_INVALID, f"{path}/params/{key}", f"'{key}' needs a numeric field of '{items.name}'"
                )

    def _check_transition(self, field: FieldDef, transitions: Any, path: str) -> None:
        values = set(field.values or [])
        valid = (
            field.type == "enum"
            and isinstance(transitions, dict)
            and all(
                source in values and isinstance(targets, list) and set(targets) <= values
                for source, targets in transitions.items()
            )
        )
        if not valid:
            self._add(
                C.RULE_PARAMS_INVALID,
                f"{path}/params/transitions",
                "'transition' needs an enum 'field' and 'transitions' mapping each state to allowed next states",
                hint=f"States: {', '.join(sorted(values))}" if values else None,
            )

    def _check_features(self) -> None:
        """Epic 33: a feature's target and its computed fields name real entities and fields."""
        for f_index, attached in enumerate(self.spec.features):
            path = f"/features/{f_index}"
            target = self._entity_ref(attached.on, f"{path}/on")
            taken = set(self.fields[target.name]) if target else set()
            for c_index, computed in enumerate(attached.computed):
                carrier = self.entities.get(computed.target) if computed.target else target
                if computed.target:
                    self._entity_ref(computed.target, f"{path}/computed/{c_index}/target")
                if computed.match and carrier is not None:
                    self._field_refs(carrier, [computed.match], f"{path}/computed/{c_index}/match")
            for c_index, computed in enumerate(attached.computed):
                c_path = f"{path}/computed/{c_index}"
                rows = self._entity_ref(computed.entity, f"{c_path}/entity")
                keys = [computed.key, *computed.where, *([computed.owner] if computed.owner else [])]
                self._field_refs(rows, keys, f"{c_path}/fields")
                if computed.field in taken and not computed.target:
                    self._add(C.UNKNOWN_FIELD_REF, f"{c_path}/field", f"'{computed.field}' is already a field")
                if computed.kind == "mine" and not computed.owner:
                    self._add(C.UNKNOWN_FIELD_REF, f"{c_path}/owner", "A `mine` field needs the rows' owner field")
                taken.add(computed.field)

    def _check_seed(self) -> None:
        for s_index, seed in enumerate(self.spec.seed):
            path = f"/seed/{s_index}"
            entity = self._entity_ref(seed.entity, f"{path}/entity")
            if entity is None:
                continue
            fields = self.fields[entity.name]
            primary = self._primary(entity)
            seen_keys: set[str] = set()
            for row_index, record in enumerate(seed.records):
                row_path = f"{path}/records/{row_index}"
                for key, value in record.items():
                    field = fields.get(key)
                    if field is None:
                        self._add(C.SEED_INVALID, f"{row_path}/{key}", f"'{entity.name}' has no field '{key}'")
                    elif value is None:
                        if field.required or field.primary:
                            self._add(C.SEED_INVALID, f"{row_path}/{key}", f"'{key}' is required")
                    elif not value_matches_type(value, field):
                        self._add(C.SEED_INVALID, f"{row_path}/{key}", f"{value!r} is not a valid {field.type}")
                for name, field in fields.items():
                    auto_key = field.primary and field.type in ("uuid", "integer")
                    needed = (field.required or field.primary) and field.default is None and not auto_key
                    if needed and name not in record:
                        self._add(C.SEED_INVALID, row_path, f"Missing required field '{name}'")
                if primary is not None and primary.name in record:
                    key = json.dumps(record[primary.name])
                    if key in seen_keys:
                        self._add(C.SEED_INVALID, f"{row_path}/{primary.name}", f"Duplicate primary key {key}")
                    seen_keys.add(key)

    def _check_bindings(self) -> None:
        operation_ids = {op.operation_id for op in self.spec.operations}
        for b_index, binding in enumerate(self.spec.frontend_bindings):
            if binding.operation_id not in operation_ids:
                self._add(
                    C.UNKNOWN_OPERATION_REF,
                    f"/x-frontendBindings/{b_index}/operationId",
                    f"Binding refers to unknown operation '{binding.operation_id}'",
                )

    def _trigger(self, trigger: Any, path: str) -> tuple[str, str] | None:
        """Story 10.6: one of an entity event, an operation, a cron schedule; (kind, value) when it is valid."""
        events = {f"{name[:1].lower()}{name[1:]}" for name in self.entities}
        if isinstance(trigger, str):
            kind, _, value = trigger.partition(":")
            given = {kind: value.strip()} if kind in ("cron", "event", "operation") and value else {}
        else:
            given = {key: value for key, value in trigger.model_dump().items() if value}
        if len(given) != 1:
            self._add(C.SCHEMA_VIOLATION, f"{path}/trigger", "A trigger needs exactly one of event, operation, cron")
            return None
        ((kind, value),) = given.items()
        if kind == "event":
            entity, _, name = value.partition(".")
            if entity not in events or not re.fullmatch(r"[a-z][A-Za-z0-9]*", name):
                self._add(C.SCHEMA_VIOLATION, f"{path}/trigger/event",
                          f"'{value}' is not an event: <entity>.created|updated|deleted|<name>",
                          hint=f"Entities: {', '.join(sorted(events))}")  # fmt: skip
                return None
        elif kind == "operation" and value not in {op.operation_id for op in self.spec.operations}:
            self._add(C.UNKNOWN_FIELD_REF, f"{path}/trigger/operation", f"Unknown operation '{value}'")
            return None
        elif kind == "cron" and not re.fullmatch(r"(\S+\s+){4}\S+", value.strip()):
            self._add(C.SCHEMA_VIOLATION, f"{path}/trigger/cron", f"'{value}' is not a five-field cron expression")
            return None
        return kind, value

    def _check_jobs(self) -> None:
        seen: set[str] = set()
        for index, job in enumerate(self.spec.background_jobs):
            path = f"/backgroundJobs/{index}"
            if job.name in seen:
                self._add(C.SCHEMA_VIOLATION, f"{path}/name", f"Job name '{job.name}' is used twice")
            seen.add(job.name)
            self._trigger(job.trigger, path)

    def _record_entity(self, kind: str, value: str) -> str | None:
        """The entity whose record a trigger carries (an event's, an operation's); None for cron."""
        if kind == "event":
            name = value.partition(".")[0]
            return next((entity for entity in self.entities if f"{entity[:1].lower()}{entity[1:]}" == name), None)
        if kind == "operation":
            return next((op.entity for op in self.spec.operations if op.operation_id == value), None)
        return None

    def _path_issue(self, root: str | None, path: str) -> str | None:
        """Why a `record.ref.field` path does not resolve from the trigger's record (None: it does)."""
        if root is None:
            return "a scheduled email has no record: use a literal address and no placeholders"
        parts = path.split(".")
        expected = f"{root[:1].lower()}{root[1:]}"
        if parts[0] != expected or len(parts) < 2:
            return f"starts from the trigger's record, '{expected}.<field>'"
        entity = root
        for index, part in enumerate(parts[1:], start=1):
            fields = self.fields[entity]
            if index == len(parts) - 1:
                return None if part in fields else f"'{entity}' has no field '{part}'"
            parent = next((rel.from_ for rel in self.spec.relationships
                           if rel.to == entity and rel.type != "many-to-many"
                           and (rel.foreign_key or default_foreign_key(rel.from_)) == f"{part}Id"),
                          None)  # fmt: skip
            if parent is None:
                return f"'{entity}' has no reference '{part}' (a foreign key '{part}Id')"
            entity = parent
        return None

    def _check_emails(self) -> None:
        """Story 10.7: a trigger, a recipient and placeholders that resolve from the trigger's record."""
        names: set[str] = set()
        for index, email in enumerate(self.spec.emails):
            path = f"/emails/{index}"
            if email.name in names:
                self._add(C.SCHEMA_VIOLATION, f"{path}/name", f"Email name '{email.name}' is used twice")
            names.add(email.name)
            trigger = self._trigger(email.trigger, path)
            if trigger is None:
                continue
            root = self._record_entity(*trigger)
            if email.to == "currentUser":  # Story 10.7: events carry the record, not who changed it (yet)
                hint = "use the path to the user's address, e.g. 'booking.user.email'"
                self._add(C.SCHEMA_VIOLATION, f"{path}/to", "'currentUser' is not supported yet", hint=hint)
            elif "@" not in email.to or " " in email.to:
                issue = self._path_issue(root, email.to)
                if issue:
                    self._add(C.UNKNOWN_FIELD_REF, f"{path}/to", f"'{email.to}' {issue}")
            for key in ("subject", "body"):
                for placeholder in re.findall(r"\{\{\s*([^}]+?)\s*\}\}", getattr(email, key)):
                    issue = self._path_issue(root, placeholder)
                    if issue:
                        self._add(C.UNKNOWN_FIELD_REF, f"{path}/{key}", f"Placeholder '{placeholder}' {issue}")

    def _check_webhooks(self) -> None:
        """Story 10.8: outgoing events are events (10.6); incoming sources are unique, their event types names."""
        webhooks = self.spec.webhooks
        if webhooks is None:
            return
        for index, event in enumerate(webhooks.outgoing.events if webhooks.outgoing else []):
            self._trigger(JobTrigger(event=event), f"/webhooks/outgoing/events/{index}")
        sources: set[str] = set()
        for index, source in enumerate(webhooks.incoming):
            path = f"/webhooks/incoming/{index}"
            if source.source in sources or source.source in ("subscriptions", "deliveries"):
                self._add(C.SCHEMA_VIOLATION, f"{path}/source", f"Source '{source.source}' is taken")
            sources.add(source.source)
            for e_index, event in enumerate(source.events):
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", event):
                    self._add(C.SCHEMA_VIOLATION, f"{path}/events/{e_index}", f"'{event}' is not an event type")
            if source.action == "custom" and not source.description:
                self._add(C.SCHEMA_VIOLATION, f"{path}/description", "A custom handler needs a description")

    def _check_payments(self) -> None:
        """Story 10.9: an entity with a numeric amount, a currency, and an enum status with the paid (failed) state."""
        payments = self.spec.payments
        if payments is None:
            return
        entity = self._entity_ref(payments.entity, "/payments/entity")
        if entity is None:
            return
        fields = self.fields[entity.name]
        amount = payments.amount_field or next(
            (str(r.params.get("field")) for r in self.spec.rules if r.kind == "sumEquals" and r.entity == entity.name),
            None,
        )
        if amount is None or amount not in fields or fields[amount].type not in ("integer", "float", "decimal"):
            self._add(C.RULE_PARAMS_INVALID, "/payments/amountField",
                      f"'{entity.name}' needs a numeric amount field (or a sumEquals rule)")  # fmt: skip
        if bool(payments.currency) == bool(payments.currency_field):
            self._add(C.SCHEMA_VIOLATION, "/payments/currency", "Give 'currency' or 'currencyField', one of them")
        elif payments.currency_field and payments.currency_field not in fields:
            self._add(
                C.UNKNOWN_FIELD_REF, "/payments/currencyField", f"'{entity.name}' has no '{payments.currency_field}'"
            )
        status = fields.get(payments.status_field)
        if status is None or status.type != "enum":
            self._add(C.RULE_PARAMS_INVALID, "/payments/statusField", f"'{payments.status_field}' is not an enum field")
            return
        for key, value in (("paidStatus", payments.paid_status), ("failedStatus", payments.failed_status)):
            if value is not None and value not in (status.values or []):
                self._add(C.RULE_PARAMS_INVALID, f"/payments/{key}", f"'{value}' is not a value of '{status.name}'")

    def _check_unsupported(self) -> None:
        self._check_jobs()
        self._check_emails()
        self._check_webhooks()
        self._check_payments()
        for key, items in (("integrations", self.spec.integrations),):
            for index, item in enumerate(items):
                self._add(
                    C.UNSUPPORTED_FEATURE,
                    f"/{key}/{index}",
                    f"'{item.name}' will be generated as a stub and listed as unresolved",
                    warning=True,
                )
