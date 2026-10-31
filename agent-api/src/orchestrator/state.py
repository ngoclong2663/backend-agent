from typing import Annotated, Any, TypedDict

from src.modules.shared.domain.enums import GenerationMode, GenerationStatus, Lane, LaneStatus

NODES = (
    "validate_inputs",
    "build_contract",
    "validate_spec",
    "plan_architecture",
    "generate_database",
    "generate_backend",
    "generate_tests",
    "run_validation",
    "repair_code",
    "plan_frontend",
    "scaffold_frontend",
    "generate_assets",
    "generate_frontend",
    "validate_frontend",
    "repair_frontend",
    "integrate",
    "package_artifacts",
)
BACKEND_NODES = (
    "validate_spec",
    "plan_architecture",
    "generate_database",
    "generate_backend",
    "generate_tests",
    "run_validation",
    "repair_code",
)
FRONTEND_NODES = (
    "plan_frontend",
    "scaffold_frontend",
    "generate_assets",
    "generate_frontend",
    "validate_frontend",
    "repair_frontend",
)

# The nodes each mode's graph is built from (Stories 12.2, 13.x; 14.1 runs the two lanes in parallel).
MODE_NODES: dict[GenerationMode, tuple[str, ...]] = {
    GenerationMode.BACKEND: (*BACKEND_NODES, "package_artifacts"),
    GenerationMode.DYNAMIC: (
        "validate_inputs",
        "build_contract",
        *BACKEND_NODES[1:],
        *FRONTEND_NODES,
        "integrate",
        "package_artifacts",
    ),
    GenerationMode.STATIC: ("validate_inputs", *FRONTEND_NODES, "package_artifacts"),
}

NODE_STATUS = {
    "run_validation": GenerationStatus.VALIDATING,
    "repair_code": GenerationStatus.REPAIRING,
    "validate_frontend": GenerationStatus.VALIDATING,
    "repair_frontend": GenerationStatus.REPAIRING,
}

# Which lane a node belongs to; job-level nodes (inputs, contract, packaging) have none.
NODE_LANE: dict[str, Lane] = {
    **{node: Lane.BACKEND for node in BACKEND_NODES},
    **{node: Lane.FRONTEND for node in FRONTEND_NODES},
    "integrate": Lane.INTEGRATION,
}


def status_for(node: str) -> GenerationStatus:
    return NODE_STATUS.get(node, GenerationStatus.RUNNING)


def lane_status_for(node: str) -> LaneStatus:
    return LaneStatus(status_for(node).value)


class Outcome:
    COMPLETED = "completed"
    SPEC_INVALID = "spec_invalid"
    REPAIR_LIMIT = "repair_limit"


def _latest_commit(current: str | None, update: str | None) -> str | None:
    return update or current


class GenerationState(TypedDict, total=False):
    """Checkpointed graph state: identifiers and references only — files live in the workspace."""

    generation_id: str
    mode: str
    spec_id: str | None
    frontend_spec_id: str | None
    engine: str
    options: dict[str, Any]
    workspace: str
    spec_valid: bool
    spec_ref: str | None
    frontend_ref: str | None
    contract_ref: str | None
    plan_ref: str | None
    repair_attempts: int
    max_repair_attempts: int
    validation: dict[str, str]
    failed_checks: list[str]
    failure_digest_ref: str | None
    implicated_files: list[str]
    error_summary: str | None
    artifact_ids: dict[str, str]
    last_commit: str | None
    outcome: str | None
    # frontend lane (Epic 13)
    frontend_plan_ref: str | None
    frontend_repair_attempts: int
    frontend_validation: dict[str, str]
    frontend_failed_checks: list[str]
    frontend_digest_ref: str | None
    frontend_implicated_files: list[str]
    frontend_last_commit: Annotated[str | None, _latest_commit]
    cached_components: list[str]  # Story 17.3: cache keys this job took from the component cache
    evicted_components: list[str]  # … and the ones it evicted because they broke the site
    asset_fallbacks: list[dict[str, str]]  # Story 15.3: drawings shown as placeholders (id, reason)
    backend_error: str | None
    # integration lane (Epic 14)
    integration: dict[str, Any]
    integration_reason: str | None


class BackendLaneOutput(TypedDict, total=False):
    """State keys written exclusively by the backend lane when running in parallel with the frontend lane."""

    plan_ref: str | None
    repair_attempts: int
    validation: dict[str, str]
    failed_checks: list[str]
    failure_digest_ref: str | None
    implicated_files: list[str]
    last_commit: str | None
    backend_error: str | None


class FrontendLaneOutput(TypedDict, total=False):
    """State keys written exclusively by the frontend lane when running in parallel with the backend lane."""

    frontend_plan_ref: str | None
    frontend_repair_attempts: int
    frontend_validation: dict[str, str]
    frontend_failed_checks: list[str]
    frontend_digest_ref: str | None
    frontend_implicated_files: list[str]
    frontend_last_commit: Annotated[str | None, _latest_commit]
    cached_components: list[str]
    evicted_components: list[str]
    asset_fallbacks: list[dict[str, str]]
    outcome: str | None
    error_summary: str | None
