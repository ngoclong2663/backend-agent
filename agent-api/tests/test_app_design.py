"""The design brief completed by code (Epic 23): archetypes and their frames (23.2), field roles and views checked
against the data (23.3–23.5), looks (23.7) and areas (23.10). Pure functions, no model call."""

import json
from pathlib import Path

import pytest

from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.modules.shared.domain.frontend_spec.app import outline_schema
from src.orchestrator.backend.planner import build_plan
from src.orchestrator.frontend.app.design import ARCHETYPES, archetype_for, complete_design, kit_design
from src.orchestrator.frontend.app.files import app_data
from src.orchestrator.frontend.app.outline import complete_outline
from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
from src.orchestrator.frontend.planner import plan_frontend
from src.orchestrator.integration.contract import build_contract

EXAMPLES = Path(__file__).parents[2] / "examples"
KIT = (
    Path(__file__).parents[1]
    / "templates"
    / "nextjs_overlay"
    / "files"
    / "dynamic"
    / "app"
    / "src"
    / "components"
    / "app"
)


def _backend(name: str) -> dict:
    return validate_spec_data(json.loads((EXAMPLES / "specs" / f"{name}.json").read_text())).normalized


@pytest.mark.parametrize(
    ("name", "archetype"),
    [
        ("news-feed", "feed"),
        ("video-library", "catalogue"),
        ("learning-platform", "learning"),
        ("agency-projects", "workspace"),
        ("clinic-bookings", "booking"),
        ("plant-shop", "storefront"),
        ("event-tickets", "booking"),
    ],
)
def test_the_requirements_words_pick_the_archetype(name, archetype):
    assert archetype_for((EXAMPLES / "requirements" / f"{name}.md").read_text()) == archetype


def test_without_words_the_product_type_then_a_back_office():
    assert archetype_for("Keep track of things.", ["Video Streaming/OTT"]) == "catalogue"
    assert archetype_for("Keep track of things.") == "back-office"


@pytest.mark.parametrize("archetype", sorted(ARCHETYPES))
def test_each_archetype_gives_its_frame(archetype):
    design, areas, replaced = complete_design({"archetype": archetype}, None, _backend("event-tickets"))
    defaults = ARCHETYPES[archetype]
    assert {k: design[k] for k in ("shell", "mobileNav", "frame")} == {
        k: defaults[k] for k in ("shell", "mobileNav", "frame")
    }
    assert "density" not in design, "the theme's density unless the brief sets one"
    assert areas == []


def test_a_view_that_does_not_fit_the_data_is_replaced_with_a_note():
    brief = {
        "archetype": "workspace",
        "mainEntity": "Task",
        "entities": [
            {"entity": "Task", "view": "board", "roles": {"title": "title", "badge": "priority", "stat": "title"}},
            {"entity": "Project", "view": "media-grid", "roles": {"title": "name"}},
            {"entity": "Ghost", "view": "table"},
        ],
    }
    design, _, replaced = complete_design(brief, None, _backend("agency-projects"))
    task, project = design["entities"]["Task"], design["entities"]["Project"]
    assert task["view"] == "board" and task["groupBy"] == "priority", "the badge names an enum: the board's columns"
    assert project["view"] == "cards"
    assert any("media grid" in line and "needs an image" in line for line in replaced)
    assert any("'Ghost' is not in the BackendSpec" in line for line in replaced)
    assert any("stat 'title' left out (already the title)" in line for line in replaced)


def test_a_board_takes_the_status_flow_and_a_calendar_its_date():
    design, _, _ = complete_design(
        {"entities": {"Task": {"view": "board"}}, "mainEntity": "Task"}, None, _backend("agency-projects")
    )
    assert design["entities"]["Task"]["groupBy"] == "status", "the field with a transition rule"
    design, _, _ = complete_design(
        {"archetype": "booking", "mainEntity": "Appointment", "entities": {"Appointment": {"view": "calendar"}}},
        None,
        _backend("clinic-bookings"),
    )
    appointment = design["entities"]["Appointment"]
    assert appointment["view"] == "calendar" and appointment["dateField"] not in ("createdAt", "updatedAt")
    assert design["homeView"] == "agenda"


def test_geminis_shapes_are_read_as_written():
    """Story 23.0: entities as an object keyed by entity, `meta` as one string."""
    brief = json.loads(
        (Path(__file__).parent / "fixtures" / "app-golden" / "video-library" / "design-brief.json").read_text()
    )
    design, _, replaced = complete_design(brief, None, _backend("video-library"))
    video = design["entities"]["Video"]
    assert video["view"] == "media-grid" and video["roles"]["media"] == "thumbnail"
    assert video["roles"]["meta"] == ["publishDate"], "a string read as a list of one"
    assert any("subtitle 'category' left out (already the badge)" in line for line in replaced)
    assert design["homeView"] == "catalogue" and design["shell"] == "topbar"


def test_roles_must_fit_the_fields_type():
    brief = {"entities": {"Plant": {"view": "cards", "roles": {"media": "name", "price": "size", "title": "price"}}}}
    design, _, replaced = complete_design(brief, None, _backend("plant-shop"))
    roles = design["entities"]["Plant"]["roles"]
    assert "price" not in roles and roles.get("title") != "price"
    assert roles["media"] != "name", "the first image field instead"
    assert len([line for line in replaced if "left out" in line]) == 3


def test_filters_need_a_filter_the_list_has():
    brief = {"entities": {"Tag": {"view": "table", "filtersStyle": "chips"}}}
    design, _, replaced = complete_design(brief, None, _backend("news-feed"))
    assert design["entities"]["Tag"]["filtersStyle"] == "toolbar"
    assert any("chips needs a filter" in line for line in replaced)


def test_looks_are_recipes_once_each():
    design, _, replaced = complete_design(
        {"looks": [{"recipe": "glass"}, "glass", {"recipe": "vaporwave"}, "brutalist"]}, None, _backend("news-feed")
    )
    assert [look["recipe"] for look in design["looks"]] == ["glass", "brutalist"]
    assert any("'vaporwave' is not a recipe" in line for line in replaced)


def test_areas_take_the_apps_roles_once_each():
    areas_raw = [
        {"id": "attendees", "label": "Attendees", "roles": ["attendee", "ghost"], "archetype": "catalogue",
         "shell": "topbar", "mainEntity": "Event", "entities": {"Event": {"view": "media-grid"}}},
        {"id": "Organizers", "roles": ["organizer", "attendee"], "archetype": "back-office", "mainEntity": "Event",
         "homeView": "dashboard", "entities": {"Event": {"view": "table"}}},
    ]  # fmt: skip
    design, areas, replaced = complete_design({"archetype": "catalogue"}, areas_raw, _backend("event-tickets"))
    assert [(a["id"], a["roles"], a["prefix"]) for a in areas] == [
        ("attendees", ["attendee"], "/"),
        ("organizers", ["organizer"], "/organizers"),
    ]
    assert areas[0]["design"]["shell"] == "topbar" and areas[1]["design"]["shell"] == "sidebar"
    assert areas[1]["design"]["entities"]["Event"]["view"] == "table"
    assert any("'ghost' is not a role of the app" in line for line in replaced)
    assert any("'attendee' is in another area" in line for line in replaced)


def test_one_area_is_the_app_itself():
    _, areas, replaced = complete_design(
        {}, [{"id": "all", "roles": ["attendee", "organizer"]}], _backend("event-tickets")
    )
    assert areas == [] and any("one area is the app itself" in line for line in replaced)


def test_an_outline_without_a_brief_keeps_its_own_choices():
    backend = _backend("flashcards")
    raw = json.loads((EXAMPLES / "app-outlines" / "flashcards.json").read_text())
    outline, notes = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    design = outline["design"]
    assert (
        design["shell"] == "sidebar"
        and design["homeView"] == "dashboard"
        and outline["home"] == raw.get("home", "dashboard")
    )
    for name, entity in outline["entities"].items():
        if name in design["entities"] and raw.get("entities", {}).get(name, {}).get("listStyle"):
            assert design["entities"][name]["view"] == entity["listStyle"]


def test_a_brief_decides_the_home_page_and_the_spec_validates():
    backend = _backend("news-feed")
    raw = json.loads((EXAMPLES / "app-outlines" / "news-feed.json").read_text())
    raw["design"] = json.loads(
        (Path(__file__).parent / "fixtures" / "app-golden" / "news-feed" / "design-brief.json").read_text()
    )
    outline, notes = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    assert outline["home"] == "Post" and outline["design"]["homeView"] == "feed"
    assert outline["design"]["entities"]["Post"]["view"] == "feed"
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    spec = app_frontend_spec(backend, outline, {"colorScheme": "light-dark"}, contract).spec
    result = validate_frontend_spec_data(spec)
    assert result.report.valid, result.report.errors
    data = app_data(plan_frontend(result.normalized, contract), result.normalized, contract)
    assert data["design"]["shell"] == "topbar" and data["design"]["entities"]["Post"]["view"] == "feed"
    assert data["areas"] == []


def test_the_kit_reads_todays_layout_for_an_app_drafted_before_epic_23():
    old = {"entities": {"Deck": {"listStyle": "cards"}}}
    assert kit_design(old) | {} == {
        "archetype": "back-office", "shell": "sidebar", "mobileNav": "drawer", "frame": "standard",
        "homeView": "dashboard", "entities": {}, "looks": [], "mainEntity": "Deck", "recipe": None,
    }  # fmt: skip


def test_the_v2_prompt_reads_the_outline_without_the_design():
    assert "design" not in outline_schema(design=False)["properties"]
    assert {"design", "areas"} <= set(outline_schema()["properties"])


def test_the_kit_dispatches_the_shells_through_the_design_registry():
    """Epic 30: the shells live in `shells.tsx`; AppShell names none of them (the generated registry does)."""
    shells = (KIT / "shells.tsx").read_text()
    for marker in ("export function TopBarShell", "export function SidebarShell", "function BottomTabs"):
        assert marker in shells
    shell = (KIT / "AppShell.tsx").read_text()
    assert "designRegistry.shells[design.shell]" in shell and '"topbar"' not in shell
    assert "FRAME_WIDTH[layout.frame]" in (KIT / "AppPage.tsx").read_text()


# -- Story 30.4: card anatomies and positions ----------------------------------------------------------------------


def test_a_record_without_media_reads_text_first_and_a_poster_is_portrait():
    backend = _backend("media-library")
    design, _, replaced = complete_design(
        {
            "mainEntity": "Lesson",
            "entities": {
                "Lesson": {"view": "media-grid", "roles": {"media": "poster", "title": "title"}},
                "Caption": {"view": "cards", "roles": {"title": "label"}},
                "Course": {
                    "view": "cards",
                    "card": "overlay",
                    "roles": {"media": "cover", "title": "title"},
                    "columns": 9,
                },
            },
        },
        None,
        backend,
    )
    lesson, caption, course = (design["entities"][name] for name in ("Lesson", "Caption", "Course"))
    assert lesson["card"] == "stacked" and lesson["aspect"] == "portrait", "a poster field is portrait"
    assert caption["card"] == "text-first" and "aspect" not in caption, "no media: text first"
    assert course["card"] == "overlay" and course["aspect"] == "square" and course["columns"] == 6
    assert any("columns 9 clamped to 6" in line for line in replaced)


def test_a_card_that_needs_media_falls_back_with_a_note():
    backend = _backend("media-library")
    design, _, replaced = complete_design(
        {
            "mainEntity": "Caption",
            "entities": {"Caption": {"view": "cards", "card": "overlay", "roles": {"title": "label"}}},
        },
        None,
        backend,
    )
    assert design["entities"]["Caption"]["card"] == "stacked"
    assert any("overlay needs an image, a video or an audio field; shown as stacked" in line for line in replaced)


def test_detail_layouts_need_their_data():
    backend = _backend("media-library")
    design, _, replaced = complete_design(
        {
            "mainEntity": "Lesson",
            "entities": {
                "Lesson": {"detailView": "media-side", "roles": {"media": "video", "title": "title"}},
                "Caption": {"detailView": "reader", "roles": {"title": "label"}},
                "Course": {"detailView": "split-panel", "roles": {"title": "title"}},
                "Episode": {"detailView": "reader", "roles": {"title": "title"}},
            },
        },
        None,
        backend,
    )
    entities = design["entities"]
    assert entities["Lesson"]["detailView"] == "media-side"
    assert entities["Caption"]["detailView"] == "record" and any(
        "reader needs a long text field" in line for line in replaced
    )
    assert entities["Course"]["detailView"] == "split-panel", "a course has lessons as children"
    assert entities["Episode"]["detailView"] == "reader", "episode notes are a text field"


def test_the_card_plugins_are_copied_only_when_used():
    from src.orchestrator.frontend.app.plan import design_plugins

    outline = {"design": {"shell": "topbar", "entities": {"Lesson": {"view": "media-grid", "card": "overlay"}}}}
    assert design_plugins(outline) == [{"kind": "card", "name": "overlay"}]
    assert design_plugins({"design": {"shell": "topbar", "entities": {"Lesson": {"view": "table"}}}}) == []


# -- Story 30.5: media layouts -------------------------------------------------------------------------------------


def test_shelves_need_a_group_and_media_a_featured_home_needs_media_and_a_date():
    backend = _backend("media-library")
    design, _, replaced = complete_design(
        {
            "mainEntity": "Lesson",
            "homeView": "featured",
            "entities": {
                "Lesson": {"view": "shelves", "roles": {"media": "video", "title": "title", "badge": "topic"}},
                "Caption": {"view": "shelves", "roles": {"title": "label"}},
            },
        },
        None,
        backend,
    )
    lesson, caption = design["entities"]["Lesson"], design["entities"]["Caption"]
    assert lesson["view"] == "shelves" and lesson["groupBy"] == "topic", "the badge's enum groups the shelves"
    assert caption["view"] == "media-grid" or caption["view"] == "cards"
    assert any("shelves needs" in line and "Caption" in line for line in replaced)
    assert design["homeView"] == "featured", "lessons have a video and a date"
    plain, _, notes = complete_design(
        {"mainEntity": "Caption", "homeView": "featured", "entities": {"Caption": {"view": "table"}}}, None, backend
    )
    assert plain["homeView"] == "catalogue" and any("featured needs" in line for line in notes)


def test_a_video_record_opens_on_a_watch_page_and_falls_back_to_its_player():
    backend = _backend("media-library")
    design, _, _ = complete_design(
        {"mainEntity": "Lesson", "entities": {"Lesson": {"roles": {"media": "video"}}}}, None, backend
    )
    assert design["entities"]["Lesson"]["detailView"] == "watch"
    asked, _, replaced = complete_design(
        {"mainEntity": "Course", "entities": {"Course": {"detailView": "watch", "roles": {"media": "cover"}}}},
        None,
        backend,
    )
    assert asked["entities"]["Course"]["detailView"] == "media"
    assert any("watch page (watch) needs a video or an audio field; shown as media" in line for line in replaced)


def test_a_featured_home_sorts_the_main_list_newest_first():
    from src.orchestrator.frontend.app.design import list_features

    backend = _backend("media-library")
    outline = {
        "design": {
            "homeView": "featured",
            "mainEntity": "Lesson",
            "entities": {"Lesson": {"view": "shelves", "roles": {"meta": ["publishedAt"]}}},
        }
    }
    unsorted = [
        {**op, "sort": []} if op.get("entity") == "Lesson" and op.get("action") == "list" else op
        for op in backend["operations"]
    ]
    operations, notes = list_features(backend, unsorted, outline)
    lesson_list = next(op for op in operations if op.get("entity") == "Lesson" and op.get("action") == "list")
    assert "publishedAt" in (lesson_list.get("sort") or []) and any(
        "gained sort publishedAt" in n["message"] for n in notes
    )


# -- Stories 30.6 and 30.7: font pairings, the seed and the candidates --------------------------------------------


def test_font_pairings_follow_the_script_and_the_requested_heading_kind():
    from src.orchestrator.frontend.app.design import assign_pairings, pairing_candidates

    assert "japanese-gothic" not in pairing_candidates("en", None, "catalogue"), "Japanese faces are for Japanese apps"
    japanese = pairing_candidates("ja", None, "catalogue")
    assert japanese and all(name.startswith("japanese-") for name in japanese), (
        "a Japanese app needs a pairing that sets Japanese"
    )
    serif = pairing_candidates("en", {"headingFont": "serif"}, "feed")
    assert set(serif) <= {"editorial", "bookish"} and serif, "serif headings: a display or serif heading face"
    design = {"archetype": "catalogue", "looks": [{"recipe": "minimal"}, {"recipe": "editorial"}, {"recipe": "aurora"}]}
    notes = assign_pairings(design, "en", seed=7)
    pairings = [look["fontPairing"] for look in design["looks"]]
    assert len(set(pairings)) >= 2 and design["fontPairing"] == pairings[0] and notes == []
    again = {"archetype": "catalogue", "looks": [{"recipe": "minimal"}, {"recipe": "editorial"}, {"recipe": "aurora"}]}
    assign_pairings(again, "en", seed=7)
    assert [look["fontPairing"] for look in again["looks"]] == pairings, "the same seed, the same type"
    ja = {"archetype": "catalogue", "fontPairing": "loud", "looks": [{"recipe": "minimal"}, {"recipe": "editorial"}]}
    notes = assign_pairings(ja, "ja", seed=1)
    assert ja["fontPairing"].startswith("japanese-") and any("does not set this app's script" in n for n in notes)


def test_the_look_pairing_writes_the_theme_type():
    from src.orchestrator.frontend.app.plan import pairing_theme

    outline = {
        "design": {
            "looks": [
                {"recipe": "editorial", "fontPairing": "editorial"},
                {"recipe": "minimal", "fontPairing": "neutral"},
            ],
            "recipe": "minimal",
        }
    }
    theme = pairing_theme({"style": "dashboard", "typography": {"headingFont": "Lora", "bodyFont": "Lora"}}, outline)
    assert theme["typography"]["headingFont"] == "Inter" and theme["typography"]["headingWeight"] == 600
    first = pairing_theme({"style": "dashboard"}, {"design": {**outline["design"], "recipe": None}})
    assert first["typography"]["headingFont"] == "Playfair Display" and first["typography"]["ratio"] == "dramatic"
    assert pairing_theme({"style": "dashboard"}, {"design": {}}) == {"style": "dashboard"}


def _seeded(seed, raw=None):
    backend = _backend("media-library")
    design, _, _ = complete_design(raw or {"archetype": "catalogue", "mainEntity": "Lesson"}, None, backend, seed=seed)
    main = design["entities"]["Lesson"]
    return (
        design["shell"],
        design["homeView"],
        main["view"],
        main.get("detailView"),
        main.get("card"),
        main.get("filtersStyle"),
    )


def test_the_seed_picks_among_candidates_the_same_seed_the_same_design():
    prints = {_seeded(seed) for seed in range(12)}
    assert len(prints) >= 3, prints
    assert _seeded(3) == _seeded(3)
    shells = {print_[0] for print_ in prints}
    assert shells <= {"sidebar", "topbar", "topbar-tabs"}, "a catalogue is never a rail"
    assert "watch" in {print_[3] for print_ in prints} or "media" in {print_[3] for print_ in prints}


def test_the_briefs_own_choices_win_over_the_seed_and_a_look_breaks_ties():
    raw = {"archetype": "catalogue", "mainEntity": "Lesson", "shell": "topbar", "homeView": "catalogue",
           "entities": {"Lesson": {"view": "media-grid", "detailView": "media"}}}  # fmt: skip
    for seed in range(6):
        shell, home, view, detail, _, _ = _seeded(seed, raw)
        assert (shell, home, view, detail) == ("topbar", "catalogue", "media-grid", "media")
    backend = _backend("media-library")
    for seed in range(6):
        design, _, _ = complete_design(
            {
                "archetype": "catalogue",
                "mainEntity": "Lesson",
                "looks": [{"recipe": "cinema"}],
                "entities": {"Lesson": {"view": "media-grid"}},
            },
            None, backend, seed=seed,
        )  # fmt: skip
        assert design["entities"]["Lesson"]["card"] == "overlay", "cinema prefers the overlay card"
        assert design["density"] == "comfortable"


def test_without_a_seed_the_archetype_defaults_apply_as_before():
    backend = _backend("media-library")
    design, _, _ = complete_design({"archetype": "catalogue", "mainEntity": "Lesson"}, None, backend)
    assert design["shell"] == "topbar" and design["homeView"] == "catalogue" and "seed" not in design
    assert design["entities"]["Lesson"]["view"] == "media-grid"
