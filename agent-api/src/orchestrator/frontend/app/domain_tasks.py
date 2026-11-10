"""Epic 33 (Story 33.1): a domain's UX tasks judged on a planned app, without a browser.

A task names a role, a goal and a check; the check reads the FrontendSpec the planner wrote (pages, sections, actions,
forms) and the contract. Each result says passed or failed, the clicks it took and, when it failed, why, so the
baseline (today's kit) and later runs (the domain plugins) are compared task by task.
"""

from typing import Any

from src.modules.shared.domain.backend_spec.naming import name_words

from .ux_checks import _actions, _area_of, _page_operation


def _words(text: str) -> set[str]:
    return {word.lower() for word in name_words(text)}


def _matches(op_id: str | None, verbs: list[str]) -> bool:
    """An operation id whose words include one of the verbs (`delivery.accept`, `alert.acknowledgeAlert`)."""
    if not op_id:
        return False
    words = _words(op_id.replace(".", " "))
    return any(verb.lower() in words or any(word.startswith(verb.lower()) for word in words) for verb in verbs)


def _action_matches(action: dict[str, Any], verbs: list[str]) -> bool:
    """An action doing one of the verbs: by its operation, its reaction kind (a like toggle) or its id."""
    if _matches(action.get("operationId"), verbs):
        return True
    if action.get("reaction") in verbs:
        return True
    return _matches(str(action.get("id") or "").replace("-", " "), verbs)


class _Area:
    """The pages of the area whose roles include the task's role, and its home page."""

    def __init__(self, spec: dict[str, Any], role: str) -> None:
        areas = (spec.get("app") or {}).get("areas") or [{"id": "app", "roles": [], "prefix": "/"}]
        role_l = role.lower()
        chosen = next((a for a in areas if any(role_l in r.lower() or r.lower() in role_l for r in a["roles"])), None)
        self.found = chosen is not None
        self.area = chosen or areas[0]
        prefix = self.area["prefix"].rstrip("/") or "/"
        self.pages = [p for p in spec["pages"] if _area_of(p["route"], areas) == self.area["id"]]
        self.home = next((p for p in self.pages if p["route"] == prefix), self.pages[0] if self.pages else None)
        self.forms = {form["id"]: form for form in spec.get("forms") or []}

    def actions(self) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
        return [(page, component, action) for page in self.pages for component, action in _actions(page)]

    def clicks(self, verbs: list[str]) -> int | None:
        """Clicks from the area's home: an action on the home is 1, an action on another page 2, a form page 3."""
        if self.home is not None and any(_action_matches(a, verbs) for _, a in _actions(self.home)):
            return 1
        if any(_action_matches(a, verbs) for _, _, a in self.actions()):
            return 2
        if any(_matches(_page_operation(page, self.forms), verbs) for page in self.pages):
            return 3
        return None


def _result(task: dict[str, Any], passed: bool, why: str = "", clicks: int | None = None) -> dict[str, Any]:
    budget = task.get("budget")
    if passed and budget is not None and clicks is not None and clicks > budget:
        passed, why = False, f"{clicks} clicks, the budget is {budget}"
    return {
        "id": task["id"],
        "role": task["role"],
        "goal": task["goal"],
        "passed": passed,
        "clicks": clicks,
        "why": why,
    }


def _check_action(task, area: _Area, verbs: list[str]) -> dict[str, Any]:
    clicks = area.clicks(verbs)
    if clicks is None:
        return _result(task, False, f"no action for {'/'.join(verbs)} in the {area.area['id']} area")
    return _result(task, True, clicks=clicks)


def _check_reaction_state(task, area: _Area, verbs: list[str]) -> dict[str, Any]:
    found = [a for _, _, a in area.actions() if _action_matches(a, verbs)]
    if not found:
        return _result(task, False, f"no {'/'.join(verbs)} action")
    stateful = [a for a in found if a.get("state")]
    if not stateful:
        return _result(task, False, "the button shows no state (the person can't see they already did it)")
    return _result(task, True, clicks=area.clicks(verbs))


def _parent_field(field: dict[str, Any]) -> bool:
    name = field.get("name") or ""
    return name.startswith("parent") and name.endswith("Id")


def _check_reply(task, area: _Area, spec: dict[str, Any]) -> dict[str, Any]:
    """A reply is made from the comment being answered: a comment thread section, or a Reply action on a comment whose
    form sets the parent from that comment. A parent picked from a list on the add-comment form is not a reply."""
    threads = [s for page in area.pages for s in page.get("sections") or [] if s.get("component") == "CommentThread"]
    if threads:
        return _result(task, True, clicks=2)
    picker = False
    for _, _, action in area.actions():
        form = area.forms.get(action.get("form") or "")
        parents = [f for f in (form or {}).get("fields") or [] if _parent_field(f)]
        if any(f.get("hidden") and str(f.get("value", "")).startswith("$record") for f in parents):
            return _result(task, True, clicks=3)
        picker = picker or bool(parents)
    if picker:
        return _result(task, False, "the parent comment is picked from a list on the add-comment form, not replied to")
    return _result(task, False, "comments have no reply: nothing creates a comment under another comment")


def _check_section(task, area: _Area, components: list[str]) -> dict[str, Any]:
    for page in area.pages:
        if any(s.get("component") in components for s in page.get("sections") or []):
            return _result(task, True, clicks=1 if page is area.home else 2)
    return _result(task, False, f"no {'/'.join(components)} section in the area")


def _check_field_shown(task, area: _Area, words: list[str]) -> dict[str, Any]:
    for page in area.pages:
        for section in page.get("sections") or []:
            fields = (section.get("data") or {}).get("fields") or []
            content = section.get("content") or {}
            if any(any(w in f.lower() for w in words) for f in fields) or any(content.get(w) is True for w in words):
                return _result(task, True, clicks=1 if page is area.home else 2)
    return _result(task, False, f"no {'/'.join(words)} shown in the area")


def _check_filter(task, area: _Area, entity_words: list[str], field_words: list[str]) -> dict[str, Any]:
    for page in area.pages:
        for section in page.get("sections") or []:
            entity = ((section.get("content") or {}).get("entity") or "").lower()
            if section.get("component") != "AppList" or not any(w in entity for w in entity_words):
                continue
            controls = (section.get("content") or {}).get("controls") or {}
            filters = controls.get("filters") or [] if isinstance(controls, dict) else []
            names = [f.get("field", f) if isinstance(f, dict) else f for f in filters]
            if any(any(w in str(n).lower() for w in field_words) for n in names):
                return _result(task, True, clicks=1 if page is area.home else 2)
    return _result(task, False, f"no {'/'.join(entity_words)} list filtered by {'/'.join(field_words)}")


def _check_action_with_file(task, area: _Area, verbs: list[str]) -> dict[str, Any]:
    found = [a for _, _, a in area.actions() if _action_matches(a, verbs)]
    if not found:
        return _result(task, False, f"no {'/'.join(verbs)} action")
    for action in found:
        form = area.forms.get(action.get("form") or "")
        if form and any(f.get("type") in ("file", "image") or f.get("upload") for f in form.get("fields") or []):
            return _result(task, True, clicks=area.clicks(verbs))
    return _result(task, False, "the action takes no photo")


def _check_resume(task, area: _Area) -> dict[str, Any]:
    if area.home is None:
        return _result(task, False, "the area has no home")
    for section in area.home.get("sections") or []:
        if (section.get("content") or {}).get("resume") or section.get("component") == "AppResume":
            return _result(task, True, clicks=1)
    return _result(task, False, "the home has no way back to the last lesson")


def judge(spec: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each task's result on the planned app (a FrontendSpec)."""
    out = []
    for task in tasks:
        area = _Area(spec, task["role"])
        if not area.found:
            out.append(_result(task, False, f"no area for the role '{task['role']}'"))
            continue
        check = task["check"]
        kind = check["kind"]
        if kind == "action":
            out.append(_check_action(task, area, check["verbs"]))
        elif kind == "reaction_state":
            out.append(_check_reaction_state(task, area, check["verbs"]))
        elif kind == "reply":
            out.append(_check_reply(task, area, spec))
        elif kind == "section":
            out.append(_check_section(task, area, check["components"]))
        elif kind == "field_shown":
            out.append(_check_field_shown(task, area, check["words"]))
        elif kind == "filter":
            out.append(_check_filter(task, area, check["entity_words"], check["field_words"]))
        elif kind == "action_with_file":
            out.append(_check_action_with_file(task, area, check["verbs"]))
        elif kind == "resume":
            out.append(_check_resume(task, area))
        else:
            out.append(_result(task, False, f"unknown check '{kind}'"))
    return out


def summary(results: list[dict[str, Any]]) -> dict[str, int]:
    return {"tasks": len(results), "passed": sum(r["passed"] for r in results)}
