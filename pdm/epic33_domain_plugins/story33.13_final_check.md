# Story 33.13 — Final check: real runs in the UI, against the baseline

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.8–33.12

## User story

As the user, I want to type requirements for each domain in the UI and use each app in its people's roles, so that I
can see the domains work on requirements nobody tuned them for.

## Context

- The final checks of Epics 28–32 ran in the UI's one-click flow as `admin@bga.local`, dynamic mode, on the real
  engine, at most two requirements at a time; a failing step is cancelled, fixed with a regression test on the real
  drafted spec, and rerun.

## Steps

1. The five reference requirements (33.1), then five fresh ones written for this check (one per domain, varied in
   wording and look), at most two at a time.
2. Each app used signed in as each role (demo users): 33.1's tasks done by hand, the walker's tour and the report's UX
   block recorded.
3. One requirement that fits no domain, to confirm it's generated as before.
4. The report against 33.1's baseline: each task before and after.

## Acceptance criteria

- [x] The runs and their timings are in this Status, with each failure's fix and regression test.
- [x] Every 33.1 task that failed in the baseline passes, and the generic requirement plans as before.

## Verify

`make lint`, `make test`, `make up`, the real runs, `make app-design-report ARGS="--domains"`.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** Real runs through the API's one-click flow (the same `POST /generations` the UI
sends, as `admin@bga.local`, dynamic mode, Antigravity, at most two at a time, then one at a time at the user's
request to spare resources). Drafts on `draft_app@v10`: every reference requirement was recognized as its domain and
merged (news 4/4, learning 5/5, drivers 4/5, IoT 5/5 tasks; socials 5/5 re-planned with today's plugins).

| Run | Generation | Result |
|---|---|---|
| News | `gen_01M72277RV6S8RX6R1D097ZFWR` | **COMPLETED**, every check; live: save toggles its count and state, a second save 409, follow a section, a reply under a comment |
| Learning | `gen_01M722Y7BMGRMM3T7ZXXAMGN3T` | **COMPLETED**, every check; live: enroll, complete a lesson, the course's progress 0/1 → 1/1 |
| IoT | `gen_01M723FCN7JMSVS1WHPNQ8RBW5` | **COMPLETED**, every check |
| Drivers | `gen_01M725Y40JRJ2H2FSZGY54VVKF` | **COMPLETED_WITH_WARNINGS** (lint: the engine's own `== True`, and a generated test's unused `body`, fixed after); live: earnings 401 signed out, online state, a shop's delivery with a generated tracking code |

Findings, each fixed with a regression test on the real drafted spec (`tests/test_generation_fixes.py`,
`tests/test_fixture_integrity.py`):

1. Docker ran out of network address pools (left by earlier sandboxes): the unused `bga` networks were removed.
2. The computed fields had defaults in the response DTO, so the app's OpenAPI marked them optional (the openapi check):
   now required.
3. News: the rules plugin checked `dto.status` on an update whose DTO has no status (it moves only through its actions):
   every update answered 500. The rules plugin checks only fields the body carries.
4. Learning: the relations plugin left a one-to-one child (a quiz) out of the fixtures for the create scenario while a
   submission still pointed at it: the seed's foreign key failed. Its dependents go with it (re-pointing them filled the
   pair the unique rule's success scenario keeps free, and the mocks answered 409).
5. Drivers: three availabilities over two demo drivers repeated a unique key: a unique foreign key now takes each parent
   once in the fixtures.
6. Drivers: the earnings aggregates (behind sign-in, an ownership policy) were open to anyone and their 401 was missing:
   an aggregate route keeps every dependency; `complete_backend@v6` also asks the engine to declare a custom handler's
   error responses.
7. Drivers: the create left out a required `shopId` (named after the creating `shop_owner` role) and a unique
   `trackingCode`: the creating role's own id comes from the signed-in user, and a required unique code nobody sends
   gets a generated code (`@code`); the generated tests seed such an id without a parent.
8. The API container still ran the image from before the epic: its validator didn't know the `features` block, the
   stored spec kept no normalized JSON, and the generation page said "Untitled project". `make up` rebuilt it.

Deviations: no socials generation (the user stopped it; it is to be tested on Claude Code); no requirement outside the
domains was generated (the v9 prompt path is covered by tests); the walker's tours were not replayed (the static judge
measures the tasks); a figure's ownership policy is not applied to its sum (a driver's earnings are everyone's).
