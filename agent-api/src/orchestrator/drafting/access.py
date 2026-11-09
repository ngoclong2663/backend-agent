"""Who may see it and who may do it, correct by default (Epic 25, Stories 25.2 and 25.3).

General rules over what a drafted BackendSpec already declares, for any product; no model call. They use the
policies the generator already enforces (Story 10.3: `role`, and `ownership` with `bypassRoles`), so the backend,
the contract, the mocks, the scenarios and `allowedActions` all follow from the BackendSpec (Epic 25 D3).

- **Records tied to a person are private** (25.2). An entity is tied to a person when an `ownership` policy names
  its owner field, or when one of its fields is the user of a role (`<role>Id` / `<role>UserId`). Its reads, edits
  and record actions without a policy get the owner's policy (staff roles bypass it to read), and its figures are for
  the staff roles only. Reference data (no person field) is unchanged.
- **An action belongs to its role** (25.3). A record action that the owner performs (its policy names only the
  owner's role, or it is the ownership policy with a staff bypass) becomes owner-only: the bypass that lets staff
  read does not let them act for the owner. A record action given to the role of a second person field (an assigned
  worker: `contractorUserId` for `contractor`) becomes that person's only.
- **A status with a flow changes only through its actions** (25.3): when an entity's `transition` rule has record
  actions, the generic update no longer accepts the status field.

`secure_access(spec)` changes the raw BackendSpec in place and returns notes for the draft's assumptions.
"""

import copy
import re
from dataclasses import dataclass, field
from typing import Any

MUTATING = ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class Owned:
    """An entity's person field: the field, the owner's role(s), the staff that bypass it to read, and its policy."""

    entity: str
    field: str
    roles: list[str]
    staff: list[str]
    policy: str  # the read policy: ownership with the staff's bypass
    own_policy: str | None = None  # the act policy: ownership without bypass (made on first use)
    workers: dict[str, str] = field(default_factory=dict)  # role → its person field (an assigned worker)


def _words(name: str) -> list[str]:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return [word for word in re.split(r"[_\W]+", snake) if word]


def _role_of_field(name: str, roles: list[str]) -> str | None:
    """`customerId` → customer, `contractorUserId` → contractor, `frontDeskId` → front_desk; None when no role."""
    words = _words(name)
    if words[-1:] == ["id"]:
        words = words[:-1]
    if words[-1:] == ["user"]:
        words = words[:-1]
    stem = "_".join(words)
    for role in roles:
        if stem == "_".join(_words(role)):
            return role
    return None


def _policies(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {policy["name"]: policy for policy in spec.get("policies") or [] if isinstance(policy, dict)}


def _new_policy(spec: dict[str, Any], name: str, body: dict[str, Any]) -> str:
    names = set(_policies(spec))
    base, index = name, 2
    while name in names:
        name, index = f"{base}{index}", index + 1
    spec.setdefault("policies", []).append({"name": name, **body})
    return name


def _first_segment(path: str) -> str:
    return next((part for part in str(path or "").split("/") if part), "")


def infer_entities(spec: dict[str, Any]) -> None:
    """An operation without `entity` (a custom action the draft left bare) takes the entity whose CRUD operations
    share its first path segment (`/repair-requests/{id}/reopen` → RepairRequest)."""
    by_segment: dict[str, str] = {}
    for op in spec.get("operations") or []:
        if op.get("entity") and op.get("type") == "crud":
            by_segment.setdefault(_first_segment(op.get("path")), op["entity"])
    for op in spec.get("operations") or []:
        if not op.get("entity") and _first_segment(op.get("path")) in by_segment:
            op["_entity"] = by_segment[_first_segment(op.get("path"))]


def _entity(op: dict[str, Any]) -> str:
    return op.get("entity") or op.get("_entity") or ""


def _record_op(op: dict[str, Any]) -> bool:
    return "{" in str(op.get("path") or "")


def _user_fields(entity: dict[str, Any], roles: list[str]) -> dict[str, str]:
    """Field → role, for the entity's uuid fields named after a role."""
    out = {}
    for item in entity.get("fields") or []:
        if item.get("type") != "uuid" or item.get("primary"):
            continue
        role = _role_of_field(item["name"], roles)
        if role is not None:
            out[item["name"]] = role
    return out


def _staff_of(spec: dict[str, Any], entity: str, owner_roles: list[str], roles: list[str]) -> list[str]:
    """Roles a role policy on the entity's operations names, other than the owner's: those who manage its records."""
    policies = _policies(spec)
    named: list[str] = []
    for op in spec.get("operations") or []:
        policy = policies.get(op.get("policy") or "")
        if _entity(op) == entity and policy and policy.get("type") == "role":
            named += [role for role in policy.get("roles") or [] if role not in named]
    return [role for role in roles if role in named and role not in owner_roles]


def find_owned(spec: dict[str, Any], create: bool = True) -> dict[str, Owned]:
    """The person-tied entities and their owner (the draft's ownership policy first, else the one field named after a
    role, preferring a role whose users create the records). `create=False` reads only: the policies an entity would
    get are named but not added to the spec."""
    auth = spec.get("auth") or {}
    roles = [str(role) for role in auth.get("roles") or []]
    if auth.get("type") != "jwt" or len(roles) < 2:
        return {}
    policies = _policies(spec)
    entities = {entity["name"]: entity for entity in spec.get("entities") or [] if isinstance(entity, dict)}
    user_entity = auth.get("userEntity") or "User"
    owned: dict[str, Owned] = {}
    # 1. the draft's own ownership policies (the one most operations use is the entity's owner)
    uses: dict[tuple[str, str], int] = {}
    for op in spec.get("operations") or []:
        policy = policies.get(op.get("policy") or "")
        if policy and policy.get("type") == "ownership" and _entity(op) in entities and policy.get("ownerField"):
            key = (_entity(op), policy["name"])
            uses[key] = uses.get(key, 0) + 1
    for (entity, name), _ in sorted(uses.items(), key=lambda item: -item[1]):
        if entity in owned:
            continue
        policy = policies[name]
        bypass = [role for role in policy.get("bypassRoles") or [] if role in roles]
        matched = _role_of_field(policy["ownerField"], roles)
        owners = [matched] if matched else [role for role in roles if role not in bypass]
        if not owners or len(owners) > 1 and not matched:
            owners = owners[:1] if len(owners) == 1 else []
        if not owners:
            continue
        owners = _maker_owns(spec, entity, owners, bypass) or owners
        owned[entity] = Owned(entity, policy["ownerField"], owners, bypass, name)
    # 2. a field named after a role, on an entity without an ownership policy
    for name, entity in entities.items():
        if name == user_entity or name in owned:
            continue
        fields = _user_fields(entity, roles)
        creators = _creators(spec, name)
        candidates = list(fields.items())
        if len(candidates) > 1:  # the creators' own field, else the one required (an assignee is set later)
            required = {item["name"] for item in entity.get("fields") or [] if item.get("required")}
            candidates = [(f, role) for f, role in candidates if role in creators] or [
                (f, role) for f, role in candidates if f in required
            ]
        if len(candidates) != 1:
            continue
        owner_field, role = candidates[0]
        makers = _maker_owns(spec, name, [role], [])
        if makers is not None and len(makers) == 1:
            role = makers[0]  # the field's name says another role; the record is its maker's
        staff = _staff_of(spec, name, [role, *(r for f, r in fields.items() if f != owner_field)], roles)
        if not staff and role in creators:
            # a record created by the role its person field names (an instructor's course, a seller's listing) names
            # its maker, not a person it is private to, so every other role reads it (writes stay the owner's)
            staff = [r for r in roles if r != role]
        policy_name = f"{name[:1].lower()}{name[1:]}Own{''.join(w.title() for w in _words(role))}"
        body = {"type": "ownership", "ownerField": owner_field, "bypassRoles": staff}
        policy = _new_policy(spec, policy_name, body) if create else policy_name
        owned[name] = Owned(name, owner_field, [role], staff, policy)
    # assigned workers: the entity's other person fields
    for item in owned.values():
        for owner_field, role in _user_fields(entities[item.entity], roles).items():
            if owner_field != item.field and role not in item.roles:
                item.workers[role] = owner_field
    return owned


def _managers(spec: dict[str, Any], entity: str, bypass: list[str]) -> set[str]:
    """Roles that manage an entity's records beyond creating them: a role policy on any of its other operations, or an
    ownership bypass (they read every record)."""
    policies = _policies(spec)
    named = set(bypass)
    for op in spec.get("operations") or []:
        policy = policies.get(op.get("policy") or "")
        if _entity(op) == entity and op.get("action") != "create" and policy and policy.get("type") == "role":
            named |= set(policy.get("roles") or [])
    return named


def _maker_owns(spec: dict[str, Any], entity: str, owners: list[str], bypass: list[str]) -> list[str] | None:
    """The creating roles, when they make the record for themselves although its person field is named after another
    role: they create it and manage nothing else of it (a viewer's like or comment in a field named `creatorId`). Staff
    who create for a person manage those records too (update, assign, read every one). None otherwise."""
    creators = _creators(spec, entity)
    if not creators or set(creators) & set(owners) or set(creators) <= _managers(spec, entity, bypass):
        return None
    return creators


def _creators(spec: dict[str, Any], entity: str) -> list[str]:
    policies = _policies(spec)
    for op in spec.get("operations") or []:
        if op.get("entity") == entity and op.get("action") == "create":
            policy = policies.get(op.get("policy") or "")
            if policy and policy.get("type") == "role":
                return list(policy.get("roles") or [])
    return []


def secure_access(spec: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    infer_entities(spec)
    try:
        owned = find_owned(spec)
        if owned:
            notes += _secure(spec, owned)
    finally:
        for op in spec.get("operations") or []:
            op.pop("_entity", None)
    return notes


def _secure(spec: dict[str, Any], owned: dict[str, Owned]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []

    def note(index: int, message: str) -> None:
        notes.append({"spec": "backend", "path": f"/operations/{index}", "message": message, "suggestion": None})

    def own_policy(item: Owned) -> str:
        if item.own_policy is None:
            item.own_policy = _new_policy(
                spec,
                f"{item.entity[:1].lower()}{item.entity[1:]}OwnerOnly",
                {"type": "ownership", "ownerField": item.field, "bypassRoles": []},
            )
        return item.own_policy

    worker_policies: dict[tuple[str, str], str] = {}

    def worker_policy(item: Owned, role: str) -> str:
        key = (item.entity, role)
        if key not in worker_policies:
            worker_policies[key] = _new_policy(
                spec,
                f"{item.entity[:1].lower()}{item.entity[1:]}Assigned{''.join(w.title() for w in _words(role))}",
                {"type": "ownership", "ownerField": item.workers[role], "bypassRoles": []},
            )
        return worker_policies[key]

    readers: dict[str, str] = {}

    def reader_policy(item: Owned) -> str:
        if item.entity not in readers:
            bypass = [*item.staff, *(role for role in item.workers if role not in item.staff)]
            readers[item.entity] = _new_policy(
                spec,
                f"{item.entity[:1].lower()}{item.entity[1:]}Readers",
                {"type": "ownership", "ownerField": item.field, "bypassRoles": bypass},
            )
        return readers[item.entity]

    staff_figures: dict[str, str] = {}
    # a visibility policy says who sees an entity's records (the roles it names see those matching its `where`, every
    # other role sees every record, Story 23.9), so its reads are not the owner's alone: the owner's policy on them
    # would leave the other roles an empty list
    visible = {
        policy["entity"]: policy["name"]
        for policy in spec.get("policies") or []
        if isinstance(policy, dict) and policy.get("type") == "visibility" and policy.get("entity")
    }
    for index, op in enumerate(spec.get("operations") or []):
        item = owned.get(_entity(op))
        if item is None:
            continue
        policies = _policies(spec)
        policy = policies.get(op.get("policy") or "")
        action, method = op.get("action"), str(op.get("method") or "").upper()
        op_id = op.get("operationId")
        if policy is None and action in ("get", "list") and item.entity in visible:
            note(index, f"{op_id}: who sees a record follows the visibility policy {visible[item.entity]}")
            continue
        # 25.2: reads, edits and record actions without a policy get the owner's (an assigned worker opens a record
        # by its id: the worker's roles bypass the read, not the lists)
        if policy is None and (
            action in ("get", "list", "update", "delete") or (_record_op(op) and op.get("type") == "custom")
        ):
            op["policy"] = reader_policy(item) if action == "get" and item.workers else item.policy
            every_role = [str(r) for r in (spec.get("auth") or {}).get("roles") or []]
            if set(item.staff) >= set(every_role) - set(item.roles):
                note(index, f"{op_id}: made by its {'/'.join(item.roles)} for everyone (every other role reads it)")
            else:
                note(index, f"{op_id}: private to its {'/'.join(item.roles)} (the staff read every record)")
            continue
        # 25.2: figures over private records are the staff's
        if op.get("type") == "aggregate" and policy is None and item.staff:
            if item.entity not in staff_figures:
                staff_figures[item.entity] = _new_policy(
                    spec,
                    f"{item.entity[:1].lower()}{item.entity[1:]}StaffFigures",
                    {"type": "role", "roles": item.staff},
                )
            op["policy"] = staff_figures[item.entity]
            note(index, f"{op_id}: a figure over private records, for {', '.join(item.staff)}")
            continue
        if not (_record_op(op) and op.get("type") == "custom" and method in MUTATING) or policy is None:
            continue
        # 25.3: the owner's actions are the owner's only; an assigned worker's actions that worker's only
        named = list(policy.get("roles") or []) if policy.get("type") == "role" else []
        if policy["name"] == item.policy and item.staff or (named and set(named) <= set(item.roles)):
            op["policy"] = own_policy(item)
            note(index, f"{op_id}: only the record's own {'/'.join(item.roles)} may do this")
        elif named and len(named) == 1 and named[0] in item.workers:
            op["policy"] = worker_policy(item, named[0])
            note(index, f"{op_id}: only the {named[0]} assigned to the record may do this")
    notes += _status_through_actions(spec)
    notes += created_for_someone(spec, owned)
    return notes


def _status_through_actions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """25.3: an entity whose status has a flow (`transition` rule) and record actions that move it: the generic
    update no longer writes the status (its transition rule leaves the update too)."""
    notes: list[dict[str, Any]] = []
    entities = {entity["name"]: entity for entity in spec.get("entities") or [] if isinstance(entity, dict)}
    rules = [rule for rule in spec.get("rules") or [] if isinstance(rule, dict) and rule.get("kind") == "transition"]
    ops = spec.get("operations") or []
    for rule in rules:
        entity = entities.get(rule.get("entity") or "")
        status = (rule.get("params") or {}).get("field")
        if entity is None or not status:
            continue
        actions = [
            op
            for op in ops
            if _entity(op) == entity["name"] and op.get("type") == "custom" and _record_op(op)
            and rule["id"] in (op.get("rules") or [])
        ]  # fmt: skip
        if not actions:
            continue
        for index, op in enumerate(ops):
            if op.get("entity") != entity["name"] or op.get("action") != "update":
                continue
            request = op.get("request") if isinstance(op.get("request"), dict) else {}
            fields = request.get("fields")
            if fields is None:
                fields = [
                    item["name"]
                    for item in entity.get("fields") or []
                    if not item.get("primary") and item.get("default") != "now"
                ]
            if status not in fields:
                continue
            payload = {key: value for key, value in copy.deepcopy(request).items() if key != "properties"}
            op["request"] = {**payload, "entity": entity["name"], "fields": [name for name in fields if name != status]}
            if rule["id"] in (op.get("rules") or []):
                op["rules"] = [rule_id for rule_id in op["rules"] if rule_id != rule["id"]]
            names = ", ".join(action["operationId"] for action in actions)
            notes.append(
                {
                    "spec": "backend",
                    "path": f"/operations/{index}",
                    "message": f"{op['operationId']}: '{status}' changes only through its actions ({names})",
                    "suggestion": None,
                }
            )
    return notes


def owner_from_request(spec: dict[str, Any], entity: str) -> bool:
    """25.4, for the policies plugin: the entity is a person's record that only staff create, so its owner field
    comes with the request (a reference to the user), not from the signed-in user."""
    infer_entities(spec)
    try:
        item = find_owned(spec, create=False).get(entity)
    finally:
        for op in spec.get("operations") or []:
            op.pop("_entity", None)
    return item is not None and staff_creates(spec, entity, item.roles)


def staff_creates(spec: dict[str, Any], entity: str, owner_roles: list[str]) -> bool:
    """25.4: every create of the entity is done by roles other than its owner's (staff create it for someone)."""
    creators = _creators(spec, entity)
    return bool(creators) and not set(creators) & set(owner_roles)


def _ensure_user_entity(spec: dict[str, Any]) -> str:
    auth = spec.get("auth") or {}
    user_entity = auth.get("userEntity") or "User"
    login = auth.get("loginField") or "email"
    entities = spec.setdefault("entities", [])
    if not any(entity.get("name") == user_entity for entity in entities):
        roles = [str(role) for role in auth.get("roles") or []]
        fields: list[dict[str, Any]] = [
            {"name": "id", "type": "uuid", "primary": True},
            {"name": login, "type": "string", "required": True, "unique": True, "maxLength": 255},
        ]
        if roles:  # the auth plugin keeps a declared role field (the directory filters on it)
            fields.append({"name": "role", "type": "enum", "values": roles, "default": roles[0]})
        entities.append({"name": user_entity, "fields": fields, "displayField": login})
    return user_entity


def _ensure_person_link(spec: dict[str, Any], entity: str, person_field: str) -> None:
    """The person field references the user entity (a picker in forms, the seed's demo users)."""
    user_entity = _ensure_user_entity(spec)
    relationships = spec.setdefault("relationships", [])
    if any(r.get("to") == entity and r.get("foreignKey") == person_field for r in relationships):
        return
    relationships.append(
        {
            "name": f"{entity[:1].lower()}{entity[1:]}{person_field[:1].upper()}{person_field[1:]}",
            "type": "one-to-many",
            "from": user_entity,
            "to": entity,
            "foreignKey": person_field,
            "onDelete": "SET NULL" if not _required(spec, entity, person_field) else "CASCADE",
        }
    )


def _required(spec: dict[str, Any], entity: str, name: str) -> bool:
    found = next((e for e in spec.get("entities") or [] if e.get("name") == entity), {})
    return any(f.get("name") == name and f.get("required") for f in found.get("fields") or [])


def _ensure_directory(spec: dict[str, Any], roles: list[str]) -> None:
    """`user.list` / `user.get` for the roles that pick a person in a form (never public: the directory is staff's)."""
    auth = spec.get("auth") or {}
    user_entity = _ensure_user_entity(spec)
    login = auth.get("loginField") or "email"
    operations = spec.setdefault("operations", [])
    stem = user_entity[:1].lower() + user_entity[1:]
    existing = next((op for op in operations if op.get("entity") == user_entity and op.get("action") == "list"), None)
    if existing is not None:
        policy = _policies(spec).get(existing.get("policy") or "")
        if policy and policy.get("type") == "role":
            policy["roles"] = [*policy["roles"], *(role for role in roles if role not in policy["roles"])]
        return
    staff = _new_policy(spec, f"{stem}Directory", {"type": "role", "roles": list(roles)})
    operations += [
        {
            "operationId": f"{stem}.list",
            "type": "crud",
            "action": "list",
            "entity": user_entity,
            "method": "GET",
            "path": "/users",
            "summary": "Find a user",
            "policy": staff,
            "pagination": {"defaultLimit": 20, "maxLimit": 100},
            "search": [login],
            "filters": ["role"] if auth.get("roles") else [],
        },
        {
            "operationId": f"{stem}.get",
            "type": "crud",
            "action": "get",
            "entity": user_entity,
            "method": "GET",
            "path": "/users/{id}",
            "summary": "A user",
            "policy": staff,
        },
    ]


def created_for_someone(spec: dict[str, Any], owned: dict[str, Owned]) -> list[dict[str, Any]]:
    """25.4: a person's record that only staff create names its person: the owner field is a reference to the user
    entity (a picker over `user.list`, for the staff who create), not the creator. The policies plugin then leaves the
    field to the request (`policies.plan`: no `currentUser` when every create is the staff's). 25.5: an assigned
    worker's field references the user entity too (staff pick the worker; the seed assigns demo workers)."""
    notes: list[dict[str, Any]] = []
    for item in owned.values():
        pickers = list(item.staff)
        if item.workers and pickers:
            for worker_field in item.workers.values():
                _ensure_person_link(spec, item.entity, worker_field)
            _ensure_directory(spec, pickers)
        if not staff_creates(spec, item.entity, item.roles):
            continue
        creators = _creators(spec, item.entity)
        _ensure_person_link(spec, item.entity, item.field)
        _ensure_directory(spec, creators)
        notes.append(
            {
                "spec": "backend",
                "path": f"/entities/{item.entity}",
                "message": (
                    f"{item.entity}: {', '.join(creators)} create it for a {'/'.join(item.roles)}, chosen in the form "
                    f"({item.field}); it then belongs to that {'/'.join(item.roles)}"
                ),
                "suggestion": None,
            }
        )
    return notes


def person_roles(spec: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """25.5: (entity, field) → the roles whose users a person field names (owner and assigned workers), read only."""
    out: dict[tuple[str, str], list[str]] = {}
    infer_entities(spec)
    try:
        owned = find_owned(spec, create=False)
    finally:
        for op in spec.get("operations") or []:
            op.pop("_entity", None)
    for item in owned.values():
        out[(item.entity, item.field)] = list(item.roles)
        for role, worker_field in item.workers.items():
            out[(item.entity, worker_field)] = [role]
    return out
