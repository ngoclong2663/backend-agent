# Story 33.14 — Feedback on screens: the user comments, the app changes

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47, FR-29 · **Depends on:** 33.7, 33.13

## User story

As a user looking at my generated app, I want to click a part of the preview, write what I want changed and see the
change applied, so that I can fix the UI without rewriting my requirement and generating again.

## Context

- Epic 16 (site revisions and feedback, not built) was designed before the app kit: it sends a comment to an engine to
  edit the app's files. Apps run the shared kit, so engine edits would fight the generator; this story replaces
  Epic 16's feedback path for apps.
- With domain plugins an app is a set of choices: the domain, a type per area, each feature's options, each slot's
  placement, the design plugins, the labels and the theme. Most feedback is a change of choices.
- The kit marks every section (`data-bga-section="<page>/<section>"`, `data-bga-component`), so a comment pinned on the
  preview knows which page, section and component it's about.

## Steps

1. **Inspect mode** on the preview (the UI's generation page): hover highlights a section, a click pins a comment to
   it; comments are kept on the generation (`app_feedback` rows: target, text, author, state).
2. **A comment becomes a change of choices**: one LLM turn gets the comment, its target and the app's current choices
   with what the plugins offer for that target (the other placements of the slot, the type's options, the feature's
   options, the design plugins for that kind, the labels), and answers a patch of choices only. Code validates the
   patch against the registry and the contract.
3. **Three outcomes**, shown to the user before anything changes:
   - **a choice change** (placement, type option, feature option, label, design plugin, theme): the frontend is
     re-planned and rebuilt, backend untouched, about one to two minutes;
   - **a data change** (a feature option that adds fields, a BackendSpec edit): shown as such, with the backend lane's
     time; applied only when the user confirms;
   - **not expressible** by any plugin: either one custom component for this app in a protected view slot (Story
     23.11's opt-in slots, one engine call, checked by code), or saved as a **plugin request** with the comment, the
     domain and the type.
4. **Revisions**: each applied change is a numbered revision of the app (the choices before and after, the frontend
   commit, the preview image tag), listed on the generation page; any revision can be restored.
5. **Plugin requests** are listed for the maintainers (`GET /api/v1/plugin-requests`, grouped by domain, type and
   target), so recurring requests become plugin work instead of rules in the planner.
6. Tests: comments on each kind of target turned into valid patches on the recorded drafts; a patch outside the
   registry refused; a data change never applied without confirmation; a restore returns the previous choices and
   screens.

## Acceptance criteria

- [ ] On a generated socials app, "put the comments under the video instead of a popup" and "rename Inbox to
      Activity" are applied as choice changes and the preview shows them within two minutes, with no backend run.
- [ ] A request no plugin can express is offered as a custom slot or saved as a plugin request, never silently
      dropped; every applied change can be restored.

## Verify

`make test`, `make kit-test`, a real run in the UI with three comments of each outcome.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** `orchestrator/feedback.py`: one LLM turn (`screen_feedback`, the comment passed
as data, what it points at, the app's menu, pages, the target page's actions and its accent) answers a patch from a
fixed vocabulary (`rename-menu`, `page-title`, `comments` inline or sheet, `remove-action`, `accent`) or says `data` /
`request`; code applies each change to a copy of the FrontendSpec, drops what doesn't fit with why, and turns a choices
answer with nothing applicable into a request (never silently lost). `POST /api/v1/generations/{id}/feedback`
(`{target: "<page>/<section>", comment}`) returns the outcome, the changes and the revised FrontendSpec; requests are
appended to `ARTIFACT_ROOT/plugin-requests.jsonl`, listed for admins at `GET /api/v1/generations/plugin-requests`. The
kit's `CommentThread` renders in a sheet when `placement: "sheet"`. Tests: `test_screen_feedback.py`.

Deviations: no inspect mode in the UI yet; applying a revised spec is a new generation from it (no revision history or
restore, no frontend-only rebuild); the turn runs in the API process with the configured LLM provider (a container API
can't reach the host-only Antigravity login; the worker-queued version is future work); no custom view slot offer.
