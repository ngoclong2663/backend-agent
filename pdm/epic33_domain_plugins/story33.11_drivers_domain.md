# Story 33.11 — Drivers (courier)

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.7

## User story

As a driver I want to go online, take an offer in one tap and follow clear steps from pickup to drop-off; as a
customer I want to see where my delivery is; as dispatch I want to create deliveries and see who carries what.

## Context

- A small domain: one delivery moves from a shop to a customer. No maps or GPS (D10): addresses are text, the route is
  a link out to a maps site.

## Steps

1. **Domain** `templates/domains/drivers/`: roles `delivery` (pickup and drop-off addresses, contact names and phones,
   parcel size, fee, the customer), `stop` (optional; a delivery's pickup and drop-off as stops); areas Drivers
   (mobile-first, a new `courier` pattern), Customers (track), Dispatch (`back-office`); required features dispatch,
   availability, tracking; optional proof of delivery, earnings.
2. **Features**:
   - `dispatch` (`attachesTo: delivery`): states offered → accepted → at pickup → picked up → at drop-off →
     delivered, or failed (with a reason) or cancelled; an offer goes to online drivers and the first to accept takes
     it (a concurrency rule, Story 10.10); one active delivery per driver; dispatch can also assign directly;
   - `availability` (`attachesTo: person`, drivers): online and offline; only online drivers see offers;
   - `tracking` (`attachesTo: delivery`): every state change with its time, shown to the customer as a timeline with
     the driver's first name;
   - `proof-of-delivery`: a photo (storage plugin) or the customer's four-digit code before Delivered;
   - `earnings`: a ledger line per delivered job (fee, tip), today and this week, per driver.
3. **Type `courier`**:
   - driver: an Online switch on top; Offers (newest first, fee and distance text, Accept in one tap, refreshed by
     polling); Active job (`AppSteps`: the next action as one big button, the address with "Open in maps", call the
     contact); History; Earnings;
   - customer: a delivery's tracking timeline and the driver's first name;
   - dispatch: create a delivery, the board of deliveries by state, drivers online.
4. **The reference requirement** generated end to end and its tasks passing.

## Acceptance criteria

- [ ] A driver accepts the newest offer in one tap, moves it through every step to Delivered with a photo, and sees
      the fee in today's earnings; the customer's timeline shows each step; two drivers can't take the same offer.

## Verify

`make domain-check NAME=drivers`, `make test` (including the concurrency rule's scenarios), `make kit-test`, the real
run in the UI.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** `templates/domains/drivers` (role delivery; areas drivers, customers, dispatch)
with **availability** (an `Availability` row per driver: online while it exists; `AppPresence`, the Online switch, first
on the driver's home through the `courier` type), **proof-of-delivery** (a target field: the delivery's photo becomes an
image, and the move to the delivered state, a transition or the model's own "complete" operation, asks for it in a
dialog) and **tracking** (kit-only: `AppTimeline` shows the delivery's status as steps, in the order its states are
declared). The real v10 draft drafted a customer role (the domain offers the area) and passes **4 of 5** tasks
(baseline 2): accept in one tap, deliver with a photo, go online, follow the steps; earnings sat two clicks away in that
draft (the model's figures, not a domain feature).

Deviations: dispatch is the model's own flow (offers, the first to accept, one job at a time are its rules when
drafted); earnings are the model's aggregates; offers are not limited to online drivers.
