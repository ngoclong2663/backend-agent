# Epic 34 — Designed themes: a palette and type made for the product

## Overview

Proposed and started 2026-11-10 at the user's request. An app's colours and type come from UI UX Pro Max's data: code
matches the requirement to a product category and takes that category's palette and font pair; the requirement's own
look (`requested`, Story 23.13) is painted on top. When the category and the words agree the result is good (the
courier app: delivery → warm orange, the user asked for orange); when they don't, it is generic: the yarn shop asked for
"crisp, minimal, Scandinavian, one moss green accent" and got Tailwind's default blue `#2563eb`, emerald and Inter for
headings and body, with the moss green painted over parts of it.

This epic adds a **design turn**: one LLM turn, after the draft, that designs the theme for this product. The method is
a design lead's, written in our own words: start from the product's world and the requirement's look; a small set of
named colours with one bold accent; neutrals tinted toward the accent; a display face paired with a body face from the
bundled set (a font pairing plugin, Epic 30); never the looks that read as machine-made (cream and terracotta, a
purple-to-blue gradient, Tailwind's default blue with Inter everywhere, near-black with one acid green). **Code checks
every pick** (contrast in light and the derived dark, the pairing exists, the clichés, the requested accent) and
repairs once; the design data stays as the fallback.

**Requirements:** FR-48 (new: designed themes), extends FR-44 (design plugins) and Story 23.13 (the requested look).

## Decisions

| # | Decision | Instead of |
|---|---|---|
| D1 | **One design turn per app draft**, on the draft engine, structured output: a concept line, six colours (primary, secondary, accent, background, foreground, muted), a font pairing from the registry, corners and density | The category palette alone |
| D2 | **Fonts through the font pairing plugins** (Epic 30): the turn picks a pairing's name, so every face is bundled; the first look takes it | Free font names the kit may not have |
| D3 | **Code enforces what a prompt can only ask**: AA text contrast on the light palette (the dark one is derived and checked by `frontend/theme.py` as today), a primary readable as a button, neutrals never pure grey, a cliché list, the requested accent kept | Trusting the model |
| D4 | **One repair, then the fallback**: a theme that fails the checks is asked again once with the reasons; still failing, the design data's theme stays | A loop |
| D5 | **The requirement still wins**: its requested colours and scheme are in the brief and are applied after (`follow_requested`) | The design turn overriding the user |
| D6 | **Measured**: themes of the reference requirements before and after (cliché hits, contrast, how different the apps are from each other), and a blind page of before/after pairs the user picks from | Judging by taste alone |
| D7 | **Switchable**: `DESIGN_THEMES` (default on); off restores today's themes byte for byte | A change no one can turn off |

## Stories

| Story | What |
|---|---|
| [34.1](story34.1_theme_measures.md) | Theme measures and the baseline: cliché hits, contrast, distinctness over the reference drafts |
| [34.2](story34.2_design_turn.md) | The design turn: `design_theme@v1` (our own guidance), its answer schema, the brief |
| [34.3](story34.3_checks_and_repair.md) | Code checks, one repair, the fallback; neutrals tinted by code |
| [34.4](story34.4_wiring.md) | Wiring into `draft_app`: the theme and the first look's pairing; notes; `DESIGN_THEMES` |
| [34.5](story34.5_final_check.md) | Final check: real drafts, the measures against the baseline, the blind page |

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations, Story 34.5).** The design turn designs every reference app's theme in one
turn; clichés 1 → 0 and grey surfaces 2 → 0 against the baseline. The blind comparison is the user's to make.
