"""Product patterns (Epic 32, Story 32.2): what kind of product each area is, and the pattern its screens follow.

- **Child shapes** (`child_shapes`), from the contract alone: a record's child is an `interaction` when its create has
  nothing required to fill in (a like, a bookmark, a view), a `contribution` when it asks for a person's text (a
  comment, a review), a `part` otherwise (an order's item, a lesson); `owned` when its owner comes from the session.
- **The area's kind** (`area_kind`): its archetype, unless every role of the area manages the main entity's records
  (it changes or removes other people's: a role policy or an ownership bypass on its update or delete): staff, so
  `back-office` whatever the requirement's words made the look (Story 32.1's finding: the front desk was `booking`).
- **The area's pattern** (`area_pattern`): the ready pattern plugin of that kind, else `back-office`, which is the
  planner as it always was.
"""

from typing import Any

from src.modules.shared.domain.frontend_spec.design_registry import DesignPluginDescriptor, registry
from src.orchestrator.integration.contract import contract_operations

from .screens import resolve

DEFAULT_PATTERN = "back-office"
SERVER_SOURCES = frozenset({"currentUser", "server"})
QUANTITY_WORDS = ("quantity", "qty")


def _meta(found: dict[str, Any]) -> dict[str, Any]:
    return found["operation"].get("x-bga") or {}


def _user_entity(contract: dict[str, Any]) -> str:
    return ((contract.get("x-bga") or {}).get("auth") or {}).get("userEntity") or "User"


def create_request(contract: dict[str, Any], op_id: str) -> tuple[dict[str, Any], set[str]]:
    """The create's request properties (resolved) and its required names."""
    found = contract_operations(contract)[op_id]
    body = (found["operation"].get("requestBody") or {}).get("content", {}).get("application/json", {})
    schema = resolve(contract, body.get("schema") or {})
    props = {
        name: resolve(contract, prop) | {"x-bga": prop.get("x-bga") or {}}
        for name, prop in (schema.get("properties") or {}).items()
    }
    return props, set(schema.get("required") or [])


def child_shapes(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Entity → its parents (`{entity, field}`, the user entity left out), its shape, `owned` and its create."""
    ops = contract_operations(contract)
    entities = (contract.get("x-bga") or {}).get("entities") or {}
    user = _user_entity(contract)
    creates = {
        _meta(found).get("entity"): op_id for op_id, found in ops.items() if _meta(found).get("action") == "create"
    }
    out: dict[str, dict[str, Any]] = {}
    for name, info in entities.items():
        parents = [
            {"entity": ref["entity"], "field": ref["field"]}
            for ref in info.get("references") or []
            if ref.get("entity") and ref["entity"] != user and ref["entity"] != name
        ]
        if not parents:
            continue
        op_id = creates.get(name)
        shape, owned, quantity = "part", False, False
        if op_id is not None:
            props, required = create_request(contract, op_id)
            fks = {parent["field"] for parent in parents}
            owned = any(prop["x-bga"].get("source") == "currentUser" for prop in props.values())
            quantity = any(any(word in prop_name.lower() for word in QUANTITY_WORDS) for prop_name in props)
            wanted = {
                key: prop
                for key, prop in props.items()
                if key in required and key not in fks and prop["x-bga"].get("source") not in SERVER_SOURCES
            }
            if not wanted:
                shape = "interaction"
            elif any(prop.get("type") == "string" and not prop.get("enum") for prop in wanted.values()):
                shape = "contribution"
        out[name] = {"parents": parents, "shape": shape, "owned": owned, "quantity": quantity, "create": op_id}
    return out


def children_of(shapes: dict[str, dict[str, Any]], entity: str | None) -> dict[str, dict[str, Any]]:
    """The children of one entity, each with the foreign key that names it."""
    out = {}
    for child, info in shapes.items():
        parent = next((p for p in info["parents"] if p["entity"] == entity), None)
        if parent is not None:
            out[child] = info | {"field": parent["field"]}
    return out


def manages(contract: dict[str, Any], entity: str | None, roles: list[str]) -> bool:
    """Every one of these roles manages the entity's records: it changes or removes other people's (a role policy
    naming it on the entity's update or delete, or an ownership bypass there: the front desk edits any appointment).
    Reading every record is not managing it, nor is an action people take on a record (view, like, watch)."""
    if not entity or not roles:
        return False
    managers: set[str] = set()
    for found in contract_operations(contract).values():
        meta = _meta(found)
        if meta.get("entity") != entity or meta.get("action") not in ("update", "delete"):
            continue
        policy = meta.get("policy") or {}
        if policy.get("type") == "role":
            managers |= set(policy.get("roles") or [])
        elif policy.get("type") == "ownership":
            managers |= set(policy.get("bypassRoles") or [])
    return set(roles) <= managers


def area_kind(archetype: str | None, roles: list[str], main: str | None, contract: dict[str, Any]) -> str:
    """What the area is for its people: staff who manage the main entity get `back-office`."""
    if manages(contract, main, roles):
        return DEFAULT_PATTERN
    return archetype or DEFAULT_PATTERN


def area_pattern(kind: str) -> DesignPluginDescriptor:
    """The ready pattern of the kind, else `back-office` (the planner as it always was). `BGA_DESIGN_INCLUDE_DRAFTS=1`
    (the registry's switch for the checks) plans a draft pattern too."""
    found = next((p for p in registry().ready("pattern") if p.name == kind), None)
    if found is not None:
        return found
    default = registry().get("pattern", DEFAULT_PATTERN)
    assert default is not None, "the back-office pattern ships with the agent"
    return default


def manages_some(contract: dict[str, Any], entity: str | None, roles: list[str]) -> bool:
    """Some of these roles manage the entity's records: a mixed area (members and editors in one app)."""
    return any(manages(contract, entity, [role]) for role in roles)


def screen_pattern(
    archetype: str | None, roles: list[str], main: str | None, contract: dict[str, Any]
) -> DesignPluginDescriptor:
    """The pattern an area's screens follow: its kind's, except in a mixed area, which stays a back-office until it
    is split into an area per audience (a consumer pattern's menu would hide the staff's screens)."""
    kind = area_kind(archetype, roles, main, contract)
    if kind != DEFAULT_PATTERN and manages_some(contract, main, roles):
        return area_pattern(DEFAULT_PATTERN)
    return area_pattern(kind)


def app_areas(spec: dict[str, Any], roles: list[str]) -> list[dict[str, Any]]:
    """Each area (an app without areas is one area at `/` for every role) with its archetype and main entity."""
    app = spec.get("app") or {}
    design = app.get("design") or {}
    found = app.get("areas") or [{"id": "app", "prefix": "/", "roles": [], "design": {}}]
    out = []
    for area in found:
        own = {**design, **(area.get("design") or {})}
        out.append(
            {
                "id": area["id"],
                "prefix": area.get("prefix") or "/",
                "roles": list(area.get("roles") or []) or list(roles),
                "archetype": own.get("archetype") or DEFAULT_PATTERN,
                "main": own.get("mainEntity") or (app.get("home") if app.get("home") != "dashboard" else None),
            }
        )
    return out


def contract_roles(contract: dict[str, Any]) -> list[str]:
    """The app's roles as the contract knows them (its demo users', in order)."""
    users = ((contract.get("x-bga") or {}).get("auth") or {}).get("demoUsers") or []
    return list(dict.fromkeys(str(user["role"]) for user in users if user.get("role")))


def area_patterns(
    spec: dict[str, Any], contract: dict[str, Any], roles: list[str] | None = None
) -> dict[str, dict[str, str]]:
    """Area id → its kind and the pattern its screens follow (`plan.app.patterns`)."""
    out = {}
    for area in app_areas(spec, roles if roles is not None else contract_roles(contract)):
        kind = area_kind(area["archetype"], area["roles"], area["main"], contract)
        pattern = screen_pattern(area["archetype"], area["roles"], area["main"], contract)
        out[area["id"]] = {"kind": kind, "pattern": pattern.name}
    return out
