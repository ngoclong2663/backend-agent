# Story 34.4 — Wiring into the draft

**Epic:** [34 — Designed themes](epic34_designed_themes.md) · **Requirements:** FR-48

## User story

As a user, I want the designed theme in my draft and my generated app, so that the preview shows it.

## Steps

1. `draft_app`: after the design data's theme (`app_theme`), the design turn designs it; the first look takes the designed pairing; `follow_requested` applies the requirement's look after.
2. Notes: the concept line and what code changed.
3. `DESIGN_THEMES` (default on); off, the theme is today's exactly.

## Acceptance criteria

- [x] A draft carries the designed theme and pairing; off, the theme is today's.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `draft_app(designer=...)`: after `app_theme(chosen)` the design turn runs (progress "designing
the theme"), its theme replaces the data's (the destructive colour, style and direction stay), `apply_pairing` puts
the pairing on the design and the leading look, and `follow_requested(outline, theme, designed, requirement)` runs
after: a designed theme keeps what it designed close to the requested look (the yarn shop's first real draft had its
tinted surfaces repainted grey from the requested white). `DraftRunner._designer` calls the draft's LLM provider
(`draft_provider`, the business steps' one) with the draft's speed model and records the call (`design_theme@v1` in
the usage). `DESIGN_THEMES` (default on; `.env.example`), a draft or generation request's `designThemes`; a
fake-engine draft only when asked; off in tests (`docs/development/test-doubles.md`). Notes: the concept line, the
pairing, why, and what code changed. Test: a fake-engine draft with a fake provider carries the designed theme and
pairing; off, the data's theme.
