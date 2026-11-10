# Story 34.1 — Theme measures and the baseline

**Epic:** [34 — Designed themes](epic34_designed_themes.md) · **Requirements:** FR-48

## User story

As the user, I want to know whether designed themes are better than today's, so that the change is judged, not assumed.

## Steps

1. A pure function `theme_measures(theme)`: AA text contrast (the foreground on the background, the primary's own text), the primary readable on the background (3:1), neutrals tinted or pure grey, and cliché hits (named rules with the colours and fonts they catch).
2. `distinctness(themes)`: how far the apps' primaries are from each other in hue, and how many share a font pairing.
3. `make theme-report [ARGS=--baseline]` over the recorded reference drafts; the baseline `tests/fixtures/themes/baseline.json`.

## Acceptance criteria

- [x] The measures and the baseline are in the repository and tested.

## Status

Proposed 2026-11-10.

**Done 2026-11-10.** `drafting/themes.py`: `theme_measures` (text contrast, the primary's label, the primary on the
page, grey surfaces, cliché hits), `cliches` with named rules in `CLICHES` (`framework-blue`, `indigo-on-white`,
`cream-terracotta`, `acid-on-black`, `one-plain-sans`), `distinctness` (each app's nearest hue gap, the mean gap,
apps sharing their faces). `make theme-report [ARGS="--baseline" | "--html OUT"]` (`scripts/theme_report.py`) over
the six reference requirements in `tests/fixtures/themes/requirements/` (the five domains and the yarn shop); a theme
is measured as the app draws it (its leading look's pairing). Baseline `tests/fixtures/themes/baseline.json`, from
the recorded `domain-*-v10` drafts and the yarn shop's last real draft: 6/6 readable, 1 with a cliché (the yarn shop,
Inter throughout), 2 with grey surfaces (news, yarn), mean hue gap 101°, 2 apps sharing faces.

Deviation: the baseline was better than the epic's overview assumed (the yarn shop's latest draft had the requested
moss, not Tailwind's blue); the rules were tightened on real colours (a courier's vivid orange is not terracotta, a
deep navy is not the indigo look).
