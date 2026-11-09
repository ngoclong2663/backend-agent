"""How different drafted designs are (Story 20.1). Pure functions over FrontendSpecs (dicts) and screenshots, used by
`scripts/design_diversity.py` (the diversity report) and, from Story 20.4, by the difference test.

A design is described by four **visual fields**: the hero layout, the heading font, the hue family of the primary
colour and the key visual (what carries the first screen: a photo, an illustration, type). Two directions should
share at most one of them; the epic's targets (`pdm/epic20_design_diversity`) are measured with these functions.
"""

import colorsys
import re
from collections import Counter
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path
from typing import Any

from src.modules.shared.domain.frontend_spec import THEME_PRESETS
from src.modules.shared.domain.frontend_spec.normalizer import iter_sections

from ..frontend.theme import _rgb

VISUAL_FIELDS = ("hero", "headingFont", "hueFamily", "keyVisual")
LAYOUT_NODES = frozenset({"Columns", "Stack", "Grid", "Tabs"})
HOME_ROUTE = "/"
# A primary colour this grey (HSL saturation) or this dark / light has no hue a visitor notices.
NEUTRAL_SATURATION = 0.15
NEUTRAL_LIGHTNESS = (0.08, 0.95)
HUE_BUCKET = 30
# The first screen of a home page screenshot (px at 1440 wide) and the size it is compared at.
FIRST_SCREEN = (1440, 900)
THUMBNAIL = (64, 40)


def hue_family(color: str | None) -> str:
    """`neutral`, or the primary's hue in 30° buckets (`h0`, `h30`, … `h330`)."""
    rgb = _rgb(color or "")
    if rgb is None:
        return "neutral"
    hue, lightness, saturation = colorsys.rgb_to_hls(*rgb)
    if saturation < NEUTRAL_SATURATION or not NEUTRAL_LIGHTNESS[0] < lightness < NEUTRAL_LIGHTNESS[1]:
        return "neutral"
    return f"h{int(hue * 360) // HUE_BUCKET * HUE_BUCKET}"


def _home(spec: dict[str, Any]) -> dict[str, Any] | None:
    return next((page for page in spec.get("pages") or [] if page.get("route") == HOME_ROUTE), None)


def home_sections(spec: dict[str, Any]) -> list[str]:
    """The home page's section components in order, layout nodes left out (their children count)."""
    page = _home(spec)
    if page is None:
        return []
    return [
        s.get("component", "")
        for s in iter_sections(page.get("sections") or [])
        if s.get("component") not in LAYOUT_NODES
    ]


def _hero(spec: dict[str, Any]) -> dict[str, Any] | None:
    page = _home(spec)
    sections = iter_sections((page or {}).get("sections") or [])
    return next((section for section in sections if section.get("component") == "Hero"), None)


def key_visual(spec: dict[str, Any]) -> str:
    """What carries the first screen: the direction card's key visual when the theme records one (Story 20.4), else
    from the hero: `photo`, `illustration`, `image` (a link or a plain upload), `type` (a hero without an image) or
    `none` (no hero)."""
    hero = _hero(spec)
    if hero is None:
        return "none"
    recorded = ((spec.get("theme") or {}).get("direction") or {}).get("keyVisual")
    if isinstance(recorded, str) and recorded:
        return recorded
    content = hero.get("content") or {}
    image = content.get("image") or content.get("backgroundImage")
    if not image:
        return "type"
    if not str(image).startswith("asset:"):
        return "image"
    assets = {asset.get("id"): asset for asset in spec.get("assets") or [] if isinstance(asset, dict)}
    asset = assets.get(str(image).removeprefix("asset:")) or {}
    source = str(asset.get("source") or "placeholder")
    if source == "photo" or (source.startswith("upload:") and asset.get("prompt")):
        return "photo"
    if source == "generate" or asset.get("kind") in ("illustration", "pattern"):
        return "illustration"
    return "image"


def visual_fields(spec: dict[str, Any]) -> dict[str, str]:
    """The four visual fields of a FrontendSpec, with the theme preset's values where the spec sets none."""
    theme = spec.get("theme") or {}
    preset = THEME_PRESETS.get(theme.get("style") or "minimal", THEME_PRESETS["minimal"])
    typography = theme.get("typography") or {}
    hero = _hero(spec)
    return {
        "hero": str(((hero or {}).get("content") or {}).get("variant") or "split") if hero else "none",
        "headingFont": str(typography.get("headingFont") or preset["typography"]["headingFont"]),
        "hueFamily": hue_family((theme.get("colors") or {}).get("primary") or preset["colors"]["primary"]),
        "keyVisual": key_visual(spec),
    }


def shared_fields(first: dict[str, str], second: dict[str, str], compare: tuple[str, ...] = VISUAL_FIELDS) -> list[str]:
    return [field for field in compare if first.get(field) == second.get(field)]


def pair_distance(first: dict[str, str], second: dict[str, str]) -> int:
    """How many of the four visual fields differ (0–4)."""
    return len(VISUAL_FIELDS) - len(shared_fields(first, second))


def off_default(home: list[str], default: list[str]) -> bool:
    """True when the home page does not open like the category's default order: its first three sections differ
    from the default's first three among the sections the page has."""
    expected = [name for name in default if name in home]
    return home[:3] != expected[:3]


def difference_problems(
    fields: list[dict[str, str]],
    homes: list[list[str]],
    default: list[str],
    compare: tuple[str, ...] = VISUAL_FIELDS,
) -> list[str]:
    """The epic's difference test (D3) over a draft's directions: any two share at most one visual field, at most
    one `split` hero, at least one home page off the category default. Empty when it passes. `compare` leaves out
    fields the requirement fixes (brand colours or fonts are the same in every direction)."""
    problems = []
    for (i, first), (j, second) in combinations(enumerate(fields), 2):
        shared = shared_fields(first, second, compare)
        if len(shared) > 1:
            problems.append(f"directions {i + 1} and {j + 1} share {', '.join(shared)}")
    splits = sum(1 for item in fields if item.get("hero") == "split")
    if splits > 1:
        problems.append(f"{splits} directions use the split hero")
    if default and homes and not any(off_default(home, default) for home in homes):
        problems.append("every home page follows the category's default order")
    return problems


def distinct_triples(fields: Iterable[dict[str, str]]) -> int:
    """Distinct (hero, heading font, hue family) combinations."""
    return len({(item["hero"], item["headingFont"], item["hueFamily"]) for item in fields})


# -- sections and copy (Story 20.9's measures; meaningful with a real engine) ----------------------------------------


def section_types(spec: dict[str, Any]) -> set[str]:
    """Every section component used on any page, layout nodes left out."""
    return {
        str(section.get("component"))
        for page in spec.get("pages") or []
        for section in iter_sections(page.get("sections") or [])
        if section.get("component") and section.get("component") not in LAYOUT_NODES
    }


def section_frequency(specs: list[dict[str, Any]]) -> dict[str, float]:
    """The share of specs that use each section type, most common first."""
    if not specs:
        return {}
    counts = Counter(name for spec in specs for name in section_types(spec))
    return {name: round(count / len(specs), 3) for name, count in counts.most_common()}


def jaccard(first: set[str], second: set[str]) -> float:
    union = first | second
    return round(len(first & second) / len(union), 3) if union else 1.0


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def copy_lines(spec: dict[str, Any]) -> set[str]:
    """Headings and CTA labels of every section (normalized), the copy visitors notice first."""
    found: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and key in ("heading", "title", "label") and value.strip():
            found.add(_normal(value))

    for page in spec.get("pages") or []:
        for section in iter_sections(page.get("sections") or []):
            content = section.get("content") or {}
            visit({k: v for k, v in content.items() if k in ("heading", "title", "cta", "secondaryCta", "actions")})
    return found


def repeated_copy(specs: list[dict[str, Any]]) -> dict[str, int]:
    """Headings and CTA labels used by more than one spec, with how many use them."""
    counts = Counter(line for spec in specs for line in copy_lines(spec))
    return {line: count for line, count in counts.most_common() if count > 1}


# -- screenshots -----------------------------------------------------------------------------------------------------


def first_screen(path: Path) -> list[int]:
    """The first screen of a full-page screenshot as greyscale pixels at `THUMBNAIL` size (what a squint shows)."""
    from PIL import Image

    with Image.open(path) as image:
        width = min(image.width, FIRST_SCREEN[0])
        top = image.crop((0, 0, width, min(image.height, FIRST_SCREEN[1])))
        return list(top.convert("L").resize(THUMBNAIL, Image.Resampling.BOX).get_flattened_data())


def image_similarity(first: list[int], second: list[int]) -> float:
    """1 − mean absolute difference of two greyscale thumbnails (1.0 = the same light and dark masses)."""
    if len(first) != len(second) or not first:
        raise ValueError("thumbnails must have the same size")
    return round(1 - sum(abs(a - b) for a, b in zip(first, second, strict=True)) / (255 * len(first)), 4)


EDGE_THUMBNAIL = (96, 60)  # Story 30.1: layout lines, finer than the squint's masses


def edge_signature(path: Path) -> list[int]:
    """The first screen's edge map as bits at `EDGE_THUMBNAIL` size (Story 30.1): where layout lines are, whatever the
    colours. The greyscale squint (`first_screen`) measures light and dark masses, which on signed-in app screens is
    mostly white space; edges tell a sidebar from a top bar and a grid of cards from a table."""
    from PIL import Image, ImageFilter

    with Image.open(path) as image:
        width = min(image.width, FIRST_SCREEN[0])
        top = image.crop((0, 0, width, min(image.height, FIRST_SCREEN[1]))).convert("L")
        edges = top.filter(ImageFilter.FIND_EDGES).resize(EDGE_THUMBNAIL, Image.Resampling.BOX)
        return [1 if value > 12 else 0 for value in edges.get_flattened_data()]


def edge_similarity(first: list[int], second: list[int]) -> float:
    """Jaccard similarity of two edge maps (1.0 = the same lines in the same places)."""
    if len(first) != len(second) or not first:
        raise ValueError("edge maps must have the same size")
    both = sum(1 for a, b in zip(first, second, strict=True) if a and b)
    either = sum(1 for a, b in zip(first, second, strict=True) if a or b)
    return round(both / either, 4) if either else 1.0
