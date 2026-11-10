from typing import Any

from .naming import table_name, to_camel, to_kebab
from .schema_v1 import BackendSpecV1, Entity, JobTrigger, Operation, Pagination


def default_foreign_key(parent_entity: str) -> str:
    return f"{to_camel(parent_entity)}Id"


def owning_entity(operation: Operation, entities: list[Entity]) -> str | None:
    """The entity a custom operation without `entity` belongs to: the one its operationId starts with
    (`booking.create`), else the one whose table its path starts with (`/classes/today`). Operations are planned per
    entity, so one without an entity would be left out of the backend and the contract."""
    prefix = operation.operation_id.split(".")[0].lower()
    segment = operation.path.strip("/").split("/")[0].replace("-", "_").lower()
    by_name = next((entity.name for entity in entities if entity.name.lower() == prefix), None)
    by_path = next((entity.name for entity in entities if (entity.table or table_name(entity.name)) == segment), None)
    return by_name or by_path


def normalize_spec(spec: BackendSpecV1) -> dict[str, Any]:
    """Fills implicit defaults so later stages (planner, prompts, manifest) never re-derive them."""
    normalized = spec.model_copy(deep=True)
    normalized.project.slug = normalized.project.slug or to_kebab(normalized.project.name)
    for entity in normalized.entities:
        entity.table = entity.table or table_name(entity.name)
        for field in entity.fields:
            if field.nullable is None:
                field.nullable = not (field.required or field.primary)
    for relationship in normalized.relationships:
        if relationship.type != "many-to-many" and relationship.foreign_key is None:
            relationship.foreign_key = default_foreign_key(relationship.from_)
    for operation in normalized.operations:
        operation.auth = operation.auth or "none"
        if operation.type == "custom" and operation.entity is None:
            operation.entity = owning_entity(operation, normalized.entities)
        if (operation.action == "list" and operation.pagination is None) or operation.pagination is True:
            # Story 25.1: `true` on any operation (a custom list too) means the default limits
            operation.pagination = Pagination()
        elif operation.pagination is False:
            operation.pagination = None
    for job in [*normalized.background_jobs, *normalized.emails]:  # Story 10.6: `cron:0 2 * * *` → {"cron": …}
        if isinstance(job.trigger, str):
            kind, _, value = job.trigger.partition(":")
            if kind in ("cron", "event", "operation") and value:
                job.trigger = JobTrigger(**{kind: value.strip()})
    data = normalized.model_dump(by_alias=True, mode="json", exclude_none=True)
    if not data.get("features"):  # Epic 33: only specs with merged features carry the block
        data.pop("features", None)
    return data
