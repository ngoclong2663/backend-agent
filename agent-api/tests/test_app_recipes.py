"""Style recipes and the three looks (Story 23.7): the requirement's words first, the data's styles, guards for
sensitive products, and a range (Story 23.0: the model alone offered only quiet looks)."""

from src.orchestrator.drafting.app import product_rows
from src.orchestrator.frontend.app.design import kit_design
from src.orchestrator.frontend.app.recipes import (
    FAMILY,
    RECIPES,
    complete_looks,
    first_recipe,
    recipe_for,
    recommended_looks,
    style_words,
)


def test_style_words_name_recipes_in_the_requirements_order():
    assert style_words("A shop that feels like liquid glass, with neo-brutalism buttons.") == ["glass", "brutalist"]
    assert style_words("A calm minimalist journal") == ["minimal"]
    assert style_words("A glassy theme") == [], "whole words only"


def test_the_datas_style_names_map_to_recipes():
    assert recipe_for("Glassmorphism") == "glass" and recipe_for("Claymorphism + Vibrant & Block-based") == "clay"
    assert recipe_for("Dark Mode (OLED)") == "neon" and recipe_for("Minimalism & Swiss Style") == "swiss"
    assert recipe_for("Motion-Driven") is None


def test_recommended_looks_come_from_the_ranked_products():
    rows = [
        {
            "Product Type": "Online Course/E-learning",
            "Primary Style Recommendation": "Claymorphism + Vibrant & Block-based",
            "Secondary Styles": "Motion-Driven , Flat Design",
        },
    ]
    looks = recommended_looks(rows)
    assert [look["recipe"] for look in looks] == ["clay", "playful", "minimal"]
    assert looks[0]["why"] == "Claymorphism for Online Course/E-learning"


def test_the_requirements_words_come_first():
    brief = [{"recipe": "minimal", "reason": "calm"}, {"recipe": "swiss"}, {"recipe": "editorial"}]
    looks, notes = complete_looks(brief, "Make it feel like liquid glass.", [], [])
    assert [look["recipe"] for look in looks] == ["glass", "minimal", "swiss"]
    assert looks[0]["reason"] == "The requirement asks for it"


def test_three_quiet_looks_get_a_bolder_third():
    """Story 23.0: minimal, swiss, editorial in every draft."""
    brief = [{"recipe": "minimal"}, {"recipe": "swiss"}, {"recipe": "editorial"}]
    recommended = [{"recipe": "aurora", "why": "Aurora UI for Magazine/Blog"}]
    looks, notes = complete_looks(brief, "A news feed for developers", recommended, ["Magazine/Blog"])
    assert [look["recipe"] for look in looks] == ["minimal", "swiss", "aurora"]
    assert any("three quiet looks offer no choice" in note for note in notes)
    assert {FAMILY[look["recipe"]] for look in looks} != {"quiet"}


def test_sensitive_products_get_no_neon_or_toy_look_unless_asked():
    brief = [{"recipe": "neon"}, {"recipe": "playful"}, {"recipe": "minimal"}]
    looks, notes = complete_looks(brief, "Appointment booking for a dental clinic", [], ["Dental Clinic"])
    recipes = [look["recipe"] for look in looks]
    assert "neon" not in recipes and "playful" not in recipes and len(recipes) == 3
    assert any("does not suit this product" in note for note in notes)
    asked, _ = complete_looks([], "A dental clinic app with a neon cyberpunk look", [], ["Dental Clinic"])
    assert asked[0]["recipe"] == "neon", "the user's own words win over the guard"


def test_looks_are_always_three_known_recipes():
    looks, _ = complete_looks([{"recipe": "vaporwave"}, "glass"], "", [], [])
    assert len(looks) == 3 and all(look["recipe"] in RECIPES for look in looks)
    assert len({look["recipe"] for look in looks}) == 3


def test_the_kit_shows_the_users_pick_else_the_first_look():
    design = {"looks": [{"recipe": "glass"}, {"recipe": "minimal"}, {"recipe": "aurora"}]}
    assert first_recipe(design) == "glass" and first_recipe({**design, "recipe": "aurora"}) == "aurora"
    assert kit_design({"design": design})["recipe"] == "glass"
    assert kit_design({})["recipe"] is None, "an app drafted before Epic 23 keeps today's look"


def test_product_rows_rank_the_design_data():
    rows = product_rows("An online course platform with lessons and enrolments")
    assert rows and all("Product Type" in row for row in rows)
    assert product_rows("   ") == []


def test_a_recipe_that_keeps_the_palette_takes_its_hues_from_the_theme():
    """2026-11-10 (the socials app on Claude): the playful recipe painted a fixed sky-blue-to-mint page behind a pink
    app's text. A recipe that doesn't set the palette mixes its gradients and shadows from the theme's tokens."""
    import re

    from src.orchestrator.frontend.app.recipes import recipe_blocks

    literal = re.compile(r"oklch\(\s*[\d.]+\s+[\d.]+\s+[\d.]+|#[0-9a-fA-F]{6}\b")
    for name, css in recipe_blocks().items():
        if "--primary:" in css or "--background:" in css:
            continue  # a recipe with its own palette (neon, cinema, paper, …) sets the tokens itself
        assert not literal.findall(css), f"{name} hard-codes colours: {literal.findall(css)[:3]}"


def test_a_one_scheme_app_is_drawn_in_its_scheme():
    """The same app: dark only, but next-themes drew it light (no `.dark`), so the light rules applied over its dark
    colours. The site config carries the scheme; the provider forces it."""
    from pathlib import Path

    from src.orchestrator.frontend.codegen import site_ts

    plan = {
        "shell": {"shell": "app", "logoText": "Loop", "logo": None, "navigation": [],
                  "footer": {"text": None, "links": []}, "themeToggle": False},
        "theme": {"colorScheme": "dark"},
        "routes": [],
    }  # fmt: skip
    spec = {"project": {"name": "Loop", "locale": "en", "mode": "dynamic"}}
    assert '"colorScheme": "dark"' in site_ts(plan, spec)
    providers = Path(__file__).parents[1] / "templates/nextjs_overlay/files/common/src/app/providers.tsx"
    assert "forcedTheme={forced}" in providers.read_text()
