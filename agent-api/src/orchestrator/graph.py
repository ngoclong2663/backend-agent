import asyncio
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.modules.shared.domain.enums import GenerationMode, LaneStatus
from src.sandbox import SandboxError

from . import tracing
from .context import BackendLaneAborted, EngineFailure, JobCancelled, JobContext
from .nodes import NODE_FUNCTIONS
from .state import (
    BACKEND_NODES,
    FRONTEND_NODES,
    MODE_NODES,
    BackendLaneOutput,
    FrontendLaneOutput,
    GenerationState,
)

ATTEMPT_NODES = {"run_validation", "repair_code", "validate_frontend", "repair_frontend"}
BACKEND_LANE_NODES = (
    "plan_architecture",
    "generate_database",
    "generate_backend",
    "generate_tests",
    "run_validation",
    "repair_code",
)
FRONTEND_LANE_NODES = (
    "plan_frontend",
    "scaffold_frontend",
    "generate_assets",
    "generate_frontend",
    "validate_frontend",
    "repair_frontend",
)
NODE_COMMIT_PATHS: dict[str, list[str]] = {
    "generate_assets": [
        "src/assets",
        "src/components/assets",
        "public/assets",
    ],
    "generate_frontend": [
        ":!src/assets",
        ":!src/components/assets",
        ":!public/assets",
    ],
}
# State that goes into a node span: identifiers and refs only (Story 8.1); files stay in the workspace.
TRACED_STATE = (
    "spec_ref",
    "frontend_ref",
    "contract_ref",
    "plan_ref",
    "repair_attempts",
    "frontend_plan_ref",
    "frontend_repair_attempts",
    "failed_checks",
    "implicated_files",
    "validation",
)


def route_after_spec(state: GenerationState) -> str:
    return "valid" if state.get("spec_valid") else "invalid"


def route_after_validation(state: GenerationState) -> str:
    if state.get("backend_error"):
        return "repair limit reached"
    if not state.get("failed_checks"):
        return "passed"
    if state.get("repair_attempts", 0) < state["max_repair_attempts"]:
        return "failed"
    return "repair limit reached"


def route_after_frontend_validation(state: GenerationState) -> str:
    if not state.get("frontend_failed_checks"):
        return "passed"
    if state.get("frontend_repair_attempts", 0) < state["max_repair_attempts"]:
        return "failed"
    return "repair limit reached"


def route_after_frontend_lane(state: GenerationState) -> str:
    return "passed" if not state.get("frontend_failed_checks") else "repair limit reached"


def _attempt(name: str, state: GenerationState) -> int:
    if name in ("validate_frontend", "repair_frontend"):
        return state.get("frontend_repair_attempts", 0) + 1
    return state.get("repair_attempts", 0) + 1 if name in ATTEMPT_NODES else 1


def _node(name: str, ctx: JobContext | None):
    fn = NODE_FUNCTIONS[name]

    async def run(state: GenerationState) -> dict[str, Any]:
        if (
            ctx is not None
            and ctx.mode == GenerationMode.DYNAMIC
            and name in BACKEND_NODES
            and ctx.backend_aborted_reason
        ):
            if not ctx.frontend_failed:
                await ctx.set_lane("backend", LaneStatus.FAILED, reason=ctx.backend_aborted_reason)
            return {"backend_error": ctx.backend_aborted_reason}
        attempt = _attempt(name, state)
        span_name = f"{name}#{attempt}" if name in ATTEMPT_NODES else name
        refs = {key: state.get(key) for key in TRACED_STATE if state.get(key) is not None}
        with tracing.span(
            span_name, inputs={"attempt": attempt, **refs}, metadata={"node": name, "attempt": attempt}
        ) as span:
            try:
                run_id = await ctx.enter_node(name, attempt)
            except BackendLaneAborted as exc:
                span.end(outputs={"status": "cancelled", "reason": exc.reason}, error=exc.reason)
                if not ctx.frontend_failed:
                    await ctx.set_lane("backend", LaneStatus.FAILED, reason=exc.reason)
                return {"backend_error": exc.reason}
            try:
                update, summary = await fn(state, ctx)
            except JobCancelled:
                await ctx.leave_node(name, run_id, "cancelled", {})
                raise
            except BackendLaneAborted as exc:
                await ctx.leave_node(name, run_id, "cancelled", {"reason": exc.reason})
                span.end(outputs={"status": "cancelled", "reason": exc.reason}, error=exc.reason)
                if not ctx.frontend_failed:
                    await ctx.set_lane("backend", LaneStatus.FAILED, reason=exc.reason)
                return {"backend_error": exc.reason}
            except asyncio.CancelledError:
                if ctx.cancel_requested.is_set():
                    await asyncio.shield(ctx.leave_node(name, run_id, "cancelled", {}))
                raise
            except (EngineFailure, SandboxError) as exc:
                reason = str(exc)[:500]
                await ctx.leave_node(name, run_id, "failed", {"error": reason})
                span.end(outputs={"status": "failed", "error": reason}, error=reason)
                if ctx.mode == GenerationMode.DYNAMIC and name in BACKEND_NODES:
                    if not ctx.frontend_failed:
                        await ctx.set_lane("backend", LaneStatus.FAILED, reason=reason)
                    return {"backend_error": reason}
                if ctx.mode == GenerationMode.DYNAMIC and name in FRONTEND_NODES:
                    await ctx.set_lane("frontend", LaneStatus.FAILED, reason=reason)
                    await ctx.abort_backend("frontend lane failed", frontend_failed=True)
                raise
            except Exception as exc:
                reason = str(exc)[:500]
                await ctx.leave_node(name, run_id, "failed", {"error": reason})
                if ctx.mode == GenerationMode.DYNAMIC and name in FRONTEND_NODES:
                    await ctx.set_lane("frontend", LaneStatus.FAILED, reason=reason)
                    await ctx.abort_backend("frontend lane failed", frontend_failed=True)
                raise
            # The commit is the recovery point: a resumed job resets the repository to it.
            frontend = name in FRONTEND_NODES and ctx.workspace.frontend.joinpath(".git").exists()
            repo = "frontend" if frontend else "project"
            paths = NODE_COMMIT_PATHS.get(name)
            async with ctx._commit_lock:
                sha = ctx.workspaces.commit(ctx.workspace, f"node:{name} attempt:{attempt}", repo=repo, paths=paths)
                ctx.workspaces.check_size(ctx.workspace)
                if name in ("repair_code", "repair_frontend"):
                    summary["diffStats"] = ctx.workspaces.head_stats(ctx.workspace, repo=repo)
            status = summary.pop("_status", "succeeded")
            await ctx.leave_node(name, run_id, status, summary)
            span.end(outputs={"status": status, **summary}, error=f"{name} {status}" if status == "failed" else None)
            return {**update, "frontend_last_commit" if frontend else "last_commit": sha}

    run.__name__ = name
    return run


def _backend_subgraph(ctx: JobContext | None) -> StateGraph:
    sub = StateGraph(GenerationState, output_schema=BackendLaneOutput)
    for name in BACKEND_LANE_NODES:
        sub.add_node(name, _node(name, ctx))
    sub.add_edge(START, "plan_architecture")
    for source, target in (
        ("plan_architecture", "generate_database"),
        ("generate_database", "generate_backend"),
        ("generate_backend", "generate_tests"),
        ("generate_tests", "run_validation"),
        ("repair_code", "run_validation"),
    ):
        sub.add_conditional_edges(
            source,
            lambda state, nxt=target: END if state.get("backend_error") else nxt,
            {target: target, END: END},
        )
    sub.add_conditional_edges(
        "run_validation",
        route_after_validation,
        {"passed": END, "failed": "repair_code", "repair limit reached": END},
    )
    return sub


def _frontend_subgraph(ctx: JobContext | None) -> StateGraph:
    sub = StateGraph(GenerationState, output_schema=FrontendLaneOutput)
    for name in FRONTEND_LANE_NODES:
        sub.add_node(name, _node(name, ctx))
    sub.add_edge(START, "plan_frontend")
    sub.add_edge("plan_frontend", "scaffold_frontend")
    sub.add_edge("scaffold_frontend", "generate_assets")
    sub.add_edge("scaffold_frontend", "generate_frontend")
    sub.add_edge("generate_assets", "validate_frontend")
    sub.add_edge("generate_frontend", "validate_frontend")
    sub.add_conditional_edges(
        "validate_frontend",
        route_after_frontend_validation,
        {"passed": END, "failed": "repair_frontend", "repair limit reached": END},
    )
    sub.add_edge("repair_frontend", "validate_frontend")
    return sub


def build_graph(ctx: JobContext | None, mode: GenerationMode = GenerationMode.BACKEND) -> StateGraph:
    """backend: today's graph. static: frontend lane only. dynamic (Story 14.1): validate_inputs → build_contract →
    parallel backend_lane + frontend_lane subgraphs → integrate (Story 14.2/14.3) → package_artifacts."""
    graph = StateGraph(GenerationState)
    if mode == GenerationMode.DYNAMIC:
        graph.add_node("validate_inputs", _node("validate_inputs", ctx))
        graph.add_node("build_contract", _node("build_contract", ctx))
        graph.add_node("backend_lane", _backend_subgraph(ctx).compile())
        graph.add_node("frontend_lane", _frontend_subgraph(ctx).compile())
        graph.add_node("integrate", _node("integrate", ctx))
        graph.add_node("package_artifacts", _node("package_artifacts", ctx))
        graph.add_edge(START, "validate_inputs")
        graph.add_conditional_edges("validate_inputs", route_after_spec, {"valid": "build_contract", "invalid": END})
        graph.add_edge("build_contract", "backend_lane")
        graph.add_edge("build_contract", "frontend_lane")
        graph.add_edge("backend_lane", END)
        graph.add_conditional_edges(
            "frontend_lane",
            route_after_frontend_lane,
            {"passed": "integrate", "repair limit reached": END},
        )
        graph.add_edge("integrate", "package_artifacts")
        graph.add_edge("package_artifacts", END)
        return graph

    for name in MODE_NODES[mode]:
        graph.add_node(name, _node(name, ctx))
    if mode == GenerationMode.BACKEND:
        graph.add_edge(START, "validate_spec")
        graph.add_conditional_edges("validate_spec", route_after_spec, {"valid": "plan_architecture", "invalid": END})
        graph.add_edge("plan_architecture", "generate_database")
        graph.add_edge("generate_database", "generate_backend")
        graph.add_edge("generate_backend", "generate_tests")
        graph.add_edge("generate_tests", "run_validation")
        graph.add_conditional_edges(
            "run_validation",
            route_after_validation,
            {"passed": "package_artifacts", "failed": "repair_code", "repair limit reached": END},
        )
        graph.add_edge("repair_code", "run_validation")
    else:
        graph.add_edge(START, "validate_inputs")
        graph.add_conditional_edges("validate_inputs", route_after_spec, {"valid": "plan_frontend", "invalid": END})
        graph.add_edge("plan_frontend", "scaffold_frontend")
        graph.add_edge("scaffold_frontend", "generate_assets")
        graph.add_edge("scaffold_frontend", "generate_frontend")
        graph.add_edge("generate_assets", "validate_frontend")
        graph.add_edge("generate_frontend", "validate_frontend")
        graph.add_conditional_edges(
            "validate_frontend",
            route_after_frontend_validation,
            {"passed": "package_artifacts", "failed": "repair_frontend", "repair limit reached": END},
        )
        graph.add_edge("repair_frontend", "validate_frontend")
    graph.add_edge("package_artifacts", END)
    return graph


def _display_graph(mode: GenerationMode = GenerationMode.BACKEND) -> StateGraph:
    if mode != GenerationMode.DYNAMIC:
        return build_graph(None, mode)
    graph = StateGraph(GenerationState)
    for name in MODE_NODES[GenerationMode.DYNAMIC]:
        graph.add_node(name, _node(name, None))
    graph.add_edge(START, "validate_inputs")
    graph.add_conditional_edges("validate_inputs", route_after_spec, {"valid": "build_contract", "invalid": END})
    graph.add_edge("build_contract", "plan_architecture")
    graph.add_edge("build_contract", "plan_frontend")
    graph.add_edge("plan_architecture", "generate_database")
    graph.add_edge("generate_database", "generate_backend")
    graph.add_edge("generate_backend", "generate_tests")
    graph.add_edge("generate_tests", "run_validation")
    graph.add_conditional_edges(
        "run_validation",
        route_after_validation,
        {"passed": "integrate", "failed": "repair_code", "repair limit reached": "integrate"},
    )
    graph.add_edge("repair_code", "run_validation")
    graph.add_edge("plan_frontend", "scaffold_frontend")
    graph.add_edge("scaffold_frontend", "generate_assets")
    graph.add_edge("scaffold_frontend", "generate_frontend")
    graph.add_edge("generate_assets", "validate_frontend")
    graph.add_edge("generate_frontend", "validate_frontend")
    graph.add_conditional_edges(
        "validate_frontend",
        route_after_frontend_validation,
        {"passed": "integrate", "failed": "repair_frontend", "repair limit reached": END},
    )
    graph.add_edge("repair_frontend", "validate_frontend")
    graph.add_edge("integrate", "package_artifacts")
    graph.add_edge("package_artifacts", END)
    return graph


def describe_graph(mode: GenerationMode = GenerationMode.BACKEND) -> dict[str, Any]:
    drawable = _display_graph(mode).compile().get_graph()
    nodes = [{"id": node_id, "label": node_id.strip("_")} for node_id in drawable.nodes]
    edges = [
        {
            "source": edge.source,
            "target": edge.target,
            "conditional": edge.conditional,
            "label": edge.data if isinstance(edge.data, str) else None,
        }
        for edge in drawable.edges
    ]
    return {"nodes": nodes, "edges": edges}
