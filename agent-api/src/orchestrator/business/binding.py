"""The business words bound to the app (Story 26.3) and the guided tour's data (Story 26.4).

The binding (one provider call at draft time, `business/flow.py`) names, per workflow step, the operation that
performs it and the page where it is done. Code checks every name against the contract and the planned screens; what
does not match is a **binding problem** with its reason, never dropped silently. From the binding, `tour_workflows`
writes what `app.json` `workflows` gives the kit's `AppTour`: per core workflow, its steps in order, each with its role,
page (route) and the action target on that page (`data-bga-section` / `data-bga-action`). Epic 28 adds each step's
`kind` (`do`: the user performs its operation; `look`: a section that shows data; `note`: automatic, another role's or
not on the screens) and, for steps on a record page, `needs` (the earlier step that makes a record ready for it).
"""

import hashlib
import json
from typing import Any

from .model import actor_name, all_steps, core, paths


def _resolve(doc: dict[str, Any], schema: Any) -> Any:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 10:
        target: Any = doc
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        schema, seen = target, seen + 1
    return schema


def _fields(doc: dict[str, Any], schema: Any, request: bool) -> dict[str, Any]:
    schema = _resolve(doc, schema)
    if not isinstance(schema, dict):
        return {}
    if schema.get("type") == "array":
        return {"[]": _fields(doc, schema.get("items"), request)}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    for name, prop in (schema.get("properties") or {}).items():
        prop = _resolve(doc, prop)
        if not isinstance(prop, dict):
            continue
        source = (prop.get("x-bga") or {}).get("source")
        if request and (prop.get("readOnly") or source in ("currentUser", "server")):
            continue
        kind = prop.get("type") or ("object" if "properties" in prop else "any")
        if isinstance(kind, list):  # ["string", "null"]: nullable
            kind = next((k for k in kind if k != "null"), "any")
        text = kind + (f" {prop['format']}" if prop.get("format") else "")
        if prop.get("enum"):
            text = "enum " + "|".join(map(str, prop["enum"]))
        if kind == "array" and isinstance(prop.get("items"), dict):
            items = _resolve(doc, prop["items"])
            text = f"array of {items.get('type') or 'object'}"
        if request and name in required:
            text += " required"
        out[name] = text
    return out


def compact_operations(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """The contract's operations in a few words each: method, path, roles, query, body and response fields."""
    operations = []
    for path, methods in (contract.get("paths") or {}).items():
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            entry: dict[str, Any] = {
                "operationId": op.get("operationId"),
                "method": method.upper(),
                "path": path,
                "summary": op.get("summary") or op.get("description") or "",
            }
            policy = (op.get("x-bga") or {}).get("policy") or {}
            if policy.get("roles"):
                entry["roles"] = policy["roles"]
            if op.get("security"):
                entry["signedIn"] = True
            params = [p.get("name") for p in op.get("parameters") or [] if p.get("in") == "query"]
            if params:
                entry["query"] = params
            body = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
            if body:
                entry["body"] = _fields(contract, body, request=True)
            for code, response in (op.get("responses") or {}).items():
                if str(code).startswith("2"):
                    schema = ((response.get("content") or {}).get("application/json") or {}).get("schema")
                    entry["status"] = int(code)
                    if schema:
                        entry["response"] = _fields(contract, schema, request=False)
                    break
            operations.append(entry)
    return operations


def compact_pages(frontend_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The planned screens in a few words: page id, route, title, sections with their actions."""
    forms = {form["id"]: form for form in frontend_spec.get("forms") or [] if isinstance(form, dict)}
    pages = []
    for page in frontend_spec.get("pages") or []:
        sections = []
        for section in page.get("sections") or []:
            content = section.get("content") or {}
            text = section.get("component") or "?"
            operation = (section.get("data") or {}).get("operationId")
            form = forms.get(section.get("form") or "")
            if operation:
                text += f" of {operation}"
            if form:
                text += f" (form submitting {form.get('operationId')})"
            actions = [
                a.get("operationId") or a.get("label") or a.get("id")
                for a in content.get("actions") or []
                if isinstance(a, dict)
            ]
            if actions:
                text += f" (actions: {', '.join(map(str, actions))})"
            sections.append(text)
        pages.append({"page": page.get("id"), "route": page.get("route"), "title": page.get("title"),
                      "sections": sections})  # fmt: skip
    return pages


def demo_roles(spec: dict[str, Any]) -> dict[str, int]:
    """Role → how many demo users it has (the auth plugin's and the policies plugin's second users)."""
    from src.orchestrator.plugins import extended_spec

    auth = spec.get("auth") or {}
    if not auth:
        return {}
    extended = extended_spec(spec)
    user_entity = auth.get("userEntity") or "User"
    out: dict[str, int] = {}
    for seed in extended.get("seed") or []:
        if seed.get("entity") == user_entity:
            for record in seed.get("records") or []:
                if record.get("role"):
                    out[record["role"]] = out.get(record["role"], 0) + 1
    return out


def check_binding(
    binding: dict[str, Any],
    operations: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    roles: dict[str, int],
    business: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every name the binding uses, checked: operations, pages, roles, status values; with `business`, every core
    step bound (an operation and a page, or `automatic`) or listed with why not. Returns the problems."""
    by_id = {op["operationId"]: op for op in operations}
    page_ids = {page["page"] for page in pages}
    problems = list(binding.get("unbound") or [])
    for kind in ("setup", "steps", "effects"):
        for item in binding.get(kind) or []:
            if kind == "steps" and item.get("automatic"):
                continue
            if item.get("operationId") not in by_id:
                what = f"{kind} {item.get('step') or item.get('var') or item.get('effect')}"
                problems.append({"what": what, "reason": f"unknown operation {item.get('operationId')!r}"})
            for key in ("pathParamsJson", "queryJson", "bodyJson"):
                text = item.get(key) or ""
                if text:
                    try:
                        if not isinstance(json.loads(text), dict):
                            raise ValueError("not an object")
                    except ValueError:
                        what = f"{kind} {item.get('step') or item.get('var')}"
                        problems.append({"what": what, "reason": f"{key} is not a JSON object"})
    for item in binding.get("steps") or []:
        if item.get("page") and item["page"] not in page_ids:
            problems.append({"what": f"page of {item.get('step')}", "reason": f"unknown page {item['page']!r}"})
    for record in binding.get("records") or []:
        op = by_id.get(record.get("getOperation") or "")
        if op is None:
            problems.append({"what": f"record {record.get('record')}", "reason": "no operation reads one by id"})
            continue
        field = (op.get("response") or {}).get(record.get("statusField") or "", "")
        allowed = field[5:].split("|") if isinstance(field, str) and field.startswith("enum ") else None
        for status in record.get("statuses") or []:
            if allowed is not None and status.get("value") not in allowed:
                problems.append(
                    {
                        "what": f"status {status.get('business')!r} of {record.get('record')}",
                        "reason": f"{status.get('value')!r} is not one of {allowed}",
                    }
                )
    for actor in binding.get("actors") or []:
        if actor.get("role") and actor["role"] not in roles:
            problems.append({"what": f"actor {actor.get('actor')}", "reason": f"unknown role {actor['role']!r}"})
    return problems + _unbound_core_steps(binding, business or {}, problems)


def _unbound_core_steps(
    binding: dict[str, Any], business: dict[str, Any], problems: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Core steps the binding left out or bound without a page (a step already named in a problem is not repeated)."""
    bound: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in binding.get("steps") or []:
        bound.setdefault((item.get("workflow"), item.get("step")), []).append(item)
    named = " ".join(str(p.get("what") or "") for p in problems)
    out = []
    for workflow in core(business):
        for _, step in all_steps(workflow):
            items = bound.get((workflow["id"], step["id"])) or []
            if any(i.get("automatic") or (i.get("operationId") and i.get("page")) for i in items):
                continue
            if step["id"] in named:
                continue
            reason = "bound without a page" if items else "the binding left this step out"
            out.append({"what": f"step {step['id']} of {workflow['id']}", "reason": reason})
    return out


# -- 26.4 the tour's data ---------------------------------------------------------------------------------------------


def action_targets(frontend_spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """operationId → where the UI performs it: page, route, section, action (an action button, a form's submit)."""
    forms = {form["id"]: form for form in frontend_spec.get("forms") or [] if isinstance(form, dict)}
    out: dict[str, list[dict[str, Any]]] = {}
    for page in frontend_spec.get("pages") or []:
        for section in page.get("sections") or []:
            base = {"page": page.get("id"), "route": page.get("route"), "section": section.get("id")}
            for action in (section.get("content") or {}).get("actions") or []:
                if isinstance(action, dict) and action.get("operationId"):
                    out.setdefault(action["operationId"], []).append({**base, "action": action.get("id")})
            form = forms.get(section.get("form") or "")
            if form and form.get("operationId"):
                out.setdefault(form["operationId"], []).append({**base, "action": "submit"})
            data = (section.get("data") or {}).get("operationId")
            if data:
                out.setdefault(data, []).append({**base, "action": None})
            opened = (section.get("content") or {}).get("onOpen")  # Epic 32: done by opening the record (a view)
            if isinstance(opened, dict) and opened.get("operationId"):
                out.setdefault(opened["operationId"], []).append({**base, "action": None})
    return out


def tour_workflows(
    business: dict[str, Any], binding: dict[str, Any], frontend_spec: dict[str, Any]
) -> dict[str, Any] | None:
    """`app.json` `workflows`: one tour per core workflow (its main path), each step with its role, page, target and
    text. A step whose target is not on the screens keeps its text and says why (`skip`)."""
    roles = {item.get("actor"): item.get("role") for item in binding.get("actors") or [] if item.get("role")}
    bound = {(s.get("workflow"), s.get("path"), s.get("step")): s for s in binding.get("steps") or []}
    targets = action_targets(frontend_spec)
    pages = {page.get("id"): page for page in frontend_spec.get("pages") or []}
    tours = []
    for workflow in core(business):
        main = dict(paths(workflow))["main"]
        steps = []
        for step in main:
            item = bound.get((workflow["id"], "main", step["id"])) or {}
            role = roles.get(step.get("actor"))
            text = step.get("action") or ""
            if step.get("statusAfter"):
                text += f" (the {step.get('record')} becomes {step['statusAfter']})"
            if step.get("rule"):
                text += f". Rule: {step['rule']}"
            entry: dict[str, Any] = {
                "id": step["id"],
                "role": role,
                "actor": actor_name(business, step.get("actor", "")),
                "title": text[:1].upper() + text[1:],
                "operationId": item.get("operationId") or None,
            }
            if step.get("statusAfter"):
                entry["statusAfter"] = step["statusAfter"]
            if item.get("automatic"):
                entry["automatic"] = True
            places = targets.get(item.get("operationId") or "") or []
            wanted = item.get("page")
            # an action that performs the step, on the bound page first; else (a step that looks at something) the
            # section that shows the operation's data
            place = (
                next((p for p in places if p["page"] == wanted and p["action"]), None)
                or next((p for p in places if p["action"]), None)
                or next((p for p in places if p["page"] == wanted), None)
                or next(iter(places), None)
            )
            if place is None and wanted in pages:
                place = {"page": wanted, "route": pages[wanted].get("route"), "section": None, "action": None}
            if place is not None:
                entry |= {"page": place["page"], "route": place["route"]}
                if place.get("section"):
                    entry["target"] = {"section": place["section"], "action": place.get("action")}
            if role is None:
                entry["skip"] = "no app role plays this actor"
            elif "target" not in entry and not item.get("automatic"):
                entry["skip"] = "no screen performs this step"
            entry["kind"] = step_kind(entry)
            if step.get("record"):
                entry["record"] = step["record"]
            needs = _needs(steps, entry, step.get("record"))
            if needs is not None:
                entry["needs"] = needs
            steps.append(entry)
        tours.append(
            {
                "id": workflow["id"],
                "name": workflow.get("name"),
                "outcome": workflow.get("outcome"),
                "roles": sorted({s["role"] for s in steps if s.get("role")}),
                "steps": steps,
            }
        )
    if not tours:
        return None
    version = hashlib.sha256(json.dumps(tours, sort_keys=True).encode()).hexdigest()[:12]
    return {"version": version, "tours": tours}


def step_kind(entry: dict[str, Any]) -> str:
    """Epic 28 (D2): `do` when the step performs an operation through a control on the screen (an action button, a
    form's submit), `look` when its target is a section that shows data, `note` when the app does it by itself, no app
    role plays its actor or no screen performs it. A step of another role is a `note` for the viewer: the kit decides
    that at run time, since the role depends on who is signed in."""
    if entry.get("automatic") or entry.get("skip") or not entry.get("target"):
        return "note"
    return "do" if entry["target"].get("action") else "look"


def _needs(earlier: list[dict[str, Any]], entry: dict[str, Any], record: str | None) -> dict[str, Any] | None:
    """Story 28.4: a `do` step on a record page needs a record its action is allowed on. The earlier `do` step of
    the same workflow on the same record is what makes one (a create, or the status change before this one), with
    the status it leaves the record in when the binding knows it."""
    if entry.get("kind") != "do" or not record or "[" not in str(entry.get("route") or ""):
        return None
    for previous in reversed(earlier):
        if previous.get("record") == record and previous.get("kind") == "do":
            needs: dict[str, Any] = {"step": previous["id"], "role": previous.get("role")}
            status = previous.get("statusAfter")
            if status:
                needs["status"] = status
            return needs
    return None
