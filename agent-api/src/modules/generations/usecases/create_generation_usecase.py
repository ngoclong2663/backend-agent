import json
import uuid
from typing import Annotated, Any

from fastapi import Depends
from pydantic import BaseModel

from src.libs.decorators.transactional_decorator import Transactional
from src.libs.exceptions import ErrorCode, UnprocessableEntityException
from src.libs.ids import new_generation_id
from src.libs.security import ensure_owner
from src.modules.generations.domain.attach_specs import attach_draft_specs
from src.modules.generations.infrastructure.adapters import EngineRegistryDep, EventPublisherDep, JobQueueDep, RedisDep
from src.modules.generations.ports.output import IGenerationRepoDep
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.entities import (
    BackendSpecEntity,
    FrontendSpecEntity,
    GenerationEntity,
    SpecDraftEntity,
    UserEntity,
)
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus, SpecDraftStatus, SpecSource
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.modules.shared.domain.generation_modes import initial_lanes
from src.modules.shared.domain.requirement import Requirement, validate_requirement
from src.modules.specs.ports.output import IBackendSpecRepoDep, IFrontendSpecRepoDep, ISpecDraftRepoDep
from src.modules.uploads.ports.output import IUploadRepoDep

IDEMPOTENCY_TTL_S = 24 * 3600
NEEDS_BACKEND = {GenerationMode.BACKEND, GenerationMode.DYNAMIC}
NEEDS_FRONTEND = {GenerationMode.STATIC, GenerationMode.DYNAMIC}
EXPECTED_INPUTS = {
    GenerationMode.BACKEND: "'backendSpec' or 'specId'",
    GenerationMode.STATIC: "'frontendSpec' or 'frontendSpecId'",
    GenerationMode.DYNAMIC: "one of 'frontendSpec' / 'frontendSpecId' and one of 'backendSpec' / 'specId'",
}


class RequirementInput(BaseModel):
    text: str | None = None
    format: str | None = None
    file_name: str | None = None


class GenerationInputs(BaseModel):
    mode: GenerationMode = GenerationMode.BACKEND
    requirement: RequirementInput | None = None
    backend_spec: dict[str, Any] | None = None
    spec_id: uuid.UUID | None = None
    frontend_spec: dict[str, Any] | None = None
    frontend_spec_id: uuid.UUID | None = None
    draft_id: uuid.UUID | None = None

    def check(self) -> None:
        """Story 12.2 & 19.10: exactly the inputs the mode needs, else 422 MODE_INPUT_MISMATCH."""
        if self.requirement is not None:
            if any(
                value is not None
                for value in (
                    self.backend_spec,
                    self.spec_id,
                    self.frontend_spec,
                    self.frontend_spec_id,
                    self.draft_id,
                )
            ):
                raise UnprocessableEntityException(
                    "Cannot provide both requirement and specs/draftId",
                    code=ErrorCode.MODE_INPUT_MISMATCH,
                )
            validate_requirement(
                self.requirement.text,
                self.requirement.file_name,
                self.requirement.format,  # type: ignore[arg-type]
            )
            return

        backend = [value for value in (self.backend_spec, self.spec_id) if value is not None]
        frontend = [value for value in (self.frontend_spec, self.frontend_spec_id) if value is not None]
        ok = len(backend) == (1 if self.mode in NEEDS_BACKEND else 0) and len(frontend) == (
            1 if self.mode in NEEDS_FRONTEND else 0
        )
        if not ok:
            raise UnprocessableEntityException(
                f"Mode '{self.mode}' takes exactly {EXPECTED_INPUTS[self.mode]}",
                code=ErrorCode.MODE_INPUT_MISMATCH,
            )
        declared = (self.frontend_spec or {}).get("project", {}) if isinstance(self.frontend_spec, dict) else {}
        spec_mode = declared.get("mode") if isinstance(declared, dict) else None
        if isinstance(spec_mode, str) and spec_mode != self.mode:
            raise self.mode_mismatch(spec_mode)

    def mode_mismatch(self, spec_mode: str) -> UnprocessableEntityException:
        return UnprocessableEntityException(
            f"The FrontendSpec is for a '{spec_mode}' site but the generation mode is '{self.mode}'",
            code=ErrorCode.MODE_INPUT_MISMATCH,
        )


class CreateGenerationUsecase:
    def __init__(
        self,
        generation_repo: IGenerationRepoDep,
        spec_repo: IBackendSpecRepoDep,
        frontend_spec_repo: IFrontendSpecRepoDep,
        draft_repo: ISpecDraftRepoDep,
        upload_repo: IUploadRepoDep,
        queue: JobQueueDep,
        events: EventPublisherDep,
        registry: EngineRegistryDep,
        redis: RedisDep,
    ):
        self.generation_repo = generation_repo
        self.spec_repo = spec_repo
        self.frontend_spec_repo = frontend_spec_repo
        self.draft_repo = draft_repo
        self.upload_repo = upload_repo
        self.queue = queue
        self.events = events
        self.registry = registry
        self.redis = redis

    async def execute(
        self,
        user: UserEntity,
        inputs: GenerationInputs,
        options: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> GenerationEntity:
        inputs.check()
        if options.get("deployPreview") and not options.get("generateDockerfile") and inputs.mode in NEEDS_BACKEND:
            raise UnprocessableEntityException(
                "deployPreview requires generateDockerfile", code=ErrorCode.OPTIONS_CONFLICT
            )
        engine = options.get("engine") or self.registry.default
        if engine not in self.registry.code_engine_names():
            raise UnprocessableEntityException(f"Engine '{engine}' cannot generate code", code=ErrorCode.ENGINE_UNKNOWN)
        # The fake engine drafts for itself (its drafts are bundled examples); others use the draft default.
        draft_engine = options.get("draftEngine") or ("fake" if engine == "fake" else self.registry.draft_default)
        draft_engine = self.registry.check_draft_engine(draft_engine)  # Story 22.8: API engines (or the fake) only
        options = {**options, "engine": engine, "draftEngine": draft_engine}
        if inputs.mode in NEEDS_FRONTEND:
            options["frontend"] = options.get("frontend") or {
                "runTests": True,
                "generatePreview": True,
                "mockApi": True,
            }
        else:
            options.pop("frontend", None)

        idempotency_redis_key = f"bga:idem:{user.id}:{idempotency_key}" if idempotency_key else None
        if idempotency_redis_key:
            existing_id = await self.redis.get(idempotency_redis_key)
            existing = self.generation_repo.find_by_id(existing_id) if existing_id else None
            if existing is not None:
                return existing

        if inputs.requirement is not None:
            req = validate_requirement(
                inputs.requirement.text,
                inputs.requirement.file_name,
                inputs.requirement.format,  # type: ignore[arg-type]
            )
            draft_id = uuid.uuid4()
            gen_id = new_generation_id()
            options = {**options, "draftId": str(draft_id), "autoGenerate": True}
            generation = await self._persist_from_requirement(
                user, inputs, options, engine, gen_id, draft_id, req, draft_engine
            )
            if idempotency_redis_key:
                await self.redis.set(idempotency_redis_key, generation.id, ex=IDEMPOTENCY_TTL_S, nx=True)
            # Queued draft, not generation:
            await self.queue.enqueue_draft(str(draft_id), draft_engine)
            await self.events.publish(
                generation.id,
                "status.changed",
                status=generation.status,
                payload={"engine": engine, "mode": generation.mode, "lanes": generation.lanes},
            )
            return generation

        generation = await self._persist(user, inputs, options, engine)
        if idempotency_redis_key:
            await self.redis.set(idempotency_redis_key, generation.id, ex=IDEMPOTENCY_TTL_S, nx=True)
        # Enqueued only after the commit, so the worker can always see the row it is handed.
        await self.queue.enqueue(generation.id, generation.engine)
        await self.events.publish(
            generation.id,
            "status.changed",
            status=generation.status,
            payload={"engine": engine, "mode": generation.mode, "lanes": generation.lanes},
        )
        return generation

    @Transactional
    async def _persist_from_requirement(
        self,
        user: UserEntity,
        inputs: GenerationInputs,
        options: dict[str, Any],
        engine: str,
        gen_id: str,
        draft_id: uuid.UUID,
        req: Requirement,
        draft_engine: str,
    ) -> GenerationEntity:
        generation = self.generation_repo.create(
            GenerationEntity(
                id=gen_id,
                owner_id=user.id,
                mode=inputs.mode,
                status=GenerationStatus.DRAFTING,
                spec_id=None,
                frontend_spec_id=None,
                lanes=initial_lanes(inputs.mode),
                options=options,
                engine=engine,
            )
        )
        self.draft_repo.create(
            SpecDraftEntity(
                id=draft_id,
                owner_id=user.id,
                source=SpecSource.REQUIREMENT,
                mode=inputs.mode,
                requirement_text=req.text,
                requirement_format=req.format,
                requirement_file_name=req.file_name,
                engine=draft_engine,
                status=SpecDraftStatus.PENDING,
                generation_id=gen_id,
                inputs={  # Epic 26 D7 / Epic 24: the business layer and its provider, and the draft's speed
                    key: options[key]
                    for key in ("businessWorkflows", "llmProvider", "draftSpeed", "designThemes")
                    if options.get(key) is not None
                },
            )
        )
        return generation

    @Transactional
    async def _persist(self, user, inputs: GenerationInputs, options, engine) -> GenerationEntity:
        draft = self._draft(user, inputs)
        if draft is not None:
            options = {**options, "draftId": str(draft.id)}
        generation = self.generation_repo.create(
            GenerationEntity(
                id=new_generation_id(),
                owner_id=user.id,
                mode=inputs.mode,
                lanes=initial_lanes(inputs.mode),
                options=options,
                engine=engine,
            )
        )
        if draft is not None:
            # Explicit `specId` / `frontendSpecId` win over the draft's specs (as without a draft).
            given_backend = inputs.mode in NEEDS_BACKEND and inputs.spec_id is not None
            given_frontend = inputs.mode in NEEDS_FRONTEND and inputs.frontend_spec_id is not None
            return attach_draft_specs(
                generation.id,
                draft,
                self.generation_repo,
                self.spec_repo,
                self.frontend_spec_repo,
                self.upload_repo,
                backend_spec_data=inputs.backend_spec,
                frontend_spec_data=inputs.frontend_spec,
                is_admin=user.is_admin,
                backend_entity=self._backend_spec(user, inputs, draft) if given_backend else None,
                frontend_entity=self._frontend_spec(user, inputs, draft) if given_frontend else None,
                draft_repo=self.draft_repo,
            )
        backend = self._backend_spec(user, inputs, None) if inputs.mode in NEEDS_BACKEND else None
        frontend = self._frontend_spec(user, inputs, None) if inputs.mode in NEEDS_FRONTEND else None
        return self.generation_repo.update(
            generation.id,
            spec_id=backend.id if backend else None,
            frontend_spec_id=frontend.id if frontend else None,
        )

    def _draft(self, user: UserEntity, inputs: GenerationInputs) -> SpecDraftEntity | None:
        """The finished draft the inline specs were edited from; its requirement goes with the specs."""
        if inputs.draft_id is None:
            return None
        draft = self.draft_repo.find_by_id(inputs.draft_id)
        if draft is None:
            raise UnprocessableEntityException("draftId does not exist", code=ErrorCode.VALIDATION_ERROR)
        ensure_owner(draft.owner_id, user.id, user.is_admin, resource="Draft")
        if draft.status not in (SpecDraftStatus.SUCCEEDED, SpecDraftStatus.NEEDS_REVIEW):
            raise UnprocessableEntityException(f"The draft is {draft.status}", code=ErrorCode.VALIDATION_ERROR)
        if draft.mode != inputs.mode:
            raise UnprocessableEntityException(
                f"The draft is for mode '{draft.mode}' but the generation mode is '{inputs.mode}'",
                code=ErrorCode.MODE_INPUT_MISMATCH,
            )
        return draft

    @staticmethod
    def _origin(draft: SpecDraftEntity | None) -> dict[str, Any]:
        if draft is None or draft.source != SpecSource.REQUIREMENT:
            return {"source": SpecSource.JSON}
        return {"source": SpecSource.REQUIREMENT, "requirement_text": draft.requirement_text}

    def _backend_spec(
        self, user: UserEntity, inputs: GenerationInputs, draft: SpecDraftEntity | None = None
    ) -> BackendSpecEntity:
        if inputs.spec_id is not None:
            spec = self.spec_repo.find_by_id(inputs.spec_id)
            if spec is None:
                raise UnprocessableEntityException("specId does not exist", code=ErrorCode.VALIDATION_ERROR)
            ensure_owner(spec.owner_id, user.id, user.is_admin, resource="BackendSpec")
            return spec
        # Invalid inline specs are accepted on purpose: the first node reports them as a FAILED job.
        backend_spec = inputs.backend_spec
        result = validate_spec_data(backend_spec)
        version = backend_spec.get("specVersion")
        return self.spec_repo.create(
            BackendSpecEntity(
                owner_id=user.id,
                spec_version=version if isinstance(version, str) else "unknown",
                raw_json=json.dumps(backend_spec, ensure_ascii=False, indent=2),
                normalized_json=result.normalized,
                **self._origin(draft),
            )
        )

    def _frontend_spec(
        self, user: UserEntity, inputs: GenerationInputs, draft: SpecDraftEntity | None = None
    ) -> FrontendSpecEntity:
        if inputs.frontend_spec_id is not None:
            spec = self.frontend_spec_repo.find_by_id(inputs.frontend_spec_id)
            if spec is None:
                raise UnprocessableEntityException("frontendSpecId does not exist", code=ErrorCode.VALIDATION_ERROR)
            ensure_owner(spec.owner_id, user.id, user.is_admin, resource="FrontendSpec")
            if spec.mode is not None and spec.mode != inputs.mode:
                raise inputs.mode_mismatch(spec.mode)
            self._check_uploads(user, json.loads(spec.raw_json))
            return spec
        frontend_spec = inputs.frontend_spec
        self._check_uploads(user, frontend_spec)
        result = validate_frontend_spec_data(frontend_spec)
        version = frontend_spec.get("specVersion")
        return self.frontend_spec_repo.create(
            FrontendSpecEntity(
                owner_id=user.id,
                spec_version=version if isinstance(version, str) else "unknown",
                mode=result.normalized["project"]["mode"] if result.normalized else None,
                raw_json=json.dumps(frontend_spec, ensure_ascii=False, indent=2),
                normalized_json=result.normalized,
                **self._origin(draft),
            )
        )

    def _check_uploads(self, user: UserEntity, frontend_spec: Any) -> None:
        """Story 15.4: every `upload:<id>` asset is one of the user's uploads (FE_UNKNOWN_UPLOAD)."""
        assets = frontend_spec.get("assets") if isinstance(frontend_spec, dict) else None
        issues = []
        for index, asset in enumerate(assets if isinstance(assets, list) else []):
            source = asset.get("source") if isinstance(asset, dict) else None
            if not isinstance(source, str) or not source.startswith("upload:"):
                continue
            upload = self.upload_repo.find(source.removeprefix("upload:"))
            if upload is None or (upload.owner_id != user.id and not user.is_admin):
                issues.append(
                    {
                        "code": "FE_UNKNOWN_UPLOAD",
                        "path": f"/assets/{index}/source",
                        "message": f"'{source}' is not one of your uploads",
                        "severity": "error",
                    }
                )
        if issues:
            raise UnprocessableEntityException(
                "The FrontendSpec uses uploads that do not exist", code=ErrorCode.SPEC_INVALID, details=issues
            )


CreateGenerationUsecaseDep = Annotated[CreateGenerationUsecase, Depends(CreateGenerationUsecase)]
