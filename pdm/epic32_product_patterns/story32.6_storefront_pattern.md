# Story 32.6 — The `storefront` pattern

**Epic:** [32 — Product patterns](epic32_product_patterns.md) · **Requirements:** FR-46, FR-34 (payments) ·
**Depends on:** 32.3, 32.4

## User story

As a shopper, I want to browse products, put one in my cart from its page, change quantities in the cart, check out
and see my orders, so that buying works the way shops do, while the owner keeps their back-office.

## Context

- Golden: `plant-shop` (shopper and owner areas; collections, plants, cart items, orders and order items; payments
  plugin, `order.checkout`). Today the shopper's area plans cart items and orders as tables with form pages, like the
  owner's.
- Payments (Story 10.9, 22.7): checkout from the record's amount, `pay` in `allowedActions` until paid.

## Steps

1. **Descriptor** `templates/design/pattern/storefront/plugin.json`: `menu: [main, cart, mine]`; `children`:
   `interaction` → `inline`, `contribution` (reviews) → `inline` list with a sheet to write one, `part` → `tab`;
   `public: [contribution]`; `home: catalogue`; `never: [dashboard, edit-others]`.
2. **Cart shape from the contract** (code): an entity owned by the shopper that references the main entity with a
   quantity and is consumed by a checkout operation is the cart. Add to cart is the product's action (a quantity
   stepper when the field exists, else one click); the cart is one page: lines with quantity steppers and remove,
   the total from the contract's amounts when present, and the checkout action.
3. **Orders read-only for the shopper**: their orders list and record pages, with `pay` until paid and the order's
   parts as a list; no edit page for an order in the shopper's area.
4. Plugin gates for the new kit parts (the cart page, the stepper action) as Epic 30's D6 asks.
5. Tests: `plant-shop`'s shopper area plans under `storefront` and passes the 32.1 storefront checks; the owner's area
   stays `back-office` and unchanged; "put the first product in the cart" takes one click from the home.

## Acceptance criteria

- [x] `storefront` is `ready` and passes its gates; `plant-shop`'s shopper area passes the storefront checks.
- [x] The owner's area plans exactly as before.

## Verify

`make design-plugin-check KIND=pattern NAME=storefront`, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-09.

**Done 2026-11-09 (with deviations).** `templates/design/pattern/storefront` is `ready`. `plant-shop`'s shopper area
(its screens snapshot updated on purpose): the menu is Plants, Cart and My Orders; the product page carries **Add to
cart** (the cart's create with its quantity in the kit's dialog, the product from the route: two clicks from the home);
no shopper dashboard, no cart form page, no edit page or owner's action on products; orders read-only with `pay` until
paid; reviews would be public (`contribution`, 32.4). The owner's `management` area is byte-identical
(`test_planner_patterns.py`). The shopper area passes every storefront check; the UX baseline went from 29 failures to
24, all of them in areas still planned as `back-office` (mixed areas, and the archetypes without a pattern:
`catalogue`, `booking`, `learning`).

The registry's name scan (`test_no_hand_written_list_of_plugin_names_remains`) leaves the `pattern` kind out: a
pattern is named after its one archetype (the descriptor checks it), so the archetype vocabulary is the source its
names follow.

Found by the suite after promoting the pattern: a recorded draft, "a watering log for my houseplants" (no logins),
takes a `storefront` look from its words (a "plant shop" product row); as a look that was harmless, as behaviour it
dropped the owner's own dashboard. A pattern now names its `needs` (`signIn`: people sign in; `purchase`: a person's
cart of the main entity, or a payment; `patterns.pattern_fits`), and an area whose archetype's pattern needs what the
contract lacks is `back-office` (`feed` needs `signIn`, `storefront` both).

Deviations: the cart is the cart entity's own list page (lines with edit and remove), not a new cart page with
quantity steppers and a total (step 2's kit parts are not built); checkout stays the orders page's collection action,
as the contract places it. Collections leave the shopper's menu (the menu is the main entity, the cart and the
person's own records); they remain the plant list's filter and the catalogue home's groups.
