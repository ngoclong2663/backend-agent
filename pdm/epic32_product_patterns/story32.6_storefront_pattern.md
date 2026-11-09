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

- [ ] `storefront` is `ready` and passes its gates; `plant-shop`'s shopper area passes the storefront checks.
- [ ] The owner's area plans exactly as before.

## Verify

`make design-plugin-check KIND=pattern NAME=storefront`, `make app-design-report`, `make test`.

## Status

Proposed 2026-11-09.
