"""Autofix for drafted FrontendSpec (Story 18.3).

Repairs common drafting mistakes deterministically before invoking an engine repair loop.
"""

from typing import Any

from .normalizer import route_params


def _iter_all_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        result.append(section)
        children = section.get("children")
        if isinstance(children, list):
            result.extend(_iter_all_sections(children))
    return result


def _page_entity(page: dict[str, Any]) -> str | None:
    for section in _iter_all_sections(page.get("sections") or []):
        data = section.get("data")
        if isinstance(data, dict):
            op = data.get("operationId")
            if isinstance(op, str) and "." in op:
                return op.split(".", 1)[0]
            col = data.get("collection")
            if isinstance(col, str) and col:
                return col
    return None


def _find_prefix_page(pages: list[dict[str, Any]], target_route: str) -> dict[str, Any] | None:
    candidates = []
    target_clean = target_route.rstrip("/") + "/"
    for p in pages:
        p_route = p.get("route", "")
        if route_params(p_route) or p_route in ("", "/"):
            continue
        p_clean = p_route.rstrip("/") + "/"
        if target_clean.startswith(p_clean):
            candidates.append((len(p_route), p))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return None


def _find_list_page_for_entity(pages: list[dict[str, Any]], entity: str) -> dict[str, Any] | None:
    for p in pages:
        if route_params(p.get("route", "")):
            continue
        for section in _iter_all_sections(p.get("sections") or []):
            data = section.get("data")
            if isinstance(data, dict):
                op = data.get("operationId")
                col = data.get("collection")
                if isinstance(op, str) and "." in op:
                    op_entity, op_action = op.split(".", 1)
                    if op_entity == entity and (op_action in ("list", "all", "find") or data.get("action") == "list"):
                        return p
                if isinstance(col, str) and col == entity:
                    return p
    return None


def autofix_frontend_spec(spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inspects `spec` for links targeting pages with unbound route parameters (FE_ROUTE_PARAM_UNBOUND),
    points them at the nearest prefix page or list page for the same entity, or removes them if optional.
    Returns `(fixed_spec, notes)` where notes are assumption entries."""
    pages = [p for p in spec.get("pages") or [] if isinstance(p, dict)]
    pages_by_id = {p["id"]: p for p in pages if "id" in p}
    notes: list[dict[str, Any]] = []

    def resolve_target(target_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        target_page = pages_by_id.get(target_id)
        if not target_page:
            return None, []
        params = route_params(target_page.get("route", ""))
        if not params:
            return None, []
        # Target needs route params!
        target_route = target_page.get("route", "")
        prefix = _find_prefix_page(pages, target_route)
        if prefix:
            return prefix, params
        entity = _page_entity(target_page)
        if entity:
            list_page = _find_list_page_for_entity(pages, entity)
            if list_page:
                return list_page, params
        return None, params

    def make_note(
        path: str,
        target_id: str,
        target_route: str,
        params: list[str],
        candidate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        param_str = ", ".join(f"[{p}]" for p in params)
        if candidate:
            cand_id = candidate.get("id")
            cand_route = candidate.get("route", "")
            msg = (
                f"Link to '{target_id}' ({target_route}) now points to '{cand_id}' ({cand_route}): "
                f"a link cannot fill {param_str}"
            )
        else:
            msg = f"Link to '{target_id}' ({target_route}) was removed: a link cannot fill {param_str}"
        return {"spec": "frontend", "path": path, "message": msg, "suggestion": None}

    # 1. layout.header.navigation
    layout = spec.get("layout")
    if isinstance(layout, dict):
        header = layout.get("header")
        if isinstance(header, dict) and isinstance(header.get("navigation"), list):
            new_nav = []
            for idx, item in enumerate(header["navigation"]):
                if isinstance(item, dict) and isinstance(item.get("page"), str):
                    cand, params = resolve_target(item["page"])
                    if params:
                        target_id = item["page"]
                        target_route = pages_by_id[target_id].get("route", "")
                        if cand:
                            item["page"] = cand["id"]
                            notes.append(
                                make_note(
                                    f"/layout/header/navigation/{idx}/page", target_id, target_route, params, cand
                                )
                            )
                            new_nav.append(item)
                        else:
                            notes.append(
                                make_note(f"/layout/header/navigation/{idx}", target_id, target_route, params, None)
                            )
                    else:
                        new_nav.append(item)
                else:
                    new_nav.append(item)
            header["navigation"] = new_nav

        # 2. layout.footer.links
        footer = layout.get("footer")
        if isinstance(footer, dict) and isinstance(footer.get("links"), list):
            new_links = []
            for idx, item in enumerate(footer["links"]):
                if isinstance(item, dict) and isinstance(item.get("page"), str):
                    cand, params = resolve_target(item["page"])
                    if params:
                        target_id = item["page"]
                        target_route = pages_by_id[target_id].get("route", "")
                        if cand:
                            item["page"] = cand["id"]
                            notes.append(
                                make_note(f"/layout/footer/links/{idx}/page", target_id, target_route, params, cand)
                            )
                            new_links.append(item)
                        else:
                            notes.append(
                                make_note(f"/layout/footer/links/{idx}", target_id, target_route, params, None)
                            )
                    else:
                        new_links.append(item)
                else:
                    new_links.append(item)
            footer["links"] = new_links

    # 3. Section content
    def fix_content(container: Any, path: str) -> None:
        if isinstance(container, dict):
            # Check keys
            keys_to_delete = []
            for key, val in list(container.items()):
                subpath = f"{path}/{key}"
                if key == "page" and isinstance(val, str):
                    cand, params = resolve_target(val)
                    if params:
                        target_id = val
                        target_route = pages_by_id[target_id].get("route", "")
                        if cand:
                            container["page"] = cand["id"]
                            notes.append(make_note(subpath, target_id, target_route, params, cand))
                elif isinstance(val, dict):
                    if "page" in val and isinstance(val["page"], str):
                        cand, params = resolve_target(val["page"])
                        if params:
                            target_id = val["page"]
                            target_route = pages_by_id[target_id].get("route", "")
                            if cand:
                                val["page"] = cand["id"]
                                notes.append(make_note(f"{subpath}/page", target_id, target_route, params, cand))
                            elif key in ("cta", "secondary_cta", "link"):
                                keys_to_delete.append((key, target_id, target_route, params))
                            continue
                    fix_content(val, subpath)
                elif isinstance(val, list):
                    fix_content(val, subpath)
            for k, target_id, target_route, params in keys_to_delete:
                del container[k]
                notes.append(make_note(f"{path}/{k}", target_id, target_route, params, None))

        elif isinstance(container, list):
            items_to_remove = []
            for idx, item in enumerate(container):
                subpath = f"{path}/{idx}"
                if isinstance(item, dict):
                    if "page" in item and isinstance(item["page"], str):
                        cand, params = resolve_target(item["page"])
                        if params:
                            target_id = item["page"]
                            target_route = pages_by_id[target_id].get("route", "")
                            if cand:
                                item["page"] = cand["id"]
                                notes.append(make_note(f"{subpath}/page", target_id, target_route, params, cand))
                            else:
                                items_to_remove.append((item, target_id, target_route, params, subpath))
                            continue
                    fix_content(item, subpath)
            for item, target_id, target_route, params, subpath in items_to_remove:
                container.remove(item)
                notes.append(make_note(subpath, target_id, target_route, params, None))

    for p_idx, page in enumerate(pages):
        for s_idx, section in enumerate(page.get("sections") or []):
            if isinstance(section, dict) and "content" in section:
                fix_content(section["content"], f"/pages/{p_idx}/sections/{s_idx}/content")

    return spec, notes
