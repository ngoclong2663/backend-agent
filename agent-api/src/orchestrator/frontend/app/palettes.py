"""Recipe palettes from the app's own colours (2026-11-10). Five recipes (neon, cinema, luxe, terminal, paper) used to
set every colour token themselves: a neon look painted a cyan primary on violet whatever the app's theme or the user's
requested colours were. A recipe now names a palette **mood** (`plugin.json` `palette`) and code derives its tokens
from the app's built palette (`theme.build_theme`): the recipe keeps its character (dark and glowing, quiet, high
contrast, neutral greys, warm paper), the hues stay the app's, and every text token is made readable after."""

import colorsys
from typing import Any

from src.modules.shared.domain.frontend_spec.design_registry import registry

from ..theme import _hex, _readable, _rgb, contrast, luminance, mix, on

MOODS = ("tinted-dark", "quiet-dark", "contrast", "neutral", "paper")
DARK_MOODS = frozenset({"tinted-dark", "quiet-dark"})  # looks that are dark only: the app becomes a dark-scheme app
PAPER, PAPER_INK, PAPER_NIGHT = "#f4ecdc", "#3a2e22", "#2a231b"
SURFACES = ("background", "card", "popover", "muted", "secondary", "accent", "border", "input")
SIDEBAR = ("sidebar", "sidebar-accent", "sidebar-border")


def mood_of(recipe: str | None) -> str | None:
    plugin = registry().get("recipe", recipe) if recipe else None
    return getattr(plugin, "palette", None) if plugin is not None else None


def _grey(color: str, amount: float = 1.0) -> str:
    """`color` with `amount` of its saturation taken out (its lightness kept)."""
    rgb = _rgb(color)
    if rgb is None:
        return color
    h, light, s = colorsys.rgb_to_hls(*rgb)
    return _hex(colorsys.hls_to_rgb(h, light, s * (1 - amount)))


def _m(first: str, second: str, amount: float) -> str:
    return mix(first, second, amount) or first


def _tokens(base: dict[str, str], surfaces: dict[str, str], foreground: str, primary: str) -> dict[str, str]:
    """A whole palette from the mood's surfaces, text and primary: what sits on them is derived and made readable."""
    out = {**base, **surfaces}
    background = out["background"]
    foreground = _readable(foreground, background, 7.0)
    out.update(
        {
            "foreground": foreground,
            "card-foreground": foreground,
            "popover-foreground": foreground,
            "secondary-foreground": foreground,
            "accent-foreground": foreground,
            "sidebar-foreground": foreground,
            "sidebar-accent-foreground": foreground,
            "muted-foreground": _readable(_m(foreground, background, 0.4), background, 4.5),
            "primary": primary,
            "primary-foreground": on(primary),
            "ring": primary,
            "sidebar-primary": primary,
            "sidebar-primary-foreground": on(primary),
            "chart-1": primary,
            "chart-3": _m(primary, foreground, 0.4),
            "chart-5": _m(primary, background, 0.5),
        }
    )
    out["popover"] = out.get("popover") or out["card"]
    out["input"] = out.get("input") or out["border"]
    return out


def mood_palette(mood: str, palette: dict[str, str], dark: bool) -> dict[str, str]:
    """The `mood`'s tokens from one built palette of the app. Dark or light is the palette's own (a dark-scheme
    app's `light` block holds dark colours); `dark` only breaks a tie for a palette without a background."""
    p = dict(palette)
    lum = luminance(p.get("background") or "")
    dark = lum < 0.5 if lum is not None else dark
    bg, fg, primary, second = p["background"], p["foreground"], p["primary"], p.get("chart-2") or p["primary"]
    if mood == "tinted-dark":  # neon: dark surfaces tinted with the app's primary, a bright primary that glows
        bg = _m(bg, primary, 0.1)
        surfaces = {
            "background": bg,
            "card": _m(_m(bg, fg, 0.05), primary, 0.06),
            "muted": _m(_m(bg, fg, 0.09), primary, 0.08),
            "secondary": _m(_m(bg, fg, 0.08), second, 0.2),
            "accent": _m(bg, primary, 0.2),
            "border": _m(bg, primary, 0.45),
            "sidebar": _m(bg, "#000000", 0.15),
            "sidebar-accent": _m(bg, primary, 0.2),
            "sidebar-border": _m(bg, primary, 0.45),
        }
        surfaces["input"] = surfaces["border"]
        return _tokens(p, surfaces, fg, _readable(primary, bg, 4.5))
    if mood == "quiet-dark":  # cinema: near-neutral dark surfaces, the media and the app's primary carry the colour
        surfaces = {key: _grey(p[key], 0.85) for key in (*SURFACES, *SIDEBAR) if key in p}
        surfaces["background"] = _m(surfaces["background"], "#000000", 0.25)
        surfaces["sidebar"] = _m(surfaces["background"], "#000000", 0.2)
        return _tokens(p, surfaces, _grey(fg, 0.85), _readable(primary, surfaces["background"], 3.0))
    if mood == "contrast":  # luxe: the page near white (or black), ink-dark text, the primary deepened toward the ink
        page = "#000000" if dark else "#ffffff"
        bg = _m(bg, page, 0.6)
        ink = _m(fg, "#ffffff" if dark else "#000000", 0.4)
        surfaces = {
            "background": bg,
            "card": bg,
            "muted": _m(bg, ink, 0.05),
            "secondary": _m(bg, ink, 0.06),
            "accent": _m(bg, ink, 0.06),
            "border": _m(bg, ink, 0.14),
            "sidebar": _m(bg, ink, 0.025),
            "sidebar-accent": _m(bg, ink, 0.06),
            "sidebar-border": _m(bg, ink, 0.14),
        }
        return _tokens(p, surfaces, ink, _readable(_m(primary, ink, 0.3), bg, 4.5))
    if mood == "neutral":  # terminal: neutral greys, hairlines, the app's primary as the one colour
        surfaces = {key: _grey(p[key]) for key in (*SURFACES, *SIDEBAR) if key in p}
        surfaces["border"] = surfaces["input"] = surfaces["sidebar-border"] = _m(surfaces["background"], _grey(fg), 0.3)
        return _tokens(p, surfaces, _grey(fg), _readable(primary, surfaces["background"], 4.5))
    if mood == "paper":  # paper: warm paper surfaces and ink, ruled lines, the app's primary
        paper = PAPER_NIGHT if dark else PAPER
        bg = _m(bg, paper, 0.55)
        ink = _m(fg, "#f1e8d6" if dark else PAPER_INK, 0.3)
        surfaces = {
            "background": bg,
            "card": _m(bg, "#000000" if dark else "#ffffff", 0.35),
            "muted": _m(bg, ink, 0.06),
            "secondary": _m(bg, ink, 0.08),
            "accent": _m(bg, ink, 0.08),
            "border": _m(bg, ink, 0.16),
            "sidebar": _m(bg, ink, 0.035),
            "sidebar-accent": _m(bg, ink, 0.08),
            "sidebar-border": _m(bg, ink, 0.16),
        }
        return _tokens(p, surfaces, ink, _readable(primary, bg, 3.0))
    return p


def with_mood(theme: dict[str, Any], mood: str | None) -> dict[str, Any]:
    """A built theme (`build_theme`) with the mood's palette in each scheme; the theme as it is without a mood."""
    if mood not in MOODS:
        return theme
    out = dict(theme)
    dark_light = theme.get("colorScheme") == "dark"  # a dark-scheme app's `light` block holds its dark palette
    if isinstance(theme.get("light"), dict):
        out["light"] = mood_palette(mood, theme["light"], dark=dark_light)
    if isinstance(theme.get("dark"), dict):
        out["dark"] = mood_palette(mood, theme["dark"], dark=True)
    return out


def text_contrast(palette: dict[str, str]) -> dict[str, float]:
    """The palette's text pairs (tests and the report): text, muted text and the primary's label."""
    pairs = {
        "foreground": ("foreground", "background"),
        "muted-foreground": ("muted-foreground", "background"),
        "card-foreground": ("card-foreground", "card"),
        "primary-foreground": ("primary-foreground", "primary"),
    }
    return {name: round(contrast(palette[a], palette[b]) or 0, 2) for name, (a, b) in pairs.items()}
