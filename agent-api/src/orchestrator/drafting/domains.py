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
    chosen = {str(f) for f in block.get("features") or []} & {use.feature for use in domain.features.optional}
    for use in [*domain.features.required, *(u for u in domain.features.optional if u.feature in chosen)]:
        feature = registry().feature(use.feature)
        role = use.on or (feature.attaches_to if feature else None)
        target = roles.get(role or "") if role not in ("person", "app") else None
        uses.append({"feature": use.feature, "on": target, "options": dict(use.options)})
    merged, notes = attach(backend, uses)
    attached = {item["feature"] for item in merged.get("features") or []}
    missing = [use.feature for use in domain.features.required if use.feature not in attached]
    if missing:
        notes.append(_note(f"The {domain.label} domain needs {', '.join(missing)}, which did not attach; kept generic"))
        return backend, None, notes
    types = {
        area: kind
        for area, kind in (block.get("types") or {}).items()
        if registry().type(domain.name, str(kind)) is not None
    }
    checked = {"name": domain.name, "roles": roles, "types": types, "features": sorted(chosen & attached)}
    notes.insert(0, _note(f"Built on the {domain.label} domain"))
    return merged, checked, notes


def _note(message: str) -> Note:
    return {"spec": "backend", "path": "/features", "message": message, "suggestion": None}
