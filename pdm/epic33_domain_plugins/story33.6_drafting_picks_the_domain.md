# Story 33.6 — `draft_app@v10`: the domain, the type and the features

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.3, 33.4

## User story

As a user describing an app, I want the drafting step to recognize what kind of product I'm describing and build on
that domain, so that I get its complete features without having to list them.

## Context

- `draft_app@v9` writes the BackendSpec and the outline in one LLM turn; code ranks archetypes
  (`archetype_candidates`) and offers only the registry's choices (`design_choices`).

## Steps

1. **Code ranks domains** from the requirement (each domain's `words`, plus the design data's product type), and offers
   the ready domains with their types (the `choose` line) and optional features.
2. **`draft_app@v10`**: v9 plus, when a domain is offered, the answer's `domain` block: the domain, the type per area,
   the optional features turned on, and which drafted entity plays each core role. The prompt says not to draft the
   features' entities. The prompt grows by the offered domains' lines only; with none offered it is v9's.
3. **The contract check** (code): the roles are filled by entities with the fields each role needs; the areas' people
   are the BackendSpec's roles; required features attach. A failure gets one repair turn with the errors; a second
   failure keeps the draft on today's generic path, with a note naming why.
4. **The requirement wins** (D8): "comments are private", "no likes", "drivers choose their own offers" override a
   feature option or a type default, with a note.
5. The draft's review page shows the domain, the type and the features, and lets the user switch type or turn an
   optional feature off before generating.
6. Tests: the v10 prompt snapshot; the five 33.1 drafts recognized as their domain; a requirement outside every
   domain stays generic; a failed contract falls back with a note.

## Acceptance criteria

- [ ] Each reference requirement drafts into its domain with the roles filled and the features attached.
- [ ] A requirement outside the five domains drafts exactly as with v9.

## Verify

`make test`; the five drafts on the real engine (with the user's approval).

## Status

Proposed 2026-11-10.

**Code done 2026-11-10 (the real drafts come with each domain story).** `drafting/domains.py`: `rank_domains` (the
ready domains whose words the requirement uses, at least two), `offered`, and `apply_domain` (the model's `domain`
block checked: the domain is ready, each core role played by a drafted entity, the model's choice or one named like
the role, else the main entity; the required and chosen optional features attached; anything that doesn't hold keeps
the generic flow with a note). `draft_app@v10` is v9 plus the domain block, shown only when a domain is ranked
(otherwise the text is v9's, tested); the outline gains `domain` (only v10's schema shows it); the merge runs after
`fix_backend_defaults`, before the checks, so repairs see the whole spec; the completed outline keeps what code
checked. Tests: `test_domain_drafting.py`.

Deviations: a failed contract falls back without a repair turn (the role is found by code first); the review page's
domain and type switches (step 5) and the requirement overriding a feature option (step 4) are not done yet.

Real drafts 2026-11-10 (Antigravity, the socials reference requirement): the first v10 draft named the domain and
drafted no Comment or Like, but also dropped Follow and Notification ("the domain brings follows"). The prompt now names
exactly what a domain brings ("Brings: Comments (…); Reactions (…)") and says everything else is drafted as usual;
the second draft kept Follow, Notification and Report and was merged with comments and reactions
(`tests/fixtures/drafts/domain-socials-v10/`). Its tasks: 4 of 5 (baseline 2); follow has no state until 33.8.
