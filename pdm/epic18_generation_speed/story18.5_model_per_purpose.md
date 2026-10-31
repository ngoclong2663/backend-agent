# Story 18.5 — Model per purpose: drawings on `flash-low`

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30 · **Depends on:** 15.2

## User story

As the operator, I want to choose the model for each kind of engine call, so that SVG drawings use a fast,
low-thinking model while code generation keeps the stronger default.

## Evidence

- `generate_assets` took 291 s for 3 SVGs; the hero alone was one 143 s step with 15 901 thinking tokens
  (`<workspace>/state/logs/00529268….antigravity.stdout.log`).
- `agy models` (2026-10-30) lists `gemini-3.8-flash-low`, `-medium` (today's default, `ANTIGRAVITY_MODEL`),
  `-high`, plus Claude and other models.
- The model is fixed per engine: `AntigravityEngine.model` / `ClaudeCodeEngine.model` → `--model`; the stream
  parsers take the same value for pricing (`pricing.py` matches by longest prefix, so `gemini-3.8-flash-low` is
  priced as `gemini-3.8-flash`).

## Steps

1. `EngineRequest` (`agent-api/src/engines/port.py`) gets `model: str | None = None`.
2. Settings (`config.py`, `.env.example`):
   - `antigravity_purpose_models: dict[str, str] = {"generate_assets": "gemini-3.8-flash-low"}`
   - `claude_code_purpose_models: dict[str, str] = {}`
   (pydantic-settings reads them as JSON from `ANTIGRAVITY_PURPOSE_MODELS` / `CLAUDE_CODE_PURPOSE_MODELS`). An
   empty or missing entry means the engine default.
3. Each engine gets its purpose map in its constructor (see where engines are built: `engines/registry.py` or
   bootstrap). In `build_invocation`, the model is `request.model or purpose_models.get(request.purpose) or
   self.model`; pass that same value to the stream parser so `model_calls` and the price use the real model.
4. `cli_invocations.model` already exists: make sure it holds the model actually used (check `run_engine` in
   `orchestrator/context.py` and the draft usage record in `drafting.py`).
5. Do **not** change the asset cache key (`frontend_assets.asset_key`): a drawing that passed the checks is
   reusable whatever model drew it.
6. Update `docs/engines/antigravity.md` (model per purpose) and the fake engine if it asserts on argv.
7. Unit tests: the argv carries `--model gemini-3.8-flash-low` for `generate_assets` and the default for
   `generate_custom_component`; an explicit `request.model` wins; the parser/usage records the per-call model.

## Acceptance criteria

- [x] `generate_assets` runs on `gemini-3.8-flash-low` by default; other purposes on `ANTIGRAVITY_MODEL`.
- [x] Both engines accept a purpose → model map from settings.
- [x] `cli_invocations.model` and `model_calls.model` show the model actually used.
- [x] Unit tests from step 7 pass.

## Status

- **2026-10-30:** Added `model: str | None = None` to `EngineRequest`. Added `antigravity_purpose_models` (defaulting to `{"generate_assets": "gemini-3.8-flash-low"}`) and `claude_code_purpose_models` to `Config` and `.env.example`. Passed purpose model maps to engine constructors and resolved model in `build_invocation` with precedence `request.model or purpose_models.get(request.purpose) or self.model`. Configured parsers to record actual model on usage and model calls. Updated `docs/engines/antigravity.md` and added unit tests in `test_engine_adapters.py`. All 29 tests pass.

## Verify

`make lint`, `make test`. In the final measurement, compare `generate_assets` time and whether all drawings pass
`frontend:assets` (no `FE_ASSET_FALLBACK` warnings). If the low model's drawings fall back, report it rather than
switching models silently.
