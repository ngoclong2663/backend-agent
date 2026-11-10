"""Business rules as a plugin (Story 10.4): the spec's `rules[]`, one definition per rule in the plan.

- `transition` (an enum field moves only along the allowed next states; 409 `INVALID_TRANSITION`), `immutableAfter`
  (a record in one of the states cannot change or be deleted; 409 `RESOURCE_LOCKED`) and `sumEquals` (a numeric
  field equals the total of the record's items; 422 `TOTAL_MISMATCH`) are written from templates: a constant per rule
  in `src/libs/rules/catalog.py`, a check in the use case (pre-check hook), `allowedActions` entries
  (`transition:<STATE>`; no `update` or `delete` on a locked record), template tests and contract scenarios. They
  check updates (and deletes, for a lock); creating a record is not checked.
- `ownerOnly` is ownership: the policies plugin writes it (10.3).
- `custom` rules are the engine's: the planner gives each one an error code, a status and a field, which the contract
  lists and the engine's note says to raise. A custom rule too vague to implement (`params.ambiguous`, or a
  description of a few words) is not implemented: it stays in `unresolved` and the operation's description says so.
"""

import re
from typing import Any

from src.modules.shared.domain.backend_spec.naming import pluralize, to_snake

from . import concurrency
from .base import ActionCheck, CaseContext, Code, Plugin, RepositoryMethod

TEMPLATED = ("immutableAfter", "transition", "sumEquals")  # also the order of the checks in a use case
ANSWERS = {
    "transition": (409, "INVALID_TRANSITION"),
    "immutableAfter": (409, "RESOURCE_LOCKED"),
    "sumEquals": (422, "TOTAL_MISMATCH"),
}
EXCEPTIONS = {400: "BadRequestException", 403: "ForbiddenException", 404: "NotFoundException", 409: "ConflictException"}
CATALOG = "src.libs.rules.catalog"
MIN_WORDS = 5  # a custom rule's description shorter than this cannot say who may do what, when


def constant(rule_id: str) -> str:
    """`taskStatusFlow` / `task.status-flow` → `TASK_STATUS_FLOW`."""
    return re.sub(r"[^A-Za-z0-9]+", "_", to_snake(rule_id)).strip("_").upper()


def _rules(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {rule["id"]: rule for rule in spec.get("rules", [])}


def _checks(op: dict[str, Any], kind: str | None = None) -> list[dict[str, Any]]:
    return [check for check in op.get("ruleChecks") or [] if kind is None or check["kind"] == kind]


def _ambiguous(rule: dict[str, Any]) -> str | None:
    flag = (rule.get("params") or {}).get("ambiguous")
    if flag:
        return flag if isinstance(flag, str) else "flagged as ambiguous"
    if len((rule.get("description") or "").split()) < MIN_WORDS:
        return "its description is too short to say who may do what, in which state"
    return None


def _tuple(values: list[str]) -> str:
    inner = ", ".join(f'"{value}"' for value in values)
    return f"({inner},)" if len(values) == 1 else f"({inner})"


def _test(op: dict[str, Any], rule: str, case: str, expect: int, description: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"test_{op['handler']}__{to_snake(constant(rule).lower())}_{case}",
        "operationId": op["operationId"],
        "case": f"rule_{case}",
        "rule": rule,
        "expectStatus": expect,
        "description": description,
        **extra,
    }


class RulesPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="rules")

    def applies(self, spec: dict[str, Any]) -> bool:
        rules = _rules(spec)
        return any(rule["kind"] in concurrency.KINDS for rule in rules.values()) or any(
            rules.get(rule_id, {}).get("kind") not in (None, "ownerOnly")
            for op in spec.get("operations", [])
            for rule_id in op.get("rules") or []
        )

    # -- the plan -------------------------------------------------------------------------------------------------

    def plan(self, plan: dict[str, Any], spec: dict[str, Any]) -> None:
        rules = _rules(spec)
        models = {model["entity"]: model for model in plan["models"] if model.get("entity")}
        spec_ops = {op["operationId"]: op for op in spec.get("operations", [])}
        status: dict[str, dict[str, Any]] = {}  # rule id → how it ended up (for `unresolved`)
        for module in plan["modules"]:
            if module.get("plugin"):
                continue
            model = models[module["entity"]]
            by_api = {column["apiName"]: column for column in model["columns"]}
            for op in module["operations"]:
                for rule_id in (spec_ops.get(op["operationId"]) or {}).get("rules") or []:
                    rule = rules.get(rule_id)
                    if rule is None or rule["kind"] in ("ownerOnly", *concurrency.KINDS):
                        continue
                    entry = status.setdefault(rule_id, {"operations": [], "kind": rule["kind"]})
                    entry["operations"].append(op["operationId"])
                    if rule["kind"] == "custom":
                        self._custom(op, rule, by_api, entry)
                    else:
                        self._templated(plan, module, model, op, rule, by_api, entry)
        for rule in rules.values():  # Story 10.10: data invariants, on the entity's writes whoever names them
            if rule["kind"] not in concurrency.KINDS:
                continue
            module = next(
                (m for m in plan["modules"] if m.get("entity") == rule["entity"] and not m.get("plugin")), None
            )
            if module is None:
                continue
            concurrency.plan_rule(plan, rule, module, models[rule["entity"]])
            ops = [op["operationId"] for op in module["operations"] if rule["id"] in (op.get("templatedRules") or [])]
            status[rule["id"]] = {"operations": ops, "kind": rule["kind"]}
        unresolved = [entry for entry in plan["unresolved"] if entry["kind"] != "rules" or entry["ref"] not in status]
        for rule_id, entry in status.items():
            if entry.get("skipped"):
                message = f"Not implemented: {entry['skipped']}"
            elif entry.get("engine"):
                answer = entry["engine"]
                message = (
                    f"Custom rule: the engine implements it in {', '.join(entry['operations'])} and answers "
                    f"{answer['status']} {answer['code']}"
                )
            elif entry.get("inert"):
                message = entry["inert"]
            else:
                continue
            unresolved.append({"kind": "rules", "ref": rule_id, "message": message})
        plan["unresolved"] = unresolved

    @staticmethod
    def _answer_error(op: dict[str, Any], status: int, code: str) -> None:
        error = {"status": status, "exception": EXCEPTIONS.get(status), "code": code}
        if error not in op["errors"]:
            op["errors"].append(error)

    def _custom(self, op: dict[str, Any], rule: dict[str, Any], by_api: dict, entry: dict) -> None:
        reason = _ambiguous(rule)
        if reason:
            op["skippedRules"] = [*op.get("skippedRules", []), rule["id"]]
            op["notes"] = [*op.get("notes", []), f"Not implemented: rule {rule['id']} is ambiguous ({reason})."]
            entry["skipped"] = reason
            return
        params = rule.get("params") or {}
        answer = {
            "id": rule["id"],
            "code": params.get("code") or constant(rule["id"]),
            "status": params.get("status") or 409,
            "message": rule["description"],
        }
        if params.get("field") in by_api:
            answer["field"] = params["field"]
        op["customRules"] = [*op.get("customRules", []), answer]
        self._answer_error(op, answer["status"], answer["code"])
        entry["engine"] = answer

    def _templated(self, plan, module, model, op, rule, by_api, entry) -> None:
        kind, params = rule["kind"], rule.get("params") or {}
        applies = ("update", "delete") if kind == "immutableAfter" else ("update",)
        if op.get("action") not in applies:
            entry["inert"] = f"A {kind} rule checks {' and '.join(applies)}s; on {op['operationId']} it checks nothing"
            return
        column = by_api[params["field"]]
        column["ruled"] = True
        check: dict[str, Any] = {
            "id": rule["id"],
            "kind": kind,
            "constant": constant(rule["id"]),
            "field": column["apiName"],
            "attr": column["attr"],
        }
        values = list((column.get("enum") or {}).get("values") or [])
        if kind == "transition":
            allowed = {state: list(params["transitions"].get(state, [])) for state in values}
            check["allowed"] = allowed
            targets = [state for state in values if any(state in nexts for nexts in allowed.values())]
            actions = module.setdefault("recordActions", [])
            actions += [f"transition:{state}" for state in targets if f"transition:{state}" not in actions]
        elif kind == "immutableAfter":
            check["states"] = [state for state in values if state in params["states"]]
        else:
            items = next(m for m in plan["models"] if m.get("entity") == params["items"])
            fk = next(
                c
                for c in items["columns"]
                if (c.get("foreignKey") or {}).get("references", "").partition(".")[0] == model["table"]
            )
            item_columns = {c["apiName"]: c for c in items["columns"]}
            check |= {
                "items": items["entity"],
                "itemsModel": items["class"],
                "itemsForeignKey": fk["attr"],
                "itemAttr": item_columns[params["itemField"]]["attr"],
                "quantityAttr": item_columns[params["quantityField"]]["attr"] if params.get("quantityField") else None,
                "method": f"{to_snake(pluralize(to_snake(items['entity'])))}_total",
            }
        op["ruleChecks"] = sorted([*_checks(op), check], key=lambda c: TEMPLATED.index(c["kind"]))
        op["templatedRules"] = [*op.get("templatedRules", []), rule["id"]]
        self._answer_error(op, *ANSWERS[kind])
        module["tests"] += self._tests(op, check)

    @staticmethod
    def _tests(op: dict[str, Any], check: dict[str, Any]) -> list[dict[str, Any]]:
        locks = _checks(op, "immutableAfter")
        locked = {state for lock in locks for state in lock["states"]}
        if check["kind"] == "transition":
            for state, nexts in check["allowed"].items():
                refused = [s for s in check["allowed"] if s not in nexts and s != state]
                if state in locked or not nexts or not refused:
                    continue
                pair = {"from": state, "attr": check["attr"], "field": check["field"]}
                return [
                    _test(op, check["id"], "allowed", 200, f"{state} → {nexts[0]} is allowed", to=nexts[0], **pair),
                    _test(op, check["id"], "refused", 409, f"{state} → {refused[0]} is refused", to=refused[0], **pair),
                ]
            return []
        if check["kind"] == "immutableAfter":
            if not check["states"]:
                return []
            state = check["states"][0]
            return [_test(op, check["id"], "locked", 409, f"a record in {state} cannot change", state=state)]
        return [
            _test(op, check["id"], "total_matches", 200, "a total equal to the items' is accepted"),
            _test(op, check["id"], "total_mismatch", 422, "a total that differs from the items' is refused"),
        ]

    # -- the contract ---------------------------------------------------------------------------------------------

    def contract(self, contract: dict[str, Any], plan: dict[str, Any], spec: dict[str, Any]) -> None:
        from ..integration.contract import contract_operations

        meta = contract["x-bga"]
        concurrency.adjust_fixtures(contract, plan)  # before any scenario reads them
        planned = {op["operationId"]: (module, op) for module in plan["modules"] for op in module["operations"]}
        described: dict[str, dict[str, Any]] = {}
        for op_id, entry in contract_operations(contract).items():
            if op_id not in planned:
                continue
            module, op = planned[op_id]
            operation = entry["operation"]
            xbga = operation.setdefault("x-bga", {})
            errors = xbga.setdefault("errors", [])
            for check in _checks(op):
                status, code = ANSWERS[check["kind"]]
                self._error(errors, status, code, check["field"], check["id"], _message(check))
                described.setdefault(
                    check["id"],
                    {
                        "operations": [],
                        "implementation": "template",
                        "status": status,
                        "code": code,
                        "field": check["field"],
                    },
                )
            for answer in op.get("customRules") or []:
                self._error(
                    errors, answer["status"], answer["code"], answer.get("field"), answer["id"], answer["message"]
                )
                described.setdefault(
                    answer["id"],
                    {
                        "operations": [],
                        "implementation": "engine",
                        "status": answer["status"],
                        "code": answer["code"],
                        **({"field": answer["field"]} if "field" in answer else {}),
                    },
                )
                for scenario in xbga.get("scenarios") or []:  # the rule may refuse what the scenario sends
                    if str(scenario["expect"]["status"]).startswith("2"):
                        scenario["expect"].setdefault("or", []).append(
                            {"status": answer["status"], "code": answer["code"]}
                        )
            for rule_id in op.get("skippedRules") or []:
                note = f"Not implemented: rule {rule_id} is ambiguous ({_ambiguous(_rules(spec)[rule_id])})."
                operation["description"] = (
                    f"{operation['description']}\n\n{note}" if operation.get("description") else note
                )
                described.setdefault(rule_id, {"operations": [], "implementation": "none"})
            for rule_id in {
                *(c["id"] for c in _checks(op)),
                *(a["id"] for a in op.get("customRules") or []),
                *(op.get("skippedRules") or []),
            }:
                described[rule_id]["operations"].append(op_id)
            for rule in concurrency.rules_of(op):  # Story 10.10
                refusal = {  # not `entry`: that is the contract operation the scenarios below need (Story 22.8)
                    "status": 409,
                    "code": rule["code"],
                    "message": rule["message"],
                    "rule": rule["id"],
                    "fields": rule["fields"],
                }
                errors[:] = [e for e in errors if not (e["code"] == rule["code"] and "rule" not in e)]
                if refusal not in errors:
                    errors.append(refusal)
                described.setdefault(rule["id"], {"operations": [], "implementation": "template", "status": 409,
                                                  "code": rule["code"], "fields": rule["fields"]})  # fmt: skip
                described[rule["id"]]["operations"].append(op_id)
            if concurrency.rules_of(op) and op.get("action") == "create" and xbga.get("scenarios"):
                concurrency.contract_scenarios(contract, plan, module, op, xbga["scenarios"])
            if _checks(op) and xbga.get("scenarios") is not None:
                self._scenarios(contract, plan, module, op, entry["path"], xbga["scenarios"])
        rules = []
        for rule in spec.get("rules", []):
            info = described.get(rule["id"], {"operations": [], "implementation": "none"})
            if rule["kind"] == "ownerOnly":
                info = {
                    "operations": [
                        op["operationId"]
                        for _, op in planned.values()
                        if rule["id"] in (op.get("templatedRules") or [])
                    ],
                    "implementation": "template",
                }
            rules.append(
                {**rule, **{key: sorted(value) if key == "operations" else value for key, value in info.items()}}
            )
        meta["rules"] = rules

    @staticmethod
    def _error(errors: list, status: int, code: str, field: str | None, rule: str, message: str) -> None:
        entry = {
            "status": status,
            "code": code,
            "message": message,
            "rule": rule,
            **({"fields": [field]} if field else {}),
        }
        for index, error in enumerate(errors):
            if error["status"] == status and error["code"] == code and "rule" not in error:
                errors[index] = entry
                return
        if entry not in errors:
            errors.append(entry)

    def _scenarios(self, contract, plan, module, op, path, scenarios) -> None:
        from .policies import scenario_user

        meta = contract["x-bga"]
        records = meta["fixtures"].get(module["entity"]) or []
        pk = (meta["entities"].get(module["entity"]) or {}).get("primaryKey") or "id"
        own = (re.findall(r"\{(\w+)\}", path) or [None])[-1]
        locks = _checks(op, "immutableAfter")

        def locked(record: dict[str, Any]) -> bool:
            return any(record.get(lock["field"]) in lock["states"] for lock in locks)

        def reach(name: str, record: dict[str, Any], expect: dict[str, Any], body: Any = None) -> dict[str, Any]:
            scenario: dict[str, Any] = {"name": name, "params": {own: record[pk]}}
            user = scenario_user(contract, plan, op, record)
            if user:
                scenario["user"] = user
            if body is not None:
                scenario["body"] = body
            scenario["expect"] = expect
            return scenario

        open_records = [record for record in records if not locked(record)]
        by_id = {str(record.get(pk)): record for record in records}
        # refusals answered before the lock (401, 403, 404, 422) reach a locked record as well as an open one
        before_lock = {"UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND", "VALIDATION_ERROR", "RESOURCE_LOCKED"}
        if locks and open_records:  # what the earlier scenarios reach must not be locked (they expect other answers)
            for scenario in scenarios:
                record = by_id.get(str(scenario["params"].get(own)))
                # 2026-11-07: moving "another user's record" onto the first open record made its user that record's
                # owner (a 200 where the contract expected 404)
                if record is not None and locked(record) and scenario["expect"].get("code") not in before_lock:
                    moved = reach(scenario["name"], open_records[0], scenario["expect"])
                    scenario["params"] = {**scenario["params"], own: moved["params"][own]}
                    scenario.pop("user", None)
                    if "user" in moved and scenario.get("auth") is not False:
                        scenario["user"] = moved["user"]
        if locks and not open_records:
            # every seeded record is locked (e.g. its only status is a final one): what would need an open record
            # cannot happen; the refusals answered before the lock stay (401, 403, 404, 422)
            scenarios[:] = [
                scenario
                for scenario in scenarios
                if by_id.get(str(scenario["params"].get(own))) is None or scenario["expect"].get("code") in before_lock
            ]
        body = {} if op["action"] == "update" else None
        for lock in locks:
            target = next((record for record in records if record.get(lock["field"]) in lock["states"]), None)
            if target is not None:
                scenarios.append(reach("locked record", target, {"status": 409, "code": "RESOURCE_LOCKED"}, body))
        for check in _checks(op, "transition"):
            for record in open_records:
                state = record.get(check["field"])
                nexts = check["allowed"].get(state) or []
                refused = [s for s in check["allowed"] if s not in nexts and s != state]
                if not nexts or not refused:
                    continue
                target = next((s for s in nexts if not any(s in lock["states"] for lock in locks)), nexts[0])
                scenarios.append(
                    reach(
                        f"refused transition ({state} → {refused[0]})",
                        record,
                        {"status": 409, "code": "INVALID_TRANSITION"},
                        {check["field"]: refused[0]},
                    )
                )
                scenarios.append(
                    reach(f"allowed transition ({state} → {target})", record, {"status": 200}, {check["field"]: target})
                )
                break
        for check in _checks(op, "sumEquals"):
            record = open_records[0] if open_records else None
            if record is None:
                continue
            total = _number(_items_total(contract, plan, check, record[pk]))
            for scenario in scenarios:  # a success that sends the field sends the right total
                if isinstance(scenario.get("body"), dict) and check["field"] in scenario["body"]:
                    if str(scenario["expect"]["status"]).startswith("2"):
                        scenario["body"][check["field"]] = total
            scenarios.append(
                reach(
                    "total mismatch",
                    record,
                    {"status": 422, "code": "TOTAL_MISMATCH"},
                    {check["field"]: _number(total + 1)},
                )
            )

    # -- the project ----------------------------------------------------------------------------------------------

    def files(self, plan: dict[str, Any] | None) -> dict[str, str]:
        files = super().files(plan)
        checks = {
            check["id"]: check
            for module in (plan or {}).get("modules", [])
            for op in module["operations"]
            for check in _checks(op)
        }
        if checks:
            files["src/libs/rules/catalog.py"] = _catalog(list(checks.values()))
        return files

    def prechecks(self, plan, module, op, record) -> list[Code]:
        if module.get("plugin"):
            return []
        if record is None:  # Story 10.10: a create checks its parent's capacity
            lines = concurrency.capacity_precheck(module, op) if op.get("action") == "create" else []
            imports = (("src.libs.exceptions", ("ConflictException", "ErrorCode")),)
            return [Code(tuple(lines), imports)] if lines else []
        snake = to_snake(module["entity"])
        lines, names = [], []
        # the body's fields when the operation names them: a transition or a total the body can't carry is not checked
        # against it (a status that moves only through its actions is not in the update's DTO; found on a real news
        # draft: `dto.status` on a DTO without it answered every update with 500)
        sent = {to_snake(name) for name in op["requestFields"]} if op.get("requestFields") is not None else None
        for check in _checks(op):
            if check["kind"] != "immutableAfter" and sent is not None and check["attr"] not in sent:
                continue
            names.append(check["constant"])
            if check["kind"] == "immutableAfter":
                lines.append(f"{check['constant']}.check({record}.{check['attr']})")
            elif check["kind"] == "transition":
                lines.append(f"{check['constant']}.check({record}.{check['attr']}, dto.{check['attr']})")
            else:
                total = f"self.{snake}_repo.{check['method']}({snake}_id)"
                lines.append(f"{check['constant']}.check(dto.{check['attr']}, {total})")
        return [Code(tuple(lines), ((CATALOG, tuple(names)),))] if lines else []

    def repository_methods(self, plan, module) -> list[RepositoryMethod]:
        if module.get("plugin"):
            return []
        model = next(m for m in plan["models"] if m.get("entity") == module["entity"])
        pk = next(column for column in model["columns"] if column["primaryKey"])
        snake = to_snake(module["entity"])
        id_imports = (("uuid", ()),) if pk["pythonType"] == "uuid.UUID" else ()
        out, seen = [], set()
        for op in module["operations"]:
            for rule in concurrency.rules_of(op, "capacity"):  # Story 10.10: the count under the parent's lock
                if rule["method"] in seen:
                    continue
                seen.add(rule["method"])
                signature, body, imports = concurrency.capacity_method(plan, rule)
                out.append(RepositoryMethod(signature, body, tuple(imports), ()))
            for check in _checks(op, "sumEquals"):
                if check["method"] in seen:
                    continue
                seen.add(check["method"])
                items = check["itemsModel"]
                amount = f"col({items}.{check['itemAttr']})"
                if check["quantityAttr"]:
                    amount += f" * col({items}.{check['quantityAttr']})"
                out.append(
                    RepositoryMethod(
                        f"{check['method']}(self, {snake}_id: {pk['pythonType']}) -> Decimal",
                        (
                            f'"""The total of the {snake.replace("_", " ")}\'s {check["items"]} rows (rule '
                            f'{check["id"]})."""',
                            f"total = func.sum({amount})",
                            f"query = select(func.coalesce(total, 0)).where(col({items}.{check['itemsForeignKey']})"
                            f" == {snake}_id)",
                            "return Decimal(str(self.session.exec(query).one()))",
                        ),
                        (("decimal", ("Decimal",)), *id_imports),
                        (
                            ("sqlmodel", ("col", "func", "select")),
                            ("src.modules.shared.infrastructure.models", (items,)),
                        ),
                    )
                )
        return out

    def action_checks(self, plan, module) -> list[ActionCheck]:
        if module.get("plugin"):
            return []
        checks = []
        for op in module["operations"]:
            locks = _checks(op, "immutableAfter")
            unlocked = [f"not {lock['constant']}.locked(entity.{lock['attr']})" for lock in locks]
            imports = tuple((CATALOG, (check["constant"],)) for check in _checks(op))
            if op.get("action") in ("update", "delete"):
                checks += [ActionCheck(op["action"], condition, imports=imports) for condition in unlocked]
            for check in _checks(op, "transition"):
                targets = [state for state in check["allowed"] if any(state in n for n in check["allowed"].values())]
                for state in targets:
                    condition = f'"{state}" in {check["constant"]}.next_states(entity.{check["attr"]})'
                    checks.append(ActionCheck(f"transition:{state}", condition, imports=imports))
                    checks += [ActionCheck(f"transition:{state}", c, imports=imports) for c in unlocked]
        return checks

    def test_case(self, plan, module, op, test, ctx: CaseContext) -> Code | None:
        case = test["case"]
        if case == "rule_concurrent" and not module.get("plugin"):  # Story 10.10
            lines, imports = concurrency.concurrent_test(plan, module, op, test, ctx.seed_for)
            return Code(lines, imports)
        if module.get("plugin") or not case.startswith("rule_") or ctx.record_path is None:
            return None
        from ..backend.codegen import _member

        model = next(m for m in plan["models"] if m.get("entity") == module["entity"])
        columns = {column["attr"]: column for column in model["columns"]}
        method = op["method"].lower()
        head = f"def {test['id']}(client):"
        if case in ("rule_allowed", "rule_refused", "rule_locked"):
            attr = test.get("attr") or next(c["attr"] for c in _checks(op, "immutableAfter") if c["id"] == test["rule"])
            enum = columns[attr]["enum"]["class"]
            state = test.get("from") or test["state"]
            imports = (("src.modules.shared.domain.entities", (enum,)),)
            seed = f"    record = {ctx.seed}({attr}={enum}.{_member(state)})"
            if case == "rule_locked":
                body = ", json={}" if method == "patch" else ""
                return Code(
                    (
                        head,
                        seed,
                        "",
                        f"    response = client.{method}({ctx.record_path}{body})",
                        "",
                        "    assert response.status_code == 409",
                        '    assert response.json()["error"]["code"] == "RESOURCE_LOCKED"',
                    ),
                    imports,
                )
            send = f'    response = client.patch({ctx.record_path}, json={{"{test["field"]}": "{test["to"]}"}})'
            if case == "rule_allowed":
                return Code(
                    (
                        head,
                        seed,
                        "",
                        send,
                        "",
                        "    assert response.status_code == 200, response.text",
                        f'    assert response.json()["{test["field"]}"] == "{test["to"]}"',
                    ),
                    imports,
                )
            return Code(
                (
                    head,
                    seed,
                    "",
                    send,
                    "",
                    "    assert response.status_code == 409",
                    '    assert response.json()["error"]["code"] == "INVALID_TRANSITION"',
                ),
                imports,
            )
        check = next(c for c in _checks(op, "sumEquals") if c["id"] == test["rule"])
        pk = next(column for column in model["columns"] if column["primaryKey"])
        item_seed = ctx.seed_for(check["items"])
        quantity = check["quantityAttr"]
        lines = [head, f"    record = {ctx.seed}()"]
        for price, count in ((10, 2), (5, 1)):
            extra = f", {quantity}={count}" if quantity else ""
            lines.append(
                f"    {item_seed}({check['itemsForeignKey']}=record.{pk['attr']}, {check['itemAttr']}={price}{extra})"
            )
        total = 25 if quantity else 15
        if case == "rule_total_matches":
            return Code(
                (
                    *lines,
                    "",
                    f'    response = client.patch({ctx.record_path}, json={{"{check["field"]}": {total}}})',
                    "",
                    "    assert response.status_code == 200, response.text",
                )
            )
        return Code(
            (
                *lines,
                "",
                f'    response = client.patch({ctx.record_path}, json={{"{check["field"]}": {total + 1}}})',
                "",
                "    assert response.status_code == 422",
                '    assert response.json()["error"]["code"] == "TOTAL_MISMATCH"',
            )
        )

    def engine_note(self, plan: dict[str, Any]) -> str | None:
        custom = {
            answer["id"]: answer
            for module in plan["modules"]
            for op in module["operations"]
            for answer in op.get("customRules") or []
        }
        if not custom:
            return None
        lines = [
            f"- `{answer['id']}`: answer {answer['status']} with code `{answer['code']}`"
            + (f' and `details={{"fields": ["{answer["field"]}"]}}`' if answer.get("field") else "")
            for answer in custom.values()
        ]
        return (
            "Business rules (Story 10.4): the predefined kinds are already checked (`src/libs/rules`). Implement each "
            "custom rule in its operation's use case and raise exactly its code (`ConflictException(message, "
            'code="CODE", details=...)` and the like; 422: `BaseException(422, message, "CODE", details)`), with '
            "tests for an accepted and a refused case:\n" + "\n".join(lines)
        )


def _message(check: dict[str, Any]) -> str:
    if check["kind"] == "transition":
        return f"{check['field']} cannot move to that state from the current one"
    if check["kind"] == "immutableAfter":
        return f"The record cannot change once {check['field']} is {' or '.join(check['states'])}"
    return f"{check['field']} must equal the total of the {check['items']} rows"


def _items_total(contract: dict[str, Any], plan: dict[str, Any], check: dict[str, Any], record_id: Any) -> float:
    items = next(m for m in plan["models"] if m.get("entity") == check["items"])
    by_attr = {column["attr"]: column["apiName"] for column in items["columns"]}
    rows = contract["x-bga"]["fixtures"].get(check["items"]) or []
    total = 0.0
    for row in rows:
        if row.get(by_attr[check["itemsForeignKey"]]) != record_id:
            continue
        amount = float(row.get(by_attr[check["itemAttr"]]) or 0)
        if check["quantityAttr"]:
            amount *= float(row.get(by_attr[check["quantityAttr"]]) or 0)
        total += amount
    return round(total, 2)


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def _catalog(checks: list[dict[str, Any]]) -> str:
    kinds = {"transition": "Transition", "immutableAfter": "ImmutableAfter", "sumEquals": "SumEquals"}
    used = sorted({kinds[check["kind"]] for check in checks})
    out = [
        '"""The spec\'s business rules (Story 10.4), from the plan: use cases check them, responses list what they',
        'allow."""',
        "",
        f"from .kinds import {', '.join(used)}",
    ]
    for check in sorted(checks, key=lambda c: c["constant"]):
        out += [
            "",
            f"{check['constant']} = {kinds[check['kind']]}(",
            f'    rule="{check["id"]}",',
            f'    field="{check["field"]}",',
        ]
        if check["kind"] == "transition":
            out.append("    allowed={")
            out += [f'        "{state}": {_tuple(nexts)},' for state, nexts in check["allowed"].items()]
            out.append("    },")
        elif check["kind"] == "immutableAfter":
            out.append(f"    states={_tuple(check['states'])},")
        out.append(")")
    return "\n".join(out) + "\n"
