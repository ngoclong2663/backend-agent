"""Epic 33 (Story 33.6): the domain a requirement describes, and the draft built on it.

Code ranks the ready domains from the requirement's words and offers them to `draft_app@v10`; the model names one in
the outline (`domain`: the domain, the entity playing each core role, a type per area, the optional features it turns
on). Code checks that answer against the domain (roles played by real entities, features that attach) and merges the
features into the BackendSpec. A requirement no domain fits, or an answer that doesn't hold, keeps the generic flow.
"""

import re
from typing import Any

from src.modules.shared.domain.domains.registry import DomainDescriptor, registry

from .features import attach

Note = dict[str, Any]
MIN_SCORE = 2  # distinct domain words a requirement must use before the domain is offered


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()))


def rank_domains(requirement: str) -> list[DomainDescriptor]:
    """The ready domains whose words the requirement uses, best first (at least `MIN_SCORE` distinct words)."""
    tokens = _tokens(requirement)
    scored = []
    for domain in registry().ready_domains():
        score = len({word.lower() for word in domain.words} & tokens)
        if score >= MIN_SCORE:
            scored.append((score, domain))
    scored.sort(key=lambda item: (-item[0], item[1].order, item[1].name))
    return [domain for _, domain in scored]


def offered(domains: list[DomainDescriptor]) -> list[dict[str, Any]]:
    """What the prompt shows of each offered domain."""
    out = []
    for domain in domains:
        out.append(
            {
                "name": domain.name,
                "choose": domain.choose,
                "roles": {name: role.label for name, role in domain.roles.items() if not role.person},
                "areas": [{"id": area.id, "label": area.label, "people": area.people} for area in domain.areas],
                "types": [(kind.name, kind.choose) for kind in registry().ready_types(domain.name)],
                "brings": [_brought(use.feature) for use in domain.features.required],
                "optional": [use.feature for use in domain.features.optional],
            }
        )
    return out


def _brought(name: str) -> str:
    """A feature as the prompt names it: its label and what it does (`Comments: people write comments …`)."""
    feature = registry().feature(name)
    return f"{feature.label} ({feature.choose.rstrip('.')})" if feature else name


AUTHOR_FIELDS = ("authorId", "creatorId", "ownerId", "userId", "memberId", "postedById", "createdById")
SECTION_FIELDS = ("section", "sectionId", "category", "categoryId", "topic", "topicId")


def role_field(backend: dict[str, Any], entity: str, kind: str) -> str | None:
    """A drafted entity's field by what it means: `author` (its ownership policy's owner, else a field named like a
    maker), `section` (its section, category or topic)."""
    found = next((e for e in backend.get("entities") or [] if e["name"] == entity), None)
    if found is None:
        return None
    fields = [field["name"] for field in found.get("fields") or []]
    if kind == "author":
        owner = next(
            (
                p.get("ownerField")
                for p in backend.get("policies") or []
                if p.get("entity") == entity and p.get("type") == "ownership" and p.get("ownerField") in fields
            ),
            None,
        )
        roles = [f"{role[:1].lower()}{role[1:]}Id" for role in (backend.get("auth") or {}).get("roles") or []]
        return owner or next((f for f in (*AUTHOR_FIELDS, *roles) if f in fields), None)
    if kind == "section":
        return next((f for f in SECTION_FIELDS if f in fields), None)
    if kind == "photo":  # the record's own photo field when it has one (`doorPhoto`), else the feature's
        typed = {field["name"]: field.get("type") for field in found.get("fields") or []}
        named = [f for f in fields if any(word in f.lower() for word in ("proof", "photo", "picture", "image"))]
        return next((f for f in named if typed.get(f) in ("image", "file")), None) or (
            named[0] if named else "proofPhoto"
        )
    return None


def _options(
    backend: dict[str, Any], target: str | None, options: dict[str, Any], roles: dict[str, str]
) -> dict[str, Any] | None:
    """A use's options with their placeholders resolved (None: the draft has no such field): `{author}`, `{section}`
    (the target's field by meaning), `{time}` (its first date-time field), `{entity:<role>}` (the entity playing a
    role), `{role:<role>}` (the target's key to that entity: `courseId`), `{state:<word>}` (the target's status value
    containing the word)."""
    out = dict(options)
    fields = {f["name"]: f for e in backend.get("entities") or [] if e["name"] == target for f in e.get("fields") or []}
    for name, value in options.items():
        if not (isinstance(value, str) and value.startswith("{") and value.endswith("}")):
            continue
        what, _, arg = value[1:-1].partition(":")
        resolved: str | None
        if what == "entity":
            resolved = roles.get(arg)
        elif what == "role":
            entity = roles.get(arg) or ""
            resolved = (
                f"{entity[:1].lower()}{entity[1:]}Id" if f"{entity[:1].lower()}{entity[1:]}Id" in fields else None
            )
        elif what == "time":
            resolved = next((n for n, f in fields.items() if f.get("type") == "datetime" and n != "createdAt"), None)
            resolved = resolved or ("createdAt" if "createdAt" in fields else None)
        elif what == "state":
            values = [str(v) for f in fields.values() if f.get("type") == "enum" for v in f.get("values") or []]
            resolved = next((v for v in values if arg.lower() in v.lower()), None)
        else:
            resolved = role_field(backend, target or "", what)
        if resolved is None:
            return None
        out[name] = resolved
    return out


def _entity_for(role_name: str, domain: DomainDescriptor, named: str | None, entities: list[str], main: str | None):
    """The drafted entity playing a core role: the model's choice when it exists, else one named like the role."""
    if named in entities:
        return named
    words = {w.lower() for w in domain.roles[role_name].words}
    found = next((e for e in entities if e.lower() in words or e.lower().rstrip("s") in words), None)
    if found:
        return found
    area_main = next((a for a in domain.areas if a.main == role_name), None)
    return main if area_main and main in entities else None


def apply_domain(backend: dict[str, Any], outline: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[Note]]:
    """The BackendSpec with the domain's features merged, the domain block code checked (None: the generic flow), and
    the notes. `outline` is the drafted outline (any JSON)."""
    block = (outline or {}).get("domain") if isinstance(outline, dict) else None
    if not isinstance(block, dict) or not block.get("name"):
        return backend, None, []
    domain = registry().domain(str(block["name"]))
    if domain is None:
        return backend, None, [_note(f"The draft named the domain '{block['name']}', which is not available")]
    entities = [entity["name"] for entity in backend.get("entities") or []]
    main = ((outline.get("design") or {}).get("mainEntity")) if isinstance(outline.get("design"), dict) else None
    roles: dict[str, str] = {}
    for name, role in domain.roles.items():
        if role.person:
            continue
        found = _entity_for(name, domain, (block.get("roles") or {}).get(name), entities, main)
        if found is None:
            message = f"No entity plays the {domain.label} domain's {role.label.lower()}; kept generic"
            return backend, None, [_note(message)]
        roles[name] = found
    uses = []
    skipped: list[Note] = []
    chosen = {str(f) for f in block.get("features") or []} & {use.feature for use in domain.features.optional}
    for use in [*domain.features.required, *(u for u in domain.features.optional if u.feature in chosen)]:
        feature = registry().feature(use.feature)
        role = use.on or (feature.attaches_to if feature else None)
        target = roles.get(role or "") if role not in ("person", "app") else None
        options = _options(backend, target, use.options, roles)
        if options is None:
            skipped.append(_note(f"{use.feature} left out: {target} has no field for it"))
            continue
        uses.append({"feature": use.feature, "on": target, "options": options})
    merged, notes = attach(backend, uses)
    notes = skipped + notes
    attached = {item["feature"] for item in merged.get("features") or []}
    missing = [use.feature for use in domain.features.required if use.feature not in attached]
    if missing:
        notes.append(_note(f"The {domain.label} domain needs {', '.join(missing)}, which did not attach; kept generic"))
        return backend, None, notes
    types: dict[str, str] = {}
    for area, name in (block.get("types") or {}).items():  # a type stays only on an area it lays out
        kind = registry().type(domain.name, str(name))
        if kind is not None and area in kind.areas:
            types[str(area)] = str(name)
    for area in domain.areas:  # an area the answer named no type for takes the domain's first ready one
        if area.id not in types:
            fitting = next((kind for kind in registry().ready_types(domain.name) if area.id in kind.areas), None)
            if fitting is not None:
                types[area.id] = fitting.name
    for area in (outline.get("areas") or []) if isinstance(outline.get("areas"), list) else []:
        # the draft's own area ids (`driver` for the domain's `drivers`): matched by its roles and the domain's people
        if not isinstance(area, dict) or area.get("id") in types:
            continue
        roles_lower = {str(r).lower() for r in area.get("roles") or []}
        for domain_area in domain.areas:
            people = {p.lower() for p in domain_area.people}
            if domain_area.id in types and any(r in people or r.rstrip("s") in people for r in roles_lower):
                types[str(area.get("id"))] = types[domain_area.id]
                break
    checked = {"name": domain.name, "roles": roles, "types": types, "features": sorted(chosen & attached)}
    notes.insert(0, _note(f"Built on the {domain.label} domain"))
    return merged, checked, notes


def _note(message: str) -> Note:
    return {"spec": "backend", "path": "/features", "message": message, "suggestion": None}
