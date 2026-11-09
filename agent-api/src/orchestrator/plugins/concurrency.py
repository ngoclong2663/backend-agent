"""The rules that concurrent requests must not break (Story 10.10), for the rules plugin.

- `capacity` (`{parent, capacityField, where?}` on the child entity): its create locks the parent row
  (`SELECT … FOR UPDATE`) and counts the children that count, in the request's transaction; 409 `CAPACITY_REACHED`.
- `noOverlap` (`{start, end, scope?, where?}`): a PostgreSQL exclusion constraint (`btree_gist`, a `tstzrange` or
  `daterange` with `&&`), so the database refuses the second of two overlapping records; 409 `OVERLAP`.
- `uniqueTogether` (`{fields, where?}`): a unique constraint (a partial unique index with `where`); 409 `DUPLICATE`.

The constraints' violations are mapped by name in the repository (`model.constraintErrors`). Each kind's template
test sends two requests at once: exactly one succeeds.
"""

import datetime as dt
from typing import Any

from src.modules.shared.domain.backend_spec.naming import to_snake

KINDS = ("capacity", "noOverlap", "uniqueTogether")
ANSWERS = {"capacity": (409, "CAPACITY_REACHED"), "noOverlap": (409, "OVERLAP"), "uniqueTogether": (409, "DUPLICATE")}


def _sql(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def where_sql(where: dict[str, Any] | None, columns: dict[str, dict[str, Any]]) -> str | None:
    """The `where` of a rule as SQL on the table's columns (for a partial index or exclusion constraint)."""
    parts = []
    for name, condition in (where or {}).items():
        column = columns[name]["attr"]
        if isinstance(condition, dict):
            ((op, value),) = condition.items()
        else:
            op, value = "eq", condition
        if op in ("in", "notIn"):
            values = ", ".join(_sql(v) for v in value)
            parts.append(f"{column} {'IN' if op == 'in' else 'NOT IN'} ({values})")
        else:
            parts.append(f"{column} {'<>' if op == 'ne' else '='} {_sql(value)}")
    return " AND ".join(parts) or None


def counts(row: dict[str, Any], where: dict[str, Any] | None) -> bool:
    """A fixture row the rule counts."""
    for name, condition in (where or {}).items():
        value = row.get(name)
        if isinstance(condition, dict):
            ((op, expected),) = condition.items()
        else:
            op, expected = "eq", condition
        ok = {
            "eq": value == expected,
            "ne": value != expected,
            "in": value in (expected or []),
            "notIn": value not in (expected or []),
        }[op]
        if not ok:
            return False
    return True


def counting_value(column: dict[str, Any], condition: Any) -> Any:
    """A value of `column` the rule counts (a test's records must count)."""
    values = list((column.get("enum") or {}).get("values") or [])
    if isinstance(condition, dict):
        ((op, expected),) = condition.items()
        if op == "in":
            return expected[0]
        excluded = expected if op == "notIn" else [expected]
        return next((v for v in values if v not in excluded), None)
    return condition


def plan_rule(plan: dict[str, Any], rule: dict[str, Any], module: dict[str, Any], model: dict[str, Any]) -> dict:
    """Adds the rule to the plan (constraint, check, errors, tests); returns its plan definition."""
    by_api = {column["apiName"]: column for column in model["columns"]}
    params = rule.get("params") or {}
    kind = rule["kind"]
    name = f"{'ex' if kind == 'noOverlap' else 'uq'}_{model['table']}_{to_snake(rule['id'])}"[:63]
    status, code = ANSWERS[kind]
    definition: dict[str, Any] = {"id": rule["id"], "kind": kind, "where": params.get("where"), "code": code}
    if kind == "capacity":
        fk = by_api[params["parent"]]
        table = fk["foreignKey"]["references"].partition(".")[0]
        parent = next(m for m in plan["models"] if m["table"] == table)
        parent_pk = next(c for c in parent["columns"] if c["primaryKey"])
        limit = next(c for c in parent["columns"] if c["apiName"] == params["capacityField"])
        definition |= {
            "constant": None,
            "field": fk["apiName"],
            "attr": fk["attr"],
            "parentModel": parent["class"],
            "parentEntity": parent["entity"],
            "parentPk": parent_pk["attr"],
            "capacityAttr": limit["attr"],
            "capacityField": limit["apiName"],
            "pkType": parent_pk["pythonType"],
            "model": model["class"],
            "method": f"{to_snake(parent['entity'])}_taken",
            "message": f"The {to_snake(parent['entity']).replace('_', ' ')} is full",
            "fields": [fk["apiName"]],
        }
    elif kind == "noOverlap":
        start, end = by_api[params["start"]], by_api[params["end"]]
        scope = [by_api[f] for f in params.get("scope") or []]
        range_fn = "daterange" if start["type"] == "date" else "tstzrange"
        elements = [f'(column("{c["attr"]}"), "=")' for c in scope]
        elements.append(f'(func.{range_fn}(column("{start["attr"]}"), column("{end["attr"]}"), "[)"), "&&")')
        where = where_sql(params.get("where"), by_api)
        code_text = (
            f'ExcludeConstraint({", ".join(elements)}, name="{name}", using="gist"'
            + (f", where=text({where!r})" if where else "")
            + ")"
        )
        imports = [["sqlalchemy", ["column", "func"]], ["sqlalchemy.dialects.postgresql", ["ExcludeConstraint"]]]
        if where:
            imports.append(["sqlalchemy", ["text"]])
        model.setdefault("tableArgs", []).append({"code": code_text, "imports": imports})
        fields = [*(c["apiName"] for c in scope), start["apiName"], end["apiName"]]
        definition |= {
            "name": name,
            "start": start["apiName"],
            "end": end["apiName"],
            "startType": start["type"],
            "scope": [c["apiName"] for c in scope],
            "fields": fields,
            "message": "It overlaps another one",
        }
    else:
        columns = [by_api[f] for f in params["fields"]]
        where = where_sql(params.get("where"), by_api)
        quoted = ", ".join(f'"{c["attr"]}"' for c in columns)
        attrs = sorted(c["attr"] for c in columns)
        own = next((g for g in model.get("uniqueConstraints") or [] if sorted(g) == attrs), None) if not where else None
        if own is not None:
            # the entity already declares this unique pair (`uniqueConstraints`): a second identical constraint
            # makes Alembic's check report one as new, so the rule answers through the entity's own constraint
            name = f"uq_{model['table']}_{'_'.join(own)}"[:63]
        elif where:
            code_text = f'Index("{name}", {quoted}, unique=True, postgresql_where=text({where!r}))'
            imports = [["sqlalchemy", ["Index", "text"]]]
            model.setdefault("tableArgs", []).append({"code": code_text, "imports": imports})
        else:
            code_text = f'UniqueConstraint({quoted}, name="{name}")'
            imports = [["sqlalchemy", ["UniqueConstraint"]]]
            model.setdefault("tableArgs", []).append({"code": code_text, "imports": imports})
        definition |= {
            "name": name,
            "fields": [c["apiName"] for c in columns],
            "message": f"This {', '.join(c['apiName'] for c in columns)} is taken",
        }
    if kind != "capacity":
        model.setdefault("constraintErrors", {})[definition["name"]] = {
            "code": code,
            "message": definition["message"],
            "fields": definition["fields"],
        }
    for column in (by_api[f] for f in definition["fields"]):
        column["ruled"] = True
    for op in module["operations"]:
        if op.get("action") in ("create", "update") and (kind != "capacity" or op["action"] == "create"):
            error = {"status": status, "exception": "ConflictException", "code": code}
            if error not in op["errors"]:
                op["errors"].append(error)
            op["concurrencyRules"] = [*op.get("concurrencyRules", []), definition]
            op["templatedRules"] = [*op.get("templatedRules", []), rule["id"]]
            if op["action"] == "create":
                module["tests"].append(
                    {
                        "id": f"test_{op['handler']}__{to_snake(rule['id'])}_concurrent",
                        "operationId": op["operationId"],
                        "case": "rule_concurrent",
                        "rule": rule["id"],
                        "expectStatus": 409,
                        "description": "two requests at once: exactly one succeeds",
                    }
                )
    return definition


def rules_of(op: dict[str, Any], kind: str | None = None) -> list[dict[str, Any]]:
    return [rule for rule in op.get("concurrencyRules") or [] if kind is None or rule["kind"] == kind]


def capacity_precheck(module: dict[str, Any], op: dict[str, Any]) -> list[str]:
    snake = to_snake(module["entity"])
    lines = []
    for rule in rules_of(op, "capacity"):
        lines += [
            f"taken, capacity = self.{snake}_repo.{rule['method']}(dto.{rule['attr']})  # locks it (Story 10.10)",
            "if capacity is not None and taken >= capacity:",
            f'    raise ConflictException("{rule["message"]}", ErrorCode.CAPACITY_REACHED, '
            f'details={{"fields": ["{rule["field"]}"]}})',
        ]
    return lines


def capacity_method(plan: dict[str, Any], rule: dict[str, Any]) -> tuple[str, tuple[str, ...], list]:
    """(signature, body, imports) of the repository's count under the parent's row lock."""
    model = next(m for m in plan["models"] if m["class"] == rule["model"])
    by_api = {c["apiName"]: c for c in model["columns"]}
    conditions, imports = (
        [],
        [
            ("sqlmodel", ("col", "func", "select")),
            ("src.modules.shared.infrastructure.models", (rule["parentModel"], rule["model"])),
        ],
    )
    for name, condition in (rule["where"] or {}).items():
        column = by_api[name]
        if isinstance(condition, dict):
            ((op, value),) = condition.items()
        else:
            op, value = "eq", condition
        enum = (column.get("enum") or {}).get("class")
        if enum:
            imports.append(("src.modules.shared.domain.entities", (enum,)))

        def literal(v: Any, enum: str | None = enum) -> str:
            from ..backend.codegen import _member

            return f"{enum}.{_member(v)}" if enum else repr(v)

        target = f"col({rule['model']}.{column['attr']})"
        if op in ("in", "notIn"):
            items = ", ".join(literal(v) for v in value)
            conditions.append(f"{'' if op == 'in' else '~'}{target}.in_([{items}])")
        else:
            conditions.append(f"{target} {'!=' if op == 'ne' else '=='} {literal(value)}")
    where = "".join(f"\n    .where({c})" for c in conditions)
    parent = rule["parentModel"]
    body = (
        f'"""Locks the {rule["parentEntity"]} row and counts its records that count (rule {rule["id"]})."""',
        f"parent = self.session.exec(select({parent}).where(col({parent}.{rule['parentPk']}) == parent_id)"
        ".with_for_update()).first()",
        "if parent is None:",
        "    return 0, None",
        "query = (",
        f"    select(func.count()).select_from({rule['model']}).where(col({rule['model']}.{rule['attr']}) == parent_id)"
        + where,
        ")",
        f"return self.session.exec(query).one(), parent.{rule['capacityAttr']}",
    )
    pk_type = rule["pkType"]
    if pk_type == "uuid.UUID":
        imports.append(("uuid", ()))
    return f"{rule['method']}(self, parent_id: {pk_type}) -> tuple[int, int | None]", body, imports


def concurrent_test(
    plan: dict[str, Any], module: dict[str, Any], op: dict[str, Any], test: dict[str, Any], seed_for
) -> tuple[tuple[str, ...], tuple]:
    """Two requests at once (each its own client on the app): exactly one is created, the other is refused."""
    rule = next(r for r in rules_of(op) if r["id"] == test["rule"])
    model = next(m for m in plan["models"] if m.get("entity") == module["entity"])
    by_api = {c["apiName"]: c for c in model["columns"]}
    lines = [f"def {test['id']}(client):", "    first, second = _payload(), _payload()"]
    for name, condition in (rule["where"] or {}).items():  # both records count
        value = counting_value(by_api[name], condition)
        lines.append(f'    first["{name}"] = second["{name}"] = {value!r}')
    if rule["kind"] == "capacity":
        lines.insert(1, f"    parent = {seed_for(rule['parentEntity'])}({rule['capacityAttr']}=1)")
        lines.append(f'    first["{rule["field"]}"] = second["{rule["field"]}"] = str(parent.{rule["parentPk"]})')
    elif rule["kind"] == "noOverlap":
        day = "2026-03-01"
        if rule["startType"] == "date":
            a, b = (f"{day}", "2026-03-03"), ("2026-03-02", "2026-03-04")
        else:
            a, b = (f"{day}T10:00:00Z", f"{day}T11:00:00Z"), (f"{day}T10:30:00Z", f"{day}T11:30:00Z")
        for scope in rule["scope"]:
            lines.append(f'    second["{scope}"] = first["{scope}"]')
        lines.append(f'    first["{rule["start"]}"], first["{rule["end"]}"] = "{a[0]}", "{a[1]}"')
        lines.append(f'    second["{rule["start"]}"], second["{rule["end"]}"] = "{b[0]}", "{b[1]}"')
    else:
        for field in rule["fields"]:
            lines.append(f'    second["{field}"] = first["{field}"]')
    path = op["path"]
    lines += [
        "",
        "    def send(body: dict) -> int:",
        f'        return TestClient(client.app, headers=dict(client.headers)).post("{path}", json=body).status_code',
        "",
        "    with ThreadPoolExecutor(2) as pool:",
        "        statuses = sorted(pool.map(send, [first, second]))",
        "",
        "    assert statuses == [201, 409]",
        f'    again = client.post("{path}", json=second)',
        f'    assert again.status_code == 409 and again.json()["error"]["code"] == "{rule["code"]}"',
    ]
    imports = (("concurrent.futures", ("ThreadPoolExecutor",)), ("fastapi.testclient", ("TestClient",)))
    return tuple(lines), imports


def _caller_id(meta: dict[str, Any], plan: dict[str, Any], scenario: dict[str, Any]) -> Any:
    """The seeded id of the demo user a scenario runs as (`scenario.user`, else the default one), or None."""
    auth = plan.get("auth") or {}
    demo = auth.get("demoUsers") or []
    login = scenario.get("user") or (demo[0]["login"] if demo else None)
    user_model = next((m for m in plan["models"] if m.get("entity") == auth.get("userEntity")), None)
    if login is None or user_model is None:
        return None
    pk = next(c["apiName"] for c in user_model["columns"] if c["primaryKey"])
    users = meta["fixtures"].get(auth["userEntity"]) or []
    return next((row.get(pk) for row in users if row.get(auth.get("loginField")) == login), None)


def contract_scenarios(
    contract: dict[str, Any],
    plan: dict[str, Any],
    module: dict[str, Any],
    op: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> None:
    """Full, overlap and duplicate scenarios from the fixtures, and a success that breaks none of them."""
    meta = contract["x-bga"]
    entity = module["entity"]
    records = meta["fixtures"].get(entity) or []
    success = next((s for s in scenarios if s["name"] == "success" and isinstance(s.get("body"), dict)), None)
    if success is None or not records:
        return
    blocked: dict[str, set[Any]] = {}  # a capacity rule's full parents: other scenarios reach records elsewhere

    def open_record(rule: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (
                r
                for r in records
                if counts(r, rule["where"]) and all(r.get(field) not in values for field, values in blocked.items())
            ),
            None,
        )

    for rule in rules_of(op):
        if rule["kind"] == "capacity":
            parents = meta["fixtures"].get(rule["parentEntity"]) or []
            parent_pk = next(
                c["apiName"]
                for m in plan["models"]
                if m["entity"] == rule["parentEntity"]
                for c in m["columns"]
                if c["primaryKey"]
            )
            taken = {
                p[parent_pk]: sum(
                    1 for r in records if r.get(rule["field"]) == p[parent_pk] and counts(r, rule["where"])
                )
                for p in parents
            }
            full = next((p for p in parents if (p.get(rule["capacityField"]) or 0) <= taken[p[parent_pk]]), None)
            room = next((p for p in parents if (p.get(rule["capacityField"]) or 0) > taken[p[parent_pk]] + 1), None)
            blocked[rule["field"]] = {
                p[parent_pk] for p in parents if (p.get(rule["capacityField"]) or 0) <= taken[p[parent_pk]]
            }
            if room is not None:
                success["body"][rule["field"]] = room[parent_pk]
                for scenario in scenarios:  # the earlier scenarios (a missing field, an unknown id) are not about it
                    body = scenario.get("body")
                    if isinstance(body, dict) and body.get(rule["field"]) in blocked[rule["field"]]:
                        body[rule["field"]] = room[parent_pk]
            if full is not None:
                scenarios.append(
                    {
                        "name": f"{rule['parentEntity'][:1].lower()}{rule['parentEntity'][1:]} full",
                        "params": success["params"],
                        "body": {**success["body"], rule["field"]: full[parent_pk]},
                        "expect": {"status": 409, "code": "CAPACITY_REACHED"},
                        **({"user": success["user"]} if success.get("user") else {}),
                    }
                )
        elif rule["kind"] == "noOverlap":
            later = "2027-06-01" if rule["startType"] == "date" else "2027-06-01T09:00:00Z"
            end = "2027-06-02" if rule["startType"] == "date" else "2027-06-01T10:00:00Z"
            success["body"][rule["start"]], success["body"][rule["end"]] = later, end
            taken = open_record(rule)
            if taken is not None:
                body = {
                    **success["body"],
                    rule["start"]: taken[rule["start"]],
                    rule["end"]: taken[rule["end"]],
                    **{s: taken[s] for s in rule["scope"]},
                }
                for name, condition in (rule["where"] or {}).items():
                    column = next(
                        c for m in plan["models"] if m["entity"] == entity for c in m["columns"] if c["apiName"] == name
                    )
                    body[name] = counting_value(column, condition)
                scenarios.append(
                    {
                        "name": "overlap",
                        "params": success["params"],
                        "body": body,
                        "expect": {"status": 409, "code": "OVERLAP"},
                        **({"user": success["user"]} if success.get("user") else {}),
                    }
                )
        else:
            fields = rule["fields"]
            columns = {c["apiName"]: c for m in plan["models"] if m["entity"] == entity for c in m["columns"]}
            # the owner the server sets from the signed-in user is not in the body: the scenario's user's id
            server_set = {f for f in fields if (columns.get(f) or {}).get("source") == "currentUser"}
            caller = _caller_id(meta, plan, success) if server_set else None
            pairs = {tuple(r.get(f) for f in fields) for r in records if counts(r, rule["where"])}
            mine = tuple(caller if f in server_set else success["body"].get(f) for f in fields)
            varied = next((f for f in fields if f not in server_set and f in success["body"]), None)
            if mine in pairs and varied is not None:  # the success would be a duplicate of a seeded record
                at = fields.index(varied)
                column = columns[varied]
                if column.get("foreignKey"):
                    table = column["foreignKey"]["references"].partition(".")[0]
                    parent = next(m for m in plan["models"] if m["table"] == table)
                    pk = next(c["apiName"] for c in parent["columns"] if c["primaryKey"])
                    options = [p[pk] for p in meta["fixtures"].get(parent["entity"]) or []]
                    free = next((o for o in options if (*mine[:at], o, *mine[at + 1 :]) not in pairs), None)
                    if free is not None:
                        before = success["body"][varied]
                        for scenario in scenarios:  # the creates built from the success's body move with it (else
                            body = scenario.get("body")  # their seeded pair is a second conflict, answered first)
                            if isinstance(body, dict) and body.get(varied) == before:
                                body[varied] = free
                elif isinstance(success["body"].get(varied), str):
                    success["body"][varied] = f"{success['body'][varied]} (new)"
            text_field = next(
                (f for f in rule["fields"] if isinstance(success["body"].get(f), str) and not f.endswith("Id")), None
            )
            for index, scenario in enumerate(scenarios):  # the success creates its pair: the others get their own
                body = scenario.get("body")
                if scenario is success or not isinstance(body, dict) or not isinstance(body.get(text_field), str):
                    continue
                body[text_field] = f"s{index}-{body[text_field]}"
            # a seeded pair of the scenario's own user (the server sets the owner: another user's pair is no clash)
            taken = (
                open_record(rule)
                if not server_set
                else next(
                    (
                        r
                        for r in records
                        if counts(r, rule["where"])
                        and all(r.get(f) == caller for f in server_set)
                        and all(r.get(f) not in values for f, values in blocked.items())
                    ),
                    None,
                )
            )
            if taken is not None:
                body = {**success["body"], **{f: taken[f] for f in fields if f not in server_set}}
                for other in rules_of(op, "noOverlap"):  # a slot of its own: the success took the body's
                    date = other["startType"] == "date"
                    body[other["start"]] = "2027-08-01" if date else "2027-08-01T09:00:00Z"
                    body[other["end"]] = "2027-08-02" if date else "2027-08-01T10:00:00Z"
                scenarios.append(
                    {
                        "name": "duplicate",
                        "params": success["params"],
                        "body": body,
                        "expect": {"status": 409, "code": "DUPLICATE"},
                        **({"user": success["user"]} if success.get("user") else {}),
                    }
                )


def adjust_fixtures(contract: dict[str, Any], plan: dict[str, Any]) -> None:
    """A noOverlap rule's fixtures get a real range (the end an hour, or a day, after the start), so the seeded
    records can be overlapped."""
    meta = contract["x-bga"]
    for module in plan["modules"]:
        for op in module["operations"]:
            for rule in rules_of(op, "noOverlap"):
                for row in meta["fixtures"].get(module["entity"]) or []:
                    start = row.get(rule["start"])
                    if not isinstance(start, str):
                        continue
                    if rule["startType"] == "date":
                        row[rule["end"]] = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()
                    else:
                        moment = dt.datetime.fromisoformat(start.replace("Z", "+00:00")) + dt.timedelta(hours=1)
                        row[rule["end"]] = moment.isoformat().replace("+00:00", "Z")
