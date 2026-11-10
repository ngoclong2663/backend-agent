"""Epic 33 (Story 33.4): merge feature plugins into a drafted BackendSpec.

A feature's descriptor (`templates/features/<name>/feature.json`) carries a BackendSpec fragment written with
placeholders; attached to a drafted entity it becomes plain entities, relationships, operations, rules and policies,
so the whole existing pipeline (validation, access rules, CRUD templates, contract, mocks, screens) works on it. What
plain entries can't say (computed fields) goes in the spec's `features` block. The model's own entity for the same
thing (a drafted `Comment` beside the `comments` feature) is dropped with a note: the feature owns its data.

Placeholders: `{Target}` / `{target}` / `{targets}` / `{targetPath}` (the entity, camel, kebab plural, kebab),
`{Person}` / `{person}` (the signed-in user's entity), `{kind}` / `{Kind}` (each value of the `kinds` option, in
computed fields), and `"{option:<name>}"` as a whole list item (replaced by that option's values).
"""

import copy
from typing import Any

from src.modules.shared.domain.backend_spec.naming import pluralize, to_kebab
from src.modules.shared.domain.domains.registry import FeatureDescriptor, registry

Note = dict[str, Any]


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def _option_values(feature: FeatureDescriptor, options: dict[str, Any], name: str) -> list[Any]:
    value = options.get(name, (feature.options.get(name) or {}).get("default"))
    return list(value) if isinstance(value, list) else [value]


def _fill(value: Any, words: dict[str, str], lists: dict[str, list[Any]]) -> Any:
    """The fragment with its placeholders filled (keys too)."""
    if isinstance(value, str):
        for key, word in words.items():
            value = value.replace("{" + key + "}", word)
        return value
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if isinstance(item, str) and item.startswith("{option:") and item.endswith("}"):
                out.extend(lists.get(item[len("{option:") : -1], []))
            else:
                out.append(_fill(item, words, lists))
        return out
    if isinstance(value, dict):
        return {_fill(key, words, lists): _fill(item, words, lists) for key, item in value.items()}
    return value


def _words(target: str, person: str) -> dict[str, str]:
    return {
        "Target": target,
        "target": _camel(target),
        "targets": to_kebab(pluralize(target)),
        "targetPath": to_kebab(target),
        "Person": person,
        "person": _camel(person),
    }


def _entity_names(spec: dict[str, Any]) -> list[str]:
    return [entity["name"] for entity in spec.get("entities") or []]


def _replaced(spec: dict[str, Any], feature: FeatureDescriptor, target: str, owned: set[str]) -> list[str]:
    """Drafted entities the feature takes over: named like one of its words (`comment`, `like`) and pointing at the
    target (a `<target>Id` field or a relationship from the target)."""
    words = {word.lower() for word in feature.replaces}
    fk = f"{_camel(target)}Id"
    children = {rel["to"] for rel in spec.get("relationships") or [] if rel.get("from") == target}
    out = []
    for entity in spec.get("entities") or []:
        name = entity["name"]
        if name in owned or name == target:
            continue
        bare = name.lower().removeprefix(target.lower())
        if not any(bare == w or bare == pluralize(w) or name.lower() == w for w in words):
            continue
        fields = {field["name"] for field in entity.get("fields") or []}
        if fk in fields or name in children:
            out.append(name)
    return out


def _drop(spec: dict[str, Any], names: set[str]) -> None:
    """Removes entities and everything that names them (relationships, operations, rules, policies, seeds)."""
    spec["entities"] = [e for e in spec.get("entities") or [] if e["name"] not in names]
    spec["relationships"] = [
        r for r in spec.get("relationships") or [] if r.get("from") not in names and r.get("to") not in names
    ]
    dropped_ops = {op["operationId"] for op in spec.get("operations") or [] if op.get("entity") in names}
    spec["operations"] = [op for op in spec.get("operations") or [] if op["operationId"] not in dropped_ops]
    spec["rules"] = [r for r in spec.get("rules") or [] if r.get("entity") not in names]
    spec["policies"] = [p for p in spec.get("policies") or [] if p.get("entity") not in names]
    spec["seed"] = [s for s in spec.get("seed") or [] if s.get("entity") not in names]
    if spec.get("x-frontendBindings"):
        spec["x-frontendBindings"] = [b for b in spec["x-frontendBindings"] if b.get("operationId") not in dropped_ops]


def attach(spec: dict[str, Any], uses: list[dict[str, Any]]) -> tuple[dict[str, Any], list[Note]]:
    """`uses`: `[{"feature": "comments", "on": "Clip", "options": {...}}]`. Returns a new spec with each feature merged
    (skipped with a note when its target is missing or a name clashes) and the notes."""
    out = copy.deepcopy(spec)
    notes: list[Note] = []
    person = ((out.get("auth") or {}).get("userEntity")) or "User"
    out.setdefault("features", [])
    owned = {name for attached in out["features"] for name in attached.get("entities") or []}
    for use in uses:
        feature = registry().feature(use["feature"])
        target = use.get("on")
        if feature is None:
            notes.append(_note(f"/features/{use['feature']}", f"The '{use['feature']}' feature is not available"))
            continue
        if target not in _entity_names(out) and feature.attaches_to not in ("app", "person"):
            notes.append(_note(f"/features/{feature.name}", f"'{target}' is not an entity; {feature.label} left out"))
            continue
        target = target or person
        options = {**{k: v.get("default") for k, v in feature.options.items()}, **(use.get("options") or {})}
        words = _words(target, person)
        lists = {name: _option_values(feature, options, name) for name in feature.options}
        fragment = _fill(feature.spec, words, lists)
        new_names = [entity["name"] for entity in fragment.get("entities") or []]
        replaced = _replaced(out, feature, target, owned)
        if replaced:
            _drop(out, set(replaced))
            for name in replaced:
                notes.append(
                    _note(
                        f"/entities/{name}", f"'{name}' is now the {feature.label} feature's ({', '.join(new_names)})"
                    )
                )
        clash = [name for name in new_names if name in _entity_names(out)]
        if clash:
            notes.append(_note(f"/entities/{clash[0]}", f"'{clash[0]}' already exists; {feature.label} left out"))
            continue
        for key in ("entities", "relationships", "operations", "rules", "policies", "seed"):
            if fragment.get(key):
                out.setdefault(key, []).extend(fragment[key])
        computed = []
        for item in feature.computed:
            values = lists.get("kinds") if "{kind}" in item.field or "{Kind}" in item.field else [None]
            for value in values or [None]:
                extra = {} if value is None else {"kind": str(value), "Kind": str(value)[:1].upper() + str(value)[1:]}
                filled = _fill(item.model_dump(exclude_none=True), {**words, **extra}, lists)
                filled["where"] = {k: (str(value) if v == "{kind}" else v) for k, v in filled.get("where", {}).items()}
                computed.append(filled)
        out["features"].append(
            {"feature": feature.name, "on": target, "options": options, "entities": new_names, "computed": computed}
        )
        owned.update(new_names)
        notes.append(_note(f"/features/{feature.name}", f"{feature.label} added to {target}"))
    if not out["features"]:
        out.pop("features")
    return out, notes


def _note(path: str, message: str) -> Note:
    return {"spec": "backend", "path": path, "message": message, "suggestion": None}
