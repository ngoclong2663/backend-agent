"""UX checks per kind of product (Epic 32, Story 32.1): how a planned app behaves for the people of each area.

Pure functions over a planned app (the FrontendSpec of `app_frontend_spec`, its BackendSpec and contract); no
browser. Each area is judged by its kind (`patterns.area_kind`: its archetype, or `back-office` for staff who manage
the main entity's records): shared checks for every area, the consumer checks for areas whose people use the product
rather than manage it, and the kind's own checks (`feed`, `storefront`, `back-office`). Each finding names the
check, the page's route and why.

The main task of a consumer area is counted in clicks from the area's home on the planned screens (`task_clicks`):
an action on the home's cards is one click, on the record's page two (open it, act), a form page three (open the
record, open the form, submit); a task with no screen is `None`.
"""

from functools import partial
from typing import Any

from src.orchestrator.integration.contract import contract_operations

from .patterns import app_areas, area_kind, child_shapes, children_of
from .screens import _callable

CONSUMER = frozenset({"feed", "storefront", "catalogue", "booking", "learning"})  # people use it, staff do not run it
PLUGIN_SECTIONS = frozenset({"AppAuth", "AppPayment"})  # shared by every area: never judged as an area's screen


def _area_of(route: str, areas: list[dict[str, Any]]) -> str:
    """The area a route belongs to: the longest prefix it starts with (`/` takes what no other area takes)."""
    best, length = areas[0]["id"], -1
    for area in areas:
        prefix = area["prefix"].rstrip("/")
        if (route == prefix or route.startswith(prefix + "/") or prefix == "") and len(prefix) > length:
            best, length = area["id"], len(prefix)
    return best


def _page_operation(page: dict[str, Any], forms: dict[str, dict[str, Any]]) -> str | None:
    for section in page.get("sections") or []:
        if (section.get("data") or {}).get("operationId"):
            return section["data"]["operationId"]
        if section.get("form") in forms:
            return forms[section["form"]].get("operationId")
    return None


def _actions(page: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(section component, action) for every action of a page's sections."""
    return [
        (section["component"], action)
        for section in page.get("sections") or []
        for action in (section.get("content") or {}).get("actions") or []
    ]


def _cart(children: dict[str, dict[str, Any]]) -> str | None:
    """A shopper's cart: an owned child of the main entity with a quantity."""
    return next((child for child, info in children.items() if info["owned"] and info["quantity"]), None)


def _clicks(op_id: str | None, pages: list[dict[str, Any]], home: dict[str, Any] | None, forms: dict) -> int | None:
    """Clicks from the home to the operation: an action on the home is 1, on another page 2, a form page 3."""
    if op_id is None:
        return None
    if home is not None and any(action.get("operationId") == op_id for _, action in _actions(home)):
        return 1
    if any(action.get("operationId") == op_id for page in pages for _, action in _actions(page)):
        return 2
    if any(_page_operation(page, forms) == op_id for page in pages):
        return 3
    return None


def ux_checks(spec: dict[str, Any], backend: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Per area: its archetype, the checks it passes and fails (with the route and why), and its main task's clicks."""
    areas = app_areas(spec, list((backend.get("auth") or {}).get("roles") or []))
    for area in areas:  # judged by what the area is for its people (Story 32.2: staff areas are back-office)
        area["kind"] = area_kind(area["archetype"], area["roles"], area["main"], contract)
    forms = {form["id"]: form for form in spec.get("forms") or []}
    ops = contract_operations(contract)
    shapes = child_shapes(contract)
    pages_of: dict[str, list[dict[str, Any]]] = {area["id"]: [] for area in areas}
    for page in spec.get("pages") or []:
        if any(section.get("component") in PLUGIN_SECTIONS for section in page.get("sections") or []):
            continue
        pages_of[_area_of(page["route"], areas)].append(page)
    by_id = {page["id"]: page for page in spec.get("pages") or []}
    menu = (spec.get("layout") or {}).get("header", {}).get("navigation") or []
    out = []
    for area in areas:
        pages = pages_of[area["id"]]
        callable_ = _callable(contract, area["roles"])
        failures: list[dict[str, Any]] = []
        passed: list[str] = []
        check = partial(_record, failures, passed)
        area_menu = [by_id[i["page"]] for i in menu if i.get("page") in by_id and by_id[i["page"]] in pages]
        home = next((p for p in pages if p["route"] == (area["prefix"].rstrip("/") or "/")), None)
        main = area["main"]
        children = children_of(shapes, main)
        # every area: no page its roles cannot use
        check(
            "no-unusable-page",
            [
                (page["route"], f"{op} is not for {', '.join(area['roles'])}")
                for page in pages
                if (op := _page_operation(page, forms)) and op in ops and op not in callable_
            ],
        )
        if area["kind"] in CONSUMER:
            listed = {
                (s.get("content") or {}).get("entity")
                for page in area_menu
                for s in page.get("sections") or []
                if s.get("component") == "AppList"
            }
            check(
                "no-dashboard",
                [
                    (page["route"], "a page of figures for people who use the product")
                    for page in ([home] if home else []) + area_menu
                    if any(s.get("component") == "AppDashboard" for s in page.get("sections") or [])
                ],
            )
            check(
                "no-table",
                [
                    (page["route"], f"{(s.get('content') or {}).get('entity')} as a table")
                    for page in pages
                    for s in page.get("sections") or []
                    if s.get("component") == "AppList" and (s.get("content") or {}).get("style") == "table"
                ],
            )
            cart = _cart(children) if area["kind"] == "storefront" else None
            check(
                "no-own-interaction-menu",
                [
                    ("menu", f"{entity}: a table of a person's own reactions in the menu")
                    for entity in sorted(
                        e
                        for e in listed
                        if e in children
                        and children[e]["shape"] == "interaction"
                        and children[e]["owned"]
                        and e != cart
                    )
                ],
            )
            creatable = {
                (found["operation"].get("x-bga") or {}).get("entity")
                for op_id, found in ops.items()
                if (found["operation"].get("x-bga") or {}).get("action") == "create" and op_id in callable_
            }
            check(
                "no-edit-others",
                [
                    (page["route"], f"edits {forms[s['form']]['operationId']}: these roles create no such record")
                    for page in pages
                    for s in page.get("sections") or []
                    if s.get("form") in forms
                    and ((ops.get(forms[s["form"]]["operationId"]) or {}).get("operation", {}).get("x-bga") or {}).get(
                        "action"
                    )
                    == "update"
                    and ((ops[forms[s["form"]]["operationId"]]["operation"].get("x-bga") or {}).get("entity"))
                    not in creatable
                ],
            )
        task, clicks = None, None
        if area["kind"] == "feed":
            check(
                "home-is-feed", [] if home and _lists(home, main) else [(area["prefix"], f"the home lists no {main}")]
            )
            interactions = {
                c: i for c, i in children.items() if i["shape"] == "interaction" and i["create"] in callable_
            }
            check(
                "interaction-on-record",
                [
                    (area["prefix"], f"{info['create']} is not an action on the {main}")
                    for child, info in interactions.items()
                    if not any(a.get("operationId") == info["create"] for p in pages for _, a in _actions(p))
                ],
            )
            contributions = {
                c: i for c, i in children.items() if i["shape"] == "contribution" and i["create"] in callable_
            }
            check(
                "contribution-on-record",
                [
                    (page["route"], f"{info['create']} is written on a page of its own")
                    for child, info in contributions.items()
                    for page in pages
                    if _page_operation(page, forms) == info["create"]
                ],
            )
            check(
                "contributions-readable",
                [
                    (area["prefix"], f"{child}: each person reads only their own")
                    for child in contributions
                    if _private_to_owner(ops, child, area["roles"])
                ],
            )
            first = next(iter(interactions.values()), None)
            task, clicks = (first["create"], _clicks(first["create"], pages, home, forms)) if first else (None, None)
        elif area["kind"] == "storefront":
            cart = _cart(children)
            cart_create = children[cart]["create"] if cart else None
            on_product = any(a.get("operationId") == cart_create for p in pages for _, a in _actions(p))
            check(
                "add-to-cart-on-product",
                [(area["prefix"], f"no cart of {main}")]
                if cart is None
                else ([] if on_product else [(area["prefix"], f"{cart_create} is not an action on the {main}")]),
            )
            check(
                "cart-in-menu",
                [] if cart and any(_lists(page, cart) for page in area_menu) else [("menu", "no cart in the menu")],
            )
            task, clicks = cart_create, _clicks(cart_create, pages, home, forms)
        elif area["kind"] == "back-office":
            check(
                "every-create-reachable",
                [
                    (area["prefix"], f"{op_id} has no form or action")
                    for op_id, found in ops.items()
                    if (found["operation"].get("x-bga") or {}).get("action") == "create"
                    and op_id in callable_
                    and (found["operation"].get("x-bga") or {}).get("entity") in _entities(pages)
                    and _clicks(op_id, pages, home, forms) is None
                ],
            )
        out.append(
            {
                "area": area["id"],
                "archetype": area["archetype"],
                "kind": area["kind"],
                "roles": area["roles"],
                "main": main,
                "failed": failures,
                "passed": passed,
                "task": {"operationId": task, "clicks": clicks} if task else None,
            }
        )
    return out


def _record(failures: list[dict[str, Any]], passed: list[str], name: str, found: list[tuple[str, str]]) -> None:
    """One check's outcome: its findings (route, why), or its name among the passed."""
    if found:
        failures.extend({"check": name, "route": route, "detail": detail} for route, detail in found)
    else:
        passed.append(name)


def _lists(page: dict[str, Any], entity: str | None) -> bool:
    return any(
        s.get("component") == "AppList" and (s.get("content") or {}).get("entity") == entity
        for s in page.get("sections") or []
    )


def _entities(pages: list[dict[str, Any]]) -> set[str]:
    return {
        (s.get("content") or {}).get("entity")
        for page in pages
        for s in page.get("sections") or []
        if (s.get("content") or {}).get("entity")
    }


def _private_to_owner(ops: dict[str, dict[str, Any]], entity: str, roles: list[str]) -> bool:
    """The entity's list is an ownership these roles do not bypass: each reads only their own."""
    for found in ops.values():
        meta = found["operation"].get("x-bga") or {}
        if meta.get("entity") == entity and meta.get("action") == "list":
            policy = meta.get("policy") or {}
            return policy.get("type") == "ownership" and not set(policy.get("bypassRoles") or []) & set(roles)
    return False


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the report and its baseline: failures per check, and the main tasks' clicks."""
    counts: dict[str, int] = {}
    for area in results:
        for failure in area["failed"]:
            counts[failure["check"]] = counts.get(failure["check"], 0) + 1
    return {"failures": sum(counts.values()), "byCheck": dict(sorted(counts.items()))}
