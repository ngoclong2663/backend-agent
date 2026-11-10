# Story 33.4 — The feature engine: from "this app has comments" to working code

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47, FR-34 · **Depends on:** 33.3

## User story

As a user describing an app, I want a feature like comments or deliveries to arrive complete (its data, its rules,
its API and its screen parts) so that it behaves right the first time, whatever entities the model drafted around it.

## Context

- Backend plugins (Story 10.1) already contribute files, settings, router parameters, use-case checks, response
  fields, tests and contract scenarios; the mocks emulate them (`src/mocks/plugins.ts`).
- The contract (`integration/contract.py`) is the one truth both lanes read.

## Steps

1. **Attach by role**: the draft names which core entity plays each of the domain's roles (`content: Post`); a feature
   with `attachesTo: content` attaches to that entity. A feature may attach several times (comments on posts and on
   lessons) and to `person` (follow).
2. **Merge into the BackendSpec** (code, before validation): the feature's entities (named after the target:
   `PostComment`), their fields, relationships to the target and to the signed-in user, operations, rules and
   access (who reads, who writes; Epic 25's rules accept them as written). Name clashes with drafted entities are
   resolved by dropping the drafted one with a note: the feature owns its data.
3. **Counters and state on the target**: a feature may add read-only response fields to its target (`likeCount`,
   `likedByMe`, `commentCount`, `progress`), computed by the backend and emulated by the mocks, so the kit shows state
   without extra calls.
4. **Backend code**: the feature's files are written like a backend plugin's (`scaffold_project(..., plan=)`); its
   operations are templated or written by the feature, never left to the engine.
5. **Contract and mocks**: the feature's scenarios join the contract; the mocks emulate its rules (one like per
   person, a reply's parent on the same post), so the frontend's `scenarios` check covers it.
6. **Kit parts**: the feature's components are copied when used (`templates/features/<f>/frontend/files/**`) and
   registered for the slots they fill (`comment-thread`, `reaction-button`, `progress-bar`, `job-steps`, `chart`).
7. Tests: a synthetic draft with a feature attached twice; a clash dropped with a note; counters in the contract;
   the mocks' scenarios pass.

## Acceptance criteria

- [x] A feature attached to any drafted entity yields valid backend code, contract scenarios that pass on the mocks,
      and kit parts registered for its slots.
- [x] The model's own entity for the same thing is replaced, with a note.

## Verify

`make test`, `make kit-test`, the sandbox tests (`BGA_SANDBOX_TESTS=1`) on a synthetic app.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `drafting/features.attach`: a feature's BackendSpec fragment, filled for its target (`{Target}`,
`{target}`, `{targetPath}`, `{Person}`, `{kind}`, `"{option:kinds}"`), merged as plain entries; the drafted entity it
replaces (named like one of its words and pointing at the target) dropped with everything naming it, with a note; a
clash or a missing target left out with a note. The BackendSpec gains `features` (`{feature, on, options, entities,
computed}`, code-written, never in the drafting schema). The access rules leave a feature's entities as written.
**Computed fields** are core: the planner puts them on the target model, `references()` gains `viewer` and fills a
grouped count or the caller's own row per page, the response DTO carries them (`like_count: int = 0`,
`my_like_id: UUID | None`), the policies plugin gives reads the caller when a `mine` field needs it, the contract marks
them `readOnly` with `x-bga.computed`, the mocks compute them from their store with the session's user, and fixtures
present the counts. **Self-relationships** (a reply's parent comment) now configure: both sides named after the key and
the parent's key as `remote_side` (it failed with "both of the same direction" before; the test proves both ways).
Tests: `test_feature_attach.py`, `test_feature_computed.py`, `test_self_relationship.py`.

Deviations: a person's id is a plain field owned through an ownership policy (drafts declare no user entity), so a
comment shows "You" or "Member", not a name (an author name needs a person profile: 33.8). The kit parts live in the
kit (`components/app/features/`), not copied per feature.
