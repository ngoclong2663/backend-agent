# Story 30.7 — Choosing among more plugins

**Epic:** [30 — Design plugins](epic30_design_plugins.md) · **Requirements:** FR-44, FR-37 · **Depends on:** 30.4–30.6

## User story

As a user drafting two apps of the same kind, I want them to come out different when nothing in my requirement says
otherwise, the same when I draft the same requirement again, and easy to switch in the review, so that variety is real
and under my control.

## Context

- `complete_design` (`frontend/app/design.py`) completes the model's brief with archetype defaults; the requirement's
  look comes first (23.13); the three looks span families (23.7).

## Steps

1. **Candidates:** for each axis, the ready plugins whose `archetypes` include the app's and whose `needs` the
   contract meets; the model's choice wins when it is a candidate, else the archetype default, else the seed's pick
   among candidates.
2. **Seed (D9):** the draft's seed picks among equal candidates for every axis the model left open; the same draft
   gives the same design; "try another layout" in the review is a new seed for layout axes only.
3. **Coherence rules (code):** a recipe's `prefers` breaks ties for card and density; a featured home needs a media
   card; a `terminal` recipe prefers `table` and `compact`. Rules live in descriptors, not in code branches.
4. **Review:** the Design panel lists, per axis, the candidates with their preview screenshots (30.3's `preview.png`);
   switching is a spec edit that re-renders with no engine call.
5. **Prompt:** the choice lists show only candidates for the archetype the requirement suggests, so the prompt does
   not grow with the registry.
6. Tests: candidates per archetype on synthetic specs; the same seed gives the same design; a new seed changes only
   open axes; the requirement's look always wins.

## Acceptance criteria

- [x] Five drafts of one requirement with different seeds give at least three distinct fingerprints (30.1).
- [x] The same draft re-applied gives the same design.
- [x] The prompt's size stays within 10% of today's whatever the registry's size.

## Verify

`make test`, `make app-design-report`.

## Status

Proposed 2026-11-08.

**Done 2026-11-09.** Candidates (`_Completion.candidates`: the ready plugins of the kind offered for the archetype
whose `needs` the contract meets); the brief's choice wins when it is a ready plugin (then the fallback chain), an
open axis takes the first look's recipe `prefers` when it is a candidate, else the seed's pick among the candidates
(the archetype default is one of them), without a seed the archetype default as before. The seed (D9) is the
requirement's hash (`design_seed`), written as `design.seed`; the seeded axes are the shell, the home and the main
entity's view, detail, card and filters (other entities keep their defaults); the look's `prefers.density` sets the
density when the brief leaves it open. The review's Design panel (`AppDesignPanel`) lists every axis from
`GET /api/v1/design-plugins` (shell, home; per entity view, detail, card, filters; the looks) and has "Try another
layout" (`shuffleAppDesign`: a new pick per layout axis among the archetype's candidates, a new seed, the looks kept),
each a spec edit with no engine call. The prompt lists only the ranked archetypes' candidates (`design_choices`) and
stays within 10 % of v6 (`test_draft_app_v7_prompt_lists_the_registry_choices`). Tests: `test_app_design.py` (30.7
block: ≥ 3 distinct fingerprints over 12 seeds of one brief, the same seed the same design, the brief's own choices
under any seed, cinema → overlay).

Deviations: the UI's shuffle cannot check `needs` (it has no contract); the kit falls back where data lacks (a board
without a status renders as cards, shelves without a group as a grid). Preview screenshots per plugin
(`preview.png`) are written by the plugin check and served through the registry digest's `preview` path, but the
panel shows labels and `choose` texts, not the images, for now.
