# Story 34.2 — The design turn

**Epic:** [34 — Designed themes](epic34_designed_themes.md) · **Requirements:** FR-48

## User story

As a user describing a product, I want its colours and type designed for it, so that the app looks like that product and not like a template.

## Steps

1. `prompts/design_theme/v1.md`, the guidance in our own words: the product's world first, the requirement's look as the brief, six named colours, one bold accent, tinted neutrals, a pairing from the registry's list (each with when to choose it), corners and density, and the clichés to avoid.
2. The answer schema (structured output): `concept`, `colors` (six hex), `fontPairing` (the ready pairings), `radius`, `density`, `why`.
3. The brief: the requirement, the app's name, its domain or archetype, the main entity, the requested look, and the design data's category as a hint only.

## Acceptance criteria

- [x] The prompt renders with every input, its schema is valid, and a fake answer flows through.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `prompts/design_theme/v1.md` in our own words (the product's world first, six named colours,
one bold accent, tinted neutrals, a pairing from the list with when to choose each, corners and density, the looks
to avoid, the requested look kept; a dark requested app designs its dark colours). `answer_schema(pairings)`
(structured output; `fontPairing` an enum of the offered pairings). The brief: the requirement, the app's name, its
domain or archetype, its main entities, the requested look (a colour named only in words shown as "like #hex"), the
design data's category and palette as a hint. The pairings are `pairing_candidates` (script, requested heading kind,
archetype) less one plain sans throughout, listed in the app's own seeded order. Tests: `tests/test_design_themes.py`.
