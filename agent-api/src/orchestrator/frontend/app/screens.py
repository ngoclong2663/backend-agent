"""Screen planner (Story 22.3): the app outline + the BackendSpec and its contract → the app's FrontendSpec. Pure and
deterministic, no model.

The pages are ordinary FrontendSpec pages whose sections are the app kit's (`APP_SECTIONS`); every binding in them
(operation, parameters, fields, forms) is written here from the contract, never by the model, and passes the pair
check. One section carries one binding, so the pair check and the coverage scan see every one of them: a parent's
detail page lists each child in its own `AppList` (`content.tab`), the dashboard has one `AppDashboard` per figure.

| Contract | Screen |
|---|---|
| `list` | `/<plural>`: `AppList` (search, filters, sort; row actions view, edit, delete) |
| `get` | `/<plural>/[id]`: `AppDetail`, then an `AppList` tab per child entity |
| `create` | `/<plural>/new` (`AppForm`); a child's: `/<parent>/[id]/<plural>/new`, the parent from the route |
| `update` | `/<plural>/[id]/edit` (`AppForm`, loaded from `get`) |
| `delete` | a row and detail action with a confirm dialog |
| custom on a record | a detail action (and a row action when it has no body); a body opens its `AppForm` in a dialog |
| custom list | a tab on the parent when it filters by the parent, else a page of its own in the navigation |
| custom on the collection | a summary (`AppDetail`) or an `AppActions` button on the list page |
| aggregate | a figure or chart on the dashboard (code adds the aggregate operations the outline's dashboard names) |
"""

import re
from dataclasses import dataclass, field
from typing import Any

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.backend_spec.naming import pluralize, to_camel, to_kebab, to_pascal
from src.modules.shared.domain.frontend_spec.app import MAX_DASHBOARD
from src.modules.shared.domain.frontend_spec.coverage import uncovered_operations
from src.orchestrator.integration.contract import build_contract, contract_operations, resolve

from ...checks.consistency import _response_record
from .design import list_features
from .outline import humanize

SPEC_VERSION = "1.0"
# The planner's own words (Story 23.8): (English, Japanese); `{x}` is a label, lowercased in English.
# Epic 32 (Story 32.5): actions that record a person opening a record (a view counted, a watch logged); in a consumer
# pattern they run once when the record opens, never as a button
OPEN_WORDS = frozenset(
    {"view", "views", "watch", "watched", "play", "plays", "open", "opened", "read", "visit", "visited"}
)


def _name_words(name: str) -> set[str]:
    """`VideoView` → {"video", "view"}; `recordView` → {"record", "view"}."""
    return {word.lower() for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}


WORDS = {
    "view": ("View", "表示"),
    "edit": ("Edit", "編集"),
    "pay": ("Pay", "支払う"),
    "delete": ("Delete", "削除"),
    "confirmDelete": ("Delete this {x}? This cannot be undone.", "この{x}を削除しますか？元に戻せません。"),
    "new": ("New {x}", "{x}を追加"),
    "create": ("Create {x}", "{x}を作成"),
    "editOne": ("Edit {x}", "{x}を編集"),
    "add": ("Add {x}", "{x}を追加"),
    "recent": ("Recent {x}", "最近の{x}"),
    "dashboard": ("Dashboard", "ダッシュボード"),
    "mine": ("Mine", "マイページ"),
    "addToCart": ("Add to cart", "カートに追加"),
    "created": ("{x} created", "{x}を作成しました"),
    "signIn": ("Sign in", "ログイン"),
    "createAccount": ("Create an account", "アカウントを作成"),
    "createShort": ("Create account", "登録する"),
    "email": ("E-mail", "メールアドレス"),
    "password": ("Password", "パスワード"),
    "saved": ("{x} saved", "{x}を保存しました"),
}
LIST_CONTROLS = frozenset({"limit", "offset", "sort", "q", "search", "page", "pageSize"})
SKIPPED_SOURCES = frozenset({"currentUser", "server"})  # the server sets them
RECENT = 5  # records in a dashboard's recent list
PICKER_PAGE = 50  # records a reference picker loads (searched on the server when the list has search)
RECENT_LISTS = 2  # entities with a recent list on the dashboard


# A number's unit from the last word of its name (Story 22.5), shown as the input's suffix.
UNITS = {
    "minutes": "min",
    "mins": "min",
    "hours": "h",
    "hrs": "h",
    "days": "days",
    "weeks": "weeks",
    "seconds": "s",
    "percent": "%",
    "percentage": "%",
    "pct": "%",
    "kg": "kg",
    "grams": "g",
    "km": "km",
    "miles": "mi",
    "meters": "m",
    "metres": "m",
    "cm": "cm",
    "liters": "L",
    "litres": "L",
    "ml": "mL",
}
TYPED_INPUTS = {"email": "email", "uri": "url", "url": "url", "password": "password"}


def input_kind(name: str, schema: dict[str, Any], types: list[Any], backend_type: str | None, enum: bool) -> str:
    """The form kit's input for a request property (Story 22.5): the contract's type and format first, then the
    BackendSpec's type, then the name for typed text inputs (`email`, `website` → url, `phone` → tel)."""
    fmt = schema.get("format")
    if enum:
        return "enum"
    if fmt == "date-time" or backend_type == "datetime":
        return "datetime"
    if fmt == "date" or backend_type == "date":
        return "date"
    if "boolean" in types:
        return "boolean"
    if "integer" in types:
        return "integer"
    if backend_type == "decimal" or fmt == "decimal":
        return "decimal"
    if "number" in types:
        return "number"
    if fmt in TYPED_INPUTS:
        return TYPED_INPUTS[fmt]
    if backend_type == "text" or (backend_type is None and (schema.get("maxLength") or 0) > 255):
        return "text"
    words = humanize(name).lower().split()
    if "email" in words:
        return "email"
    if "password" in words:
        return "password"
    if words and words[-1] in ("url", "website", "link", "homepage"):
        return "url"
    if words and words[-1] in ("phone", "tel", "telephone", "mobile"):
        return "tel"
    return "string"


def prefill(field: dict[str, Any], schema: dict[str, Any]) -> Any:
    """A create form's initial value: the contract's default when it is a literal of the field's kind (never a date:
    "now" is the server's)."""
    default = schema.get("default")
    for option in schema.get("anyOf") or []:
        default = option.get("default", default)
    kind = field["type"]
    if default is None or kind in ("date", "datetime"):
        return None
    if kind == "enum":
        return default if default in (field.get("values") or []) else None
    if kind == "boolean":
        return default if isinstance(default, bool) else None
    if kind in ("integer", "number", "decimal"):
        return default if isinstance(default, int | float) and not isinstance(default, bool) else None
    return default if isinstance(default, str) and default else None


def _note(path: str, message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": path, "message": message, "suggestion": None}


@dataclass
class AppScreens:
    """What the planner hands back: the FrontendSpec and its notes (decisions; operations it could not place)."""

    spec: dict[str, Any]
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)


# -- aggregates -------------------------------------------------------------------------------------------------------


def _date_field(entity: dict[str, Any]) -> str | None:
    """The date a period counts from: a `…At` timestamp set on creation, else the first date or datetime."""
    fields = [f for f in entity.get("fields") or [] if f.get("type") in ("date", "datetime")]
    created = next((f["name"] for f in fields if f.get("default") == "now"), None)
    return created or next((f["name"] for f in fields), None)


def _aggregate(item: dict[str, Any], entity: dict[str, Any]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {"fn": item.get("fn", "count")}
    if item.get("field") and aggregate["fn"] != "count":
        aggregate["field"] = item["field"]
    if item.get("groupBy"):
        aggregate["groupBy"] = item["groupBy"]
    if item.get("period"):
        aggregate["period"] = item["period"]
        aggregate["dateField"] = item.get("dateField") or _date_field(entity)
    if item.get("filter"):
        aggregate["filters"] = dict(item["filter"])
    return aggregate


def _same(existing: dict[str, Any], wanted: dict[str, Any], any_date: bool) -> bool:
    """`any_date`: the dashboard item named no date, so the BackendSpec's own aggregate decides which one."""
    keys = ("fn", "field", "groupBy", "period", "filters") + (() if any_date else ("dateField",))
    return all((existing.get(key) or None) == (wanted.get(key) or None) for key in keys)


def _aggregate_id(entity: str, aggregate: dict[str, Any], default_date: str | None = None) -> str:
    """`task.countByStatus`, `reviewLog.countThisWeek`, `plant.countThisDayOnNextWateringDate`,
    `task.countWhereStatusTodo`."""
    name = aggregate["fn"] + (to_pascal(aggregate["field"]) if aggregate.get("field") else "")
    if aggregate.get("groupBy"):
        name += "By" + to_pascal(aggregate["groupBy"])
    if aggregate.get("period"):
        name += "This" + to_pascal(aggregate["period"])
        if aggregate.get("dateField") and aggregate["dateField"] != default_date:
            name += "On" + to_pascal(aggregate["dateField"])
    for key, value in sorted((aggregate.get("filters") or {}).items()):
        words = "".join(ch for ch in str(value).title() if ch.isalnum())
        name += "Where" + to_pascal(key) + (words or "Value")
    return f"{to_camel(entity)}.{name}"


def ensure_aggregates(
    backend: dict[str, Any], outline: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """The operations the screens need, added to the BackendSpec (templated like CRUD, no engine): a `list` for every
    parent a form references (its picker, Story 22.6) and the aggregates the outline's dashboard names; aggregates the
    BackendSpec has that no dashboard item names join the dashboard. Returns the BackendSpec, the outline and notes;
    an item whose operation would make the BackendSpec invalid is dropped with a note."""
    entities = {entity["name"]: entity for entity in backend.get("entities") or []}
    operations, notes = parent_lists(backend)
    operations, feature_notes = list_features(backend, operations, outline)  # Epic 23: what the views need
    notes += feature_notes
    dashboard: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(outline.get("dashboard") or []):
        entity = entities[item["entity"]]
        aggregate = _aggregate(item, entity)
        if aggregate.get("period") and not aggregate.get("dateField"):
            notes.append(_note(f"/app/dashboard/{index}", f"{item['entity']} has no date for '{item['label']}'"))
            continue
        found = next(
            (
                op
                for op in operations
                if op.get("type") == "aggregate"
                and op.get("entity") == item["entity"]
                and _same(op.get("aggregate") or {}, aggregate, not item.get("dateField"))
            ),
            None,
        )
        if found is None:
            op_id = _aggregate_id(item["entity"], aggregate, _date_field(entity))
            table = to_kebab(pluralize(item["entity"]))
            found = {
                "operationId": op_id,
                "type": "aggregate",
                "entity": item["entity"],
                "method": "GET",
                "path": f"/{table}/aggregate/{to_kebab(op_id.split('.', 1)[1])}",
                "summary": item["label"],
                "aggregate": aggregate,
            }
            trial = {**backend, "operations": [*operations, found]}
            if not validate_spec_data(trial).report.valid or any(op["operationId"] == op_id for op in operations):
                notes.append(_note(f"/app/dashboard/{index}", f"'{item['label']}' cannot be computed; left out"))
                continue
            operations.append(found)
            notes.append(_note(f"/app/dashboard/{index}", f"'{item['label']}' is computed by {op_id} (added)"))
        used.add(found["operationId"])
        dashboard.append({**item, "operationId": found["operationId"]})
    dropped: list[str] = []
    for op in operations:  # every aggregate on a screen (coverage by construction)
        if op.get("type") != "aggregate" or op["operationId"] in used or op.get("entity") not in entities:
            continue
        if len(dashboard) >= MAX_DASHBOARD:  # Story 25.1: no room; an aggregate without a screen leaves the spec
            dropped.append(op["operationId"])
            continue
        aggregate = op.get("aggregate") or {}
        label = op.get("summary") or humanize(op["operationId"].split(".", 1)[1])
        dashboard.append(
            {
                "label": label[:80],
                "kind": "bar" if aggregate.get("groupBy") else "figure",
                "entity": op["entity"],
                "fn": aggregate.get("fn", "count"),
                "operationId": op["operationId"],
                **({"groupBy": aggregate["groupBy"]} if aggregate.get("groupBy") else {}),
            }
        )
        used.add(op["operationId"])
    if dropped:
        operations = [op for op in operations if op["operationId"] not in dropped]
        backend = without_references(backend, set(dropped))
        names = ", ".join(dropped)
        notes.append(_note("/app/dashboard", f"The dashboard holds {MAX_DASHBOARD} items; left out: {names}"))
    return {**backend, "operations": operations}, {**outline, "dashboard": dashboard}, notes


def without_references(value: Any, ids: set[str]) -> Any:
    """The BackendSpec without the given operation ids wherever a list names them (policies, rules)."""
    if isinstance(value, dict):
        return {key: without_references(item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [without_references(item, ids) for item in value if not (isinstance(item, str) and item in ids)]
    return value


def parent_lists(backend: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The BackendSpec's operations with a paginated `list` (searched on the parent's label) for each referenced parent
    that has none (`x-bga.ref.listOperation: null`): a reference is picked from it (Story 22.6). Returns the
    operations and notes."""
    from src.orchestrator.backend.planner import build_plan

    operations = list(backend.get("operations") or [])
    contract = build_contract(backend, build_plan(backend))
    missing: dict[str, str | None] = {}
    for schema in ((contract.get("components") or {}).get("schemas") or {}).values():
        for prop in (schema.get("properties") or {}).values():
            ref = (prop.get("x-bga") or {}).get("ref") or {}
            if ref.get("entity") and not ref.get("listOperation"):
                missing.setdefault(ref["entity"], ref.get("labelField"))
    entities = {entity["name"]: entity for entity in backend.get("entities") or []}
    notes = []
    for parent, label_field in sorted(missing.items()):
        if parent not in entities:
            continue
        paths = [op["path"] for op in operations if op.get("entity") == parent and op.get("type") == "crud"]
        base = next((path for path in paths if "{" not in path), None) or next(
            (path.rsplit("/{", 1)[0] for path in paths), f"/{to_kebab(pluralize(parent))}"
        )
        fields = {field["name"]: field for field in entities[parent].get("fields") or []}
        op_id = f"{to_camel(parent)}.list"
        listing: dict[str, Any] = {
            "operationId": op_id,
            "type": "crud",
            "action": "list",
            "entity": parent,
            "method": "GET",
            "path": base,
            "pagination": True,
        }
        if label_field and (fields.get(label_field) or {}).get("type") in ("string", "text"):
            listing["search"] = [label_field]
        trial = validate_spec_data({**backend, "operations": [*operations, listing]})
        if any(op["operationId"] == op_id for op in operations) or not trial.report.valid:
            notes.append(_note("/operations", f"{parent} has no list to pick it from, and one cannot be added"))
            continue
        # the normalized form (pagination limits, search params), as the callers' BackendSpec is normalized
        operations.append(next(op for op in trial.normalized["operations"] if op["operationId"] == op_id))
        notes.append(_note("/operations", f"{op_id} added: a {humanize(parent).lower()} is picked from its list"))
    return operations, notes


# -- the planner ------------------------------------------------------------------------------------------------------


class _Screens:
    def __init__(
        self,
        backend: dict[str, Any],
        outline: dict[str, Any],
        contract: dict[str, Any],
        allowed: set[str] | None = None,
        pattern: Any = None,
        main: str | None = None,
    ):
        """`pattern`: the area's product pattern (Epic 32; None or `back-office`: the planner as it always was);
        `main`: the area's main entity."""
        self.backend, self.outline, self.contract = backend, outline, contract
        self.pattern, self.main = pattern, main
        self._shapes: dict[str, dict[str, Any]] | None = None
        self.operations = contract_operations(contract)
        if allowed is not None:  # Story 23.10: an area plans only what its roles may call
            self.operations = {op_id: found for op_id, found in self.operations.items() if op_id in allowed}
        self.spec_ops = {op["operationId"]: op for op in backend.get("operations") or []}
        self.entities = {entity["name"]: entity for entity in backend.get("entities") or []}
        self.info = ((contract.get("x-bga") or {}).get("entities")) or {}
        # Story 22.7: the plugins' parts of the contract
        meta = contract.get("x-bga") or {}
        self.auth = meta.get("auth")
        self.payments = meta.get("payments") or {}
        self.transitions = {
            rule["entity"]: rule["params"] for rule in meta.get("rules") or [] if rule.get("kind") == "transition"
        }
        self.locks = {
            rule["entity"]: set((rule.get("params") or {}).get("states") or [])
            for rule in meta.get("rules") or []
            if rule.get("kind") == "immutableAfter"
        }
        self.pages: list[dict[str, Any]] = []
        self.forms: list[dict[str, Any]] = []
        self.nav: list[dict[str, Any]] = []
        self.assumptions: list[dict[str, Any]] = []
        self.unresolved: list[dict[str, Any]] = []
        self.placed: set[str] = set()
        self.crud: dict[str, dict[str, str]] = {name: {} for name in self.entities}
        self.custom: dict[str, list[str]] = {name: [] for name in self.entities}
        for op in backend.get("operations") or []:
            entity = op.get("entity")
            if entity not in self.entities or op["operationId"] not in self.operations:
                continue
            if op.get("type") == "crud" and op.get("action"):
                self.crud[entity].setdefault(op["action"], op["operationId"])
            elif op.get("type") == "custom":
                self.custom[entity].append(op["operationId"])

    # -- names and lookups

    def slug(self, entity: str) -> str:
        return to_kebab(pluralize(entity))

    def shown(self, entity: str) -> dict[str, Any]:
        return (self.outline.get("entities") or {}).get(entity) or {}

    def label(self, entity: str) -> str:
        return self.shown(entity).get("label") or humanize(entity)

    def plural(self, entity: str) -> str:
        return self.shown(entity).get("plural") or pluralize(self.label(entity))

    def references(self, entity: str) -> list[dict[str, Any]]:
        return list((self.info.get(entity) or {}).get("references") or [])

    def parent_of(self, entity: str) -> dict[str, Any] | None:
        """The first parent this entity is listed under (a required reference with a filter on the list)."""
        list_op = self.crud[entity].get("list")
        filters = self.query_params(list_op) if list_op else {}
        required = self.required_inputs(self.crud[entity].get("create"))
        for reference in self.references(entity):
            parent = reference["entity"]
            if reference["field"] in filters and parent in self.entities and "get" in self.crud[parent]:
                if not required or reference["field"] in required:
                    return reference
        return None

    def route_parent(self, entity: str) -> dict[str, Any] | None:
        """The parent a new record takes from the route: the one it is listed under, else the first required
        reference whose parent has a page (`cartItem.create` from a product's page)."""
        parent = self.parent_of(entity)
        if parent:
            return parent
        required = self.required_inputs(self.crud[entity].get("create"))
        return next(
            (
                ref
                for ref in self.references(entity)
                if ref["field"] in required and ref["entity"] in self.entities and "get" in self.crud[ref["entity"]]
            ),
            None,
        )

    def children_of(self, entity: str) -> list[tuple[str, dict[str, Any]]]:
        return [(name, ref) for name in self.entities if (ref := self.parent_of(name)) and ref["entity"] == entity]

    # -- product patterns (Epic 32)

    @property
    def consumer(self) -> bool:
        """The area's people use the product (its pattern's menu is not a back-office's)."""
        return self.pattern is not None and "every" not in (self.pattern.menu or [])

    def never(self, what: str) -> bool:
        return self.pattern is not None and what in (self.pattern.never or [])

    def shape(self, entity: str) -> str | None:
        if self._shapes is None:
            from .patterns import child_shapes

            self._shapes = child_shapes(self.contract)
        return (self._shapes.get(entity) or {}).get("shape")

    def owned(self, entity: str) -> bool:
        self.shape(entity)
        return bool(((self._shapes or {}).get(entity) or {}).get("owned"))

    def on_record(self, entity: str) -> bool:
        """The pattern places this child's create on its parent's record (`inline` or `sheet`)."""
        shape = self.shape(entity)
        if self.pattern is None or shape is None:
            return False
        return (self.pattern.children or {}).get(shape) in ("inline", "sheet")

    def on_open(self, entity: str) -> dict[str, Any] | None:
        """In a consumer area, what runs once when a record of the entity opens: its own action named like a view
        (`video.view`, `video.watch`) with nothing to fill in, else a child view created with nothing to fill in
        (`VideoView`); None in a back-office, where such an action stays a button. A child the draft says is made
        when its parent opens (`entities.<child>.create: onOpen`, Story 32.7) is, in any area."""
        for child, found in self.on_parent_children(entity):
            if self.drafted_create(child) == "onOpen" and found["form"] is None:
                return {"operationId": self.crud[child]["create"], "body": {found["parent"]["field"]: "$route.id"}}
        if not self.consumer:
            return None
        for op_id in self.custom[entity]:
            found = self.operations[op_id]
            verb = op_id.split(".", 1)[-1]  # `view`, `watch`, `recordView`
            if found["method"] == "GET" or self.path_params(op_id) != ["id"] or not _name_words(verb) & OPEN_WORDS:
                continue
            if not self.request(op_id)[0]:
                return {"operationId": op_id, "params": {"id": "$route.id"}}
        for child, found in self.on_parent_children(entity):
            if found["form"] is None and _name_words(child) & OPEN_WORDS:
                return {"operationId": self.crud[child]["create"], "body": {found["parent"]["field"]: "$route.id"}}
        return None

    def others(self, entity: str) -> bool:
        """Records these people never create, in an area that never edits other people's records (`edit-others`)."""
        return self.never("edit-others") and "create" not in self.crud[entity]

    def cart(self) -> str | None:
        """A storefront's cart line (`patterns.cart_of`): the person's own child of the main entity with a quantity."""
        if not self.consumer or "cart" not in (self.pattern.menu or []):
            return None
        from .patterns import cart_of, child_shapes

        shapes = {c: info for c, info in child_shapes(self.contract).items() if c in self.entities}
        return cart_of(shapes, self.main)

    def on_mine(self, entity: str) -> bool:
        """A person's own reaction or contribution under a record, listed on the consumer pattern's Mine page."""
        if not self.consumer or "mine" not in (self.pattern.menu or []) or entity == self.cart():
            return False
        has_parent = any(ref["entity"] in self.entities for ref in self.references(entity))
        return has_parent and self.owned(entity) and self.shape(entity) in ("interaction", "contribution")

    def edits(self, entity: str) -> bool:
        """An edit page for the entity: never in an area whose people never create its records (`edit-others`)."""
        crud = self.crud[entity]
        if "update" not in crud:
            return False
        return not self.others(entity)

    def on_parent(self, entity: str) -> dict[str, Any] | None:
        """A child's create as an action on its parent's record: when it has nothing to fill in (every pattern), or
        when the area's pattern places its shape there; `form` is None for one click, else the fields of its dialog.
        Story 32.7: the draft's `entities.<child>.create` decides first (`page`: a form page; `onRecord` / `onOpen`:
        on the record, in any area)."""
        drafted = self.drafted_create(entity)
        if drafted == "page":
            return None
        parent = self.quick_create(entity)
        if parent is not None:
            return {"parent": parent, "form": None}
        cart = entity == self.cart()  # a shop's cart line is put in the cart from the product, whatever its shape
        if drafted not in ("onRecord", "onOpen") and not cart and not self.on_record(entity):
            return None
        if "create" not in self.crud[entity]:
            return None
        parent = self.route_parent(entity)
        if cart:  # a shop's line is put in the cart from the product, whatever else it belongs to
            parent = next((ref for ref in self.references(entity) if ref["entity"] == self.main), parent)
        if parent is None:
            return None
        fields = self.form_fields(entity, self.crud[entity]["create"], {parent["field"]: "$route.id"})
        return {"parent": parent, "form": fields} if fields else None

    def drafted_create(self, entity: str) -> str | None:
        """Where the draft says the entity's records are made (`onRecord`, `onOpen`, `page`), else None."""
        return ((self.outline.get("entities") or {}).get(entity) or {}).get("create")

    def on_parent_children(self, entity: str) -> list[tuple[str, dict[str, Any]]]:
        """The children created from this entity's records (`on_parent`)."""
        return [
            (child, found)
            for child in self.entities
            if (found := self.on_parent(child)) and found["parent"]["entity"] == entity
        ]

    def quick_create(self, entity: str) -> dict[str, Any] | None:
        """A child whose create has nothing visible to fill in (the parent from the route, the owner from the signed-in
        user, the rest defaulted: a like, a follow, a bookmark): its parent reference, else None. Such a create is an
        action on the parent's record, not a form page of its own."""
        if "create" not in self.crud[entity]:
            return None
        parent = self.route_parent(entity)
        if parent is None:
            return None
        fields = self.form_fields(entity, self.crud[entity]["create"], {parent["field"]: "$route.id"})
        return parent if fields and all(field.get("hidden") for field in fields) else None

    def w(self, key: str, x: str | None = None, lower: bool = True) -> str:
        """The planner's own words in the outline's language (Story 23.8): English, or Japanese for `ja`."""
        english, japanese = WORDS[key]
        if (self.outline.get("locale") or "en").split("-")[0] == "ja":
            return japanese.format(x=x or "")
        return english.format(x=(x or "").lower() if lower else (x or ""))

    def query_params(self, op_id: str | None) -> dict[str, dict[str, Any]]:
        operation = self.operations[op_id]["operation"] if op_id else {}
        return {p["name"]: p for p in operation.get("parameters") or [] if p.get("in") == "query"}

    def path_params(self, op_id: str) -> list[str]:
        operation = self.operations[op_id]["operation"]
        return [p["name"] for p in operation.get("parameters") or [] if p.get("in") == "path"]

    def required_query(self, op_id: str) -> list[str]:
        return [name for name, p in self.query_params(op_id).items() if p.get("required")]

    def request(self, op_id: str | None) -> tuple[dict[str, Any], set[str]]:
        if not op_id:
            return {}, set()
        operation = self.operations[op_id]["operation"]
        body = (operation.get("requestBody") or {}).get("content", {}).get("application/json", {})
        schema = resolve(self.contract, body.get("schema") or {})
        return schema.get("properties") or {}, set(schema.get("required") or [])

    def required_inputs(self, op_id: str | None) -> set[str]:
        return self.request(op_id)[1]

    def response_fields(self, op_id: str) -> list[str]:
        record = _response_record(self.contract, self.operations[op_id]["operation"])
        return list(record.get("properties") or {})

    def op_label(self, op_id: str) -> str:
        summary = (self.spec_ops.get(op_id) or {}).get("summary")
        if isinstance(summary, str) and 0 < len(summary) <= 40:
            summary = summary.removeprefix("List ").removeprefix("list ").removeprefix("Get ").strip() or summary
            return summary[:1].upper() + summary[1:]
        name = op_id.split(".", 1)[1]
        entity = (self.spec_ops.get(op_id) or {}).get("entity")
        if name.startswith("list") and len(name) > 4 and entity in self.entities:  # `listDue` → `Due cards`
            return f"{humanize(name[4:])} {self.plural(entity).lower()}"
        return humanize(name)

    def place(self, op_id: str | None) -> None:
        if op_id:
            self.placed.add(op_id)

    # -- forms

    def form_fields(
        self, entity: str, op_id: str, hidden: dict[str, str] | None = None, readable: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """The request's fields as a form; `hidden` fields take a fixed value (`$route.id`), other references are
        picked by name (Story 22.6), and `readable` limits an edit form to what `get` returns."""
        properties, required = self.request(op_id)
        hidden = hidden or {}
        shown = self.shown(entity)
        references = {ref["field"]: ref for ref in self.references(entity)}
        fields = []
        for name, prop in properties.items():
            meta = prop.get("x-bga") or {}
            if meta.get("source") in SKIPPED_SOURCES:
                continue
            if name in hidden:
                fields.append({"name": name, "type": "string", "hidden": True, "value": hidden[name], "required": True})
                continue
            if readable and name not in readable:
                continue
            if self.payments.get("entity") == entity and name == self.payments.get("statusField"):
                continue  # the payment's status is the server's (Story 22.7)
            flow = self.transitions.get(entity) or {}
            creating = readable is None and op_id == self.crud[entity].get("create")
            if flow.get("field") == name and creating and name not in required:
                continue  # a new record starts in the flow's first state; it moves by its transitions
            if meta.get("source") == "upload":
                fields.append(self.upload_field(entity, name, meta.get("upload") or {}, name in required, shown))
                continue
            if name in references or meta.get("source") == "reference":
                parent = (meta.get("ref") or {}).get("entity") or (references.get(name) or {}).get("entity")
                picker = self.picker(parent, meta.get("ref") or {})
                if picker is None:
                    if name in required:  # the pair check rejects the form; the draft's fixes add the parent's list
                        self.unresolved.append(
                            _note("/forms", f"{self.label(entity)}: no list of {parent} to pick from")
                        )
                    continue
                label = (shown.get("fieldLabels") or {}).get(name)
                fields.append(
                    {
                        "name": name,
                        "type": "string",
                        "label": label if label and label != humanize(name) else self.label(parent),
                        "required": name in required,
                        "reference": picker,
                    }
                )
                continue
            field = self.form_field(entity, name, resolve(self.contract, prop), name in required, shown)
            if flow.get("field") == name and readable is not None and field["type"] == "enum":
                field["transition"] = True  # only the states the record may move to (`transition:<STATE>`)
            initial = prefill(field, resolve(self.contract, prop)) if readable is None else None
            if initial is not None:
                field["value"] = initial  # a new record starts from the contract's default (status "TODO")
            fields.append(field)
        return fields

    def form_field(
        self, entity: str, name: str, schema: dict[str, Any], required: bool, shown: dict[str, Any]
    ) -> dict[str, Any]:
        types = schema.get("type") if isinstance(schema.get("type"), list) else [schema.get("type")]
        for option in schema.get("anyOf") or []:
            types.append(option.get("type"))
            schema = {**option, **schema} if option.get("type") != "null" else schema
        backend_type = next(
            (f.get("type") for f in self.entities[entity].get("fields") or [] if f["name"] == name), None
        )
        enum = [value for value in schema.get("enum") or [] if value is not None]
        kind = input_kind(name, schema, types, backend_type, bool(enum))
        out: dict[str, Any] = {
            "name": name,
            "type": kind,
            "label": (shown.get("fieldLabels") or {}).get(name) or humanize(name),
            "required": required,
        }
        if enum:
            out["values"] = enum
        for key, target in (("minimum", "min"), ("maximum", "max"), ("maxLength", "maxLength")):
            if schema.get(key) is not None:
                out[target] = schema[key]
        help_text = (shown.get("help") or {}).get(name)
        if help_text:
            out["help"] = help_text
        if kind in ("integer", "number", "decimal"):
            out.update(self.number_addon(entity, name))
            if out.get("unit") and " " in out["label"] and out["label"] == humanize(name):
                out["label"] = out["label"].rpartition(" ")[0]  # `Duration minutes` → `Duration` with "min" beside it
        return out

    def upload_field(
        self, entity: str, name: str, upload: dict[str, Any], required: bool, shown: dict[str, Any]
    ) -> dict[str, Any]:
        """A file or image field (Story 22.7): uploaded through the storage plugin's presigned URL; the form sends the
        object's key."""
        self.place(upload.get("presign"))
        spec = {
            key: upload[key] for key in ("presign", "entity", "field", "kind", "accept", "maxSize") if upload.get(key)
        }
        field = {
            "name": name,
            "type": "string",
            "label": (shown.get("fieldLabels") or {}).get(name) or humanize(name),
            "required": required,
            "upload": {"entity": entity, "field": name, **spec},
        }
        help_text = (shown.get("help") or {}).get(name)
        return field | ({"help": help_text} if help_text else {})

    def auth_form(self, form_id: str, op_id: str, submit: str) -> str | None:
        """A sign-in or sign-up form on the auth plugin's request (Story 22.7): the account's fields, typed."""
        properties, required = self.request(op_id)
        fields = []
        for name, prop in properties.items():
            schema = resolve(self.contract, prop)
            types = schema.get("type") if isinstance(schema.get("type"), list) else [schema.get("type")]
            enum = [value for value in schema.get("enum") or [] if value is not None]
            field = {
                "name": name,
                "type": input_kind(name, schema, types, None, bool(enum)),
                "label": self.w("email")
                if name == "email"
                else self.w("password")
                if name == "password"
                else humanize(name),
                "required": name in required,
            }
            if enum:
                field["values"] = enum
            if schema.get("maxLength"):
                field["maxLength"] = schema["maxLength"]
            fields.append(field)
        return self.add_form({"id": form_id, "operationId": op_id, "fields": fields, "submitLabel": submit})

    def plugin_pages(self) -> None:
        """Story 22.7: sign-in and sign-up (auth-jwt) and the checkout's return pages (payments)."""
        if self.auth:
            login = (self.auth.get("login") or {}).get("operationId") or "auth.login"
            for page_id, route, title, variant, op_id, submit in (
                ("login", "/login", self.w("signIn"), "signIn", login, self.w("signIn")),
                ("register", "/register", self.w("createAccount"), "signUp", "auth.register", self.w("createShort")),
            ):
                if op_id not in self.operations:
                    continue
                form = self.auth_form(f"auth_{page_id}", op_id, submit)
                if form is None:
                    continue
                section = {"id": page_id, "component": "AppAuth", "form": form, "content": {"variant": variant}}
                section["content"]["title"] = title
                self.page(page_id, route, title, [section])
            self.place("auth.me")
        if self.payments.get("checkout") in self.operations:
            status = self.payments.get("status")
            for page_id, route, title, variant in (
                ("payments-success", "/payments/success", "Payment", "success"),
                ("payments-cancel", "/payments/cancel", "Payment", "cancel"),
            ):
                section = {
                    "id": page_id,
                    "component": "AppPayment",
                    "data": {"operationId": status, "params": {"paymentId": "$query.payment"}},
                    "content": {"variant": variant, "title": title, "entity": self.payments.get("entity")},
                }
                self.page(page_id, route, title, [section])
            self.place(status)

    def link_sections(self, entity: str) -> list[dict[str, Any]]:
        """A record's many-to-many links (Story 22.7, relations): one `AppLinks` tab per linked entity, its chips
        listed by the link list, added with a picker, removed one by one."""
        sections = []
        for link in (self.info.get(entity) or {}).get("links") or []:
            child, list_op = link.get("entity"), link.get("list")
            if child not in self.entities or list_op not in self.operations:
                continue
            properties, _ = self.request(link.get("add"))
            field = next(iter(properties), None)
            ref = ((properties.get(field) or {}).get("x-bga") or {}).get("ref") or {} if field else {}
            picker = self.picker(child, ref) if field else None
            content: dict[str, Any] = {"entity": child, "title": self.plural(child), "tab": self.plural(child)}
            if picker and link.get("add") in self.operations:
                content["add"] = {"operationId": link["add"], "field": field, "reference": picker}
                self.place(link["add"])
            if link.get("remove") in self.operations:
                content["remove"] = {
                    "operationId": link["remove"],
                    "param": re.findall(r"\{(\w+)\}", self.operations[link["remove"]]["path"])[-1],
                }
                self.place(link["remove"])
            sections.append(
                {
                    "id": f"{self.slug(child)}-links",
                    "component": "AppLinks",
                    "data": {"operationId": list_op, "params": {"id": "$route.id"}},
                    "content": content,
                }
            )
            self.place(list_op)
        return sections

    def picker(self, parent: str | None, ref: dict[str, Any]) -> dict[str, Any] | None:
        """A reference's picker (Story 22.6): the parent's list (searched with `q` when it has search), its label field
        and its `get` for a chosen record the first page does not hold."""
        if parent not in self.entities:
            return None
        list_op = ref.get("listOperation") or self.crud[parent].get("list")
        if not list_op or list_op not in self.operations:
            return None
        query = self.query_params(list_op)
        detail = ref.get("detailOperation") or self.crud[parent].get("get")
        out: dict[str, Any] = {"entity": parent, "listOperation": list_op}
        if detail in self.operations:
            out["detailOperation"] = detail
        label_field = ref.get("labelField") or self.shown(parent).get("displayField")
        if label_field:
            out["labelField"] = label_field
        if "q" in query:
            out["searchParam"] = "q"
        if "limit" in query:
            out["limitParam"] = "limit"
            out["pageSize"] = min(PICKER_PAGE, (query["limit"].get("schema") or {}).get("maximum") or PICKER_PAGE)
        self.place(list_op)
        return out

    def number_addon(self, entity: str, name: str) -> dict[str, str]:
        """A number's prefix or suffix (Story 22.5): the paid entity's amount in its currency, else a unit its name
        ends with (`durationMinutes` → "min")."""
        payments = self.backend.get("payments") or {}
        amount = payments.get("amountField") or payments.get("amount_field")
        if payments.get("entity") == entity and amount == name and payments.get("currency"):
            return {"currency": payments["currency"]}
        words = humanize(name).lower().split()
        unit = UNITS.get(words[-1]) if len(words) > 1 or words[-1] in ("percent", "percentage") else None
        return {"unit": unit} if unit else {}

    def add_form(self, form: dict[str, Any]) -> str | None:
        if not form["fields"]:
            return None
        self.forms.append(form)
        self.place(form.get("operationId"))
        self.place((form.get("load") or {}).get("operationId"))
        return form["id"]

    # -- sections

    def record_actions(self, entity: str, record: str, detail: bool) -> list[dict[str, Any]]:
        """Actions on one record (`$record` in a list, `$route` on its page): view, edit, delete, custom ones."""
        crud, label, slug = self.crud[entity], self.label(entity), self.slug(entity)
        actions: list[dict[str, Any]] = []
        if not detail and "get" in crud:
            actions.append(
                {"id": "view", "label": self.w("view"), "kind": "link", "page": f"{slug}-id", "params": {"id": record}}
            )
        if self.edits(entity):
            actions.append(
                {
                    "id": "edit",
                    "label": self.w("edit"),
                    "kind": "link",
                    "page": f"{slug}-id-edit",
                    "params": {"id": record},
                }
            )
        opened = (self.on_open(entity) or {}).get("operationId")
        for child, found in self.on_parent_children(entity):  # a like with one click; a comment in a dialog (Epic 32)
            op_id, parent = self.crud[child]["create"], found["parent"]
            if op_id == opened:
                self.place(op_id)
                continue  # a view is counted when the record opens
            done = {"toast": self.w("created", self.label(child), lower=False)}
            if found["form"] is None:
                actions.append(
                    {
                        "id": f"add-{self.slug(child)}",
                        # the operation's own verb ("interaction.like" → "Like"), else the noun reads as one
                        "label": self.label(child) if op_id.split(".", 1)[-1] == "create" else self.op_label(op_id),
                        "kind": "mutation",
                        "operationId": op_id,
                        "body": {parent["field"]: record},
                        "onSuccess": done,
                    }
                )
            elif detail:  # a form opens a dialog: on the record's page, where `$route.id` is the record
                form_id = self.add_form(
                    {
                        "id": f"{to_camel(child)}_create_on_{to_camel(entity)}",
                        "operationId": op_id,
                        "fields": found["form"],
                        "submitLabel": self.w("create", self.label(child)),
                        "onSuccess": done,
                    }
                )
                if form_id:
                    actions.append(
                        {
                            "id": f"add-{self.slug(child)}",
                            # a storefront's cart reads as the shop's verb
                            "label": self.w("addToCart") if child == self.cart() else self.w("add", self.label(child)),
                            "kind": "mutation",
                            "operationId": op_id,
                            "form": form_id,
                            "onSuccess": done,
                        }
                    )
            self.place(op_id)
        for op_id in self.custom[entity]:
            found = self.operations[op_id]
            if found["method"] == "GET" or self.path_params(op_id) != ["id"] or self.required_query(op_id):
                continue
            if op_id == opened:
                self.place(op_id)
                continue  # Epic 32: run when the record opens, not a button
            if (
                self.others(entity)
                and ((found["operation"].get("x-bga") or {}).get("policy") or {}).get("type") == "ownership"
            ):
                continue  # Epic 32: an owner's action (publish) on records these people never create
            properties, _ = self.request(op_id)
            if properties and not detail:
                continue  # a body opens a dialog: on the record's page only
            action: dict[str, Any] = {
                "id": to_kebab(op_id.split(".", 1)[1]),
                "label": self.op_label(op_id),
                "kind": "mutation",
                "operationId": op_id,
                "params": {"id": record},
                "onSuccess": {"toast": f"{self.op_label(op_id)}: done"},
            }
            if properties:
                form_id = self.add_form(
                    {
                        "id": f"{to_camel(entity)}_{op_id.split('.', 1)[1]}",
                        "operationId": op_id,
                        "params": {"id": "$route.id"},
                        "fields": self.form_fields(entity, op_id),
                        "submitLabel": self.op_label(op_id),
                        "onSuccess": {"toast": f"{self.op_label(op_id)}: done"},
                    }
                )
                if form_id is None:
                    continue
                action["form"] = form_id
            if found["method"] == "DELETE":
                action["confirm"] = f"{self.op_label(op_id)} this {label.lower()}?"
            self.place(op_id)
            actions.append(action)
        flow = self.transitions.get(entity) or {}
        # Story 22.7: a move per state, shown when `transition:<STATE>` is allowed; Story 25.3: not when the update
        # cannot write the status (it moves only through the record's own actions)
        if flow and "update" in crud and flow.get("field") in self.request(crud["update"])[0]:
            states = [state for targets in (flow.get("transitions") or {}).values() for state in targets]
            for state in dict.fromkeys(states):
                move: dict[str, Any] = {
                    "id": f"transition-{to_kebab(state.lower())}",
                    "label": f"Mark as {humanize(state).lower()}",
                    "kind": "mutation",
                    "operationId": crud["update"],
                    "params": {"id": record},
                    "body": {flow["field"]: state},
                    "allow": f"transition:{state}",
                    "onSuccess": {"toast": f"{label} {humanize(state).lower()}"},
                }
                if state in self.locks.get(entity, set()):
                    move["confirm"] = f"Mark this {label.lower()} as {humanize(state).lower()}? It cannot change after."
                actions.append(move)
        if self.payments.get("entity") == entity and self.payments.get("checkout") in self.operations:
            actions.append(
                {
                    "id": "pay",
                    "label": self.w("pay"),
                    "kind": "pay",
                    "operationId": self.payments["checkout"],
                    "params": {"recordId": record},
                    "allow": "pay",
                }
            )
            self.place(self.payments["checkout"])
        if "delete" in crud and not self.others(entity):
            delete: dict[str, Any] = {
                "id": "delete",
                "label": self.w("delete"),
                "kind": "mutation",
                "operationId": crud["delete"],
                "params": {"id": record},
                "confirm": self.w("confirmDelete", label),
                "variant": "destructive",
                "onSuccess": {"toast": f"{label} deleted"},
            }
            if detail and "list" in crud:
                delete["onSuccess"]["navigate"] = slug
            actions.append(delete)
            self.place(crud["delete"])
        return actions

    def list_section(
        self,
        entity: str,
        op_id: str,
        section_id: str,
        params: dict[str, Any] | None = None,
        **content: Any,
    ) -> dict[str, Any]:
        shown = self.shown(entity)
        available = self.response_fields(op_id)
        skip = set((params or {}).keys())
        fields = [f for f in shown.get("listFields") or [] if f in available and f not in skip]
        query = self.query_params(op_id)
        references = {ref["field"] for ref in self.references(entity)}
        controls: dict[str, Any] = {}
        if "q" in query:
            controls["search"] = True
        operation = self.operations[op_id]["operation"]
        ranges = (operation.get("x-bga") or {}).get("ranges") or []  # Story 23.4: a calendar's date range
        bounds = {name for rng in ranges for name in (rng["from"], rng["to"])}
        filters = [
            name
            for name in query
            if name not in LIST_CONTROLS and name not in references and name not in skip and name not in bounds
        ]
        if filters:
            controls["filters"] = filters
        if ranges:
            controls["ranges"] = ranges
        most = ((query.get("limit") or {}).get("schema") or {}).get("maximum")
        if most:
            controls["maxLimit"] = most  # what a board or a calendar may load at once
        sort_enum = resolve(self.contract, (query.get("sort") or {}).get("schema") or {}).get("enum") or []
        sort = [value for value in sort_enum if not str(value).startswith("-")]
        if sort:
            controls["sort"] = sort
        self.place(op_id)
        return {
            "id": section_id,
            "component": "AppList",
            "data": {"operationId": op_id, **({"params": params} if params else {}), "fields": fields},
            "content": {
                "entity": entity,
                "title": self.plural(entity),
                "style": self.list_style(shown.get("listStyle") or "table"),
                **({"controls": controls} if controls else {}),
                "actions": self.record_actions(entity, "$record.id", detail=False),
                **content,
            },
        }

    # -- pages

    def page(self, page_id: str, route: str, title: str, sections: list[dict[str, Any]]) -> None:
        self.pages.append({"id": page_id, "route": route, "title": title[:120], "sections": sections})

    def entity_pages(self, entity: str) -> None:
        crud, slug, label, plural = self.crud[entity], self.slug(entity), self.label(entity), self.plural(entity)
        parent = self.route_parent(entity)
        # create from the entity's own list: not for a child that needs its parent (it is created from there)
        standalone_create = "create" in crud and parent is None
        create_fields = self.form_fields(entity, crud["create"]) if standalone_create else []
        # a create with nothing to fill in (the owner from the signed-in user, the rest defaulted: "start a session")
        # has no form page: it is a button on the list, like any other collection action
        button = standalone_create and not create_fields
        list_sections: list[dict[str, Any]] = []
        list_sections += self.collection_sections(entity)
        if button:
            self.create_button(entity, list_sections)
        if "list" in crud and not self.on_mine(entity):
            create = {"create": {"page": f"{slug}-new", "label": self.w("new", label)}}
            linked = create if standalone_create and not button else {}
            list_sections.append(self.list_section(entity, crud["list"], f"{slug}-list", **linked))
        if list_sections:
            self.page(slug, f"/{slug}", plural, list_sections)
        if standalone_create and not button:
            after = f"{slug}-id" if "get" in crud else slug if list_sections else "home"
            self.create_page(entity, f"{slug}-new", f"/{slug}/new", {}, after, create_fields)
        if parent and "create" in crud and not standalone_create and self.on_parent(entity) is None:
            parent_slug = self.slug(parent["entity"])
            self.create_page(
                entity,
                f"{parent_slug}-id-{slug}-new",
                f"/{parent_slug}/[id]/{slug}/new",
                {parent["field"]: "$route.id"},
                f"{parent_slug}-id",
            )
            self.assumptions.append(
                _note("/app", f"{plural} are added from their {self.label(parent['entity']).lower()}'s page")
            )
        if "get" in crud:
            self.detail_page(entity)
        if self.edits(entity):
            self.edit_page(entity)

    def create_button(self, entity: str, sections: list[dict[str, Any]]) -> None:
        """The create of an entity with nothing to fill in: a button in the list page's actions."""
        label, op_id = self.label(entity), self.crud[entity]["create"]
        action = {
            "id": "new",
            "label": self.w("new", label),
            "kind": "mutation",
            "operationId": op_id,
            "onSuccess": {"toast": self.w("created", label, lower=False)},
        }
        bar = next((s for s in sections if s["component"] == "AppActions"), None)
        if bar is not None:
            bar["content"]["actions"].insert(0, action)
        else:
            sections.append(
                {
                    "id": f"{self.slug(entity)}-actions",
                    "component": "AppActions",
                    "content": {"entity": entity, "actions": [action]},
                }
            )
        self.place(op_id)
        self.assumptions.append(
            _note("/pages", f'{self.plural(entity)}: nothing to fill in, so "{self.w("new", label)}" is a button')
        )

    def create_page(
        self,
        entity: str,
        page_id: str,
        route: str,
        hidden: dict[str, str],
        after: str,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        label, op_id = self.label(entity), self.crud[entity]["create"]
        suffix = "" if not hidden else f"_in_{to_camel(self.route_parent(entity)['entity'])}"  # type: ignore[index]
        form_id = self.add_form(
            {
                "id": f"{to_camel(entity)}_create{suffix}",
                "operationId": op_id,
                "fields": fields if fields is not None else self.form_fields(entity, op_id, hidden),
                "submitLabel": self.w("create", label),
                "onSuccess": {"toast": self.w("created", label, lower=False), "navigate": after},
            }
        )
        if form_id:
            section = {"id": f"{to_kebab(form_id)}-form", "component": "AppForm", "form": form_id}
            self.page(page_id, route, self.w("new", label), [{**section, "content": {"entity": entity}}])

    def edit_page(self, entity: str) -> None:
        crud, slug, label = self.crud[entity], self.slug(entity), self.label(entity)
        form: dict[str, Any] = {
            "id": f"{to_camel(entity)}_update",
            "operationId": crud["update"],
            "params": {"id": "$route.id"},
        }
        if "get" in crud:  # loaded from the record; without `get` the form starts empty (a partial update)
            form["load"] = {"operationId": crud["get"], "params": {"id": "$route.id"}}
        readable = self.response_fields(crud["get"]) if "get" in crud else None
        after = f"{slug}-id" if "get" in crud else slug
        form |= {
            "fields": self.form_fields(entity, crud["update"], readable=readable),
            "submitLabel": "Save changes",
            "onSuccess": {"toast": self.w("saved", label, lower=False), "navigate": after},
        }
        form_id = self.add_form(form)
        if form_id:
            section = {
                "id": f"{slug}-edit-form",
                "component": "AppForm",
                "form": form_id,
                "content": {"entity": entity},
            }
            self.page(f"{slug}-id-edit", f"/{slug}/[id]/edit", self.w("editOne", label), [section])

    def detail_page(self, entity: str) -> None:
        crud, slug, label = self.crud[entity], self.slug(entity), self.label(entity)
        available = self.response_fields(crud["get"])
        shown = self.shown(entity)
        sections = [
            {
                "id": f"{slug}-detail",
                "component": "AppDetail",
                "data": {
                    "operationId": crud["get"],
                    "params": {"id": "$route.id"},
                    "fields": [f for f in shown.get("detailFields") or [] if f in available],
                },
                "content": {
                    "entity": entity,
                    "title": label,
                    "actions": self.record_actions(entity, "$route.id", detail=True),
                    **({"onOpen": opened} if (opened := self.on_open(entity)) else {}),
                },
            }
        ]
        self.place(crud["get"])
        for op_id in self.custom[entity]:  # a record's own summary (`deck.stats`)
            found = self.operations[op_id]
            action = (found["operation"].get("x-bga") or {}).get("action")
            if found["method"] == "GET" and action != "list" and self.path_params(op_id) == ["id"]:
                if not self.required_query(op_id):
                    sections.append(
                        {
                            "id": to_kebab(op_id.replace(".", "-")),
                            "component": "AppDetail",
                            "data": {"operationId": op_id, "params": {"id": "$route.id"}},
                            "content": {"entity": entity, "title": self.op_label(op_id), "variant": "summary"},
                        }
                    )
                    self.place(op_id)
        listed = {child for child, _ in self.children_of(entity)}
        for child in self.entities:  # children created here but not listed here (`cartItem` on a product)
            reference = self.route_parent(child)
            if child in listed or not reference or reference["entity"] != entity or "create" not in self.crud[child]:
                continue
            if self.on_parent(child) is not None:
                continue  # already an action of the record
            sections[0]["content"]["actions"].insert(
                0,
                {
                    "id": f"add-{self.slug(child)}",
                    "label": self.w("add", self.label(child)),
                    "kind": "link",
                    "page": f"{slug}-id-{self.slug(child)}-new",
                    "params": {"id": "$route.id"},
                },
            )
        for child, reference in self.children_of(entity):
            if self.consumer and self.shape(child) == "interaction" and self.on_parent(child) is not None:
                continue  # Epic 32: a like is a button on the record, not a tab of the person's like rows
            child_slug, child_crud = self.slug(child), self.crud[child]
            create = {}
            if self.on_parent(child) is not None:
                pass  # the create is an action of this record
            elif (
                "create" in child_crud
                and child_crud["create"]
                and reference["field"] in self.required_inputs(child_crud["create"])
            ):
                create = {
                    "create": {
                        "page": f"{slug}-id-{child_slug}-new",
                        "label": self.w("add", self.label(child)),
                        "params": {"id": "$route.id"},
                    }
                }
            elif "create" in child_crud:
                create = {"create": {"page": f"{child_slug}-new", "label": self.w("add", self.label(child))}}
            sections.append(
                self.list_section(
                    child,
                    child_crud["list"],
                    f"{child_slug}-tab",
                    {reference["field"]: "$route.id"},
                    tab=self.plural(child),
                    **create,
                )
            )
            for op_id in self.custom[child]:  # a child's own lists that filter by this parent (`card.listDue`)
                found = self.operations[op_id]
                if (found["operation"].get("x-bga") or {}).get("action") != "list" or found["method"] != "GET":
                    continue
                if self.path_params(op_id) or reference["field"] not in self.query_params(op_id):
                    continue
                if set(self.required_query(op_id)) - {reference["field"]}:
                    continue
                section = self.list_section(
                    child,
                    op_id,
                    to_kebab(op_id.replace(".", "-")) + "-tab",
                    {reference["field"]: "$route.id"},
                    tab=self.op_label(op_id),
                )
                section["content"]["title"] = self.op_label(op_id)
                sections.append(section)
        sections += self.link_sections(entity)
        self.page(f"{slug}-id", f"/{slug}/[id]", label, sections)

    def collection_sections(self, entity: str) -> list[dict[str, Any]]:
        """The entity's custom operations on the whole collection, on its list page: summaries and buttons. Custom
        lists that no parent tab shows get pages of their own (`custom_list_pages`)."""
        sections: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        for op_id in self.custom[entity]:
            found = self.operations[op_id]
            if self.path_params(op_id) or self.required_query(op_id):
                continue
            action = (found["operation"].get("x-bga") or {}).get("action")
            if found["method"] == "GET" and action != "list":
                sections.append(
                    {
                        "id": to_kebab(op_id.replace(".", "-")),
                        "component": "AppDetail",
                        "data": {"operationId": op_id},
                        "content": {"entity": entity, "title": self.op_label(op_id), "variant": "summary"},
                    }
                )
                self.place(op_id)
            elif found["method"] != "GET":
                properties, _ = self.request(op_id)
                item: dict[str, Any] = {
                    "id": to_kebab(op_id.split(".", 1)[1]),
                    "label": self.op_label(op_id),
                    "kind": "mutation",
                    "operationId": op_id,
                    "onSuccess": {"toast": f"{self.op_label(op_id)}: done"},
                }
                if properties:
                    form_id = self.add_form(
                        {
                            "id": f"{to_camel(entity)}_{op_id.split('.', 1)[1]}",
                            "operationId": op_id,
                            "fields": self.form_fields(entity, op_id),
                            "submitLabel": self.op_label(op_id),
                            "onSuccess": {"toast": f"{self.op_label(op_id)}: done"},
                        }
                    )
                    if form_id is None:
                        continue
                    item["form"] = form_id
                if found["method"] == "DELETE":
                    item["confirm"] = f"{self.op_label(op_id)}?"
                actions.append(item)
                self.place(op_id)
        if actions:
            sections.append(
                {
                    "id": f"{self.slug(entity)}-actions",
                    "component": "AppActions",
                    "content": {"entity": entity, "actions": actions},
                }
            )
        return sections

    def custom_list_pages(self) -> None:
        """Custom lists no parent shows (`card.listDue` without a deck): a page of their own in the navigation."""
        routes = {page["route"] for page in self.pages}
        for entity in self.entities:
            for op_id in self.custom[entity]:
                found = self.operations[op_id]
                if (found["operation"].get("x-bga") or {}).get("action") != "list" or found["method"] != "GET":
                    continue
                if self.path_params(op_id) or self.required_query(op_id):
                    continue
                slug = self.slug(entity)
                tail = [part for part in found["path"].split("/") if part and not part.startswith("{")][-1]
                name = to_kebab(tail) if tail != slug else to_kebab(op_id.split(".", 1)[1])
                route = f"/{slug}/{name}" if name not in ("new", slug) else f"/{slug}/{to_kebab(op_id.split('.')[1])}"
                if route in routes:
                    continue
                page_id = f"{slug}-{name}"
                section = self.list_section(entity, op_id, f"{to_kebab(op_id.replace('.', '-'))}-list")
                section["content"]["title"] = self.op_label(op_id)
                self.page(page_id, route, self.op_label(op_id), [section])
                self.nav.append({"label": self.op_label(op_id)[:40], "page": page_id, "entity": entity})
                routes.add(route)

    def dashboard(self, name: str) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for index, item in enumerate(self.outline.get("dashboard") or []):
            op_id = item.get("operationId")
            if op_id not in self.operations:
                continue
            content = {key: item[key] for key in ("label", "kind", "entity", "groupBy", "fn", "field") if item.get(key)}
            sections.append(
                {
                    "id": f"figure-{index + 1}",
                    "component": "AppDashboard",
                    "data": {"operationId": op_id},
                    "content": content,
                }
            )
            self.place(op_id)
        recent = [
            item["entity"] for item in self.outline.get("nav") or [] if "list" in self.crud.get(item["entity"], {})
        ]
        for entity in recent[:RECENT_LISTS]:
            op_id = self.crud[entity]["list"]
            params: dict[str, Any] = {}
            if "limit" in self.query_params(op_id):
                params["limit"] = RECENT
            sort_enum = resolve(self.contract, (self.query_params(op_id).get("sort") or {}).get("schema") or {})
            newest = next((v for v in sort_enum.get("enum") or [] if v in ("-createdAt", "-updatedAt")), None)
            if newest:
                params["sort"] = newest
            section = self.list_section(entity, op_id, f"recent-{self.slug(entity)}", params or None, variant="recent")
            section["content"]["title"] = self.w("recent", self.plural(entity))
            section["data"]["fields"] = section["data"]["fields"][:3]
            sections.append(section)
        if not sections:
            sections.append({"id": "dashboard", "component": "AppDashboard", "content": {"label": name}})
        return sections

    def reach_every_page(self) -> None:
        """An entity's list (or create-only page) that neither the navigation nor a parent's page links to joins
        the navigation, so no screen is reachable only by its address."""
        in_nav = {item["page"] for item in self.nav}
        pages = {page["id"] for page in self.pages}
        for entity in self.entities:
            if self.parent_of(entity):
                continue
            slug = self.slug(entity)
            if slug in pages and slug not in in_nav:
                self.nav.append({"label": self.plural(entity), "page": slug, "entity": entity})
                self.assumptions.append(
                    _note("/layout/header/navigation", f"{self.plural(entity)} joined the navigation")
                )
            elif slug not in pages and f"{slug}-new" in pages and f"{slug}-new" not in in_nav:
                label = self.w("new", self.label(entity))
                self.nav.append({"label": label, "page": f"{slug}-new", "entity": entity})

    def build(self, name: str) -> list[dict[str, Any]]:
        for entity in self.entities:
            self.entity_pages(entity)
        self.custom_list_pages()
        self.plugin_pages()
        home = self.outline.get("home") or "dashboard"
        if home == "dashboard" and self.never("dashboard") and self.main:
            home = self.main  # Epic 32: people who use the product open on what they came for
        listed = {page["id"] for page in self.pages}
        nav = []
        for item in self.outline.get("nav") or []:
            page = self.slug(item["entity"])
            if page in listed:
                nav.append(
                    {"label": item.get("label") or self.plural(item["entity"]), "page": page, "entity": item["entity"]}
                )
        if home != "dashboard" and self.slug(home) in listed:
            home_page = next(page for page in self.pages if page["id"] == self.slug(home))
            self.page("home", "/", home_page["title"], [dict(section) for section in home_page["sections"]])
            # Story 23.1: an app that opens on a list keeps its figures on a dashboard page of their own, so every
            # aggregate has a screen (found on the golden apps: a catalogue home left `channel.count` unused)
            figures = [
                item for item in self.outline.get("dashboard") or [] if item.get("operationId") in self.operations
            ]
            if figures and "/dashboard" not in {page["route"] for page in self.pages} and not self.never("dashboard"):
                self.page("dashboard", "/dashboard", self.w("dashboard"), self.dashboard(name))
                nav.append({"label": self.w("dashboard"), "page": "dashboard"})
        else:
            self.page("home", "/", name, self.dashboard(name))
            nav.insert(0, {"label": self.w("dashboard"), "page": "home"})
        self.nav = nav + self.nav
        if self.consumer:
            self.nav = self.pattern_menu()
        else:
            self.reach_every_page()
        self.pages.sort(key=lambda page: (page["route"] != "/", page["route"]))
        return self.pages

    def list_style(self, style: str) -> str:
        """A consumer area's lists are records to look at, never a staff table (Epic 32)."""
        return "cards" if self.consumer and style == "table" else style

    def pattern_menu(self) -> list[dict[str, Any]]:
        """The menu of a consumer pattern (Epic 32): the main entity, the cart, and one "Mine" page for the person's
        own reactions and contributions; nothing else joins it (`reach_every_page` is a back-office's)."""
        entries = self.pattern.menu or []
        pages = {page["id"] for page in self.pages}
        by_page = {item["page"]: item for item in self.nav}
        menu: list[dict[str, Any]] = []
        if "main" in entries and self.main and self.slug(self.main) in pages:
            menu.append(
                by_page.get(self.slug(self.main))
                or {"label": self.plural(self.main), "page": self.slug(self.main), "entity": self.main}
            )
        from .patterns import child_shapes

        shapes = child_shapes(self.contract)
        own = {child: info for child, info in shapes.items() if info["owned"] and child in self.entities}
        cart = self.cart()
        # the cart in the menu: the person's container of its lines when there is one (a Cart of CartItems)
        container = next(
            (p for p in (shapes.get(cart or "") or {}).get("ownedVia") or [] if self.slug(p) in pages), None
        )
        shown = container or cart
        if shown and self.slug(shown) in pages:
            menu.append(
                by_page.get(self.slug(shown))
                or {"label": self.plural(shown), "page": self.slug(shown), "entity": shown}
            )
        for entity in self.entities:  # the person's own top-level records ("My orders"): a page of their own
            if entity in (self.main, cart, container) or entity in own or self.slug(entity) not in pages:
                continue
            listing = self.operations.get(self.crud[entity].get("list") or "")
            policy = ((listing or {}).get("operation", {}).get("x-bga") or {}).get("policy") or {}
            if policy.get("type") == "ownership":
                menu.append(
                    by_page.get(self.slug(entity))
                    or {"label": self.plural(entity), "page": self.slug(entity), "entity": entity}
                )
        if "mine" in entries:
            mine = [
                child
                for child, info in own.items()
                if child != cart and info["shape"] in ("interaction", "contribution") and "list" in self.crud[child]
            ]
            if mine:
                labels = {item.get("entity"): item.get("label") for item in self.outline.get("nav") or []}
                sections = [
                    self.list_section(
                        child,
                        self.crud[child]["list"],
                        f"{self.slug(child)}-mine",
                        tab=labels.get(child) or self.plural(child),
                    )
                    for child in mine
                ]
                self.page("mine", "/mine", self.w("mine"), sections)
                menu.append({"label": self.w("mine"), "page": "mine"})
        if not menu:  # no main entity known: the outline's menu as drafted
            return [item for item in self.nav if item["page"] != "dashboard"]
        return menu


def app_frontend_spec(
    backend: dict[str, Any], outline: dict[str, Any], theme: dict[str, Any], contract: dict[str, Any] | None = None
) -> AppScreens:
    """The FrontendSpec of an app (a dict, as the draft stores it) from the completed outline, the BackendSpec (with
    the dashboard's aggregates already added, `ensure_aggregates`) and its contract."""
    project = backend.get("project") or {}
    name = outline.get("name") or project.get("name") or "App"
    app = {key: value for key, value in outline.items() if key != "dashboard"} | {"name": name}
    app["dashboard"] = [
        {key: v for key, v in item.items() if key != "operationId"} for item in outline.get("dashboard") or []
    ]
    if contract is None:  # an empty shell (Story 22.1)
        pages = [
            {
                "id": "home",
                "route": "/",
                "title": name,
                "sections": [{"id": "dashboard", "component": "AppDashboard", "content": {"label": name}}],
            }
        ]
        spec = _spec(name, project, theme, app, pages, [], [])
        return AppScreens(spec)
    areas = outline.get("areas") or []
    if areas:  # Story 23.10: a set of screens per group of roles, each under its prefix
        screens, pages, forms, navigation = _area_screens(backend, outline, contract, name, areas)
    else:
        from .design import home_entity
        from .patterns import screen_pattern

        design = outline.get("design") or {}
        main = design.get("mainEntity") or home_entity(design)
        roles = list((backend.get("auth") or {}).get("roles") or [])
        pattern = screen_pattern(design.get("archetype"), roles, main, contract)
        screens = _Screens(backend, outline, contract, pattern=pattern, main=main)
        pages = screens.build(name)
        forms = screens.forms
        navigation = [{"label": item["label"][:60], "page": item["page"]} for item in screens.nav]
    known = {page["id"] for page in pages}
    for page in pages:  # a create link to a page that was not planned (its form had no field) is no link
        for section in page.get("sections") or []:
            content = section.get("content") or {}
            link = content.get("create")
            if isinstance(link, dict) and link.get("page") not in known:
                content.pop("create")
                screens.unresolved.append(_note("/pages", f"{page['id']}: no page to create from ({link['page']})"))
    spec = _spec(name, project, theme, app, pages, forms, navigation)
    if screens.auth and any(page["id"] == "login" for page in pages):  # Story 22.7: the app signs in
        spec["auth"] = {"signIn": "login", "signUp": "register", "login": "auth.login", "me": "auth.me"}
    for op_id in uncovered_operations(spec, contract):
        found = screens.operations[op_id]
        screens.unresolved.append(
            _note(
                "/pages",
                f"{op_id} ({found['method']} {found['path']}) has no screen: the kit has no place for its parameters",
            )
        )
    return AppScreens(spec, screens.assumptions, screens.unresolved)


PLUGIN_PAGES = frozenset({"AppAuth", "AppPayment"})  # shared by every area: one sign-in, one payment return


def _callable(contract: dict[str, Any], roles: list[str]) -> set[str]:
    """The operations these roles may call (public ones too): the same rules as the kit's access map."""
    out = set()
    for op_id, found in contract_operations(contract).items():
        operation = found["operation"]
        policy = (operation.get("x-bga") or {}).get("policy") or {}
        if policy.get("type") == "role" and not set(policy.get("roles") or []) & set(roles):
            continue
        out.add(op_id)
    return out


def _renamed(value: Any, ids: dict[str, str], forms: dict[str, str]) -> Any:
    """A page part with its links to the area's pages and forms renamed (`page`, `form`, `formId` keys)."""
    if isinstance(value, list):
        return [_renamed(item, ids, forms) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key in ("page", "navigate") and isinstance(item, str) and item in ids:
            out[key] = ids[item]
        elif key in ("form", "formId") and isinstance(item, str) and item in forms:
            out[key] = forms[item]
        else:
            out[key] = _renamed(item, ids, forms)
    return out


def _area_screens(
    backend: dict[str, Any], outline: dict[str, Any], contract: dict[str, Any], name: str, areas: list[dict[str, Any]]
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Story 23.10: each area's screens from the operations its roles may call; the first area at `/`, the others
    under their prefix with their pages and forms renamed (`<area>-<id>`); sign-in and payment pages once. Every
    operation must be on a screen of some area whose roles may call it (the coverage check runs on the union)."""
    from .design import home_entity
    from .patterns import screen_pattern

    first: _Screens | None = None
    pages: list[dict[str, Any]] = []
    forms: list[dict[str, Any]] = []
    navigation: list[dict[str, Any]] = []
    shared: set[str] = set()
    for index, area in enumerate(areas):
        design = area.get("design") or {}
        allowed = _callable(contract, area.get("roles") or [])
        entities = {item.get("entity") for item in outline.get("nav") or []}
        listed = {
            entity for entity in entities
            if any(f"{entity[:1].lower()}{entity[1:]}.list" == op_id for op_id in allowed)
        }  # fmt: skip
        area_outline = {
            **outline,
            "home": home_entity(design) or "dashboard",
            "nav": [item for item in outline.get("nav") or [] if item.get("entity") in listed] or outline.get("nav"),
        }
        main = design.get("mainEntity") or home_entity(design)
        pattern = screen_pattern(design.get("archetype"), area.get("roles") or [], main, contract)
        screens = _Screens(backend, area_outline, contract, allowed, pattern=pattern, main=main)
        built = screens.build(name)
        if index == 0:
            first = screens
            shared = {page["id"] for page in built if any(s.get("component") in PLUGIN_PAGES for s in page["sections"])}
            pages += built
            forms += screens.forms
            navigation += [{"label": item["label"][:60], "page": item["page"]} for item in screens.nav]
            continue
        prefix = area["prefix"].rstrip("/")
        own = [page for page in built if page["id"] not in shared]
        ids = {page["id"]: f"{area['id']}-{page['id']}" for page in own}
        stem = re.sub(r"[^A-Za-z0-9]+", "_", area["id"])  # form ids are identifiers
        form_ids = {form["id"]: f"{stem}_{form['id']}" for form in screens.forms}
        for page in own:
            renamed = _renamed(page, ids, form_ids)
            renamed["id"] = ids[page["id"]]
            renamed["route"] = prefix + ("" if page["route"] == "/" else page["route"])
            pages.append(renamed)
        used = {s.get("form") for page in own for s in page["sections"]}
        for form in screens.forms:
            if form["id"] in used:
                forms.append({**_renamed(form, ids, form_ids), "id": form_ids[form["id"]]})
        navigation += [
            {"label": item["label"][:60], "page": ids.get(item["page"], item["page"])}
            for item in screens.nav
            if item["page"] in ids
        ]
        first.assumptions += screens.assumptions  # type: ignore[union-attr]
        first.unresolved += screens.unresolved  # type: ignore[union-attr]
    pages.sort(key=lambda page: (page["route"] != "/", page["route"]))
    return first, pages, forms, navigation


def _spec(
    name: str,
    project: dict[str, Any],
    theme: dict[str, Any],
    app: dict[str, Any],
    pages: list[dict[str, Any]],
    forms: list[dict[str, Any]],
    navigation: list[dict[str, Any]],
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "specVersion": SPEC_VERSION,
        "project": {
            "name": name,
            "mode": "dynamic",
            "flow": "app",
            **_description(project),
            **({"locale": app["locale"]} if app.get("locale") else {}),  # Story 23.8
        },
        "theme": theme,
        "layout": {"shell": "sidebar", "header": {"logoText": name, "navigation": navigation}},
        "app": app,
        "pages": pages,
    }
    if forms:
        spec["forms"] = forms
    return spec


def _description(project: dict[str, Any]) -> dict[str, Any]:
    return {"description": project["description"]} if project.get("description") else {}
