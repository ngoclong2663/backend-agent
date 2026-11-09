"""Fonts that load (Story 17.7): the curated set bundled with the pinned frontend base as `@fontsource` packages.

A theme font in this set is imported from its package (`src/app/fonts.ts`), so it installs offline from the
pre-warmed pnpm store and ships with the static export; any other name is only written into the CSS font stack and
shows as the fallback on machines without it, so the validator suggests the closest bundled font. The set comes from
the pairings in UI UX Pro Max's `typography.csv` (docs/research/design-skills.md): its most used families, the theme
presets' fonts, and two monospace fonts; Story 20.3 added eight faces with more character (OFL, docs/research/
design-diversity.md). Adding a font: add it here, then `make frontend-base` and `make runner-node`.
"""

import difflib
from dataclasses import dataclass
from typing import Literal

FontCategory = Literal["sans", "serif", "display", "mono"]
LOADED_WEIGHTS = (400, 500, 600, 700)  # body, medium, semibold, bold: what the section library uses


@dataclass(frozen=True)
class Font:
    name: str
    category: FontCategory
    weights: tuple[int, ...] = LOADED_WEIGHTS
    # Story 20.3: average glyph width against Inter (rough, by eye at display sizes). The hero sizes its headline by
    # character count, so a wide face shrinks the display steps to keep the headline on two lines (frontend_theme).
    width: float = 1.0
    # Story 23.8: the scripts the face draws; a Japanese face is stacked after the Latin one (`ja_fonts`)
    scripts: tuple[str, ...] = ("latin",)

    @property
    def package(self) -> str:
        return "@fontsource/" + self.name.lower().replace(" ", "-")


FONTS: dict[str, Font] = {
    font.name: font
    for font in (
        Font("Inter", "sans"),
        Font("Space Grotesk", "sans"),
        Font("Plus Jakarta Sans", "sans"),
        Font("DM Sans", "sans"),
        Font("Outfit", "sans"),
        Font("IBM Plex Sans", "sans"),
        Font("Poppins", "sans", width=1.1),
        Font("Rubik", "sans"),
        Font("Nunito", "sans"),
        Font("Source Sans 3", "sans"),
        Font("Roboto", "sans"),
        Font("Montserrat", "sans", width=1.12),
        Font("Atkinson Hyperlegible", "sans", (400, 700), width=1.05),
        Font("Playfair Display", "display"),
        Font("Cormorant Garamond", "display"),
        Font("EB Garamond", "serif"),
        Font("Crimson Pro", "serif"),
        Font("Source Serif 4", "serif"),
        Font("Lora", "serif"),
        Font("Merriweather", "serif", width=1.08),
        Font("JetBrains Mono", "mono", width=1.2),
        Font("Space Mono", "mono", (400, 700), width=1.25),
        # Story 20.3: faces with character, so directions are not limited to the faces every generated site uses.
        Font("Fraunces", "display"),
        Font("Instrument Serif", "display", (400,)),
        Font("Newsreader", "serif"),
        Font("Bricolage Grotesque", "sans"),
        Font("Syne", "sans", width=1.18),
        Font("Archivo", "sans"),
        Font("Unbounded", "sans", width=1.38),
        Font("Familjen Grotesk", "sans"),
    )
}
# Story 23.8: Japanese faces, bundled in the base but kept apart from FONTS, so no Latin pairing, suggestion or static
# site picks one; apps stack one after their Latin face (`frontend/app/typesetting.py`). Fontsource splits them by
# unicode-range: a page loads only the slices it uses.
JA_FONTS: dict[str, Font] = {
    font.name: font
    for font in (
        Font("Noto Sans JP", "sans", (400, 500, 700), scripts=("ja", "latin")),
        Font("Noto Serif JP", "serif", (400, 600, 700), scripts=("ja", "latin")),
        Font("Zen Kaku Gothic New", "sans", (400, 500, 700), scripts=("ja", "latin")),
        Font("BIZ UDPGothic", "sans", (400, 700), scripts=("ja", "latin")),
        Font("Shippori Mincho", "serif", (400, 600, 700), scripts=("ja", "latin")),
        Font("M PLUS 1p", "sans", (400, 500, 700), scripts=("ja", "latin")),
    )
}
JA_FALLBACK = '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif'
JA_SERIF_FALLBACK = '"Hiragino Mincho ProN", "Yu Mincho", serif'


def ja_fonts() -> list[str]:
    """The bundled Japanese faces (Story 23.8)."""
    return list(JA_FONTS)


_DEFAULT_BY_CATEGORY: dict[FontCategory, str] = {
    "sans": "Inter",
    "serif": "Source Serif 4",
    "display": "Playfair Display",
    "mono": "JetBrains Mono",
}
_SERIF_HINTS = ("serif", "garamond", "baskerville", "caslon", "didot", "bodoni", "times", "georgia", "slab")
_DISPLAY_HINTS = ("display", "playfair", "abril", "fatface", "cormorant", "fraunces", "instrument serif")
_MONO_HINTS = ("mono", "code", "courier")


def bundled_font(name: str) -> Font | None:
    return FONTS.get(name)


def guess_category(name: str) -> FontCategory:
    """The kind of an unknown family, from its name ("Fira Code" → mono, "Libre Baskerville" → serif)."""
    lowered = name.lower()
    if any(hint in lowered for hint in _MONO_HINTS):
        return "mono"
    if any(hint in lowered for hint in _DISPLAY_HINTS):
        return "display"
    if "sans" not in lowered and any(hint in lowered for hint in _SERIF_HINTS):
        return "serif"
    return "sans"


def font_category(name: str) -> FontCategory:
    font = FONTS.get(name)
    return font.category if font else guess_category(name)


def closest_font(name: str) -> str:
    """The bundled font to suggest for `name`: a near spelling ("Playfair" → Playfair Display, "inter" → Inter),
    else the default of its kind."""
    by_lower = {font.lower(): font for font in FONTS}
    if name.lower() in by_lower:
        return by_lower[name.lower()]
    category = guess_category(name)
    same_kind = [font.name for font in FONTS.values() if font.category == category]
    lowered = name.lower()
    prefixed = [font for font in same_kind if font.lower().startswith(lowered) or lowered.startswith(font.lower())]
    if prefixed:
        return prefixed[0]
    close = difflib.get_close_matches(lowered, [font.lower() for font in same_kind], n=1, cutoff=0.75)
    return by_lower[close[0]] if close else _DEFAULT_BY_CATEGORY[category]


def font_width(name: str) -> float:
    """A bundled font's width against Inter; 1.0 for fonts outside the set."""
    font = FONTS.get(name)
    return font.width if font else 1.0


def font_imports(*names: str) -> list[str]:
    """CSS files to import for these theme fonts (bundled ones only; each family once)."""
    imports: list[str] = []
    for name in dict.fromkeys(names):
        font = FONTS.get(name)
        if font is not None:
            imports += [f"{font.package}/{weight}.css" for weight in font.weights]
    return imports


# The requirement's kind of heading face (Story 23.13 `AppRequestedStyle.headingFont`) → the bundled faces of that kind
GEOMETRIC_FACES = frozenset(
    {"Outfit", "Poppins", "Montserrat", "Space Grotesk", "Plus Jakarta Sans", "DM Sans", "Syne", "Unbounded"}
)
ROUNDED_FACES = frozenset({"Nunito", "Rubik"})


def heading_kind_fits(kind: str, font: str | None) -> bool:
    """Whether a face is of the requested kind (`serif`, `sans`, `geometric`, `rounded`, `display`, `mono`)."""
    if not font:
        return False
    if kind == "geometric":
        return font in GEOMETRIC_FACES
    if kind == "rounded":
        return font in ROUNDED_FACES
    if kind == "serif":
        return font_category(font) in ("serif", "display")
    return font_category(font) == kind


def font_scripts(name: str) -> tuple[str, ...]:
    """The scripts a bundled face covers (`latin`; `ja` for the Japanese faces), `()` for an unbundled name."""
    font = FONTS.get(name) or JA_FONTS.get(name)
    return font.scripts if font else ()
