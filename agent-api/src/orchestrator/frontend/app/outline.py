"""The app outline, completed by code (Story 22.2): the model drafts what it knows; code fills every missing field
from the BackendSpec and fixes what it can (an unknown entity or field is dropped, a bad value replaced), each with
a note. No model call: an outline error never costs a repair round.
"""

import re
from typing import Any

from pydantic import ValidationError

from src.modules.shared.domain.backend_spec.naming import pluralize
from src.modules.shared.domain.frontend_spec.app import (
    MAX_DASHBOARD,
    MAX_LIST_FIELDS,
    AppDashboardItem,
    AppEntity,
    AppNavItem,
    AppOutline,
)
from src.orchestrator.frontend.app.design import complete_design, design_notes, home_entity

NUMERIC = frozenset({"integer", "float", "decimal"})
HIDDEN = frozenset({"id", "allowedActions", "passwordHash", "password"})
TEXT_TYPES = frozenset({"string", "text"})
IMAGE_TYPES = frozenset({"image"})
_WORDS = re.compile(r"([a-z0-9])([A-Z])")


def humanize(name: str) -> str:
    """`dueDate` → `Due date`, `ReviewLog` → `Review log`, `deck_id` → `Deck id`."""
    words = _WORDS.sub(r"\1 \2", name).replace("_", " ").strip()
    return words[:1].upper() + words[1:].lower()


def plural(label: str) -> str:
    """`Review log` → `Review logs`: the last word pluralized."""
    head, _, last = label.rpartition(" ")
    return f"{head} {pluralize(last)}" if head else pluralize(last)


def field_label(name: str, references: dict[str, str]) -> str:
    """A field's label: a foreign key is named after its parent (`deckId` → `Deck`)."""
    return humanize(references[name]) if name in references else humanize(name)


def _note(path: str, message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": f"/app{path}", "message": message, "suggestion": None}


class _Entity:
    """What the BackendSpec and the contract say about one entity."""

    def __init__(self, entity: dict[str, Any], info: dict[str, Any], user_entity: str = "User"):
        self.name = entity["name"]
        self.fields = {field["name"]: field for field in entity.get("fields") or []}
        self.label_field = info.get("labelField")
        # foreign key → the parent's API name (`deckId` → `deck`)
        self.references = {ref["field"]: ref["apiName"] for ref in info.get("references") or []}
        # the records it is made on (Epic 32): its referenced entities but the signed-in user's
        self.parents = [
            ref["entity"] for ref in info.get("references") or [] if ref.get("entity") not in (user_entity, self.name)
        ]

    def shown(self) -> list[str]:
        """Fields a screen can show, in the spec's order."""
        return [
            name
            for name, field in self.fields.items()
            if name not in HIDDEN and not field.get("primary") and not field.get("secret")
        ]

    def numeric(self, name: str | None) -> bool:
        return bool(name) and (self.fields.get(name) or {}).get("type") in NUMERIC

    def display_field(self) -> str | None:
        if self.label_field and self.label_field in self.fields:
            return self.label_field
        shown = self.shown()
        text = next((n for n in shown if self.fields[n].get("type") in TEXT_TYPES), None)
        return text or next(iter(shown), None)  # no text field: the first one shown

    def default_list_fields(self, display: str | None) -> list[str]:
        """The display field, then the first required fields (parents included), up to five."""
        fields = [display] if display else []
        for name in self.shown():
            field = self.fields[name]
            if (
                name not in fields
                and field.get("required")
                and field.get("type") != "text"
                and field.get("default") != "now"
            ):
                fields.append(name)
        for name in self.shown():  # fill from the optional fields when few are required
            if len(fields) >= min(4, len(self.shown())):
                break
            if name not in fields and self.fields[name].get("type") not in ("text", "json"):
                fields.append(name)
        return fields[:MAX_LIST_FIELDS]


def complete_outline(
    raw: Any,
    backend: dict[str, Any],
    contract: dict[str, Any],
    archetype_hint: str | None = None,
    seed: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The drafted outline (any JSON) → a complete outline (`AppOutline` fields, camelCase) and the notes. Epic 23:
    the design brief and the areas are completed by `design.complete_design` (`archetype_hint`: code's pick from the
    requirement when the brief names no archetype)."""
    notes: list[dict[str, Any]] = []
    info = ((contract.get("x-bga") or {}).get("entities")) or {}
    user_entity = (((contract.get("x-bga") or {}).get("auth")) or {}).get("userEntity") or "User"
    entities = {e["name"]: _Entity(e, info.get(e["name"]) or {}, user_entity) for e in backend.get("entities") or []}
    raw = dict(raw) if isinstance(raw, dict) else {}
    raw_design, raw_areas = raw.pop("design", None), raw.pop("areas", None)
    outline = _parse(_capped(raw, notes), notes)

    nav = []
    for index, item in enumerate(outline.nav):
        if item.entity not in entities:
            notes.append(_note(f"/nav/{index}", f"Navigation item '{item.entity}' names no entity; left out"))
        elif all(item.entity != kept.entity for kept in nav):
            nav.append(item)
    for name in _top_level(entities, backend):  # then every entity with a list and no parent (Story 22.3)
        if all(name != kept.entity for kept in nav):
            nav.append(AppNavItem(entity=name))
    outline.nav = nav
    if outline.home != "dashboard" and outline.home not in entities:
        notes.append(_note("/home", f"Home '{outline.home}' names no entity; the dashboard is the home page"))
        outline.home = "dashboard"

    completed: dict[str, AppEntity] = {}
    for name, entity in entities.items():
        drafted = outline.entities.get(name) or AppEntity()
        completed[name] = _entity(name, entity, drafted, notes)
    for name in sorted(set(outline.entities) - set(entities)):
        notes.append(_note(f"/entities/{name}", f"Entity '{name}' is not in the BackendSpec; left out"))
    outline.entities = completed

    dashboard = []
    for index, item in enumerate(outline.dashboard):
        problem = _dashboard_problem(item, entities)
        if problem:
            notes.append(_note(f"/dashboard/{index}", f"Dashboard item '{item.label}': {problem}; left out"))
        else:
            dashboard.append(item)
    outline.dashboard = dashboard
    out = outline.model_dump(by_alias=True, mode="json", exclude_none=True)
    out.pop("areas", None)
    briefed = isinstance(raw_design, dict)
    if not briefed:  # no brief (a draft before Epic 23, or none written): the outline's own choices are the defaults
        raw_design = {
            "homeView": "dashboard" if out.get("home", "dashboard") == "dashboard" else None,
            "mainEntity": None if out.get("home", "dashboard") == "dashboard" else out["home"],
            "entities": {
                name: {"view": item["listStyle"]} for name, item in out["entities"].items() if item.get("listStyle")
            },
        }
    locale = raw.get("locale") if isinstance(raw, dict) else None
    design, areas, replaced = complete_design(raw_design, raw_areas, backend, archetype_hint, seed=seed, locale=locale)
    if not briefed and out.get("home", "dashboard") != "dashboard" and design["homeView"] == "dashboard":
        design["homeView"] = "catalogue"  # the outline opens on a list: keep that
    if briefed:  # the brief decides the home page: a list home opens on the main entity's list
        out["home"] = home_entity(design) or "dashboard"
    out["design"] = design
    if areas:
        out["areas"] = areas
    notes += design_notes(replaced)
    return out, notes


def _capped(raw: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    """Too many list fields or dashboard items: the first ones are kept (a note), not the whole part dropped."""
    out = dict(raw)
    if isinstance(out.get("dashboard"), list) and len(out["dashboard"]) > MAX_DASHBOARD:
        notes.append(_note("/dashboard", f"More than {MAX_DASHBOARD} dashboard items; the first {MAX_DASHBOARD} kept"))
        out["dashboard"] = out["dashboard"][:MAX_DASHBOARD]
    if isinstance(out.get("entities"), dict):
        entities = {}
        for name, item in out["entities"].items():
            fields = item.get("listFields") if isinstance(item, dict) else None
            if isinstance(fields, list) and len(fields) > MAX_LIST_FIELDS:
                path = f"/entities/{name}/listFields"
                notes.append(_note(path, f"More than {MAX_LIST_FIELDS} list fields; the first {MAX_LIST_FIELDS} kept"))
                item = {**item, "listFields": fields[:MAX_LIST_FIELDS]}
            entities[name] = item
        out["entities"] = entities
    return out


def _top_level(entities: dict[str, "_Entity"], backend: dict[str, Any]) -> list[str]:
    """Entities with a CRUD `list` operation and no parent, in the BackendSpec's order: the default navigation."""
    listed = {
        op.get("entity")
        for op in backend.get("operations") or []
        if op.get("type") == "crud" and op.get("action") == "list"
    }
    return [name for name, entity in entities.items() if name in listed and not entity.references]


def _parse(raw: dict[str, Any], notes: list[dict[str, Any]]) -> AppOutline:
    """Validates the outline part by part: a part that does not fit its schema is dropped (and noted), never the
    whole outline."""
    try:
        return AppOutline.model_validate(raw)
    except ValidationError:
        pass
    kept: dict[str, Any] = {}
    for key, value in raw.items():
        try:
            AppOutline.model_validate({key: value})
            kept[key] = value
            continue
        except ValidationError as exc:
            problem = exc.errors()[0]
        if isinstance(value, list) and key in ("nav", "dashboard"):
            items = []
            for index, item in enumerate(value):
                try:
                    AppOutline.model_validate({key: [item]})
                    items.append(item)
                except ValidationError as item_exc:
                    notes.append(_note(f"/{key}/{index}", f"Not valid ({item_exc.errors()[0]['msg']}); left out"))
            kept[key] = items
        elif isinstance(value, dict) and key == "entities":
            kept[key] = {}
            for name, item in value.items():
                try:
                    AppOutline.model_validate({key: {name: item}})
                    kept[key][name] = item
                    continue
                except ValidationError as item_exc:
                    item_problem = item_exc.errors()[0]["msg"]
                if not isinstance(item, dict):
                    notes.append(_note(f"/entities/{name}", f"Not valid ({item_problem}); defaults used"))
                    continue
                try:  # the entity's valid parts, its bad ones from defaults
                    AppOutline.model_validate({key: {name: {}}})
                except ValidationError:
                    notes.append(_note(f"/entities/{name}", f"Not valid ({item_problem}); left out"))
                    continue
                parts = {}
                for part, part_value in item.items():
                    try:
                        AppEntity.model_validate({part: part_value})
                        parts[part] = part_value
                    except ValidationError as part_exc:
                        message = f"Not valid ({part_exc.errors()[0]['msg']}); the default used"
                        notes.append(_note(f"/entities/{name}/{part}", message))
                kept[key][name] = parts
        else:
            notes.append(_note(f"/{key}", f"'{key}' is not valid ({problem['msg']}); left out"))
    try:
        return AppOutline.model_validate(kept)
    except ValidationError:  # pragma: no cover: every part was checked on its own
        return AppOutline()


def _known(fields: list[str], entity: _Entity, path: str, notes: list[dict[str, Any]]) -> list[str]:
    known = [name for name in dict.fromkeys(fields) if name in entity.fields and name not in HIDDEN]
    unknown = [name for name in fields if name not in entity.fields or name in HIDDEN]
    if unknown:
        notes.append(_note(path, f"{entity.name} has no field(s) {', '.join(unknown)} to show; left out"))
    return known


def _entity(name: str, entity: _Entity, drafted: AppEntity, notes: list[dict[str, Any]]) -> AppEntity:
    path = f"/entities/{name}"
    label = drafted.label or humanize(name)
    display = drafted.display_field
    if display and display not in entity.fields:
        notes.append(
            _note(f"{path}/displayField", f"{name} has no field '{display}'; its records are named by default")
        )
        display = None
    display = display or entity.display_field()
    list_fields = _known(drafted.list_fields, entity, f"{path}/listFields", notes) or entity.default_list_fields(
        display
    )
    detail_fields = _known(drafted.detail_fields, entity, f"{path}/detailFields", notes)
    rest = [field for field in entity.shown() if field not in detail_fields]
    labels = {
        field: drafted.field_labels.get(field) or field_label(field, entity.references) for field in entity.shown()
    }
    style = drafted.list_style or (
        "cards" if any(entity.fields[f].get("type") in IMAGE_TYPES for f in list_fields) else "table"
    )
    create = drafted.create
    if create in ("onRecord", "onOpen") and not entity.parents:
        notes.append(_note(f"{path}/create", f"{name} has no parent record to be made on; placed by default"))
        create = None
    return AppEntity(
        label=label,
        plural=drafted.plural or plural(label),
        display_field=display,
        list_fields=list_fields,
        list_style=style,
        detail_fields=detail_fields + rest,
        field_labels=labels,
        help={field: text for field, text in drafted.help.items() if field in entity.fields},
        create=create,
    )


def _dashboard_problem(item: AppDashboardItem, entities: dict[str, _Entity]) -> str | None:
    entity = entities.get(item.entity)
    if entity is None:
        return f"no entity '{item.entity}'"
    if item.fn != "count" and not entity.numeric(item.field):
        return f"'{item.fn}' needs a number field of {item.entity}"
    if item.group_by and item.group_by not in entity.fields:
        return f"{item.entity} has no field '{item.group_by}' to group by"
    if item.date_field and (entity.fields.get(item.date_field) or {}).get("type") not in ("date", "datetime"):
        return f"'{item.date_field}' is not a date of {item.entity}"
    if item.date_field and not item.period:
        return "`dateField` needs a `period`"
    if item.kind != "figure" and not item.group_by:
        return "a chart needs `groupBy`"
    unknown = [name for name in item.filter if name not in entity.fields]
    if unknown:
        return f"{item.entity} has no field(s) {', '.join(unknown)} to filter on"
    return None
