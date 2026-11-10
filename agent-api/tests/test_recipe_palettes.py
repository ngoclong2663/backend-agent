"""Recipe palettes from the app's own colours (2026-11-10, the user: "the color is too ugly and hard to read").
Five recipes set every colour themselves (a neon look: a cyan primary on violet, whatever the app's theme); each
names a palette mood now and code derives it from the app's built palette: readable, the app's hue kept, its
character."""

import json
from pathlib import Path

import pytest

from src.orchestrator.drafting.themes import hue_gap
from src.orchestrator.frontend.app.palettes import DARK_MOODS, MOODS, mood_of, mood_palette, text_contrast
from src.orchestrator.frontend.app.plan import app_plan_theme
from src.orchestrator.frontend.theme import build_theme, luminance

FIXTURES = Path(__file__).parent / "fixtures" / "drafts"
APPS = ("theme-yarn", "theme-socials", "theme-news", "theme-drivers")


def _theme(app: str) -> dict:
    return json.loads((FIXTURES / app / "frontend-spec.json").read_text())["theme"]


def _saturation(color: str) -> float:
    import colorsys

    from src.orchestrator.frontend.theme import _rgb

    return colorsys.rgb_to_hls(*_rgb(color))[2]


def test_the_five_recipes_name_a_mood_and_set_no_colour_token():
    root = Path(__file__).parents[1] / "templates" / "design" / "recipe"
    assert {name: mood_of(name) for name in ("neon", "cinema", "luxe", "terminal", "paper")} == {
        "neon": "tinted-dark", "cinema": "quiet-dark", "luxe": "contrast", "terminal": "neutral", "paper": "paper",
    }  # fmt: skip
    for folder in root.iterdir():
        css = folder / "recipe.css"
        if css.is_file():
            assert "--primary:" not in css.read_text() and "--background:" not in css.read_text(), folder.name


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("mood", MOODS)
def test_each_mood_is_readable_and_keeps_the_apps_hue(app, mood):
    built = build_theme({**_theme(app), "colorScheme": "dark" if mood in DARK_MOODS else "light-dark"})
    for scheme in ("light", "dark"):
        source = built.get(scheme)
        if not source:
            continue
        palette = mood_palette(mood, source, dark=scheme == "dark" or built["colorScheme"] == "dark")
        measured = text_contrast(palette)
        assert measured["foreground"] >= 7 and measured["card-foreground"] >= 4.5, (scheme, measured)
        assert measured["muted-foreground"] >= 4.5 and measured["primary-foreground"] >= 4.5, (scheme, measured)
        if _saturation(source["primary"]) > 0.2:
            assert (hue_gap(palette["primary"], source["primary"]) or 0) <= 20, "the app's primary keeps its hue"
        if mood in DARK_MOODS:
            assert luminance(palette["background"]) < 0.05
        if mood == "neutral":
            assert _saturation(palette["background"]) < 0.02 and _saturation(palette["border"]) < 0.02
        if mood == "contrast" and luminance(source["background"]) > 0.5:
            assert luminance(palette["background"]) > 0.85


def test_a_dark_mood_makes_a_dark_scheme_app_and_no_mood_keeps_the_theme():
    outline = {"design": {"looks": [{"recipe": "neon", "fontPairing": "loud"}]}}
    neon = app_plan_theme(_theme("theme-yarn"), outline)
    assert neon["colorScheme"] == "dark" and luminance(neon["light"]["background"]) < 0.05
    assert (hue_gap(neon["light"]["primary"], _theme("theme-yarn")["colors"]["primary"]) or 0) <= 20
    plain = app_plan_theme(_theme("theme-yarn"), {"design": {"looks": [{"recipe": "minimal"}]}})
    assert (
        plain["colorScheme"] == "light-dark" and plain["light"]["primary"] == _theme("theme-yarn")["colors"]["primary"]
    )
