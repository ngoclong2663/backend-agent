"""File storage as a plugin (Story 10.5): `file` and `image` fields hold an object key in an S3-compatible bucket.

A client asks `POST /files/presign` (the plugin's `files` module) for an upload URL for one field, PUTs the file there,
then sends the key in the create or update body. The use case checks the key (pre-check hook): uploaded under the
field's prefix (and the caller's folder when the record has an owner), an allowed type, not too large. Responses add a
signed read URL per file field (`<field>Url`, response-fields hook). At startup the app creates its bucket and the CORS
rule that lets the app's origins upload (app-startup hook).

Locally every sandbox and preview reaches one shared store (`src/sandbox/object_store.py`) in its own bucket.
"""

from typing import Any

from src.modules.shared.domain.backend_spec.media import (
    SAMPLE_EXTENSION,
    is_file_kind,
    media_tracks,
    sample_content_type,
)

from .base import AppStartup, CaseContext, Code, Plugin, ResponseField, RouterParam, Setting

MODULE = "src/modules/files"
LIB = "src.libs.storage"
CATALOG = "src.libs.storage.catalog"
ERRORS = [
    {"status": 400, "exception": "BadRequestException", "code": "FILE_NOT_FOUND"},
    {"status": 422, "exception": None, "code": "FILE_TYPE_NOT_ALLOWED"},
    {"status": 422, "exception": None, "code": "FILE_TOO_LARGE"},
]
MESSAGES = {
    "FILE_NOT_FOUND": "No file was uploaded for the field under this key (upload it first: files.presign)",
    "FILE_TYPE_NOT_ALLOWED": "The field does not take this type of file",
    "FILE_TOO_LARGE": "The file is larger than the field allows",
}


def file_columns(model: dict[str, Any]) -> list[dict[str, Any]]:
    return [column for column in model["columns"] if column.get("file")]


def _rules(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(`Entity.field`, model, column) per file field, in model order."""
    return [
        (f"{model['entity']}.{column['apiName']}", model, column)
        for model in plan["models"]
        if model.get("entity")
        for column in file_columns(model)
    ]


def _model(plan: dict[str, Any], module: dict[str, Any]) -> dict[str, Any]:
    return next(m for m in plan["models"] if m.get("entity") == module["entity"])


def outside_url(value: object) -> bool:
    """A seeded file value that is a link to an outside file (a demo photo) instead of an object key: records keep and
    show it as it is; the smoke calls send the key code would have given that row (`_stand_in`)."""
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _stand_in(plan: dict[str, Any], fixtures: dict[str, Any], found: dict[str, Any], url: str) -> str:
    """The key `build_fixtures` gives a seed row without a file value (`<prefix>/<owner or shared>/seed/<n>.png`),
    for the row whose value is `url`."""
    model = next(m for m in plan["models"] if m.get("entity") == found["entity"])
    owner = next((c["apiName"] for c in model["columns"] if c.get("source") == "currentUser"), None)
    rows = fixtures.get(found["entity"]) or []
    index = next((i for i, row in enumerate(rows) if row.get(found["field"]) == url), 0)
    folder = (rows[index].get(owner) if owner and rows else None) or "shared"
    extension = SAMPLE_EXTENSION.get(found["kind"], "pdf")  # Epic 29: the kind's sample
    return f"{found['prefix']}/{folder}/seed/{index + 1}.{extension}"


def _object_type(found: dict[str, Any], key: str) -> str:
    """The content type a seeded object is uploaded with: the key's own extension when a sample has it (a `.ja.vtt`
    track), else the kind's sample type."""
    content = sample_content_type(found["kind"], found["accept"])
    if key.endswith(".vtt"):
        return "text/vtt"
    if key.endswith(".srt"):
        return "application/x-subrip"
    return content


def _owned(op: dict[str, Any]) -> bool:
    """The use case knows the caller and the record has an owner: keys must be in the caller's folder."""
    return bool((op.get("auth") or {}).get("ownership") or op.get("ownerSource"))


class StoragePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="storage")

    def applies(self, spec: dict[str, Any]) -> bool:
        return any(is_file_kind(field.get("type")) for entity in spec.get("entities", []) for field in entity["fields"])

    # -- the plan -------------------------------------------------------------------------------------------------

    def plan(self, plan: dict[str, Any], spec: dict[str, Any]) -> None:
        secured = (spec.get("auth") or {}).get("type") == "jwt"
        for *_, column in _rules(plan):
            column["ruled"] = True  # the generic update test changes another field
        for module in plan["modules"]:
            if module.get("plugin") or not file_columns(_model(plan, module)):
                continue
            for op in module["operations"]:
                if op.get("action") in ("create", "update"):
                    op["errors"] += [error for error in ERRORS if error not in op["errors"]]
                    if op["action"] == "create":
                        module["tests"] += [
                            _test(op, "upload_missing", 400, "a key nothing was uploaded under is refused"),
                            _test(op, "upload_wrong_type", 422, "a file of a type the field does not take"),
                            _test(op, "upload_too_large", 422, "a file larger than the field allows"),
                        ]
        presign = {
            "operationId": "files.presign",
            "type": "plugin",
            "action": None,
            "method": "POST",
            "path": "/files/presign",
            "handler": "presign_upload",
            "status": 200,
            "transactional": False,
            "errors": [{"status": 404, "exception": "NotFoundException", "code": "NOT_FOUND"}]
            + [{**error, "exception": None} for error in ERRORS[1:]]
            + [{"status": 422, "exception": None, "code": "VALIDATION_ERROR"}],
        }
        if secured:
            presign["auth"] = {"auth": "jwt", "policy": None}
        plan["modules"].append(
            {
                "name": "files",
                "entity": None,
                "plugin": self.name,
                "port": {"interface": None, "dep": None, "methods": []},
                "usecases": [],
                "dtoFiles": [f"{MODULE}/presenter/dtos/presign_dto.py"],
                "router": {
                    "variable": "files_router",
                    "file": f"{MODULE}/presenter/router.py",
                    "prefix": "",
                    "tag": "files",
                },
                "operations": [presign],
                "recordActions": [],
                "testFile": "tests/modules/files/test_files_api.py",
                "tests": [],
            }
        )
        plan["routers"]["order"].append("files_router")
        plan["storage"] = {
            "presign": "files.presign",
            "fields": [
                {"name": name, "entity": model["entity"], "field": column["apiName"], **column["file"]}
                for name, model, column in _rules(plan)
            ],
        }

    # -- the contract ---------------------------------------------------------------------------------------------

    def contract(self, contract: dict[str, Any], plan: dict[str, Any], spec: dict[str, Any]) -> None:
        from ..integration.contract import contract_operations, resolve

        meta = contract["x-bga"]
        schemas = contract["components"]["schemas"]
        fields = {(f["entity"], f["field"]): f for f in plan["storage"]["fields"]}
        for entry in contract_operations(contract).values():
            operation = entry["operation"]
            entity = (operation.get("x-bga") or {}).get("entity")
            body = (operation.get("requestBody") or {}).get("content", {}).get("application/json", {})
            schema = resolve(contract, body.get("schema")) if body.get("schema") else None
            for name, prop in ((schema or {}).get("properties") or {}).items():
                found = fields.get((entity, name))
                if found:  # where the value comes from: an upload through files.presign
                    prop["x-bga"] = {
                        "source": "upload",
                        "upload": {
                            "presign": "files.presign",
                            "entity": entity,
                            "field": name,
                            "kind": found["kind"],
                            "accept": found["accept"],
                            "maxSize": found["maxSize"],
                        },
                    }
            scenarios = (operation.get("x-bga") or {}).get("scenarios") or []
            for scenario in scenarios:  # a call sends a key, never a seed's outside URL (uploads take keys only)
                body_values = scenario.get("body")
                for (owner, name), found in fields.items():
                    if owner == entity and isinstance(body_values, dict) and outside_url(body_values.get(name)):
                        body_values[name] = _stand_in(plan, meta["fixtures"], found, body_values[name])
            success = next((s for s in scenarios if s["name"] == "success" and isinstance(s.get("body"), dict)), None)
            if success and (operation.get("x-bga") or {}).get("action") == "create":
                for (owner, name), found in fields.items():
                    if owner == entity and name in success["body"]:  # a key nothing was uploaded under
                        missing = f"{found['prefix']}/shared/missing/nothing.png"
                        scenarios.append({"name": f"{name} not uploaded", "params": success["params"],
                                          **({"user": success["user"]} if success.get("user") else {}),
                                          "body": {**success["body"], name: missing},
                                          "expect": {"status": 400, "code": "FILE_NOT_FOUND"}})  # fmt: skip
            for error in (operation.get("x-bga") or {}).get("errors", []):
                if error["code"] in MESSAGES:
                    error["message"] = MESSAGES[error["code"]]
                    names = [f for (e, f) in fields if e == entity]
                    if names:
                        error["fields"] = names
        for entity in {e for e, _ in fields}:  # responses: a signed URL per file field
            response = schemas.get(f"{entity}Response")
            if response is None:
                continue
            for owner, name in fields:
                if owner != entity:
                    continue
                response["properties"][f"{name}Url"] = {
                    "type": ["string", "null"],
                    "format": "uri",
                    "x-bga": {"source": "server", "file": name},
                }
                response["required"] = [*response.get("required", []), f"{name}Url"]
            info = meta["entities"].get(entity)
            if info is not None:
                info["fileFields"] = [
                    {"field": name, "urlField": f"{name}Url", "kind": found["kind"]}
                    for (owner, name), found in fields.items()
                    if owner == entity
                ]
        self._presign_operation(contract, plan)
        objects = []
        for (entity, name), found in fields.items():  # what the smoke check uploads first, so the keys exist
            for row in meta["fixtures"].get(entity) or []:
                if row.get(name):
                    key = _stand_in(plan, meta["fixtures"], found, row[name]) if outside_url(row[name]) else row[name]
                    objects.append({"key": key, "contentType": _object_type(found, key)})
        # Epic 29 (D3): the subtitle tracks of each media field, in both shapes, so the players find them
        meta["storage"] = {"presign": "files.presign", "objects": objects, "tracks": media_tracks(spec)}

    @staticmethod
    def _presign_operation(contract: dict[str, Any], plan: dict[str, Any]) -> None:
        schemas = contract["components"]["schemas"]
        schemas["PresignRequest"] = {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "x-bga": {"source": "server"}},
                "field": {"type": "string", "x-bga": {"source": "server"}},
                "contentType": {"type": "string", "x-bga": {"source": "upload"}},
                "size": {"type": "integer", "minimum": 1, "x-bga": {"source": "upload"}},
                "filename": {"type": "string", "x-bga": {"source": "upload"}},
            },
            "required": ["entity", "field", "contentType", "size", "filename"],
        }
        schemas["PresignResponse"] = {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "uploadUrl": {"type": "string", "format": "uri"},
                "method": {"type": "string", "enum": ["PUT"]},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "expiresIn": {"type": "integer"},
            },
            "required": ["key", "uploadUrl", "method", "headers", "expiresIn"],
        }
        error = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
        first = plan["storage"]["fields"][0]
        content = sample_content_type(first["kind"], first["accept"])
        good = {
            "entity": first["entity"],
            "field": first["field"],
            "contentType": content,
            "size": 68,
            "filename": "scenario.png",
        }
        scenarios = [
            {"name": "success", "params": {}, "body": good, "expect": {"status": 200}},
            {
                "name": "too large",
                "params": {},
                "body": {**good, "size": first["maxSize"] + 1},
                "expect": {"status": 422, "code": "FILE_TOO_LARGE"},
            },
            {
                "name": "unknown field",
                "params": {},
                "body": {**good, "field": "noSuchField"},
                "expect": {"status": 404, "code": "NOT_FOUND"},
            },
        ]
        if first["accept"]:
            scenarios.insert(
                1,
                {
                    "name": "wrong type",
                    "params": {},
                    "body": {**good, "contentType": "text/x-nope"},
                    "expect": {"status": 422, "code": "FILE_TYPE_NOT_ALLOWED"},
                },
            )
        operation: dict[str, Any] = {
            "operationId": "files.presign",
            "summary": "An upload URL for one file field",
            "tags": ["files"],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PresignRequest"}}},
            },
            "responses": {
                "200": {
                    "description": "Where to PUT the file, and the key to send in the record",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PresignResponse"}}},
                },
                "404": {"description": "NOT_FOUND", **error},
                "422": {"description": "FILE_TYPE_NOT_ALLOWED | FILE_TOO_LARGE | VALIDATION_ERROR", **error},
            },
            "x-bga": {
                "entity": None,
                "action": None,
                "module": "files",
                "plugin": "storage",
                "mock": "sample",
                "sample": {
                    "key": f"{first['prefix']}/shared/sample/file.png",
                    "uploadUrl": "https://storage.example/upload",
                    "method": "PUT",
                    "headers": {"Content-Type": content},
                    "expiresIn": 3600,
                },
                "errors": [
                    {
                        "status": 404,
                        "code": "NOT_FOUND",
                        "message": "This entity and field take no files",
                        "fields": ["field"],
                    },
                    {
                        "status": 422,
                        "code": "FILE_TYPE_NOT_ALLOWED",
                        "message": MESSAGES["FILE_TYPE_NOT_ALLOWED"],
                        "fields": ["contentType"],
                    },
                    {
                        "status": 422,
                        "code": "FILE_TOO_LARGE",
                        "message": MESSAGES["FILE_TOO_LARGE"],
                        "fields": ["size"],
                    },
                ],
                "scenarios": scenarios,
            },
        }
        presign = next(op for m in plan["modules"] if m["name"] == "files" for op in m["operations"])
        if presign.get("auth"):
            operation["security"] = [{"bearerAuth": []}]
            operation["x-bga"]["auth"] = "jwt"
            operation["responses"]["401"] = {"description": "UNAUTHORIZED", **error}
        contract["paths"]["/files/presign"] = {"post": operation}

    # -- the project ----------------------------------------------------------------------------------------------

    def settings(self, plan: dict[str, Any] | None) -> list[Setting]:
        return [
            Setting(
                "storage_endpoint",
                "str",
                '""',
                comment="S3-compatible server; empty: AWS S3",
                example="STORAGE_ENDPOINT=",
            ),
            Setting(
                "storage_public_endpoint",
                "str",
                '""',
                comment="the address browsers use; empty: the endpoint",
                example="STORAGE_PUBLIC_ENDPOINT=",
            ),
            Setting("storage_bucket", "str", '"uploads"', example="STORAGE_BUCKET="),
            Setting("storage_region", "str", '"us-east-1"', example="STORAGE_REGION="),
            Setting("storage_access_key", "str", '""', example="STORAGE_ACCESS_KEY="),
            Setting("storage_secret_key", "str", '""', example="STORAGE_SECRET_KEY="),
            Setting("storage_url_expire_seconds", "int", "3600", example="STORAGE_URL_EXPIRE_SECONDS=3600"),
        ]

    def app_startup(self, plan: dict[str, Any] | None) -> AppStartup | None:
        if not (plan or {}).get("storage"):
            return None
        return AppStartup(imports=((LIB, ("ensure_bucket",)),), lifespan=("ensure_bucket()",))

    def files(self, plan: dict[str, Any] | None) -> dict[str, str]:
        files = super().files(plan)
        if not (plan or {}).get("storage"):
            return files
        files["src/libs/storage/catalog.py"] = _catalog(plan)
        files |= _module_files(plan)
        files |= _test_files(plan)
        return files

    def router_params(self, plan, module, op) -> list[RouterParam]:
        if module.get("plugin") or op.get("action") not in ("create", "update"):
            return []
        if not any(c in file_columns(_model(plan, module)) for c in _request(plan, module, op)):
            return []
        return [
            RouterParam(
                "storage",
                "ObjectStorageDep",
                "IObjectStorage",
                ((LIB, ("ObjectStorageDep",)),),
                ((LIB, ("IObjectStorage",)),),
            )
        ]

    def prechecks(self, plan, module, op, record) -> list[Code]:
        if module.get("plugin") or op.get("action") not in ("create", "update"):
            return []
        model = _model(plan, module)
        columns = [c for c in _request(plan, module, op) if c in file_columns(model)]
        if not columns:
            return []
        owner = f", current_user.{plan['auth']['primaryKeyAttr']}" if _owned(op) and plan.get("auth") else ""
        lines, names = [], []
        for column in columns:
            name = f"{model['entity']}.{column['apiName']}"
            names.append(name)
            changed = f" and dto.{column['attr']} != {record}.{column['attr']}" if record else ""
            lines += [
                f"if dto.{column['attr']} is not None{changed}:  # uploaded for this field (Story 10.5)",
                f'    check_upload(storage, FILE_RULES["{name}"], dto.{column["attr"]}{owner})',
            ]
        return [Code(tuple(lines), ((LIB, ("check_upload",)), (CATALOG, ("FILE_RULES",))))]

    def response_fields(self, plan, module) -> list[ResponseField]:
        if module.get("plugin"):
            return []
        return [
            ResponseField(
                f"{column['attr']}_url", "str | None", f"signed_url(entity.{column['attr']})", ((LIB, ("signed_url",)),)
            )
            for column in file_columns(_model(plan, module))
        ]

    def test_case(self, plan, module, op, test, ctx: CaseContext) -> Code | None:
        case = test["case"]
        if module.get("plugin") or not case.startswith("upload_"):
            return None
        model = _model(plan, module)
        column = file_columns(model)[0]
        name = f"{model['entity']}.{column['apiName']}"
        if case == "upload_missing":
            key = f'"{column["file"]["prefix"]}/shared/missing/nothing.png"'
            code = "FILE_NOT_FOUND"
            status = 400
        elif case == "upload_wrong_type":
            if not column["file"]["accept"]:
                return Code((f"def {test['id']}(client):", "    pass  # the field takes any type"))
            key = f'uploaded("{name}", content_type="text/x-nope")'
            code, status = "FILE_TYPE_NOT_ALLOWED", 422
        else:
            key = f'uploaded("{name}", size={column["file"]["maxSize"] + 1})'
            code, status = "FILE_TOO_LARGE", 422
        return Code(
            (
                f"def {test['id']}(client):",
                f'    response = client.post("{op["path"]}", json={{**_payload(), "{column["apiName"]}": {key}}})',
                "",
                f"    assert response.status_code == {status}, response.text",
                f'    assert response.json()["error"]["code"] == "{code}"',
            ),
            (("tests.storage", ("uploaded",)),),
        )

    def engine_note(self, plan: dict[str, Any]) -> str:
        return (
            "Files (Story 10.5, `src/libs/storage`): a `file` / `image` field holds an object key. Clients upload "
            "through `POST /files/presign`; a use case that stores a key calls `check_upload(storage, "
            'FILE_RULES["Entity.field"], key)` first (`storage: ObjectStorageDep` from the route), and responses '
            "carry `<field>Url` (`signed_url(entity.field)`)."
        )


def _request(plan: dict[str, Any], module: dict[str, Any], op: dict[str, Any]) -> list[dict[str, Any]]:
    from ..integration.contract import _request_columns

    # the body's own fields (an update may leave a file field out: then there is nothing to check)
    fields = op.get("requestFields")
    return _request_columns(_model(plan, module), {} if fields is None else {"request": {"fields": fields}})


def _test(op: dict[str, Any], case: str, expect: int, description: str) -> dict[str, Any]:
    return {
        "id": f"test_{op['handler']}__{case}",
        "operationId": op["operationId"],
        "case": case,
        "expectStatus": expect,
        "description": description,
    }


def _catalog(plan: dict[str, Any]) -> str:
    lines = [
        '"""The app\'s file fields (Story 10.5), from the plan: what each takes and where its keys live."""',
        "",
        "from .uploads import FileRule",
        "",
        "FILE_RULES: dict[str, FileRule] = {",
    ]
    for name, _, column in _rules(plan):
        accept = ", ".join(f'"{mime}"' for mime in column["file"]["accept"])
        accept = f"({accept},)" if len(column["file"]["accept"]) == 1 else f"({accept})"
        lines += [
            f'    "{name}": FileRule(',
            f'        field="{column["apiName"]}",',
            f"        accept={accept},",
            f"        max_size={column['file']['maxSize']},",
            f'        prefix="{column["file"]["prefix"]}",',
            "    ),",
        ]
    return "\n".join([*lines, "}"]) + "\n"


def _module_files(plan: dict[str, Any]) -> dict[str, str]:
    auth = plan.get("auth") if any(m["name"] == "auth" for m in plan["modules"]) else None
    user = (
        ("from src.libs.security import CurrentUserDep\n", ", current_user: CurrentUserDep", ", current_user")
        if auth
        else ("", "", "")
    )
    owner_type = f"{auth['entityClass']} | None = None" if auth else ""
    return {
        f"{MODULE}/__init__.py": "",
        f"{MODULE}/usecases/__init__.py": (
            'from .presign_usecase import PresignUploadUsecaseDep\n\n__all__ = ["PresignUploadUsecaseDep"]\n'
        ),
        f"{MODULE}/usecases/presign_usecase.py": (
            "from typing import Annotated\n\nfrom fastapi import Depends\n\nfrom src.configs import config\n"
            "from src.libs.exceptions import NotFoundException\n"
            "from src.libs.storage import ObjectStorageDep, check_declared, new_key\n"
            "from src.libs.storage.catalog import FILE_RULES\n"
            + (f"from src.modules.shared.domain.entities import {auth['entityClass']}\n" if auth else "")
            + "from src.modules.files.presenter.dtos import PresignRequestDto, PresignResponseDto\n\n\n"
            "class PresignUploadUsecase:\n"
            "    def __init__(self, storage: ObjectStorageDep):\n        self.storage = storage\n\n"
            "    async def execute(\n        self, dto: PresignRequestDto"
            + (f", current_user: {owner_type}" if auth else "")
            + "\n    ) -> PresignResponseDto:\n"
            '        rule = FILE_RULES.get(f"{dto.entity}.{dto.field}")\n'
            "        if rule is None:\n"
            "            raise NotFoundException(\n"
            '                f"{dto.entity}.{dto.field} takes no files", details={"fields": ["field"]}\n'
            "            )\n"
            "        check_declared(rule, dto.content_type, dto.size)\n"
            + (
                f"        owner = current_user.{auth['primaryKeyAttr']} if current_user else None\n"
                "        key = new_key(rule, dto.filename, owner)\n"
                if auth
                else "        key = new_key(rule, dto.filename)\n"
            )
            + "        url = self.storage.presign_upload(key, dto.content_type, config.storage_url_expire_seconds)\n"
            "        return PresignResponseDto(\n"
            "            key=key,\n            upload_url=url,\n"
            '            headers={"Content-Type": dto.content_type},\n'
            "            expires_in=config.storage_url_expire_seconds,\n        )\n\n\n"
            "PresignUploadUsecaseDep = Annotated[PresignUploadUsecase, Depends(PresignUploadUsecase)]\n"
        ),
        f"{MODULE}/presenter/__init__.py": 'from .router import files_router\n\n__all__ = ["files_router"]\n',
        f"{MODULE}/presenter/dtos/__init__.py": (
            "from .presign_dto import PresignRequestDto, PresignResponseDto\n\n"
            '__all__ = ["PresignRequestDto", "PresignResponseDto"]\n'
        ),
        f"{MODULE}/presenter/dtos/presign_dto.py": (
            "from pydantic import BaseModel, ConfigDict, Field\nfrom pydantic.alias_generators import to_camel\n\n\n"
            "class PresignRequestDto(BaseModel):\n"
            '    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")\n\n'
            "    entity: str = Field(min_length=1, max_length=63)\n"
            "    field: str = Field(min_length=1, max_length=63)\n"
            "    content_type: str = Field(min_length=3, max_length=255)\n"
            "    size: int = Field(ge=1)\n"
            "    filename: str = Field(min_length=1, max_length=255)\n\n\n"
            "class PresignResponseDto(BaseModel):\n"
            "    model_config = ConfigDict(\n"
            "        alias_generator=to_camel,\n        populate_by_name=True,\n"
            "        json_schema_serialization_defaults_required=True,\n    )\n\n"
            '    key: str\n    upload_url: str\n    method: str = "PUT"\n    headers: dict[str, str]\n'
            "    expires_in: int\n"
        ),
        f"{MODULE}/presenter/router.py": (
            "from fastapi import APIRouter\n\n"
            + user[0]
            + "from src.modules.files.presenter.dtos import PresignRequestDto, PresignResponseDto\n"
            "from src.modules.files.usecases import PresignUploadUsecaseDep\n\n"
            'files_router = APIRouter(tags=["files"])\n\n'
            'ERROR = {"description": "Error envelope: {error: {code, message, details}}"}\n\n\n'
            '@files_router.post(\n    "/files/presign",\n    operation_id="files.presign",\n'
            "    response_model=PresignResponseDto,\n    responses={404: ERROR, 422: ERROR},\n)\n"
            "async def presign_upload(\n    body: PresignRequestDto, usecase: PresignUploadUsecaseDep"
            + user[1]
            + "\n) -> PresignResponseDto:\n"
            f"    return await usecase.execute(body{user[2]})\n"
        ),
    }


PNG_HEX = (
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def _test_files(plan: dict[str, Any]) -> dict[str, str]:
    first = plan["storage"]["fields"][0]
    auth = any(m["name"] == "auth" for m in plan["modules"])
    content = sample_content_type(first["kind"], first["accept"])
    signed_in = (
        "@pytest.fixture(autouse=True)\n"
        "def _signed_in(client):\n"
        '    client.headers["Authorization"] = f"Bearer {sign_in(client)}"\n'
        "    yield\n"
        '    client.headers.pop("Authorization", None)\n\n\n'
        if auth
        else ""
    )
    body = (
        f'{{"entity": "{first["entity"]}", "field": "{first["field"]}", "contentType": "{content}", '
        '"size": len(PNG), "filename": "a.png"}'
    )
    wrong_type = (
        "def test_a_type_the_field_does_not_take_is_422(client):\n"
        '    response = client.post("/files/presign", json={**BODY, "contentType": "text/x-nope"})\n\n'
        "    assert response.status_code == 422\n"
        '    assert response.json()["error"]["code"] == "FILE_TYPE_NOT_ALLOWED"\n\n\n'
        if first["accept"]
        else ""
    )
    return {
        "tests/storage.py": (
            '"""Story 10.5: files in the test bucket, as a client\'s upload leaves them."""\n\n'
            "import uuid\n\nfrom src.libs.storage import get_storage\n"
            "from src.libs.storage.catalog import FILE_RULES\n\n"
            f'PNG = bytes.fromhex(\n    "{PNG_HEX[:64]}"\n    "{PNG_HEX[64:]}"\n)\n\n\n'
            "def _owner() -> object | None:\n"
            "    try:\n        from tests.auth import current_user_id\n    except ImportError:\n        return None\n"
            "    return current_user_id()\n\n\n"
            "def uploaded(name: str, content_type: str | None = None, size: int | None = None) -> str:\n"
            '    """A key of the field `name` (`Entity.field`) with an object under it: a PNG, or `size` bytes."""\n'
            "    rule = FILE_RULES[name]\n"
            '    allowed = next((kind for kind in rule.accept if "*" not in kind), None)\n'
            '    content_type = content_type or allowed or "image/png"\n'
            "    owner = _owner()\n"
            "    key = f\"{rule.prefix}/{owner if owner is not None else 'shared'}/{uuid.uuid4().hex}/test.bin\"\n"
            '    get_storage().put(key, PNG if size is None else b"\\0" * size, content_type)\n'
            "    return key\n"
        ),
        "tests/modules/files/test_files_api.py": (
            '"""Generated by the Fullstack Generation Agent (Story 10.5, the storage plugin)."""\n\n'
            "import httpx\n" + ("import pytest\n" if auth else "") + "\n"
            "from src.libs.storage import signed_url\n"
            + ("from tests.auth import sign_in\n" if auth else "")
            + "from tests.storage import PNG\n\n"
            f"BODY = {body}\n\n\n" + signed_in + "def test_presign_upload_then_read(client):\n"
            '    response = client.post("/files/presign", json=BODY)\n\n'
            "    assert response.status_code == 200, response.text\n"
            "    upload = response.json()\n"
            f'    assert upload["key"].startswith("{first["prefix"]}/")\n'
            '    assert httpx.put(upload["uploadUrl"], content=PNG, headers=upload["headers"]).status_code == 200\n'
            '    assert httpx.get(signed_url(upload["key"])).content == PNG\n\n\n'
            + wrong_type
            + "def test_a_file_too_large_is_422(client):\n"
            f'    response = client.post("/files/presign", json={{**BODY, "size": {first["maxSize"] + 1}}})\n\n'
            "    assert response.status_code == 422\n"
            '    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"\n\n\n'
            "def test_a_field_without_files_is_404(client):\n"
            '    response = client.post("/files/presign", json={**BODY, "field": "noSuchField"})\n\n'
            "    assert response.status_code == 404\n"
        ),
    }
