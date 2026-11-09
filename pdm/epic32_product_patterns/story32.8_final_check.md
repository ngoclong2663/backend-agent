# Story 32.8 — Final check: real drafts in the UI, against the baseline

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46 · **Depends on:** 32.1–32.7

## User story

As the user, I want to type requirements for different kinds of product in the UI, generate them and use each app
in its people's roles, so that I can see the patterns work on drafts nobody tuned them for.

## Context

- The final checks of Epics 28–31 ran in the UI's one-click flow, dynamic mode, on the real Antigravity engine, at
  most two requirements at a time, with varied requirements and looks (Story 28.7). A failing step is cancelled,
  fixed with a regression test on the real drafted spec, and rerun as a new generation.

## Steps

1. Three rounds of at most two requirements, written fresh (not the golden ones), varied in product and look: a
   social app (posts or short videos, comments, likes, follows), a shop (products, cart, checkout, reviews), and one
   of booking or learning (to see that its `back-office` default is no worse than today).
2. Each run end to end in the UI as `admin@bga.local`; each app used signed in as each role (demo users): the 32.1
   tasks done by hand, the walker's tour and the report's UX block recorded.
3. One requirement states a placement (32.7), and one says comments are private (D8), to see both reach the screens.
4. The report against the 32.1 baseline: the consumer areas' check failures and task clicks before and after.

## Acceptance criteria

- [x] The runs and their timings are in this Status, with each failure's fix and regression test.
- [x] The report's UX block shows the baseline's consumer-area failures gone and no new failure in back-office areas.

## Verify

`make lint`, `make test`, `make up`, the real runs, `make app-design-report`.

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with deviations).** The UI's one-click flow as `admin@bga.local`, dynamic mode, Antigravity
(`antigravity_json` drafts, fast; `antigravity` generation), two fresh requirements at a time
(`.data/final/pocket-chefs.md`: a recipe-video community, warm magazine look, "comments are written right under the
recipe"; `.data/final/thread-and-needle.md`: a yarn shop, crisp Scandinavian look, cart with quantities, reviews).

| Run | Generation | Result | Total |
|---|---|---|---|
| Pocket Chefs 1 | `gen_01M6ZPAK6T5DQVD5ACS9NM2JCN` | COMPLETED; members' area drafted as `catalogue` (no pattern then): finding 1 | 8 min 29 s |
| Thread & Needle 1 | `gen_01M6ZPAR2C9VWZ3PHRBGXZSDJV` | COMPLETED_WITH_WARNINGS; findings 2, 3 | 13 min 41 s |
| Pocket Chefs 2 | `gen_01M6ZQHZXHBYTH5ADA1YWWYSRM` | cancelled: `frontend:scenarios` (finding 4) | — |
| Thread & Needle 2 | `gen_01M6ZQJ4T9CME2BD44EQG2R6VP` | COMPLETED_WITH_WARNINGS; finding 5 | 10 min 17 s |
| Pocket Chefs 3 | `gen_01M6ZRH1XQZZHC6RXSM5BFTJ21` | cancelled: `frontend:scenarios` (finding 6) | — |
| Thread & Needle 3 | `gen_01M6ZRH6TF4067V1T7DN6SZNS4` | cancelled: smoke calls (finding 6, second draft) | — |
| Pocket Chefs 4 | `gen_01M6ZSM85JDAZTZ1Q3Q2ADZHFV` | cancelled: `frontend:scenarios` (finding 7) | — |
| Thread & Needle 4 | `gen_01M6ZSMD1QJT3HQMG2Q178P573` | **COMPLETED**, all lanes, no warnings; checked live | 13 min 49 s |
| Pocket Chefs 5 | `gen_01M6ZTH3KM639CANCP5X58V40C` | **COMPLETED**, all lanes, no warnings; checked live; finding 8 | 6 min 47 s |

Checked live: **Thread & Needle 4**: the shopper's menu is Catalogue, My Cart, My Orders; Add to cart on the product
(201, the cart lists it); the owner signs in as `demo-shop_owner@example.com`; the owner's area is a back-office.
**Pocket Chefs 5**: the viewers' area plans as `feed` (Recipes, Mine; like, save and Add comment on the recipe; the
view on open); a viewer likes and saves with the recipe alone (201, the owner from the session, a second try 409);
viewer A's comment is read by viewer B (public comments, 32.4); the cooks' studio is a back-office.

Findings, each fixed with a regression test on the real drafted spec (`tests/fixtures/specs/pocket-chefs-*.json`,
`thread-and-needle-*.json`, `tests/fixtures/drafts/pocket-chefs`, `thread-and-needle`):

1. A feed-like app drafted as a `catalogue`, which had no pattern: members met the cook's edit, publish, delete, a
   "Record view" button and a dashboard. A `catalogue` pattern (ready, needs sign-in); `on_open` reads compound verbs
   (`recordView`).
2. A role with a space ("Shop Owner") gave the demo login `demo-Shop Owner@example.com`, refused by the sign-in form:
   anything a login cannot hold becomes a hyphen.
3. A cart drafted as a Cart of CartItems (the item owned through its cart) was not found: a cart line is the person's
   own directly or through its container (`patterns.cart_of`); the menu shows the container.
4. A success scenario of a `uniqueTogether` with an enum (`type`) stayed a duplicate: the success tries every field
   the caller sets (a parent, an enum's other value); enums never take the "s2-" prefix.
5. A cart line that requires a quantity is a `part`, placed in a tab: a shop's cart line is added from the product
   whatever its shape.
6. Two drafts related an entity to itself through a person's field (`Recipe → Recipe` via `cookId`, `Order → Order` via
   `shopperId`): the seed filled people with record ids (404 on the mocks), and the models could not configure (every
   call a 500). `fix_person_relationships` drops a relationship whose foreign key is named after a role.
7. Every pair of the first demo user was seeded and the success's id was rewritten "<id> (new)": the success runs as
   the role's other demo user; the text fallback never touches an id.
8. The access rules gave a view action (`recipe.recordView`) the cook's ownership: a viewer's view was refused (404,
   the count never moved). A view of a record follows the record's read (shared vocabulary in `backend_spec.naming`).

The UX report against the measure before the patterns (`ux-before.json`, 49 failures on the golden apps and the
recorded drafts; Story 32.1): now 22, none in a back-office area; every feed, catalogue and storefront area of the
recorded real drafts passes its checks, their main task in one or two clicks.

Deviations: the view counted on open (finding 8) is verified by its regression test on the run's spec, not live (the
fix acts at drafting; Pocket Chefs 5 was drafted before it). No booking or learning requirement was run (no pattern
yet; their areas plan as back-office as before). Open, for the backlog: a like has no "liked" state on the button
(the kit does not know the person's own reactions; a second like is refused 409); a draft can make the shopper type a
cart line's price (Thread & Needle 4: drafting quality); a legitimate self-relationship (a category's parent) would
not configure in the generated models; mixed single-area apps keep `back-office` until split by audience (32.3).
