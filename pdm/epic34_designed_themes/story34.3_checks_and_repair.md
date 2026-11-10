# Story 34.3 — Code checks, one repair, the fallback

**Epic:** [34 — Designed themes](epic34_designed_themes.md) · **Requirements:** FR-48

## User story

As the maintainer, I want every designed theme checked by code, so that a bad pick never reaches an app.

## Steps

1. `check_theme(answer, requested)`: hex colours, AA text contrast, a readable primary, a known pairing, no cliché, the requested accent kept (within a small distance); it returns the reasons.
2. Code fixes what needs no model: pure-grey neutrals are tinted toward the primary.
3. One repair turn with the reasons; still failing, the design data's theme with a note.

## Acceptance criteria

- [x] A failing theme is repaired once or falls back, with notes; a passing one is used as designed.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `check_theme` returns the reasons (hex colours, AA text, a primary readable as a button, a label
colour on the primary, the pairing, radius and density, the clichés, the requested accent, a requested dark scheme,
the requested heading kind). Code fixes what needs no model: `with_requested_accent` sets the user's accent when the
answer moved away from it, `tint_neutrals` tints pure-grey surfaces. `keeps`: a hex the requirement itself gives is
kept as it is; a colour named only in words (which the draft turns into a stock hex: "leaf green" → `#22c55e`) is
followed by its family (the accent's hue within 25°, the page's lightness), and a cliché is excused when the user
named the accent. One repair with the reasons, then the design data's theme with a note; a provider error falls back
the same way. Tests: the checks, the repair, the fallback, the tint, the requested accent, the family rule.
