# Research checklist for a type's page inventory

Story 33.2. Every inventory in `docs/domains/<domain>/<type>.md` follows this checklist, so the nine documents
compare and a later step (33.7) can turn each one into a type plugin.

## Rules

- Record structure only: pages, sections, actions, flows, click counts, states, what a role never sees.
- Never record a product's look, branding, copy, wording or assets. Products are named only in "Studied".
- Write what most of the studied products share. A difference worth keeping goes under "Options".
- Name each section with a slot from the shared vocabulary. Add a new slot only when no existing one fits, and
  list it under "Slots used".

## How clicks are counted

- Start from the area's home page, signed in, with seed data present.
- One click is a tap or click on a control: a menu tab, a link, a card, a button, a toggle.
- A confirm dialog counts as one more click.
- Taking or picking a photo or file counts as one click.
- Typing text and choosing answers inside a form are inputs, not clicks. Scrolling is free.
- A task that a page shows without any click counts as 0 clicks.

## The checklist, per type

1. **Studied**: 5 to 8 leading products of this kind, one line each on what kind of product it is.
2. **People and areas**: each role, the area it uses, and whether that area is mobile-first or desktop.
3. **Pages**, per area: each page, how it is reached (menu tab, link, button), its sections in order, and the
   actions on it.
4. **Per section**: its slot name and what it shows, by role (title, media, price, progress, status, count...).
5. **Main tasks**: every task in `agent-api/tests/fixtures/domains/tasks/<domain>.json` plus 2 to 4 more, each with
   its role, its path click by click, the clicks it takes, and the budget.
6. **Data the pages need**: the fields by role per page, and which of them the server computes.
7. **States**: empty, loading and error behaviours worth copying.
8. **Never shown to**: what each role never sees.
9. **Options**: variations worth offering, such as comments inline or in a sheet.
10. **Slots used**: every slot name the document uses.

## Section order of an inventory

Studied, People and areas, Pages, Main tasks, Data the pages need, States, Never shown to, Options, Slots used.
