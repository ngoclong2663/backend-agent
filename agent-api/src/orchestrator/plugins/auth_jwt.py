"""JWT authentication as a plugin (Story 10.2): register, login and me; argon2 password hashes (pwdlib); HS256
bearer tokens (PyJWT); `CurrentUserDep` on every operation with `auth: jwt`, through the router-parameter hook.

The spec names the user entity (`auth.userEntity`, default `User`; added when the spec has none) and the login field
(`auth.loginField`, default `email`). Before planning the plugin gives that entity a unique login field, a secret
`passwordHash` (never in a request or a response) and a `role`, and seeds one demo user per role. The `auth` module
(`src/modules/auth/`) is the plugin's own: codegen and the engine leave it alone.
"""

import re
import uuid
from typing import Any

from src.modules.shared.domain.backend_spec.naming import to_snake

from .base import AppStartup, Code, Plugin, RouterParam, Setting

# The argon2id hash (pwdlib, the generated app's hasher) of the demo users' password, so seeds need no hashing
DEMO_PASSWORD = "demo12345"
DEMO_HASH = "$argon2id$v=19$m=65536,t=3,p=4$t5dNVcNismgMPuOqvM9fhA$1r4SPd75z/nxLm6p6tKxg36bzZ2dCsOX4jjBmHO7d+8"
PASSWORD_FIELDS = {"password", "passwordHash", "hashedPassword", "password_hash"}
NAMESPACE = uuid.UUID("2b8f4c1e-9a6d-4e3b-8c7f-5d1a0e9b6c42")
MODULE = "src/modules/auth"
TEST_SECRET = "test-secret-not-for-production-0123456789abcdef"
INVALID = "VALIDATION_ERROR"


def _auth(spec: dict[str, Any]) -> dict[str, Any]:
    auth = spec.get("auth") or {}
    return {
        "userEntity": auth.get("userEntity") or "User",
        "loginField": auth.get("loginField") or "email",
        "roles": list(auth.get("roles") or []),
    }


def _demo_login(login_field: str, role: str) -> str:
    """`demo-<role>@example.com` (or `demo-<role>`). A role is a name people read ("Shop Owner"): anything a login
    cannot hold becomes a hyphen (`demo-Shop-Owner@example.com`), so the demo account can sign in (Story 32.8: a space
    made the shop owner's address invalid in the sign-in form). Plain roles keep their login as it was."""
    part = re.sub(r"[^A-Za-z0-9._-]+", "-", role).strip("-") or "user"
    return f"demo-{part}@example.com" if "email" in login_field.lower() else f"demo-{part}"


def _secured(op: dict[str, Any]) -> bool:
    return (op.get("auth") or {}).get("auth") == "jwt"


class AuthJwtPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="auth-jwt", requires=("rate-limit",))

    def applies(self, spec: dict[str, Any]) -> bool:
        return (spec.get("auth") or {}).get("type") == "jwt"

    # -- the spec and the plan ------------------------------------------------------------------------------------

    def extend_spec(self, spec: dict[str, Any]) -> None:
        auth = _auth(spec)
        entities = spec.setdefault("entities", [])
        entity = next((e for e in entities if e["name"] == auth["userEntity"]), None)
        if entity is None:
            tables = {e.get("table") for e in entities}
            entity = {
                "name": auth["userEntity"],
                "table": "users" if "users" not in tables else f"{to_snake(auth['userEntity'])}_accounts",
                "fields": [
                    {"name": "id", "type": "uuid", "primary": True, "required": False, "nullable": False},
                    {"name": "createdAt", "type": "datetime", "required": True, "nullable": False, "default": "now"},
                ],
            }
            entities.append(entity)
        fields = [field for field in entity["fields"] if field["name"] not in PASSWORD_FIELDS]
        login = next((field for field in fields if field["name"] == auth["loginField"]), None)
        if login is None:
            login = {"name": auth["loginField"], "type": "string", "maxLength": 255}
            fields.insert(1, login)
        login.update({"required": True, "nullable": False, "unique": True})
        fields.append({"name": "passwordHash", "type": "string", "required": True, "nullable": False, "maxLength": 255})
        if not any(field["name"] == "role" for field in fields):
            role: dict[str, Any] = {"name": "role", "required": False, "nullable": False}
            if auth["roles"]:
                role |= {"type": "enum", "values": auth["roles"], "default": auth["roles"][0]}
            else:
                role |= {"type": "string", "maxLength": 32, "default": "user"}
            fields.append(role)
        entity["fields"] = fields
        # one demo user per role, with the other required fields filled
        others = [
            field
            for field in fields
            if field.get("required")
            and field.get("default") is None
            and not field.get("primary")
            and field["name"] not in (auth["loginField"], "passwordHash")
        ]
        records = []
        for role_name in auth["roles"] or ["user"]:
            record: dict[str, Any] = {
                auth["loginField"]: _demo_login(auth["loginField"], role_name),
                "passwordHash": DEMO_HASH,
                "role": role_name,
            }
            for field in others:
                record[field["name"]] = _sample(field, role_name)
            records.append(record)
        spec.setdefault("seed", []).append({"entity": auth["userEntity"], "records": records})

    def plan(self, plan: dict[str, Any], spec: dict[str, Any]) -> None:
        auth = _auth(spec)
        model = next(m for m in plan["models"] if m.get("entity") == auth["userEntity"])
        by_api = {column["apiName"]: column for column in model["columns"]}
        by_api["passwordHash"]["secret"] = True
        login = by_api[auth["loginField"]]
        roles = auth["roles"] or ["user"]
        seeded = [  # what extend_spec seeded (a later plugin may add one: policies' second user, 10.3)
            record
            for seed in spec.get("seed", [])
            if seed["entity"] == auth["userEntity"]
            for record in seed["records"]
            if record.get("passwordHash") == DEMO_HASH
        ]
        plan["auth"] = {
            "userEntity": auth["userEntity"],
            "model": model["class"],
            "entityClass": model["entityClass"],
            "loginField": auth["loginField"],
            "loginAttr": login["attr"],
            "primaryKeyAttr": next(column["attr"] for column in model["columns"] if column["primaryKey"]),
            "roles": roles,
            "demoUsers": [
                {"login": record[auth["loginField"]], "password": DEMO_PASSWORD, "role": record["role"]}
                for record in seeded
            ],
        }
        operations = [
            _op("auth.register", "POST", "/auth/register", "register", 201, [(409, "CONFLICT"), (422, INVALID)]),
            _op("auth.login", "POST", "/auth/login", "login", 200, [(401, "UNAUTHORIZED"), (422, INVALID)]),
            _op("auth.me", "GET", "/auth/me", "me", 200, [(401, "UNAUTHORIZED")]),
        ]  # fmt: skip
        operations[2]["auth"] = {"auth": "jwt", "policy": None}
        plan["modules"].insert(
            0,
            {
                "name": "auth",
                "entity": auth["userEntity"],
                "plugin": self.name,
                "model": model["class"],
                "entityClass": model["entityClass"],
                "port": {
                    "interface": "IAccountRepository",
                    "dep": "IAccountRepoDep",
                    "file": f"{MODULE}/ports/output/account_repository.py",
                    "implementation": "AccountRepository",
                    "implementationFile": f"{MODULE}/infrastructure/persistence/account_repository.py",
                    "methods": ["find_by_login", "create"],
                },
                "usecases": [],
                "dtoFiles": [f"{MODULE}/presenter/dtos/auth_dto.py"],
                "router": {
                    "variable": "auth_router",
                    "file": f"{MODULE}/presenter/router.py",
                    "prefix": "",
                    "tag": "auth",
                },
                "operations": operations,
                "recordActions": [],
                "testFile": "tests/modules/auth/test_auth_api.py",
                "tests": [],
            },
        )
        order = plan["routers"]["order"]
        order.insert(1 if order and order[0] == "health_router" else 0, "auth_router")
        # jwt is handled now; policies are 10.3's
        plan["unresolved"] = [
            entry
            for entry in plan["unresolved"]
            if not (entry["kind"] == "auth" and (entry["ref"] == "auth" or not _policy(plan, entry["ref"])))
        ]

    def contract(self, contract: dict[str, Any], plan: dict[str, Any], spec: dict[str, Any]) -> None:
        auth = plan["auth"]
        model = next(m for m in plan["models"] if m.get("entity") == auth["userEntity"])
        schemas = contract["components"]["schemas"]
        contract["components"]["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        from ..integration.contract import _request_columns, _required, field_schema

        visible = [column for column in model["columns"] if not column.get("secret")]
        schemas["Account"] = {
            "type": "object",
            "properties": {column["apiName"]: field_schema(column) for column in visible},
            "required": [column["apiName"] for column in visible],
        }
        register = [c for c in _request_columns(model, {}) if c["apiName"] != "role"]
        register_props = {c["apiName"]: field_schema(c) | {"x-bga": {"source": "input"}} for c in register}
        register_props["password"] = {"type": "string", "minLength": 8, "maxLength": 128, "x-bga": {"source": "input"}}
        required = [c["apiName"] for c in register if _required(c)] + ["password"]
        schemas["RegisterRequest"] = {"type": "object", "properties": register_props, "required": required}
        login_schema = field_schema(next(c for c in model["columns"] if c["attr"] == auth["loginAttr"]))
        schemas["LoginRequest"] = {
            "type": "object",
            "properties": {auth["loginField"]: login_schema, "password": {"type": "string"}},
            "required": [auth["loginField"], "password"],
        }
        schemas["TokenResponse"] = {
            "type": "object",
            "properties": {"accessToken": {"type": "string"}, "tokenType": {"type": "string", "enum": ["bearer"]}},
            "required": ["accessToken", "tokenType"],
        }
        demo = auth["demoUsers"][0]
        demo_body = {auth["loginField"]: demo["login"], "password": demo["password"]}
        fresh = {_login_value(auth, "scenario"): None}
        fresh_body = {auth["loginField"]: next(iter(fresh)), "password": "scenario-pass-123"}
        for column in register:
            if column["apiName"] not in fresh_body and _required(column):
                fresh_body[column["apiName"]] = _sample({"type": column["type"], "values": _values(column)}, "scenario")
        error = {"$ref": "#/components/schemas/ErrorResponse"}

        def answer(status: str, description: str, schema: str | None) -> dict[str, Any]:
            content = {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}} if schema else None
            return {"description": description, **({"content": content} if content else {})}

        def failure(status: int, code: str) -> dict[str, Any]:
            return {str(status): {"description": code, "content": {"application/json": {"schema": error}}}}

        def body(schema: str) -> dict[str, Any]:
            reference = {"$ref": f"#/components/schemas/{schema}"}
            return {"required": True, "content": {"application/json": {"schema": reference}}}

        meta = {"entity": auth["userEntity"], "action": None, "module": "auth", "plugin": self.name, "mock": "sample"}
        contract["paths"]["/auth/register"] = {
            "post": {
                "operationId": "auth.register",
                "summary": "Create an account",
                "tags": ["auth"],
                "requestBody": body("RegisterRequest"),
                "responses": {"201": answer("201", "The new account", "Account"), **failure(409, "CONFLICT"),
                              **failure(422, "VALIDATION_ERROR")},
                "x-bga": meta | {
                    "sample": _account_sample(visible, fresh_body),
                    "errors": [
                        {"status": 409, "code": "CONFLICT", "fields": [auth["loginField"]],
                         "message": f"An account with this {auth['loginField']} already exists"},
                        {"status": 422, "code": "VALIDATION_ERROR", "message": "Some values are not valid"},
                    ],
                    "scenarios": [
                        {"name": "success", "params": {}, "body": fresh_body, "auth": False, "expect": {"status": 201}},
                        {"name": f"duplicate {auth['loginField']}", "params": {}, "auth": False,
                         "body": {**fresh_body, auth["loginField"]: demo["login"]},
                         "expect": {"status": 409, "code": "CONFLICT"}},
                        {"name": "missing password", "params": {}, "auth": False,
                         "body": {k: v for k, v in fresh_body.items() if k != "password"},
                         "expect": {"status": 422, "code": "VALIDATION_ERROR"}},
                    ],
                },
            }
        }  # fmt: skip
        contract["paths"]["/auth/login"] = {
            "post": {
                "operationId": "auth.login",
                "summary": "Sign in: a bearer token",
                "tags": ["auth"],
                "requestBody": body("LoginRequest"),
                "responses": {"200": answer("200", "A bearer token", "TokenResponse"), **failure(401, "UNAUTHORIZED"),
                              **failure(422, "VALIDATION_ERROR")},
                "x-bga": meta | {
                    "sample": {"accessToken": "demo-token", "tokenType": "bearer"},
                    "errors": [
                        {"status": 401, "code": "UNAUTHORIZED", "message": f"Wrong {auth['loginField']} or password"}
                    ],
                    "scenarios": [
                        {"name": "success", "params": {}, "body": demo_body, "auth": False, "expect": {"status": 200}},
                        {"name": "wrong password", "params": {}, "auth": False,
                         "body": {**demo_body, "password": "not-the-password"},
                         "expect": {"status": 401, "code": "UNAUTHORIZED"}},
                    ],
                },
            }
        }  # fmt: skip
        contract["paths"]["/auth/me"] = {
            "get": {
                "operationId": "auth.me",
                "summary": "The signed-in account",
                "tags": ["auth"],
                "security": [{"bearerAuth": []}],
                "responses": {"200": answer("200", "The signed-in account", "Account"), **failure(401, "UNAUTHORIZED")},
                "x-bga": meta
                | {
                    "auth": "jwt",
                    "sample": _account_sample(visible, demo_body),
                    "errors": [{"status": 401, "code": "UNAUTHORIZED", "message": "Sign in to continue"}],
                    "scenarios": [{"name": "success", "params": {}, "auth": True, "expect": {"status": 200}}],
                },
            }
        }
        # every protected operation answers 401 without a token (the scenario the smoke check runs first)
        for item in contract["paths"].values():
            for operation in item.values():
                if not isinstance(operation, dict) or not operation.get("security"):
                    continue
                meta_op = operation.setdefault("x-bga", {})
                scenarios = meta_op.setdefault("scenarios", [])
                params = scenarios[0]["params"] if scenarios else _guess_params(operation, contract)
                if params is None:
                    continue
                scenarios.insert(0, {"name": "no token", "params": params, "auth": False,
                                     "expect": {"status": 401, "code": "UNAUTHORIZED"}})  # fmt: skip
                errors = meta_op.setdefault("errors", [])
                if not any(e["status"] == 401 for e in errors):
                    errors.append({"status": 401, "code": "UNAUTHORIZED", "message": "Sign in to continue"})
                operation["responses"].setdefault("401", failure(401, "UNAUTHORIZED")["401"])
        contract["x-bga"]["auth"] = {
            "login": {
                "operationId": "auth.login",
                "path": "/auth/login",
                "body": demo_body,
                "field": auth["loginField"],  # how the smoke check signs in another demo user (10.3)
            },
            "demoUsers": auth["demoUsers"],
        }

    # -- the project ----------------------------------------------------------------------------------------------

    def settings(self, plan: dict[str, Any] | None) -> list[Setting]:
        return [
            Setting("jwt_secret", "str", None, comment="from the environment only", example="JWT_SECRET=",
                    test_value=TEST_SECRET),
            Setting("access_token_expire_minutes", "int", "60", example="ACCESS_TOKEN_EXPIRE_MINUTES=60"),
            Setting("auth_rate_limit", "str", '"10/minute"', comment="register and login, per client",
                    test_value="100000/minute"),
        ]  # fmt: skip

    def files(self, plan: dict[str, Any] | None) -> dict[str, str]:
        files = super().files(plan)
        auth = (plan or {}).get("auth")
        if auth is None:
            return files
        model = next(m for m in plan["models"] if m.get("entity") == auth["userEntity"])
        files |= _security_files(auth, model)
        files |= _module_files(auth, model)
        files |= _test_files(auth, model)
        return files

    def app_startup(self, plan: dict[str, Any] | None) -> AppStartup | None:
        if not (plan or {}).get("auth"):
            return None
        # Story 22.7: the 401 every protected route answers, in the app's OpenAPI as in the contract
        return AppStartup(
            imports=(("src.libs.security.openapi", ("document_unauthorized",)),), setup=("document_unauthorized(app)",)
        )

    def router_params(self, plan, module, op) -> list[RouterParam]:
        if module.get("plugin") or not _secured(op):
            return []
        return [RouterParam("current_user", "CurrentUserDep", None, (("src.libs.security", ("CurrentUserDep",)),))]

    def test_setup(self, plan, module) -> Code | None:
        if module.get("plugin") or not any(_secured(op) for op in module["operations"]):
            return None
        return Code(
            (
                "@pytest.fixture(autouse=True)",
                "def _signed_in(client):",
                '    """Story 10.2: the module\'s routes need a bearer token; each test signs a fresh account in."""',
                '    client.headers["Authorization"] = f"Bearer {sign_in(client)}"',
                "    yield",
                '    client.headers.pop("Authorization", None)',
            ),
            (("pytest", ()), ("tests.auth", ("sign_in",))),
        )

    def engine_note(self, plan: dict[str, Any]) -> str:
        auth = plan["auth"]
        return (
            "Authentication (`src/libs/security`, `src/modules/auth`): routes of operations with `auth: jwt` take "
            "`current_user: CurrentUserDep` (`from src.libs.security import CurrentUserDep`), the signed-in "
            f"`{auth['entityClass']}`; without a valid bearer token they answer 401 before your code runs. Pass "
            "`current_user` to the use case when the operation needs to know who is calling."
        )


# -- helpers ----------------------------------------------------------------------------------------------------------


def _op(operation_id: str, method: str, path: str, handler: str, status: int, errors: list[tuple[int, str]]) -> dict:
    return {
        "operationId": operation_id,
        "type": "plugin",
        "action": None,
        "method": method,
        "path": path,
        "handler": handler,
        "status": status,
        "transactional": method != "GET",
        "errors": [{"status": s, "exception": None, "code": c} for s, c in errors],
    }


def _policy(plan: dict[str, Any], operation_id: str) -> bool:
    return any(
        op["operationId"] == operation_id and (op.get("auth") or {}).get("policy")
        for module in plan["modules"]
        for op in module["operations"]
    )


def _values(column: dict[str, Any]) -> list[str]:
    return list((column.get("enum") or {}).get("values") or column.get("values") or [])


def _sample(field: dict[str, Any], tag: str) -> Any:
    kind = field.get("type")
    if kind == "enum":
        return (field.get("values") or ["x"])[0]
    if kind in ("integer", "float", "decimal"):
        return 1
    if kind == "boolean":
        return True
    if kind == "date":
        return "2026-01-15"
    if kind == "datetime":
        return "2026-01-15T09:00:00Z"
    if kind == "uuid":
        return str(uuid.uuid5(NAMESPACE, tag))
    return f"Demo {tag}"


def _login_value(auth: dict[str, Any], tag: str) -> str:
    return f"{tag}@example.com" if "email" in auth["loginField"].lower() else tag


def _account_sample(columns: list[dict[str, Any]], body: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for column in columns:
        if column["apiName"] in body:
            out[column["apiName"]] = body[column["apiName"]]
        elif column["primaryKey"]:
            out[column["apiName"]] = str(uuid.uuid5(NAMESPACE, "account"))
        elif column["type"] == "datetime":
            out[column["apiName"]] = "2026-01-15T09:00:00Z"
        elif (column.get("default") or {}).get("value") is not None:
            out[column["apiName"]] = column["default"]["value"]
        else:
            out[column["apiName"]] = _sample({"type": column["type"], "values": _values(column)}, "account")
    return out


def _guess_params(operation: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    """Path parameters for a protected operation without scenarios: the first fixture of its entity."""
    names = [p["name"] for p in operation.get("parameters") or [] if p.get("in") == "path"]
    if not names:
        return {}
    entity = (operation.get("x-bga") or {}).get("entity")
    rows = ((contract.get("x-bga") or {}).get("fixtures") or {}).get(entity) or []
    if not rows:
        return None
    first = rows[0]
    if len(names) == 1 and names[0] not in first:
        return {names[0]: first.get("id")}
    return {name: first[name] for name in names} if all(name in first for name in names) else None


def _python_type(column: dict[str, Any]) -> str:
    return {"uuid.UUID": "uuid.UUID", "int": "int"}.get(column.get("pythonType", ""), "str")


def _security_files(auth: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
    pk = next(column for column in model["columns"] if column["primaryKey"])
    parse = "uuid.UUID(subject)" if pk["type"] == "uuid" else ("int(subject)" if pk["type"] == "integer" else "subject")
    return {
        "src/libs/security/__init__.py": (
            "from .current_user import CurrentUserDep, OptionalUserDep, bearer_scheme, get_current_user\n"
            "from .passwords import hash_password, verify_password\n"
            "from .roles import require_roles\n"
            "from .tokens import create_access_token, decode_access_token\n\n"
            '__all__ = [\n    "CurrentUserDep",\n    "OptionalUserDep",\n    "bearer_scheme",\n'
            '    "create_access_token",\n'
            '    "decode_access_token",\n    "get_current_user",\n    "hash_password",\n    "require_roles",\n'
            '    "verify_password",\n]\n'
        ),
        "src/libs/security/roles.py": (
            "from collections.abc import Callable\n\n"
            "from src.libs.exceptions import ForbiddenException\n"
            f"from src.modules.shared.domain.entities import {auth['entityClass']}\n\n"
            "from .current_user import CurrentUserDep\n\n\n"
            f"def require_roles(*roles: str) -> Callable[..., {auth['entityClass']}]:\n"
            '    """A route dependency: the signed-in user when their role is one of `roles`, else 403 (401 without a\n'
            '    token). `current_user: Annotated[User, Depends(require_roles("admin"))]`."""\n\n'
            f"    def signed_in_with_role(current_user: CurrentUserDep) -> {auth['entityClass']}:\n"
            "        if current_user.role not in roles:\n"
            '            raise ForbiddenException("Your role cannot do this", details={"roles": list(roles)})\n'
            "        return current_user\n\n"
            "    return signed_in_with_role\n"
        ),
        "src/libs/security/current_user.py": (
            "import uuid\nfrom typing import Annotated\n\nfrom fastapi import Depends, Request\n"
            "from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer\n\n"
            "from src.libs.database.session import SessionDep\nfrom src.libs.exceptions import UnauthorizedException\n"
            f"from src.modules.shared.domain.entities import {auth['entityClass']}\n"
            f"from src.modules.shared.infrastructure.models import {auth['model']}\n\n"
            "from .tokens import decode_access_token\n\n"
            '# The OpenAPI security scheme of every protected route ("bearerAuth", as the API contract names it)\n'
            'bearer_scheme = HTTPBearer(scheme_name="bearerAuth", auto_error=False)\n\n\n'
            "def get_current_user(\n    session: SessionDep,\n"
            "    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],\n"
            f") -> {auth['entityClass']}:\n"
            '    """The signed-in user of a valid bearer token; 401 without one (missing, forged, expired)."""\n'
            "    claims = decode_access_token(credentials.credentials) if credentials else None\n"
            "    model = None\n"
            "    if claims is not None:\n"
            "        try:\n"
            '            subject = claims["sub"]\n'
            f"            model = session.get({auth['model']}, {parse})\n"
            "        except (KeyError, ValueError):\n"
            "            model = None\n"
            "    if model is None:\n"
            '        raise UnauthorizedException("Sign in to continue")\n'
            f"    return {auth['entityClass']}.model_validate(model.model_dump())\n\n\n"
            f"CurrentUserDep = Annotated[{auth['entityClass']}, Depends(get_current_user)]\n\n\n"
            f"def get_optional_user(session: SessionDep, request: Request) -> {auth['entityClass']} | None:\n"
            '    """The signed-in user on a public route (a record\'s actions depend on who asks), else None: a\n'
            "    visitor or a token that no longer works. Read from the header, so the route stays public in the\n"
            '    OpenAPI (Story 22.7)."""\n'
            '    scheme, _, token = request.headers.get("authorization", "").partition(" ")\n'
            '    claims = decode_access_token(token) if scheme.lower() == "bearer" and token else None\n'
            "    if claims is None:\n        return None\n"
            "    try:\n"
            '        subject = claims["sub"]\n'
            f"        model = session.get({auth['model']}, {parse})\n"
            "    except (KeyError, ValueError):\n        return None\n"
            f"    return None if model is None else {auth['entityClass']}.model_validate(model.model_dump())\n\n\n"
            f"OptionalUserDep = Annotated[{auth['entityClass']} | None, Depends(get_optional_user)]\n"
        ),
    }


def _module_files(auth: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
    from ..backend.codegen import _type
    from ..backend.pysource import Imports
    from ..integration.contract import _request_columns, _required

    entity, login, attr = auth["entityClass"], auth["loginField"], auth["loginAttr"]
    visible = [column for column in model["columns"] if not column.get("secret")]
    register = [c for c in _request_columns(model, {}) if c["apiName"] != "role"]

    dto_imports = Imports().add("pydantic", "BaseModel", "ConfigDict", "Field")
    dto_imports.add("pydantic.alias_generators", "to_camel")
    dto_imports.add("src.modules.shared.domain.entities", entity)
    enums = sorted({c["enum"]["class"] for c in [*visible, *register] if c["type"] == "enum"})
    if enums:
        dto_imports.add("src.modules.shared.domain.entities", *enums)
    register_fields = []
    for column in register:
        annotation = _type(column, dto_imports)
        if column["attr"] == attr:
            limit = column.get("maxLength") or 255
            register_fields.append(f"    {attr}: {annotation} = Field(min_length=3, max_length={limit})")
        elif _required(column):
            register_fields.append(f"    {column['attr']}: {annotation}")
        else:
            register_fields.append(f"    {column['attr']}: {annotation} | None = None")
    response_fields = [
        f"    {c['attr']}: {_type(c, dto_imports, response=True)}{' | None' if c['nullable'] else ''}" for c in visible
    ]
    camel = "    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True"
    dtos = (
        dto_imports.render()
        + f'\n\nclass RegisterRequestDto(BaseModel):\n{camel}, extra="forbid")\n\n'
        + "\n".join(register_fields)
        + "\n    password: str = Field(min_length=8, max_length=128)\n\n"
        f"    def to_entity(self, password_hash: str) -> {entity}:\n"
        f'        values = self.model_dump(exclude={{"password"}}, exclude_none=True)\n'
        f"        return {entity}(**values, password_hash=password_hash)\n"
        f'\n\nclass LoginRequestDto(BaseModel):\n{camel}, extra="forbid")\n\n'
        f"    {attr}: str\n    password: str\n"
        # the default is always sent: required in the response schema, as the contract has it (Story 22.7)
        f"\n\nclass TokenResponseDto(BaseModel):\n{camel}, json_schema_serialization_defaults_required=True)\n\n"
        '    access_token: str\n    token_type: str = "bearer"\n'
        f"\n\nclass AccountResponseDto(BaseModel):\n{camel})\n\n"
        + "\n".join(response_fields)
        + f'\n\n    @classmethod\n    def from_entity(cls, entity: {entity}) -> "AccountResponseDto":\n'
        "        return cls.model_validate(entity.model_dump())\n"
    )
    pk = next(column for column in model["columns"] if column["primaryKey"])
    return {
        f"{MODULE}/__init__.py": "",
        f"{MODULE}/ports/__init__.py": "",
        f"{MODULE}/ports/output/__init__.py": (
            "from .account_repository import IAccountRepository  # noqa: I001  (must load before the implementation)\n"
            "from src.modules.auth.infrastructure.persistence import IAccountRepoDep\n\n"
            '__all__ = ["IAccountRepository", "IAccountRepoDep"]\n'
        ),
        f"{MODULE}/ports/output/account_repository.py": (
            "from abc import ABC, abstractmethod\n\n"
            f"from src.modules.shared.domain.entities import {entity}\n\n\n"
            "class IAccountRepository(ABC):\n"
            "    @abstractmethod\n"
            f"    def find_by_login(self, login: str) -> {entity} | None:\n        pass\n\n"
            "    @abstractmethod\n"
            f"    def create(self, account: {entity}) -> {entity}:\n        pass\n"
        ),
        f"{MODULE}/infrastructure/__init__.py": "",
        f"{MODULE}/infrastructure/persistence/__init__.py": (
            'from .account_repository import IAccountRepoDep\n\n__all__ = ["IAccountRepoDep"]\n'
        ),
        f"{MODULE}/infrastructure/persistence/account_repository.py": (
            "from typing import Annotated\n\nfrom fastapi import Depends\nfrom sqlmodel import col, select\n\n"
            "from src.libs.database.session import SessionDep\n"
            "from src.modules.auth.ports.output.account_repository import IAccountRepository\n"
            f"from src.modules.shared.domain.entities import {entity}\n"
            f"from src.modules.shared.infrastructure.models import {auth['model']}\n\n\n"
            "class AccountRepository(IAccountRepository):\n"
            "    def __init__(self, session: SessionDep):\n        self.session = session\n\n"
            f"    def find_by_login(self, login: str) -> {entity} | None:\n"
            f"        query = select({auth['model']}).where(col({auth['model']}.{attr}) == login)\n"
            "        model = self.session.exec(query).first()\n"
            f"        return {entity}.model_validate(model.model_dump()) if model else None\n\n"
            f"    def create(self, account: {entity}) -> {entity}:\n"
            f"        model = {auth['model']}(**account.model_dump(exclude_none=True))\n"
            "        self.session.add(model)\n        self.session.flush()\n"
            f"        return {entity}.model_validate(model.model_dump())\n\n\n"
            "IAccountRepoDep = Annotated[IAccountRepository, Depends(AccountRepository)]\n"
        ),
        f"{MODULE}/usecases/__init__.py": (
            "from .login_usecase import LoginUsecaseDep\nfrom .register_usecase import RegisterUsecaseDep\n\n"
            '__all__ = ["LoginUsecaseDep", "RegisterUsecaseDep"]\n'
        ),
        f"{MODULE}/usecases/register_usecase.py": (
            "from typing import Annotated\n\nfrom fastapi import Depends\n\n"
            "from src.libs.decorators.transactional_decorator import Transactional\n"
            "from src.libs.exceptions import ConflictException\nfrom src.libs.security import hash_password\n"
            "from src.modules.auth.ports.output import IAccountRepoDep\n"
            "from src.modules.auth.presenter.dtos import AccountResponseDto, RegisterRequestDto\n\n\n"
            "class RegisterUsecase:\n"
            "    def __init__(self, account_repo: IAccountRepoDep):\n        self.account_repo = account_repo\n\n"
            "    @Transactional\n"
            "    async def execute(self, dto: RegisterRequestDto) -> AccountResponseDto:\n"
            f"        if self.account_repo.find_by_login(dto.{attr}) is not None:\n"
            "            raise ConflictException(\n"
            f'                "An account with this {login} already exists", details={{"fields": ["{login}"]}}\n'
            "            )\n"
            "        account = self.account_repo.create(dto.to_entity(hash_password(dto.password)))\n"
            "        return AccountResponseDto.from_entity(account)\n\n\n"
            "RegisterUsecaseDep = Annotated[RegisterUsecase, Depends(RegisterUsecase)]\n"
        ),
        f"{MODULE}/usecases/login_usecase.py": (
            "from typing import Annotated\n\nfrom fastapi import Depends\n\n"
            "from src.libs.exceptions import UnauthorizedException\n"
            "from src.libs.security import create_access_token, verify_password\n"
            "from src.modules.auth.ports.output import IAccountRepoDep\n"
            "from src.modules.auth.presenter.dtos import LoginRequestDto, TokenResponseDto\n\n\n"
            "class LoginUsecase:\n"
            "    def __init__(self, account_repo: IAccountRepoDep):\n        self.account_repo = account_repo\n\n"
            "    async def execute(self, dto: LoginRequestDto) -> TokenResponseDto:\n"
            f"        account = self.account_repo.find_by_login(dto.{attr})\n"
            "        if account is None or not verify_password(dto.password, account.password_hash):\n"
            f'            raise UnauthorizedException("Wrong {login} or password")\n'
            f"        token = create_access_token(account.{pk['attr']}, account.role)\n"
            "        return TokenResponseDto(access_token=token)\n\n\n"
            "LoginUsecaseDep = Annotated[LoginUsecase, Depends(LoginUsecase)]\n"
        ),
        f"{MODULE}/presenter/__init__.py": 'from .router import auth_router\n\n__all__ = ["auth_router"]\n',
        f"{MODULE}/presenter/dtos/__init__.py": (
            "from .auth_dto import AccountResponseDto, LoginRequestDto, RegisterRequestDto, TokenResponseDto\n\n"
            '__all__ = ["AccountResponseDto", "LoginRequestDto", "RegisterRequestDto", "TokenResponseDto"]\n'
        ),
        f"{MODULE}/presenter/dtos/auth_dto.py": dtos,
        f"{MODULE}/presenter/router.py": (
            "from fastapi import APIRouter, Request\n\n"
            "from src.configs import config\nfrom src.libs.rate_limit import limiter\n"
            "from src.libs.security import CurrentUserDep\n"
            "from src.modules.auth.presenter.dtos import (\n    AccountResponseDto,\n    LoginRequestDto,\n"
            "    RegisterRequestDto,\n    TokenResponseDto,\n)\n"
            "from src.modules.auth.usecases import LoginUsecaseDep, RegisterUsecaseDep\n\n"
            'auth_router = APIRouter(tags=["auth"])\n\n'
            'ERROR = {"description": "Error envelope: {error: {code, message, details}}"}\n\n\n'
            '@auth_router.post(\n    "/auth/register",\n    operation_id="auth.register",\n'
            "    response_model=AccountResponseDto,\n    status_code=201,\n    responses={409: ERROR, 422: ERROR},\n)\n"
            "@limiter.limit(config.auth_rate_limit)\n"
            "async def register(\n    request: Request, body: RegisterRequestDto, usecase: RegisterUsecaseDep\n"
            ") -> AccountResponseDto:\n"
            "    return await usecase.execute(body)\n\n\n"
            '@auth_router.post(\n    "/auth/login",\n    operation_id="auth.login",\n'
            "    response_model=TokenResponseDto,\n    responses={401: ERROR, 422: ERROR},\n)\n"
            "@limiter.limit(config.auth_rate_limit)\n"
            "async def login(request: Request, body: LoginRequestDto, usecase: LoginUsecaseDep) -> TokenResponseDto:\n"
            "    return await usecase.execute(body)\n\n\n"
            '@auth_router.get(\n    "/auth/me", operation_id="auth.me", response_model=AccountResponseDto, '
            "responses={401: ERROR}\n)\n"
            "async def me(current_user: CurrentUserDep) -> AccountResponseDto:\n"
            "    return AccountResponseDto.from_entity(current_user)\n"
        ),
    }


def _test_files(auth: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
    from ..integration.contract import _request_columns, _required

    login = auth["loginField"]
    register = [c for c in _request_columns(model, {}) if c["apiName"] not in ("role", login) and _required(c)]
    extra = "".join(
        f', "{c["apiName"]}": {_literal(_sample({"type": c["type"], "values": _values(c)}, "test"))}' for c in register
    )
    value = 'f"user{next(_ACCOUNTS)}@example.com"' if "email" in login.lower() else 'f"user{next(_ACCOUNTS)}"'
    pk = next(column for column in model["columns"] if column["primaryKey"])
    role = next(column for column in model["columns"] if column["attr"] == "role")
    parse = {"uuid": "uuid.UUID(signed_in)", "integer": "int(signed_in)"}.get(pk["type"], "signed_in")
    role_value, role_import = "role", ""
    if role["type"] == "enum":
        role_value = f"{role['enum']['class']}(role)"
        role_import = f"from src.modules.shared.domain.entities import {role['enum']['class']}\n"
    return {
        "tests/auth.py": (
            '"""Story 10.2: sign a fresh account in (the tables are emptied before every test); 10.3: with a role,\n'
            'and who that was (the owner of the records a test seeds)."""\n\n'
            "import os\nimport uuid\nfrom itertools import count\n\n"
            "from sqlalchemy import create_engine\nfrom sqlmodel import Session\n\n"
            + role_import
            + f"from src.modules.shared.infrastructure.models import {auth['model']}\n\n"
            "_ACCOUNTS = count(1)\n_SIGNED_IN: dict[str, str] = {}  # the running test → the account it signed in\n"
            'PASSWORD = "correct-horse-123"\n\n\n'
            "def account(**overrides: object) -> dict:\n"
            f'    return {{"{login}": {value}, "password": PASSWORD{extra}, **overrides}}\n\n\n'
            "def sign_in(client, role: str | None = None) -> str:\n"
            '    """A fresh account (with `role`, else the default one) signed in: its bearer token."""\n'
            "    body = account()\n"
            '    registered = client.post("/auth/register", json=body)\n'
            "    assert registered.status_code == 201, registered.text\n"
            "    _SIGNED_IN.clear()\n"
            f'    _SIGNED_IN[_test()] = str(registered.json()["{pk["apiName"]}"])\n'
            "    if role is not None:\n"
            "        _set_role(role)\n"
            f'    response = client.post("/auth/login", json={{"{login}": body["{login}"], "password": PASSWORD}})\n'
            "    assert response.status_code == 200, response.text\n"
            '    return response.json()["accessToken"]\n\n\n'
            f"def current_user_id() -> {_python_type(pk)} | None:\n"
            '    """The account `sign_in` signed in last in this test, if any."""\n'
            "    signed_in = _SIGNED_IN.get(_test())\n"
            f"    return {parse} if signed_in is not None else None\n\n\n"
            "def _test() -> str:\n"
            '    """The running test, without its phase (`setup`, `call`)."""\n'
            '    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0]\n\n\n'
            "def _set_role(role: str) -> None:\n"
            '    engine = create_engine(os.environ["DB_URL"])\n'
            "    with Session(engine) as session:\n"
            f"        account = session.get({auth['model']}, current_user_id())\n"
            "        assert account is not None\n"
            f"        account.role = {role_value}\n"
            "        session.add(account)\n"
            "        session.commit()\n"
            "    engine.dispose()\n"
        ),
        "tests/modules/auth/test_auth_api.py": (
            '"""Generated by the Fullstack Generation Agent (Story 10.2, the auth-jwt plugin)."""\n\n'
            "import datetime as dt\n\nimport jwt\n\nfrom src.configs import config\n"
            "from tests.auth import PASSWORD, account, sign_in\n\n\n"
            "def test_register_creates_an_account_without_its_password(client):\n"
            "    body = account()\n"
            '    response = client.post("/auth/register", json=body)\n'
            "    assert response.status_code == 201, response.text\n"
            f'    assert response.json()["{login}"] == body["{login}"]\n'
            '    assert "password" not in response.text.lower()\n\n\n'
            "def test_a_second_account_with_the_same_login_is_409(client):\n"
            "    body = account()\n"
            '    assert client.post("/auth/register", json=body).status_code == 201\n'
            '    response = client.post("/auth/register", json=body)\n'
            '    assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT"\n'
            f'    assert response.json()["error"]["details"]["fields"] == ["{login}"]\n\n\n'
            "def test_login_gives_a_token_that_me_accepts(client):\n"
            "    token = sign_in(client)\n"
            '    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})\n'
            "    assert response.status_code == 200, response.text\n\n\n"
            "def test_a_wrong_password_is_401(client):\n"
            "    body = account()\n"
            '    client.post("/auth/register", json=body)\n'
            f'    wrong = {{"{login}": body["{login}"], "password": PASSWORD + "x"}}\n'
            '    response = client.post("/auth/login", json=wrong)\n'
            '    assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHORIZED"\n\n\n'
            "def test_me_without_a_token_or_with_a_bad_one_is_401(client):\n"
            '    assert client.get("/auth/me").status_code == 401\n'
            '    forged = {"Authorization": "Bearer not-a-token"}\n'
            '    assert client.get("/auth/me", headers=forged).status_code == 401\n\n\n'
            "def test_an_expired_token_is_401(client):\n"
            "    sign_in(client)\n"
            "    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)\n"
            '    token = jwt.encode({"sub": "x", "exp": past}, config.jwt_secret, algorithm="HS256")\n'
            '    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401\n'
        ),
    }


def _literal(value: Any) -> str:
    return repr(value) if not isinstance(value, str) else f'"{value}"'
