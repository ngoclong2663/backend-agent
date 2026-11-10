# Story 33.1 — Reference requirements, UX tasks and the baseline

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** —

## User story

As the user, I want one fixed requirement per domain generated with today's kit and judged by tasks a real person
would do, so that every later story shows whether the domain plugins made the app better.

## Context

- Epic 32 measured patterns with UX checks per area (`frontend/app/ux_checks.py`, `make app-design-report
  ARGS="--ux-only"`) and the walker's tours on the mocks (Epic 26, 28).
- Recorded real drafts live in `tests/fixtures/drafts/<name>/` (BackendSpec + outline); the report plans them without
  an engine (`scripts/app_design_report.recorded_app`).

## Steps

1. **Five reference requirements** in `tests/fixtures/domains/requirements/` (plain text, written once, never tuned):
   - learning: an online course platform with instructors, lessons, quizzes and progress;
   - socials: a short-video community with likes, threaded comments and follows;
   - news: a city news site with sections, writers, editors, bookmarks and comments;
   - drivers: a courier app where drivers take delivery offers, pick up from shops and deliver to customers;
   - IoT: a greenhouse monitoring app with sensors (temperature, humidity, CO₂, soil moisture), cameras that detect
     pests, alert rules and device management.
2. **The UX tasks per domain** as data (`tests/fixtures/domains/tasks/<domain>.json`): each task names the role, the
   starting page, the goal and a click budget, for example:
   - socials: "reply to a comment on the first post" (≤ 3 clicks), "like a post and see it's liked" (1 click, the
     button shows the state);
   - news: "bookmark the first article" (1), "an editor publishes a reviewed article" (≤ 2);
   - learning: "resume the last lesson from home" (1), "submit a quiz" (≤ 4);
   - drivers: "accept the newest offer" (1), "mark a delivery delivered with a photo" (≤ 3);
   - IoT: "acknowledge the newest alert" (1), "see a sensor's last 24 h chart" (≤ 2), "find offline devices" (≤ 1).
3. **Draft each requirement once** on the real engine (with the user's approval; at most two at a time), record the
   drafts as fixtures (`tests/fixtures/drafts/domain-<name>/`), and run the tasks on the generated plan: the walker
   on the mocks where a task can be played, the UX checks otherwise.
4. **The baseline** `tests/fixtures/domains/baseline.json`: per task, passed or failed and why (no reply action, no
   liked state, no chart, a form page for an offer…).

## Acceptance criteria

- [x] Five requirements, their tasks and their recorded drafts are in the repository.
- [x] The baseline lists every task's result with the reason for each failure.

## Verify

`make test`; `make app-design-report ARGS="--domains --baseline"`.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** Five requirements (`agent-api/tests/fixtures/domains/requirements/`), their 24 tasks
(`tasks/<domain>.json`) and five real drafts on Antigravity (`antigravity_json`, fast, about one minute each, two at a
time; `tests/fixtures/drafts/domain-<name>/`: the BackendSpec, the completed outline and the planned FrontendSpec).
The tasks are judged on the planned app without a browser (`frontend/app/domain_tasks.py`: actions and their clicks,
a reaction's state, a reply from the comment, sections, shown fields, filters, a photo on an action, resume on the
home). `make domain-report [ARGS=--baseline]`; the baseline `tests/fixtures/domains/baseline.json`: **11 of 24**.
Every failure is one the epic answers: no liked state, a reply whose parent is picked from a list on the add-comment
form, no follow, no resume and no progress, no chart, no photo on delivery, no online switch, no customer area.

Deviations: the judge is static (the walker plays the tours in 33.13); `make domain-report` instead of
`app-design-report --domains`. Two task fixtures were made fair after the first run (the quiz's operation is named
`submission`; offline devices take two clicks, menu and filter). The socials draft's comment replies (`Comment →
Comment`) would also have broken the generated backend (the self-relationship, fixed in 33.4).
