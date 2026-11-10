"""Epic 34: designed themes. One LLM turn designs an app's colours and type for its product (`design_theme@v1`); code
measures every theme (contrast, tinted neutrals, the looks that read as machine-made), checks the turn's answer,
tints grey neutrals itself, asks once more with the reasons, and keeps the design data's theme when it still fails."""

import colorsys
import itertools
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from src.engines import PromptLibrary
from src.engines.llm import LlmError
from src.modules.shared.domain.frontend_spec.design_registry import registry as design_registry
from src.modules.shared.domain.frontend_spec.fonts import heading_kind_fits

from ..frontend.theme import _rgb, contrast, luminance, mix, on

PROMPT = ("design_theme", "v1")
COLOR_KEYS = ("primary", "accent", "secondary", "muted", "background", "foreground")
RADII = ["none", "sm", "md", "lg", "full"]
DENSITIES = ["compact", "comfortable"]
TEXT_CONTRAST = 4.5  # WCAG AA for body text
BUTTON_CONTRAST = 3.0  # a primary button against the page (WCAG non-text contrast)
NEAR = 0.12  # how close two colours are (RGB distance, 0..1.73) to count as the same colour
STOCK_BLUES = ("#2563eb", "#3b82f6", "#1d4ed8", "#0ea5e9", "#0284c7")  # Tailwind's blue-600/500/700, sky-500/600
PLAIN_SANS = ("Inter", "Roboto", "Open Sans", "Arial", "Helvetica", "system-ui")

Designer = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any] | None]]  # (rendered prompt, schema) → answer


def _hls(color: str | None) -> tuple[float, float, float] | None:
    rgb = _rgb(color or "")
    if rgb is None:
        return None
    h, light, s = colorsys.rgb_to_hls(*rgb)
    return h * 360, light, s


def distance(first: str | None, second: str | None) -> float | None:
    a, b = _rgb(first or ""), _rgb(second or "")
    if a is None or b is None:
        return None
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def hue_gap(first: str | None, second: str | None) -> float | None:
    a, b = _hls(first), _hls(second)
    if a is None or b is None:
        return None
    gap = abs(a[0] - b[0]) % 360
    return min(gap, 360 - gap)


FAMILY_HUE = 25  # degrees: a colour named in words ("leaf green") is followed by any shade within this hue


def keeps(key: str, color: str | None, wanted: str | None, requirement: str = "") -> bool:
    """Epic 34: the designed colour follows the user's. A hex the requirement itself gives is kept as it is (within a
    hair); a colour named only in words, which the draft turned into a stock hex, is followed by its family: the
    accent's hue, the page's lightness."""
    if not wanted or _rgb(color or "") is None or _rgb(wanted) is None:
        return False
    near = 2 * NEAR if key == "primary" else NEAR
    if wanted.lower() in requirement.lower() or (distance(color, wanted) or 0) <= near:
        return (distance(color, wanted) or 0) <= near
    if key == "background":
        light, asked = luminance(color or "") or 0, luminance(wanted) or 0
        return (light > 0.6 and asked > 0.6) or (light < 0.2 and asked < 0.2)
    ours, theirs = _hls(color), _hls(wanted)
    if ours is None or theirs is None:
        return False
    if theirs[2] < 0.15:  # a grey or black accent: a grey or black one
        return ours[2] < 0.15
    return ours[2] >= 0.15 and (hue_gap(color, wanted) or 0) <= FAMILY_HUE


def _grey(color: str | None) -> bool:
    """A pure grey: no hue to speak of, neither white nor black (a chosen white or near-black page is fine)."""
    hls = _hls(color)
    return hls is not None and hls[2] < 0.04 and 0.04 < hls[1] < 0.98


# The looks that read as machine-made (decision D3). Each rule names the colours and fonts it catches.
def _framework_blue(colors: dict[str, str], fonts: tuple[str, str]) -> bool:
    return any((distance(colors.get("primary"), blue) or 9) < NEAR for blue in STOCK_BLUES)


def _indigo_on_white(colors: dict[str, str], fonts: tuple[str, str]) -> bool:
    """A saturated mid-to-light indigo or violet (#6366f1, #8b5cf6) on white; a deep navy ink is not it."""
    primary, background = _hls(colors.get("primary")), _hls(colors.get("background"))
    mid = bool(primary and 0.4 <= primary[1] <= 0.8)
    return bool(
        mid and primary and background and 232 <= primary[0] <= 280 and primary[2] > 0.45 and background[1] > 0.9
    )


def _cream_terracotta(colors: dict[str, str], fonts: tuple[str, str]) -> bool:
    primary, background = _hls(colors.get("primary")), _hls(colors.get("background"))
    # terracotta is a muted clay: a vivid orange (a courier's high-visibility orange) is not caught
    cream = bool(background and 25 <= background[0] <= 55 and background[1] > 0.88 and background[2] > 0.25)
    red_orange = bool(primary and (primary[0] <= 28 or primary[0] >= 355))
    clay = bool(primary and red_orange and 0.3 <= primary[1] <= 0.6 and 0.3 < primary[2] < 0.75)
    return cream and clay


def _acid_on_black(colors: dict[str, str], fonts: tuple[str, str]) -> bool:
    primary = _hls(colors.get("primary"))
    dark = (luminance(colors.get("background") or "") or 1) < 0.02
    return bool(dark and primary and 65 <= primary[0] <= 150 and primary[2] > 0.7 and primary[1] > 0.4)


def _one_plain_sans(colors: dict[str, str], fonts: tuple[str, str]) -> bool:
    return fonts[0] == fonts[1] and fonts[0] in PLAIN_SANS


CLICHES: tuple[tuple[str, str, Callable[[dict[str, str], tuple[str, str]], bool]], ...] = (
    ("framework-blue", "the stock framework blue as the accent", _framework_blue),
    ("indigo-on-white", "a saturated indigo or violet accent on white", _indigo_on_white),
    ("cream-terracotta", "a terracotta accent on warm cream", _cream_terracotta),
    ("acid-on-black", "one acid green on near-black", _acid_on_black),
    ("one-plain-sans", "one plain sans for headings and text", _one_plain_sans),
)
COLOR_CLICHES = {"framework-blue", "indigo-on-white", "cream-terracotta", "acid-on-black"}


def _fonts(theme: dict[str, Any]) -> tuple[str, str]:
    typography = theme.get("typography") or {}
    heading = typography.get("headingFont") or "Inter"
    return heading, typography.get("bodyFont") or heading


def cliches(theme: dict[str, Any]) -> list[str]:
    colors = theme.get("colors") or {}
    fonts = _fonts(theme)
    return [name for name, _, caught in CLICHES if caught(colors, fonts)]


def theme_measures(theme: dict[str, Any]) -> dict[str, Any]:
    """Story 34.1: one theme measured (its light colours, the fonts it is drawn with)."""
    colors = theme.get("colors") or {}
    primary, background = colors.get("primary") or "", colors.get("background") or ""
    text = contrast(colors.get("foreground") or "", background)
    button_text = contrast(on(primary), primary) if _rgb(primary) else None
    button = contrast(primary, background)
    grey = [key for key in ("background", "secondary", "muted") if _grey(colors.get(key))]
    found = cliches(theme)
    return {
        "primary": primary,
        "fonts": list(_fonts(theme)),
        "textContrast": round(text, 2) if text else None,
        "buttonText": round(button_text, 2) if button_text else None,
        "buttonOnPage": round(button, 2) if button else None,
        "readable": bool(text and text >= TEXT_CONTRAST and button_text and button_text >= TEXT_CONTRAST),
        "greyNeutrals": grey,
        "cliches": found,
    }


def distinctness(themes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Story 34.1: how different the apps are: the primaries' hue gaps (each app to its nearest other) and how many
    apps share their heading and body faces with another."""
    primaries = {name: (t.get("colors") or {}).get("primary") for name, t in themes.items()}
    nearest = {}
    for name, color in primaries.items():
        gaps = [g for other, c in primaries.items() if other != name and (g := hue_gap(color, c)) is not None]
        if gaps:
            nearest[name] = round(min(gaps), 1)
    fonts = [_fonts(t) for t in themes.values()]
    shared = sum(1 for pair in fonts if fonts.count(pair) > 1)
    pairs = [hue_gap(a, b) for a, b in itertools.combinations(primaries.values(), 2)]
    pairs = [p for p in pairs if p is not None]
    return {
        "nearestHueGap": nearest,
        "meanHueGap": round(sum(pairs) / len(pairs), 1) if pairs else None,
        "sharedFonts": shared,
    }


def tint_neutrals(colors: dict[str, str]) -> list[str]:
    """Story 34.3: a pure-grey surface tinted toward the primary (in place); returns the keys changed."""
    changed = []
    for key in ("background", "secondary", "muted"):
        if _grey(colors.get(key)) and _rgb(colors.get("primary") or ""):
            colors[key] = mix(colors[key], colors["primary"], 0.06) or colors[key]
            changed.append(key)
    return changed


def answer_schema(pairings: list[str]) -> dict[str, Any]:
    hex_color = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
    return {
        "type": "object",
        "properties": {
            "concept": {"type": "string", "maxLength": 160},
            "colors": {
                "type": "object",
                "properties": {key: hex_color for key in COLOR_KEYS},
                "required": list(COLOR_KEYS),
                "additionalProperties": False,
            },
            "fontPairing": {"type": "string", "enum": pairings},
            "radius": {"type": "string", "enum": RADII},
            "density": {"type": "string", "enum": DENSITIES},
            "why": {"type": "string", "maxLength": 300},
        },
        "required": ["concept", "colors", "fontPairing", "radius", "density", "why"],
        "additionalProperties": False,
    }


def check_theme(answer: Any, requested: dict[str, Any] | None, pairings: list[str], requirement: str = "") -> list[str]:
    """Story 34.3: why a designed theme can't be used (empty: it can). Grey neutrals are no reason: code tints them."""
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    requested = requested or {}
    colors = answer.get("colors") if isinstance(answer.get("colors"), dict) else {}
    reasons = [f"colors.{key} is not a #rrggbb colour" for key in COLOR_KEYS if not _rgb(str(colors.get(key) or ""))]
    if answer.get("fontPairing") not in pairings:
        reasons.append(f"fontPairing must be one of {', '.join(pairings)}")
    for key, allowed in (("radius", RADII), ("density", DENSITIES)):
        if answer.get(key) not in allowed:
            reasons.append(f"{key} must be one of {', '.join(allowed)}")
    if any(reason.startswith("colors.") for reason in reasons):
        return reasons
    text = contrast(colors["foreground"], colors["background"]) or 0
    if text < TEXT_CONTRAST:
        reasons.append(f"the foreground on the background is {text:.1f}:1, it needs {TEXT_CONTRAST}:1")
    accent = requested.get("accent")
    own = keeps("primary", colors["primary"], accent, requirement)  # the user's own accent (or its family)
    button = contrast(colors["primary"], colors["background"]) or 0
    if button < BUTTON_CONTRAST and not own:  # the user's accent is kept readable by `follow_requested`
        reasons.append(f"the primary on the background is {button:.1f}:1, a button needs {BUTTON_CONTRAST}:1")
    label = contrast(on(colors["primary"]), colors["primary"]) or 0
    if label < TEXT_CONTRAST:
        reasons.append(f"no text colour reads on the primary ({label:.1f}:1): make it lighter or darker")
    if accent and not own:
        exact = accent.lower() in requirement.lower()
        reasons.append(
            f"the user asked for the accent {accent}: the primary must be it or very close"
            if exact
            else f"the user asked for an accent like {accent}: the primary must keep its hue"
        )
    if requested.get("scheme") == "dark" and (luminance(colors["background"]) or 0) > 0.2:
        reasons.append("the user asked for a dark app: the background must be dark and the foreground light")
    kind = requested.get("headingFont")
    plugin = design_registry().get("font-pairing", answer.get("fontPairing"))
    if kind and plugin is not None and not heading_kind_fits(kind, plugin.heading):
        reasons.append(f"the user asked for {kind} headings: choose a pairing with a {kind} display face")
    if plugin is not None:
        fonts = (plugin.heading, plugin.body)
        excused = COLOR_CLICHES if accent else set()  # the user's own colour is followed, cliché or not
        for name, what, caught in CLICHES:
            if name not in excused and caught(colors, fonts):
                reasons.append(f"{what} ({name}) is a look to avoid")
    return reasons


def with_requested_accent(answer: Any, requested: dict[str, Any] | None, requirement: str = "") -> tuple[Any, bool]:
    """Story 34.3: code sets the accent the user asked for when the answer moved away from it (no repair needed);
    returns the answer (a copy when changed) and whether it changed."""
    accent = (requested or {}).get("accent")
    colors = answer.get("colors") if isinstance(answer, dict) and isinstance(answer.get("colors"), dict) else None
    if not accent or colors is None or _rgb(str(colors.get("primary") or "")) is None:
        return answer, False
    if keeps("primary", colors["primary"], accent, requirement):
        return answer, False
    moved = {**colors, "primary": accent}
    if _rgb(str(colors.get("accent") or "")) is None or (distance(colors["accent"], colors["primary"]) or 0) <= NEAR:
        moved["accent"] = accent  # the accent was the primary's twin: it follows
    return {**answer, "colors": moved}, True


def plain_pairing(name: str) -> bool:
    """A pairing that is one plain sans throughout: never offered to the design turn (it is a cliché)."""
    plugin = design_registry().get("font-pairing", name)
    return plugin is not None and _one_plain_sans({}, (plugin.heading, plugin.body))


def designed(theme: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """The data's theme with the designed colours, radius and density (a copy); the destructive colour, the style and
    the direction stay. The fonts come from the pairing (the first look's, `pairing_theme`)."""
    plugin = design_registry().get("font-pairing", answer["fontPairing"])
    colors = {**(theme.get("colors") or {}), **{key: answer["colors"][key].lower() for key in COLOR_KEYS}}
    out = {**theme, "colors": colors, "radius": answer["radius"], "density": answer["density"]}
    if plugin is not None:
        out["typography"] = {**(theme.get("typography") or {}), "headingFont": plugin.heading, "bodyFont": plugin.body}
    return out


@dataclass
class DesignedTheme:
    theme: dict[str, Any]
    pairing: str | None = None  # None: the design data's theme stayed
    notes: list[dict[str, Any]] = field(default_factory=list)


def _note(message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": "/theme", "message": message[:600], "suggestion": None}


def _brief(requirement: str, outline: dict[str, Any], backend: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    design = outline.get("design") if isinstance(outline.get("design"), dict) else {}
    requested = design.get("requested") or {}
    named = [  # a colour the requirement names only in words is a family to choose a shade from
        f"{k} {v}" if k not in ("accent", "background") or v.lower() in requirement.lower() else f"{k} like {v}"
        for k, v in requested.items()
        if k != "words" and v
    ]
    look = "; ".join(filter(None, [requested.get("words"), ", ".join(named)]))
    kind = (outline.get("domain") or {}).get("name") or design.get("archetype") or "app"
    entities = [e["name"] for e in backend.get("entities") or [] if e.get("name") not in ("User", "Account")]
    direction = theme.get("direction") or {}
    hint = ", ".join(filter(None, [direction.get("productType"), direction.get("palette")]))
    return {
        "requirement": requirement,
        "name": outline.get("name") or "the app",
        "kind": kind,
        "main": ", ".join(entities[:4]) or "its records",
        "requested": look,
        "hint": hint,
    }


def _pairings(names: list[str]) -> list[dict[str, str]]:
    out = []
    for name in names:
        plugin = design_registry().get("font-pairing", name)
        if plugin is not None:
            out.append({"name": name, "choose": plugin.choose, "heading": plugin.heading, "body": plugin.body})
    return out


async def design_theme(
    designer: Designer,
    prompts: PromptLibrary,
    requirement: str,
    outline: dict[str, Any],
    backend: dict[str, Any],
    theme: dict[str, Any],
    pairings: list[str],
) -> DesignedTheme:
    """Stories 34.2–34.3: the theme designed for this product, checked by code, asked again once with the reasons;
    still failing (or the turn failing), the design data's `theme` with a note."""
    if not pairings:
        return DesignedTheme(theme, notes=[_note("No theme was designed: no font pairing fits this app")])
    design = outline.get("design") if isinstance(outline.get("design"), dict) else {}
    requested = design.get("requested") or {}
    pairings = [name for name in pairings if not plain_pairing(name)] or pairings
    # listed in the app's own order (its design seed): the first-listed pairing is not everyone's pick
    random.Random(design.get("seed") or len(requirement)).shuffle(pairings)
    context = {**_brief(requirement, outline, backend, theme), "pairings": _pairings(pairings)}
    schema = answer_schema(pairings)
    reasons: list[str] = []
    for _ in range(2):  # the turn, then one repair (decision D4)
        try:
            answer = await designer(prompts.render(*PROMPT, **context, reasons=reasons), schema)
        except (LlmError, TimeoutError, ValueError) as exc:  # the design data's theme is a complete fallback
            reasons = [f"the design turn failed ({type(exc).__name__}: {str(exc)[:200]})"]
            break
        answer, moved = with_requested_accent(answer, requested, requirement)
        reasons = check_theme(answer, requested, pairings, requirement)
        if not reasons:
            out = designed(theme, answer)
            tinted = tint_neutrals(out["colors"])
            why = f"; {answer['why']}" if answer.get("why") else ""
            message = f"The theme was designed for this product: {answer.get('concept') or 'no concept'}"
            message += f" (the {answer['fontPairing']} type{why})"
            if moved:
                message += f"; code set the requested accent {requested['accent']}"
            if tinted:
                message += f"; code tinted the grey {', '.join(tinted)} toward the primary"
            return DesignedTheme(out, answer["fontPairing"], [_note(message)])
    why = "; ".join(reasons[:3])
    return DesignedTheme(theme, notes=[_note(f"The design data's theme was kept: the designed one failed ({why})")])


def apply_pairing(outline: dict[str, Any], pairing: str) -> None:
    """Story 34.4: the designed pairing on the design and the leading look (the one `pairing_theme` draws with)."""
    from ..frontend.app.recipes import first_recipe

    design = outline.setdefault("design", {})
    design["fontPairing"] = pairing
    recipe = first_recipe(design)
    look = next((look for look in design.get("looks") or [] if look.get("recipe") == recipe), None)
    if look is not None:
        look["fontPairing"] = pairing
