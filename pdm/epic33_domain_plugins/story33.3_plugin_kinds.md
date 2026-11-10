# Story 33.3 — The `domain`, `type` and `feature` kinds

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47, FR-44 · **Depends on:** 33.1

## User story

As the maintainer, I want domains, types and features as folders read by one registry, so that a new domain is a set
of folders, not edits across the planner and the drafting code.

## Context

- The design registry (`frontend_spec/design_registry.py`) reads `templates/design/<kind>/<name>/plugin.json`
  (statuses `draft` / `ready`, `needs`, `fallback`, the `BGA_DESIGN_INCLUDE_DRAFTS` switch).
- Backend plugins live in `templates/plugins/<name>/` (`plugin.json`, `backend/files/**`, `frontend/files/**`).

## Steps

1. **Folders and descriptors** (validated with Pydantic, lenient loading, `strict=True` in tests):
   - `templates/domains/<domain>/domain.json`: `name`, `label`, `status`, `words` (requirement words that point to it),
     `roles` (the core entities by role, each with the fields it must have by role: a `course` has a title and a
     `lesson` list; a `device` has a status and a last-seen time), `areas` (each with its people and its pattern),
     `features` (`required`, `optional`), `checks` (the contract a draft must pass), `tasks` (33.1's UX tasks);
   - `templates/domains/<domain>/types/<type>/type.json`: `name`, `label`, `status`, `choose` (when it fits), and per
     area its pages (33.7);
   - `templates/features/<feature>/feature.json`: `name`, `status`, `attachesTo` (a role, or `person`), `entities`,
     `operations`, `rules`, `scenarios`, `mock`, `kit` (its components and the slots they fill), `checks`, and the
     backend plugin files it brings (`backend/files/**`, like `templates/plugins/`).
2. **One registry** (`modules/shared/domain/domain_registry.py`): load, validate, `ready()` per kind, the cross
   references checked (a domain's features exist, a type's slots are filled by a feature or the core entities).
3. **The generic fallback**: an app whose draft names no domain, or whose domain is not `ready`, takes today's path,
   byte for byte; every golden app's screens snapshot stays identical.
4. **Make targets**: `make domain-new NAME=` and `make feature-new NAME=` (scaffold a draft folder),
   `make domain-check NAME=` (the descriptor, its references and its tasks).
5. Tests: descriptor schemas; the registry refuses a hand-written list of domain or feature names; the golden
   snapshots unchanged.

## Acceptance criteria

- [x] The three kinds load and validate; a draft domain is never offered unless the switch is on.
- [x] Every golden app plans exactly as before.

## Verify

`make lint`, `make test`, `make domain-check NAME=socials` once 33.8 adds it.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `modules/shared/domain/domains/registry.py`: the three descriptors (`domain.json`, `type.json`,
`feature.json`), one registry with cross-references checked (a domain's features exist, a feature attaches to a known
role, a type's areas are the domain's), broken folders left out with a problem, `strict=True` in tests, drafts behind
`BGA_DESIGN_INCLUDE_DRAFTS`. `make domain-new`, `make feature-new`, `make domain-check`
(`scripts/domain_plugin.py`). An app without a domain plans as before (the golden snapshots unchanged).
Tests: `test_domain_registry.py`.
