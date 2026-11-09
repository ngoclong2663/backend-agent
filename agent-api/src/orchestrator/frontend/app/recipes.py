"""Style recipes and the three looks (Epic 23, Story 23.7). A recipe is a `recipe` design plugin (Epic 30:
`templates/design/recipe/<name>/`: the descriptor's family and guards, its `recipe.css` appended to the app's
`globals.css`); the brief names three looks and code completes them: the requirement's own style words come first, the
product's styles from UI UX Pro Max's data fill gaps, guards keep unsuitable recipes away from sensitive products, and
the three span a range (Story 23.0: the model alone picked only quiet looks in all seven drafts).

Pure functions, no model call.
"""

import re
from functools import cache
from typing import Any

from src.modules.shared.domain.frontend_spec.design_registry import registry

RECIPES: tuple[str, ...] = registry().names("recipe")
# How loud a recipe is (the descriptors' `family`): the three looks span at least two families, one of them not quiet.
FAMILY: dict[str, str] = {name: registry().plugins["recipe"][name].family or "quiet" for name in RECIPES}
FAMILIES: dict[str, tuple[str, ...]] = {
    family: tuple(name for name in RECIPES if FAMILY[name] == family) for family in ("quiet", "soft", "bold")
}
# UI UX Pro Max's style names (products.csv "Primary Style Recommendation", "Secondary Styles") → a recipe.
STYLE_RECIPES: tuple[tuple[str, str], ...] = (
    ("liquid glass", "glass"),
    ("glassmorphism", "glass"),
    ("neumorphism", "soft"),
    ("soft ui", "soft"),
    ("claymorphism", "clay"),
    ("aurora", "aurora"),
    ("gradient", "aurora"),
    ("neubrutalism", "brutalist"),
    ("brutalism", "brutalist"),
    ("cyberpunk", "neon"),
    ("neon", "neon"),
    ("dark mode", "neon"),
    ("y2k", "playful"),
    ("frutiger", "playful"),
    ("vibrant", "playful"),
    ("playful", "playful"),
    ("swiss", "swiss"),
    ("material", "material"),
    ("editorial", "editorial"),
    ("magazine", "editorial"),
    ("corporate", "enterprise"),
    ("enterprise", "enterprise"),
    ("data-dense", "enterprise"),
    ("trust", "enterprise"),
    ("minimalism", "minimal"),
    ("flat design", "minimal"),
    ("minimal", "minimal"),
    ("cinematic", "cinema"),  # Epic 30 (Story 30.6): the four new recipes
    ("luxury", "luxe"),
)
# Words in a requirement that ask for a look (whole words or phrases).
STYLE_WORDS: tuple[tuple[str, str], ...] = (
    ("liquid glass", "glass"),
    ("glassmorphism", "glass"),
    ("glass", "glass"),
    ("frosted", "glass"),
    ("neumorphism", "soft"),
    ("neumorphic", "soft"),
    ("claymorphism", "clay"),
    ("aurora", "aurora"),
    ("gradients", "aurora"),
    ("neo-brutalism", "brutalist"),
    ("neobrutalism", "brutalist"),
    ("brutalist", "brutalist"),
    ("brutalism", "brutalist"),
    ("cyberpunk", "neon"),
    ("neon", "neon"),
    ("y2k", "playful"),
    ("frutiger aero", "playful"),
    ("playful", "playful"),
    ("swiss", "swiss"),
    ("material design", "material"),
    ("editorial", "editorial"),
    ("magazine", "editorial"),
    ("minimalist", "minimal"),
    ("minimal", "minimal"),
    # Epic 30 (Story 30.6): the new recipes in the requirement's own words about the look (never a bare domain word:
    # a cinema booking app or a paper shop is not asking for the recipe)
    ("cinematic", "cinema"),
    ("like a cinema", "cinema"),
    ("paper-like", "paper"),
    ("like paper", "paper"),
    ("terminal-like", "terminal"),
    ("luxe", "luxe"),
    ("luxurious", "luxe"),
)
# Products whose users expect calm (the recipe descriptors' `guards`: styles.csv "Do Not Use For", in short).
GUARDED: dict[str, tuple[str, ...]] = {
    name: tuple(registry().plugins["recipe"][name].guards)
    for name in RECIPES
    if registry().plugins["recipe"][name].guards
}
SENSITIVE: tuple[str, ...] = tuple(dict.fromkeys(word for words in GUARDED.values() for word in words))
# The bolder looks code adds when the brief and the data offer none (the bold family, unguarded, in registry order)
DEFAULT_BOLD: tuple[str, ...] = tuple(name for name in RECIPES if FAMILY[name] == "bold" and name not in GUARDED)


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9-]+", " ", text.lower()) + " "


def style_words(requirement: str) -> list[str]:
    """The looks a requirement asks for in its own words, in the order it names them."""
    text = _words(requirement)
    found: list[tuple[int, str]] = []
    for phrase, recipe in STYLE_WORDS:
        index = text.find(f" {phrase} ")
        if index >= 0 and all(recipe != r for _, r in found):
            found.append((index, recipe))
    return [recipe for _, recipe in sorted(found)]


def recipe_for(style: str) -> str | None:
    lower = style.lower()
    return next((recipe for name, recipe in STYLE_RECIPES if name in lower), None)


def recommended_looks(product_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """The recipes UI UX Pro Max's data names for the ranked product types (primary styles first), with why."""
    out: list[dict[str, str]] = []
    for row in product_rows:
        product = row.get("Product Type", "")
        styles = [
            *re.split(r"\s*\+\s*", row.get("Primary Style Recommendation", "")),
            *re.split(r"\s*,\s*", row.get("Secondary Styles", "")),
        ]
        for style in styles:
            recipe = recipe_for(style)
            if recipe and all(recipe != item["recipe"] for item in out):
                out.append({"recipe": recipe, "why": f"{style.strip()} for {product}"})
    return out[:5]


def sensitive(requirement: str, product_types: list[str]) -> bool:
    text = _words(requirement + " " + " ".join(product_types))
    return any(f" {word} " in text for word in SENSITIVE)


def guarded(recipe: str, requirement: str, product_types: list[str]) -> bool:
    """Whether a recipe's guards name this product (Epic 30: the words live in the recipe's descriptor)."""
    text = _words(requirement + " " + " ".join(product_types))
    return any(f" {word} " in text for word in GUARDED.get(recipe, ()))


def complete_looks(
    looks: list[dict[str, Any]], requirement: str, recommended: list[dict[str, str]], product_types: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Three looks: the requirement's style words first, then the brief's, then the data's; guarded recipes left out
    for sensitive products; the three span a range (not all quiet). Returns the looks and what code changed."""
    notes: list[str] = []
    calm = sensitive(requirement, product_types)
    candidates: list[dict[str, Any]] = []
    for recipe in style_words(requirement):
        candidates.append({"recipe": recipe, "reason": "The requirement asks for it"})
    candidates += [look for look in looks if isinstance(look, dict) and look.get("recipe") in RECIPES]
    candidates += [{"recipe": item["recipe"], "reason": f"Recommended: {item['why']}"} for item in recommended]
    out: list[dict[str, Any]] = []
    for look in candidates:
        recipe = look["recipe"]
        if any(recipe == kept["recipe"] for kept in out):
            continue
        if guarded(recipe, requirement, product_types) and recipe not in style_words(requirement):
            label = registry().plugins["recipe"][recipe].label.lower()
            notes.append(f"look '{recipe}' left out: a {label} look does not suit this product")
            continue
        out.append({"recipe": recipe, **({"reason": str(look["reason"])[:200]} if look.get("reason") else {})})
    for recipe in ("minimal", *DEFAULT_BOLD):
        if len(out) >= 3:
            break
        if all(recipe != kept["recipe"] for kept in out):
            out.append({"recipe": recipe, "reason": "Added by code"})
            notes.append(f"look '{recipe}' added by code (fewer than three)")
    out = out[:3]
    if all(FAMILY[look["recipe"]] == "quiet" for look in out):
        bold = next(
            (item["recipe"] for item in recommended if FAMILY.get(item["recipe"]) != "quiet"
             and not (calm and item["recipe"] in GUARDED)),
            next(r for r in ("soft", *DEFAULT_BOLD) if not (calm and r in GUARDED)),
        )  # fmt: skip
        if all(bold != kept["recipe"] for kept in out):
            notes.append(f"look '{out[2]['recipe']}' replaced by '{bold}': three quiet looks offer no choice")
            out[2] = {"recipe": bold, "reason": "A bolder option (added by code)"}
    return out, notes


def first_recipe(design: dict[str, Any]) -> str:
    """The look on screen: the user's pick (`design.recipe`), else the first look, else minimal."""
    return design.get("recipe") or next((look["recipe"] for look in design.get("looks") or []), "minimal")


@cache
def recipe_blocks() -> dict[str, str]:
    """Each recipe's CSS (its plugin folder's `recipe.css`), placeholders still in."""
    return {name: registry().recipe_css(name) for name in RECIPES}


def recipe_css(recipe: str | None, scope: str | None = None) -> str:
    """The app's recipe, ready to append to `globals.css`: `@root` → `:root` (later than the theme's, so it wins),
    `@dark` → `:root.dark`; empty for no recipe (an app drafted before Epic 23 keeps today's look). `scope` (the
    plugin check, Story 30.3) writes it under `:root[data-recipe="<scope>"]` so one build can show every recipe."""
    body = recipe_blocks().get(recipe or "")
    if body is None:
        return ""
    root = f':root[data-recipe="{scope}"]' if scope else ":root"
    css = body.replace("@dark", f"{root}.dark").replace("@root", root)
    return (
        f"\n/* Style recipe: {recipe} (Epic 23, Story 23.7) */\n{css}"
        "@media (prefers-reduced-motion: reduce) {\n  :root * { transition: none !important; }\n}\n"
    )
