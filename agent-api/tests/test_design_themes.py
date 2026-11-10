"""Epic 34: designed themes. The measures (Story 34.1), the design turn's prompt and schema (34.2), code's checks,
one repair and the fallback (34.3), and the wiring into an app draft (34.4), on the fake engine and a fake designer."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, delete

from src.engines import EngineRegistry, PromptLibrary
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.engines.llm import LlmError
from src.libs.database import db_session_manager
from src.modules.shared.infrastructure.models import SpecDraftModel
from src.orchestrator.drafting.drafts import DraftRunner
from src.orchestrator.drafting.themes import (
    answer_schema,
    apply_pairing,
    check_theme,
    cliches,
    design_theme,
    distinctness,
    theme_measures,
    tint_neutrals,
)
from src.orchestrator.frontend.app.design import pairing_candidates
from src.orchestrator.frontend.app.plan import pairing_theme
from src.orchestrator.store import JobStore
from tests.fake_llm import FakeLlmProvider

EXAMPLES = Path(__file__).parents[2] / "examples"
PAIRINGS = pairing_candidates(None, None, None)
SERIF = {"headingFont": "Playfair Display", "bodyFont": "Source Sans 3"}
YARN = "A yarn shop. Look: crisp, minimal, Scandinavian, one moss green accent."
DATA_THEME = {  # the design data's theme for the yarn shop before this epic (Tailwind's blue, Inter everywhere)
    "style": "minimal",
    "colorScheme": "light-dark",
    "colors": {
        "primary": "#2563eb",
        "secondary": "#f1f5f9",
        "accent": "#10b981",
        "background": "#ffffff",
        "foreground": "#0f172a",
        "muted": "#f1f5f9",
        "destructive": "#dc2626",
    },
    "typography": {"headingFont": "Inter", "bodyFont": "Inter"},
    "radius": "md",
    "density": "comfortable",
}
MOSS = {
    "concept": "Undyed wool and lichen on a pale birch table",
    "colors": {
        "primary": "#4a6b2f",
        "accent": "#7d8f5a",
        "secondary": "#eef0e6",
        "muted": "#e9ecdf",
        "background": "#fafaf5",
        "foreground": "#22261c",
    },
    "fontPairing": "humanist",
    "radius": "sm",
    "density": "comfortable",
    "why": "Plant-dyed greens and a warm humanist face, like a knitting pattern booklet.",
}


def _outline(requested: dict | None = None) -> dict:
    design = {"looks": [{"recipe": "soft", "fontPairing": "neutral"}, {"recipe": "paper", "fontPairing": "bookish"}]}
    if requested:
        design["requested"] = requested
    return {"name": "Moss & Wool", "design": design}


def _backend() -> dict:
    return {"entities": [{"name": "User"}, {"name": "Yarn"}, {"name": "Pattern"}]}


def _designer(*answers):
    """A design turn answering each call with the next answer (an exception is raised); records the prompts."""
    seen: list[str] = []
    queue = list(answers)

    async def designer(prompt, schema):
        seen.append(prompt.text)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    designer.seen = seen  # type: ignore[attr-defined]
    return designer


def _design(designer, requested=None, theme=None):
    return asyncio.run(
        design_theme(designer, PromptLibrary(), YARN, _outline(requested), _backend(), theme or DATA_THEME, PAIRINGS)
    )


# Story 34.1: the measures


def test_the_measures_catch_the_stock_blue_and_one_plain_sans():
    measured = theme_measures(DATA_THEME)
    assert measured["cliches"] == ["framework-blue", "one-plain-sans"]
    assert measured["readable"] and measured["textContrast"] > 15
    assert measured["greyNeutrals"] == [], "a slate surface is tinted (blue), not a pure grey"
    grey = {**DATA_THEME, "colors": {**DATA_THEME["colors"], "muted": "#eeeeee", "background": "#ffffff"}}
    assert theme_measures(grey)["greyNeutrals"] == ["muted"], "a pure white page is a choice, a grey surface is not"


@pytest.mark.parametrize(
    ("colors", "caught"),
    [
        ({"primary": "#6366f1", "background": "#ffffff"}, "indigo-on-white"),
        ({"primary": "#b5523b", "background": "#f6efe2"}, "cream-terracotta"),
        ({"primary": "#a3e635", "background": "#0a0a0a"}, "acid-on-black"),
    ],
)
def test_each_cliche_rule_catches_its_look(colors, caught):
    theme = {"colors": {"foreground": "#111111", **colors}, "typography": {"headingFont": "Fraunces"}}
    assert cliches(theme) == [caught]
    assert cliches({"colors": MOSS["colors"], "typography": {"headingFont": "Fraunces", "bodyFont": "Inter"}}) == []
    vivid = {"colors": {"primary": "#f97316", "background": "#fff7ed"}, "typography": {"headingFont": "Outfit"}}
    assert cliches(vivid) == [], "a vivid orange on cream is not the terracotta look"


def test_distinctness_measures_hue_gaps_and_shared_fonts():
    themes = {
        "a": {"colors": {"primary": "#2563eb"}, "typography": {"headingFont": "Inter", "bodyFont": "Inter"}},
        "b": {"colors": {"primary": "#1d4ed8"}, "typography": {"headingFont": "Inter", "bodyFont": "Inter"}},
        "c": {"colors": {"primary": "#ea580c"}, "typography": {"headingFont": "Fraunces", "bodyFont": "Inter"}},
    }
    measured = distinctness(themes)
    assert measured["nearestHueGap"]["a"] < 10 and measured["nearestHueGap"]["c"] > 150
    assert measured["sharedFonts"] == 2


# Story 34.2: the prompt and its schema


def test_the_prompt_renders_every_input_and_the_schema_offers_the_pairings():
    designer = _designer(MOSS)
    _design(designer, requested={"accent": "#4a6b2f", "words": "one moss green accent"})
    prompt = designer.seen[0]
    for text in ("Moss & Wool", "Yarn, Pattern", "one moss green accent", "accent like #4a6b2f", "`humanist`", "Never"):
        assert text in prompt, text
    assert "Your last answer could not be used" not in prompt
    assert "`neutral`" not in prompt, "one plain sans throughout is a cliché: never offered"
    schema = answer_schema(PAIRINGS)
    assert schema["properties"]["fontPairing"]["enum"] == PAIRINGS
    assert set(schema["required"]) == {"concept", "colors", "fontPairing", "radius", "density", "why"}


# Story 34.3: the checks, one repair, the fallback


def test_each_app_lists_the_pairings_in_its_own_order():
    """Story 34.5: three of six real drafts took the first-listed pairing; the order follows the app's design seed."""
    orders = set()
    for seed in (1, 2, 3, 4):
        designer = _designer(MOSS)
        outline = _outline()
        outline["design"]["seed"] = seed
        asyncio.run(design_theme(designer, PromptLibrary(), YARN, outline, _backend(), DATA_THEME, list(PAIRINGS)))
        orders.add(
            tuple(line.split("`")[1] for line in designer.seen[0].splitlines() if line.strip().startswith("- `"))
        )
    assert len(orders) > 1


def test_a_passing_theme_is_used_as_designed():
    assert check_theme(MOSS, None, PAIRINGS) == []
    made = _design(_designer(MOSS))
    assert made.pairing == "humanist" and made.theme["colors"]["primary"] == "#4a6b2f"
    assert made.theme["colors"]["destructive"] == "#dc2626", "what the turn doesn't design stays the data's"
    assert made.theme["radius"] == "sm" and made.theme["typography"]["headingFont"] != "Inter"
    assert "Undyed wool" in made.notes[0]["message"]


def test_the_checks_name_what_fails():
    bad = {**MOSS, "fontPairing": "comic", "colors": {**MOSS["colors"], "foreground": "#c8c8c0", "primary": "#e9eadf"}}
    reasons = check_theme(bad, {"accent": "#c2410c", "scheme": "dark", "headingFont": "serif"}, PAIRINGS)
    text = "; ".join(reasons)
    parts = ("fontPairing must be one of", "foreground on the background", "a button needs", "an accent like #c2410c")
    for part in parts:
        assert part in text, part
    assert "dark app" in text
    assert check_theme({**MOSS, "colors": {**MOSS["colors"], "primary": "blue"}}, None, PAIRINGS) == [
        "colors.primary is not a #rrggbb colour"
    ]
    blue = {**MOSS, "colors": {**MOSS["colors"], "primary": "#2563eb"}}
    assert any("framework-blue" in r for r in check_theme(blue, None, PAIRINGS))
    assert check_theme(blue, {"accent": "#2563eb"}, PAIRINGS) == [], "the user's own colour is followed"
    serif = check_theme(MOSS, {"headingFont": "serif"}, PAIRINGS)
    assert serif and "serif headings" in serif[0]


def test_a_failing_theme_is_asked_again_once_with_the_reasons():
    blue = {**MOSS, "colors": {**MOSS["colors"], "primary": "#2563eb"}}
    designer = _designer(blue, MOSS)
    made = _design(designer)
    assert made.pairing == "humanist" and len(designer.seen) == 2
    assert "Your last answer could not be used" in designer.seen[1] and "framework-blue" in designer.seen[1]


def test_still_failing_or_a_failed_turn_keeps_the_design_data_theme():
    blue = {**MOSS, "colors": {**MOSS["colors"], "primary": "#2563eb"}}
    made = _design(_designer(blue, blue))
    assert made.theme == DATA_THEME and made.pairing is None
    assert "design data's theme was kept" in made.notes[0]["message"]
    failed = _design(_designer(LlmError("quota")))
    assert failed.theme == DATA_THEME and "design turn failed" in failed.notes[0]["message"]


def test_code_sets_the_requested_accent_instead_of_a_repair():
    """Drivers (Story 34.5's real draft): it asked for #f97316; the turn chose another orange twice and the design
    data's theme was kept. Code sets the user's accent itself; its contrast on the page is `follow_requested`'s."""
    away = {**MOSS, "colors": {**MOSS["colors"], "primary": "#0f766e", "accent": "#0f766e", "background": "#fff7ed"}}
    designer = _designer(away)
    made = _design(designer, requested={"accent": "#f97316"})
    assert len(designer.seen) == 1 and made.pairing == "humanist"
    assert made.theme["colors"]["primary"] == made.theme["colors"]["accent"] == "#f97316"
    assert "code set the requested accent #f97316" in made.notes[0]["message"]


def test_a_colour_named_in_words_is_followed_by_its_family_a_given_hex_exactly():
    """IoT and news (Story 34.5's real drafts): "a leaf green accent" was drafted as Tailwind's #22c55e and "light
    background" as slate-50, and the design turn had to keep both. Only a hex the requirement gives is binding."""
    from src.orchestrator.drafting.themes import keeps

    words = "Look: clean and technical, light background, a leaf green accent."
    assert keeps("primary", "#2f6b3a", "#22c55e", words), "a deeper leaf green follows 'leaf green'"
    assert not keeps("primary", "#2563eb", "#22c55e", words)
    assert not keeps("primary", "#2f6b3a", "#22c55e", "The accent is #22c55e."), "a given hex is kept as it is"
    assert keeps("background", "#f6f8f4", "#f8fafc", words) and not keeps("background", "#101410", "#f8fafc", words)
    assert keeps("primary", "#172e6b", "#000080", "a navy accent")

    deeper = {**MOSS, "colors": {**MOSS["colors"], "primary": "#2f6b3a"}}
    made = asyncio.run(
        design_theme(
            _designer(deeper), PromptLibrary(), words, _outline({"accent": "#22c55e", "words": words}), _backend(),
            DATA_THEME, PAIRINGS,
        )
    )  # fmt: skip
    assert made.theme["colors"]["primary"] == "#2f6b3a" and "code set" not in made.notes[0]["message"]

    from src.orchestrator.frontend.app.requested import follow_requested

    theme = {**made.theme, "colors": dict(made.theme["colors"])}
    follow_requested(_outline({"accent": "#22c55e", "words": words}), theme, designed=True, requirement=words)
    assert theme["colors"]["primary"] == "#2f6b3a", "the requested look keeps the designed shade"
    assert cliches({"colors": {"primary": "#000080", "background": "#fcfbf7"}, "typography": SERIF}) == []


def test_code_tints_grey_neutrals_toward_the_primary():
    grey = {**MOSS, "colors": {**MOSS["colors"], "muted": "#eeeeee", "secondary": "#e5e5e5"}}
    made = _design(_designer(grey))
    assert made.theme["colors"]["muted"] != "#eeeeee" and made.theme["colors"]["secondary"] != "#e5e5e5"
    assert "tinted the grey secondary, muted" in made.notes[0]["message"]
    colors = {"primary": "#4a6b2f", "background": "#ffffff", "muted": "#f2f2f2"}
    assert tint_neutrals(colors) == ["muted"] and colors["background"] == "#ffffff"


# Story 34.4: the wiring


def test_the_requested_look_keeps_a_designed_theme_close_to_it():
    """The yarn shop's real draft: it asked for white and moss; the designed surfaces (tinted toward the moss) were
    repainted grey from the background and the text, as the design data's theme is."""
    from src.orchestrator.frontend.app.requested import follow_requested

    requested = {"accent": "#4a5d4e", "background": "#ffffff", "words": "white space and a moss green accent"}
    colors = {**MOSS["colors"], "primary": "#4a5d4e", "accent": "#4a5d4e", "background": "#ffffff"}
    designed = {**DATA_THEME, "colors": {**colors, "secondary": "#eef0e6", "muted": "#e9ecdf"}}
    notes = follow_requested(_outline(requested), designed, designed=True)
    assert designed["colors"]["muted"] == "#e9ecdf" and designed["colors"]["secondary"] == "#eef0e6"
    assert "designed as" in notes[0]["message"]
    data = {**DATA_THEME, "colors": dict(DATA_THEME["colors"])}
    follow_requested(_outline(requested), data)
    assert data["colors"]["primary"] == "#4a5d4e", "the design data's theme is painted over as before"


def test_the_leading_look_takes_the_designed_pairing():
    outline = _outline()
    apply_pairing(outline, "humanist")
    assert outline["design"]["fontPairing"] == "humanist"
    assert pairing_theme(DATA_THEME, outline)["typography"]["headingFont"] != "Inter"


@pytest.fixture
def cleanup_drafts():
    yield
    with Session(db_session_manager.engine) as session:
        session.exec(delete(SpecDraftModel))
        session.commit()


def _draft(client, headers, root: Path, design: bool | None, provider: FakeLlmProvider) -> dict:
    body = {"engine": "fake", "mode": "dynamic", "requirementText": YARN}
    if design is not None:
        body["designThemes"] = design
    response = client.post("/api/v1/spec-drafts", json=body, headers=headers)
    assert response.status_code == 202, response.text
    draft_id = response.json()["draftId"]
    engine = FakeEngine(root, demo_scenario(delay_s=0))
    runner = DraftRunner(
        EngineRegistry([engine], default="fake"), PromptLibrary(), JobStore(), root, "w-theme", EXAMPLES,
        llm_provider=provider,
    )  # fmt: skip
    asyncio.run(runner.run(draft_id))
    return JobStore().draft(uuid.UUID(draft_id)).model_dump(mode="json")


@pytest.mark.usefixtures("clean_redis")
def test_an_app_draft_carries_the_designed_theme_and_off_it_is_the_data_theme(
    client, user_headers, tmp_path, cleanup_drafts
):
    provider = FakeLlmProvider({"design_theme": lambda prompt, schema: MOSS})
    designed = _draft(client, user_headers, tmp_path / "on", True, provider)
    assert designed["status"] in ("SUCCEEDED", "NEEDS_REVIEW"), designed["error"]
    spec = designed["frontend_spec"]
    assert spec["theme"]["colors"]["primary"] == "#4a6b2f"
    assert spec["app"]["design"]["fontPairing"] == "humanist"
    assert [call["prompt"] for call in designed["usage"]["calls"]][-1] == "design_theme@v1"
    assert any("designed for this product" in note["message"] for note in designed["assumptions"])

    plain = _draft(client, user_headers, tmp_path / "off", None, FakeLlmProvider({}))
    assert "design_theme@v1" not in [call["prompt"] for call in plain["usage"]["calls"]]
    assert plain["frontend_spec"]["theme"]["colors"]["primary"] != "#4a6b2f"
    assert json.dumps(plain["frontend_spec"]["theme"]) != json.dumps(spec["theme"])
