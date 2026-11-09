# Story 32.8 — Final check: real drafts in the UI, against the baseline

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** 32.1–32.7

## User story

As the user, I want to type requirements for different kinds of product in the UI, generate them and use each app
in its people's roles, so that I can see the patterns work on drafts nobody tuned them for.

## Context

- The final checks of Epics 28–31 ran in the UI's one-click flow, dynamic mode, on the real Antigravity engine, at
  most two requirements at a time, with varied requirements and looks (Story 28.7). A failing step is cancelled,
  fixed with a regression test on the real drafted spec, and rerun as a new generation.

## Steps

1. Three rounds of at most two requirements, written fresh (not the golden ones), varied in product and look: a
   social app (posts or short videos, comments, likes, follows), a shop (products, cart, checkout, reviews), and one
   of booking or learning (to see that its `back-office` default is no worse than today).
2. Each run end to end in the UI as `admin@bga.local`; each app used signed in as each role (demo users): the 32.1
   tasks done by hand, the walker's tour and the report's UX block recorded.
3. One requirement states a placement (32.7), and one says comments are private (D8), to see both reach the screens.
4. The report against the 32.1 baseline: the consumer areas' check failures and task clicks before and after.

## Acceptance criteria

- [ ] The runs and their timings are in this Status, with each failure's fix and regression test.
- [ ] The report's UX block shows the baseline's consumer-area failures gone and no new failure in back-office areas.

## Verify

`make lint`, `make test`, `make up`, the real runs, `make app-design-report`.

## Status

Proposed 2026-11-09.
