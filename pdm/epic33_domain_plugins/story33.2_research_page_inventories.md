# Story 33.2 — Research: a page inventory per type

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.1

## User story

As the user, I want each type built from how leading products of that kind organize their pages and flows, so that a
generated app feels like a real product of its kind, not a database with a menu.

## Context

- D4 and D7: a type is a page inventory; research records structure, never a product's look, name, copy or assets.

## Steps

1. **A research checklist** (`docs/domains/research-checklist.md`), the same for every type:
   - the pages each kind of person has, and how they reach each one (menu, link, button);
   - per page: its sections in order, what each section shows (by role: title, media, price, progress, status…)
     and the actions on it;
   - the main tasks with their click counts from the home page;
   - empty, loading and error states worth copying as behaviour;
   - what these products never show a given role.
2. **5–8 products per type**, studied with the checklist from their public pages (sign-up flows where free):
   - learning: course catalogue, classroom;
   - socials: short-video feed, photo and post feed;
   - news: magazine, link aggregator;
   - drivers: courier (driver and customer sides);
   - IoT: sensor monitoring, vision ops.
3. **One inventory per type** (`docs/domains/<domain>/<type>.md`): the common structure most products share, the
   variations worth offering as options, and the click budget for each main task. Products are cited as sources in the
   document only; nothing of theirs goes into templates.
4. **Review with the user** before 33.7 turns an inventory into a type plugin.

## Acceptance criteria

- [x] Nine inventories (two types each for learning, socials, news, IoT; one for drivers) reviewed by the user.
- [x] Every main task in 33.1 has a click budget backed by the research.

## Verify

The user's review of `docs/domains/`.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (reviewed and accepted by the user).** `docs/domains/research-checklist.md` (how clicks are counted:
from the area's home, signed in, a tap and a confirm each one, typing free) and nine inventories under
`docs/domains/<domain>/<type>.md`, each with the products studied, people and areas, pages with their slots in order,
main tasks with paths and budgets, the data pages need (and what the server computes), states, what each role never
sees, and options. One slot vocabulary (54 slots) across all nine. Written from knowledge of the products' structure,
not measured in the apps.
