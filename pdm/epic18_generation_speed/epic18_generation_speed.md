# Epic 18 — Generation speed: fail fast, run in parallel, cache the slow builds

## Overview

Measured on a real dynamic run with Antigravity (`gemini-3.8-flash-medium`), 2026-10-30. Requirement:
"Create a website help learner to learn vocabulary follow the ankie styling way". Draft `808c82dc…`,
generation `gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`.

| Phase | Time | What happened |
|---|---|---|
| Spec draft | **868 s** | `draft_frontend_spec` 291 s, then `repair_spec` **577 s for one error** (71 turns, 6.6 M input tokens) |
| `generate_assets` | **291 s** | one engine call drew 3 SVGs one after another (hero ~143 s of thinking) |
| `generate_frontend` | **1 089 s** | custom component 290 s → render test **hung 302 s** → repair 440 s → `cli_error` → library fallback: **the 18 min produced nothing that was used** |
| backend lane | ~70 s | not a problem |
| previews | **~285 s** | both images built from scratch, one after the other, then the frontend container recreated for the live API |

Root causes (evidence in the stories):

1. **No fail-fast in the isolated component checks.** ESLint reported `react-hooks/set-state-in-effect`
   (`useEffect(() => setQueue(records.map(...)), [records])`, an infinite render loop), but the render test still
   ran because it only waits for `tsc` (`custom_components.py:319`), and hung until the 300 s exec timeout.
2. **The component prompts do not state the React rules the checks enforce** (no setState in effects, no manual
   memoisation under the React Compiler), so the first attempt failed and needed a repair.
3. **Interrupted engine runs throw away finished work.** The repair fixed the file, but agy ended with
   "The stream was interrupted" → `cli_error` → fallback without re-running the checks.
4. **An error without a hint sends the engine exploring.** `FE_ROUTE_PARAM_UNBOUND` on a link has no `hint`
   (`validator.py:346-351`) and the draft prompt never states the rule. The repair engine read ~60 files of
   **this repository's own source** to understand the validator.
5. **The engines may read any file on the host.** Antigravity allows `read_file(*)`
   (`engines/antigravity/engine.py:17`); with `ANTIGRAVITY_AUTH=account` it runs as the user on the host. Claude
   Code pre-approves `Read`, `Glob` and `Grep` without a path (`engines/claude_code/engine.py:14`, `--allowedTools`).
   A security issue as well as a speed one.
6. **Drawings are serial and block the frontend.** `scaffold → generate_assets → generate_frontend`, although the
   component work does not need the drawings; all drawings share one engine call with medium thinking.
7. **Preview images are built from nothing, one after the other.** The frontend image downloads all 795 npm
   packages (`reused 0`; package.json carries the site's `name`, so the install layer never matches) and runs
   `next build`; the backend image re-runs `pip install`; the per-generation lock serialises the two builds.
   `integrate` runs before any preview exists (always SKIPPED), so the frontend is recreated later to go live.

Target for the same requirement (estimates from one run; the final measurement decides): draft ~868 s →
250–300 s, generation ~24.5 min → 6–7 min, previews ~285 s after completion → backend already running at
completion, frontend ~60–90 s after it (its `next build` stays in the ZIP build, by decision), with warm caches.

Out of scope here: the engine's own thinking time on code (components stay on the default model), agy stream
interruptions themselves (18.1/18.3 only keep the work done before them), and cold caches on the first run after
a dependency change.

**Decisions (user, 2026-10-30):** keep building previews **from the ZIP** (the ZIP is what the user downloads, so
the preview keeps proving it builds on its own); faster means cached, not prebuilt from the sandbox. Asset
drawings move to a lower-thinking model (`gemini-3.8-flash-low`).

**Requirements:** FR-30 (fast generation and reuse).

## Stories

| # | Story | Phase | Depends on |
|---|---|---|---|
| 18.1 | [Fail-fast component checks; keep interrupted work](story18.1_fail_fast_component_checks.md) | A | 17.3 |
| 18.2 | [React rules in the component prompts](story18.2_component_prompt_rules.md) | A | 17.3 |
| 18.3 | [Route-parameter links: hint, rule, automatic fix; focused draft repair](story18.3_draft_route_param_links.md) | A | 12.4 |
| 18.4 | [Engines read only their working directory (Antigravity and Claude Code)](story18.4_engine_read_scope.md) | A | 3.x |
| 18.5 | [Model per purpose: drawings on `flash-low`](story18.5_model_per_purpose.md) | A | 15.2 |
| 18.6 | [Cached preview builds, built in parallel](story18.6_cached_preview_builds.md) | A | 7.3, 13.5 |
| 18.7 | [Drawings in parallel with frontend generation](story18.7_parallel_assets.md) | B | 18.5 |
| 18.8 | [Previews start when their lane is done](story18.8_early_previews.md) | B | 18.6, 14.2 |
| 18.9 | [Engine context packs and pre-warmed modules](story18.9_context_packs.md) | C | 18.2, 18.3 |

## How to implement (read first)

Work in this order and **stop at each checkpoint** for review:

1. **Phase A:** 18.1 → 18.2 → 18.3 → 18.5 → 18.6, then 18.4 (it needs two approved real probes: `agy` and
   `claude`). **Checkpoint A:** stop; the reviewer reads the diff before Phase B.
2. **Phase B:** 18.7 → 18.8. **Checkpoint B:** stop for review.
3. **Phase C:** 18.9. **Checkpoint C:** stop for review, then the final measurement.

Rules (from the repository's `CLAUDE.md`; they apply to every story):

- Branch `feat/epic18-generation-speed` from `main`. **Do not commit**; the user commits after review.
- Never run paid engines (Antigravity, Claude Code) unless a story says so **and** the user has said yes in the
  conversation. Use the fake engine (`docs/development/test-doubles.md`) for every other check.
- Every new fake, stub or test-only switch goes into `docs/development/test-doubles.md` and is marked where it
  is defined.
- Prompts are versioned files (`agent-api/prompts/<id>/vN.md`). **Never edit a released version**: add `vN+1.md`
  and switch the code to it. Changing a component prompt version changes the component cache key
  (`component_cache.PROMPT_VERSION`); that is intended.
- Overlay files (`agent-api/templates/nextjs_overlay/files/...`) are edited by hand; never edit
  `templates/nextjs_base` (regenerate with `make frontend-base` only if a story says so).
- New settings go in `src/configs/config.py` with a comment, plus `.env.example` (repository root).
- After each story: `make lint`, `make test`; `BGA_SANDBOX_TESTS=1 make test` when the story touches sandbox
  or Docker code; `cd agent-ui && pnpm exec tsc --noEmit` when the UI changes.
- After each story, tick its acceptance criteria and add a dated **Status** note (what was done, deviations,
  measured times), as the Epic 17 stories do.
- Keep to the code style around the change: comment density, naming, docstrings.

## Final measurement (after Checkpoint C, needs the user's yes)

Re-run the same requirement with Antigravity (dynamic mode, same options as `gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`) and
record the same table as above in a Status note on this epic, from `node_runs`, `cli_invocations`,
`sandbox_execs`, `spec_drafts.usage` and the `preview.status` events.
