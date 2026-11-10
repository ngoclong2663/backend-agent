"""Operation coverage (Story 19.7).

Pure functions:
- `covered_operations(frontend_spec) -> set[str]`: the operations a data binding, form, action or Stats item calls.
- `uncovered_operations(frontend_spec, contract) -> list[str]`: the contract's operations none of them reaches.
"""

from typing import Any

from src.orchestrator.integration.contract import contract_operations


def _iter_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for section in sections:
        result.append(section)
        if section.get("children"):
            result.extend(_iter_sections(section["children"]))
    return result


def covered_operations(frontend_spec: dict[str, Any]) -> set[str]:
    """All API operations referenced anywhere by the frontend spec."""
    covered: set[str] = set()

    # 1. Sections (bindings, actions, stats)
    for page in frontend_spec.get("pages") or []:
        for section in _iter_sections(page.get("sections") or []):
            # Data binding
            data = section.get("data") or {}
            if data.get("operationId"):
                covered.add(data["operationId"])

            # Content actions
            content = section.get("content") or {}
            for action in content.get("actions") or []:
                if action.get("operationId"):
                    covered.add(action["operationId"])
                if action.get("undoOperationId"):  # Epic 33: a toggle's second tap (unlike, unfollow)
                    covered.add(action["undoOperationId"])
            # Epic 33: a feature's section calls its own operations (a comment thread lists, writes, edits, deletes)
            covered.update(op for op in content.get("operations") or [] if isinstance(op, str))
            # Epic 32 (Story 32.5): an operation run when a record opens (a view counted)
            if isinstance(content.get("onOpen"), dict) and content["onOpen"].get("operationId"):
                covered.add(content["onOpen"]["operationId"])

            # Stats items
            if section.get("component") == "Stats":
                for item in content.get("items") or []:
                    stat_data = item.get("data") or {}
                    if stat_data.get("operationId"):
                        covered.add(stat_data["operationId"])

    # 2. Forms (submit and load)
    for form in frontend_spec.get("forms") or []:
        if form.get("operationId"):
            covered.add(form["operationId"])
        if form.get("load") and form["load"].get("operationId"):
            covered.add(form["load"]["operationId"])

    return covered


def uncovered_operations(frontend_spec: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    """Operations in the contract that no data binding, form, action or Stats item references."""
    operations = contract_operations(contract)
    covered = covered_operations(frontend_spec)
    return sorted(
        op_id
        for op_id, entry in operations.items()
        # a plugin's own operations (sign-in, Story 10.2) get their screens with Story 22.7
        if op_id not in covered and not (entry["operation"].get("x-bga") or {}).get("plugin")
    )
