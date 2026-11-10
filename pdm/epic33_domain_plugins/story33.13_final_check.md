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

- [ ] The runs and their timings are in this Status, with each failure's fix and regression test.
- [ ] Every 33.1 task that failed in the baseline passes, and the generic requirement plans as before.

## Verify

`make lint`, `make test`, `make up`, the real runs, `make app-design-report ARGS="--domains"`.

## Status

Proposed 2026-11-10.
