# Story 18.3 — Route-parameter links: hint, rule, automatic fix; focused draft repair

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30, FR-2 · **Depends on:** 12.4

## User story

As a user, I want a draft whose only problem is a link to a page that needs an id to be fixed in milliseconds,
not by a 10-minute engine repair, and any engine repair to see the broken part of the spec directly.

## Evidence (draft `808c82dc…`)

- The only validation error after drafting:
  `FE_ROUTE_PARAM_UNBOUND` at `/pages/2/sections/1/content/cta/page`: "Page 'study' (/study/[id]) needs route
  parameters a navigation link cannot fill". **No hint.**
- `repair_spec` then took 577 s, 71 turns, 6.6 M input tokens. The Antigravity conversation shows ~60 `read_file`
  calls on this repository (`agent-api/src/modules/shared/domain/frontend_spec/validator.py`, `consistency.py`,
  tests, examples, README...) to understand the rule.
- The initial draft call read the 65 KB / 3 000-line FrontendSpec schema in 8 chunks; 18.9 deals with that.
- `drafting.py` writes the repair prompt with the error list only; the engine must read the whole spec to find
  the spot.

## Steps

1. **Hint** (`agent-api/src/modules/shared/domain/frontend_spec/validator.py`, `_check_link`): add a `hint` to
   the link case, e.g. `"Link to a page without route parameters (<candidates>), or let a data section link
   each record to it (binding 'link')"`, where `<candidates>` are page ids whose route is a parameter-free prefix
   of the target's route (`/study` for `/study/[id]`), else the known pages without parameters.
2. **Rule in the draft prompt:** add `agent-api/prompts/draft_frontend_spec/v4.md` (copy of v3) with one rule:
   navigation links, footer links and section CTAs (`page`) may only target pages without route parameters;
   detail pages are reached from a data section's record link. Switch `drafting.py` to `v4`.
3. **Automatic fix before any engine repair.** New pure function (suggested home:
   `modules/shared/domain/frontend_spec/autofix.py`, exported like the other helpers) that takes the drafted
   FrontendSpec dict and returns `(fixed_spec, notes)`:
   - for every link that fails with `FE_ROUTE_PARAM_UNBOUND` (header navigation, footer links, section content
     links: find every caller of `_check_link`), point it at the nearest parameter-free page whose route is a
     prefix of the target's route; if there is none, the page that holds a list data section bound to the same
     entity; if there is none, remove the link when the schema allows it (optional field), else leave it;
   - each change returns an assumption note
     (`{"spec": "frontend", "path": ..., "message": "Link to 'study' (/study/[id]) now points to 'decks' (/decks):
     a link cannot fill [id]", "suggestion": None}`).
   In `DraftRunner._run`, run it after `draw_images` and before `check_draft`; add its notes to the
   assumptions. Then the existing loop repairs only what is left.
4. **Focused repair prompt.** Add `agent-api/prompts/repair_spec/v2.md`. For each error, include an `excerpt`:
   the JSON at the error's path and at its parent (trimmed to ~1 500 characters), so the engine does not need to
   read the whole file. Add to the prompt: "Everything you need is below and in the spec files in this
   directory; do not look for other files." Build the excerpts in `DraftCheck.repair_errors` (or next to it) and
   switch `drafting.py` to `repair_spec@v2`.
5. **Re-check after an interrupted repair:** in the repair loop, when the engine status is not OK, still run
   `check_draft` once before giving up (same idea as 18.1): if the files now validate, the draft succeeds.
6. Unit tests: the autofix on (a) the measured case (CTA to `/study/[id]` with `/study` present), (b) no prefix
   page but a list page of the same entity, (c) neither; the hint text; the excerpt builder (path at the root, a
   nested path, a missing path); the interrupted-repair re-check with the fake engine.

## Acceptance criteria

- [x] `FE_ROUTE_PARAM_UNBOUND` on a link carries a hint naming candidate pages.
- [x] `draft_frontend_spec@v4` states the link rule; v3 unchanged.
- [x] The measured case (CTA → `/study/[id]`) is fixed without an engine call and noted as an assumption.
- [x] `repair_spec@v2` gives each error an excerpt of the spec and tells the engine not to look elsewhere.
- [x] An interrupted repair whose edit made the spec valid ends SUCCEEDED.
- [x] Unit tests listed in step 6 pass.

## Status

- **2026-10-30:** Implemented validator hint for `FE_ROUTE_PARAM_UNBOUND` with candidate page resolution. Added prompt `draft_frontend_spec@v4` enforcing navigation/CTA parameter link rule. Added `autofix_frontend_spec` in `autofix.py` executing before engine repair and noting assumptions. Added `repair_spec@v2` with structured error excerpts and anti-exploration guidance. Added post-interruption draft re-check. Added 7 unit tests in `test_draft_autofix.py` and verified all 31 drafting and autofix tests pass.

## Verify

`make lint`, `make test`. With the fake engine, a draft whose fake output contains the bad CTA ends SUCCEEDED
with `attempts = 0` (add this fake output to the fake engine if it has none, and list it in
`docs/development/test-doubles.md`).
