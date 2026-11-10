"""The requirement's own look comes first (2026-11-07). The draft writes what the requirement says about the look as
values (`design.requested`: an accent, a background, a text colour, light or dark, the headings' kind of face, the
corners, photos first); code applies them over the design data's choice for the kind of product, keeps the contrast
readable and says what it followed in a note. Nothing requested: the theme and the views stay as they were."""

from typing import Any

from src.modules.shared.domain.frontend_spec.fonts import heading_kind_fits as _fits

from ...drafting.design_cards import fix_contrast
from ..theme import THEME_PRESETS, mix

FONT_FOR_KIND = {
    "serif": "Lora",
    "sans": "Inter",
    "geometric": "Outfit",
    "rounded": "Nunito",
    "display": "Playfair Display",
    "mono": "JetBrains Mono",
}
CORNERS = {"sharp": "none", "rounded": "lg", "pill": "full"}
PHOTO_VIEWS = ("table", "cards")  # a board, a calendar or a feed keeps its own reason


def _photos_first(design: dict[str, Any]) -> list[str]:
    changed = []
    for name, entity in (design.get("entities") or {}).items():
        if not isinstance(entity, dict) or not (entity.get("roles") or {}).get("media"):
            continue  # no image field: nothing to show large
        if entity.get("view") in PHOTO_VIEWS:
            entity["view"] = "media-grid"
            changed.append(name)
        if entity.get("detailView") in (None, "record"):
            entity["detailView"] = "media"
            changed.append(name)
    return sorted(set(changed))


def _colors(
    theme: dict[str, Any], requested: dict[str, Any], designed: bool = False, requirement: str = ""
) -> list[str]:
    from ...drafting.themes import keeps

    preset = THEME_PRESETS.get(theme.get("style") or "") or THEME_PRESETS["minimal"]
    colors = {**preset["colors"], **(theme.get("colors") or {})}
    done = []

    # Epic 34: a designed theme already follows the requested colours (code checked it); what it designed close to
    # them stays (its own tinted surfaces), the design data's theme is painted over as before
    def close(key: str, wanted: str | None) -> bool:
        return designed and keeps(key, colors.get(key), wanted, requirement)

    if close("primary", requested.get("accent")):
        done.append(f"accent {requested['accent']} (designed as {colors['primary']})")
        requested = {**requested, "accent": None}
    if close("background", requested.get("background")):
        done.append(f"background {requested['background']} (designed as {colors['background']})")
        requested = {**requested, "background": None}
    if requested.get("accent"):
        colors["primary"] = colors["accent"] = requested[
            "accent"
        ]  # the kit's accent token is a tint: the primary shows
        done.append(f"accent {requested['accent']}")
    if requested.get("text"):
        colors["foreground"] = requested["text"]
        done.append(f"text {requested['text']}")
    if requested.get("background"):
        colors["background"] = requested["background"]
        surface = mix(colors["background"], colors["foreground"], 0.06) or colors["background"]
        colors["secondary"] = colors["muted"] = surface
        done.append(f"background {requested['background']}")
    if requested.get("scheme") == "dark":
        theme["colorScheme"] = "dark"
        done.append("a dark theme")
    if not done:
        return []
    checked = {
        "style": theme.get("style") if theme.get("style") in THEME_PRESETS else "minimal",
        "colors": colors,
        "typography": {"headingFont": "Inter", "bodyFont": "Inter", **(theme.get("typography") or {})},
        "radius": theme.get("radius") or "md",
        "density": theme.get("density") or "comfortable",
    }
    if not fix_contrast(checked):
        done.append("the contrast could not be made readable everywhere")
    elif checked["colors"]["primary"] != colors["primary"] or checked["colors"]["foreground"] != colors["foreground"]:
        done.append("adjusted to stay readable")
    theme["colors"] = checked["colors"]
    return done


def follow_requested(
    outline: dict[str, Any], theme: dict[str, Any], designed: bool = False, requirement: str = ""
) -> list[dict[str, Any]]:
    """Applies `outline.design.requested` to `theme` (the app theme, in place) and to the views of the outline's
    design and its areas' (in place); returns the notes. `designed`: the theme came from Epic 34's design turn."""
    design = outline.get("design") if isinstance(outline.get("design"), dict) else {}
    requested = design.get("requested") or {}
    if not requested:
        return []
    done = _colors(theme, requested, designed, requirement)
    kind = requested.get("headingFont")
    if kind:
        typography = theme.setdefault("typography", {})
        if not _fits(kind, typography.get("headingFont")):
            typography["headingFont"] = FONT_FOR_KIND[kind]
        done.append(f"{kind} headings ({typography['headingFont']})")
    if requested.get("corners"):
        theme["radius"] = CORNERS[requested["corners"]]
        done.append(f"{requested['corners']} corners")
    if requested.get("photos") == "prominent":
        shown = _photos_first(design)
        for area in outline.get("areas") or []:
            if isinstance(area, dict) and isinstance(area.get("design"), dict):
                shown += _photos_first(area["design"])
        shown = sorted(set(shown))
        done.append(f"photos first ({', '.join(shown)})" if shown else "photos first, but no entity has an image field")
    words = f" ({requested['words']})" if requested.get("words") else ""
    message = f"The look follows the requirement{words}: {'; '.join(done)}"
    return [{"spec": "frontend", "path": "/app/design/requested", "message": message[:600], "suggestion": None}]
