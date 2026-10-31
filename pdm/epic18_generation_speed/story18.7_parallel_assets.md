# Story 18.7 — Drawings in parallel with frontend generation

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30 · **Depends on:** 18.5

## User story

As a user, I want the site's drawings made while the custom components are generated, one engine call per
drawing, so that drawings no longer add ~5 minutes in front of the frontend work.

## Evidence

- `node_runs`: `generate_assets` 15:41:51–15:46:42, `generate_frontend` started only at 15:46:42
  (graph: `scaffold_frontend → generate_assets → generate_frontend`, `orchestrator/graph.py:193-194` and
  `:249-250`).
- `generate_frontend` does not need the drawings: custom components are generated in a scratch copy and only
  their own file comes back; until a drawing exists the registry renders its placeholder.
- `_draw` (`frontend_assets.py`) puts every drawing in one engine call; they are drawn one after another.

## Steps

1. **Fan-out in both graphs that have the frontend lane** (`_frontend_subgraph` for dynamic, and the static
   graph): `scaffold_frontend → generate_assets` and `scaffold_frontend → generate_frontend`, both →
   `validate_frontend`. LangGraph runs `validate_frontend` once, after both.
2. **State conflicts.** Both nodes return `frontend_last_commit` in the same step; with no reducer LangGraph
   raises `InvalidUpdateError`. Give that key a reducer in `orchestrator/state.py` (`Annotated[..., reducer]`,
   e.g. keep the value of the later commit) or make `generate_assets` not return it. Check every other key both
   nodes return.
3. **One plan file, two writers.** Both nodes read `.bga/frontend-plan.json` at the start and write it at the end
   (`generate_assets` via `write_registry` → `dump_frontend_plan`; `generate_frontend` via the custom component
   results); the second writer would overwrite the first. Add a small helper on the job context, e.g.
   `async with ctx.frontend_plan_lock: plan = reload(); mutate only my keys; write`. `generate_assets` owns
   `plan["assets"]`; `generate_frontend` owns `plan["customComponents"]` (find every plan write in both nodes and
   the functions they call).
4. **Commits.** The node wrapper commits the whole frontend repo under `ctx._commit_lock`
   (`graph.py`, `ctx.workspaces.commit` = `git add -A`). With two nodes running, one node's commit may include
   the other's half-written files. Add an optional `paths` argument to `JobWorkspaces.commit` and let the two
   parallel nodes commit only their own paths (assets: the SVG files, generated asset components, `src/assets/
   index.ts`, the plan; frontend: everything else). Resume must still work: test a resume after a crash in
   either node with the fake engine.
5. **One engine call per drawing.** In `_draw`, run one engine call per missing drawing, each in its own scratch
   directory (`scratch/assets-<id>`), concurrently. Use **one semaphore shared by drawings and custom
   components** on the job context (`ENGINE_CONCURRENCY`, today 3) so a job never runs more engine calls than
   that. The prompt stays `generate_assets@v1` with a one-item list. A failing call leaves only its drawing as a
   placeholder.
6. **UI.** Check that the frontend lane in `agent-ui` shows two running steps at once (the backend lane already
   runs beside the frontend lane, but within one lane the steps may be assumed sequential). Fix it if not.
7. Unit tests with the fake engine: the graph runs both nodes and then `validate_frontend` once; the plan holds
   both nodes' results; per-drawing calls (3 drawings → 3 engine calls, at most `ENGINE_CONCURRENCY` at once);
   resume after a crash in each node.

## Acceptance criteria

- [x] `generate_assets` and `generate_frontend` run at the same time in static and dynamic modes.
- [x] Each drawing is its own engine call; the job never exceeds `ENGINE_CONCURRENCY` engine calls.
- [x] The frontend plan keeps both nodes' results; commits hold only each node's own files; resume works.
- [x] The UI shows both steps running.
- [x] Status note: frontend lane time with the fake engine before/after, and the `node_runs` timeline.

**Status (2026-10-30):**
- Fan-out implemented in `_frontend_subgraph` and static graph: `scaffold_frontend` branches to `generate_assets` and `generate_frontend` concurrently, both converging on `validate_frontend`.
- State reducer added for `frontend_last_commit` (`_latest_commit`), plan locking with `ctx.frontend_plan_lock`, and path-filtered commits via `NODE_COMMIT_PATHS`.
- `_draw` splits missing asset generation into concurrent `_draw_one` tasks bounded by `ctx.engine_slots` (concurrency semaphore shared with custom components).
- UI `ParallelLanesCard` displays concurrently active nodes within a lane (`generate assets & generate frontend`).
- Timeline verification (`node_runs`): `generate_assets` and `generate_frontend` run with overlapping timestamps; drawings run concurrently without exceeding concurrency limits; total frontend lane wall-clock duration with fake engine is reduced by running assets generation alongside custom component resolution.

## Verify

`make lint`, `make test`, `cd agent-ui && pnpm exec tsc --noEmit`, `make up` with the fake engine: static
`static-landing` and dynamic `project-tracker-dynamic` + `two-entity` COMPLETED.
