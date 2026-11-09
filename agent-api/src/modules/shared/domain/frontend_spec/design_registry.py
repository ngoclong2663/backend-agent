"""The design plugin registry (Epic 30, Story 30.2, decisions D1–D3): every value of the app design space is one folder
under `agent-api/templates/design/<kind>/<name>/` with a `plugin.json` descriptor and, for the kinds the kit renders,
its component files. The registry is the single source: the FrontendSpec literals (`app.py`), the answer schema, the
prompt's choice lists (each descriptor's `choose` text), `complete_design`'s checks (`needs` → `fallback`) and the
kit's generated `design-registry.ts` all read it. A `draft` plugin is loaded (its tooling checks it) but never
offered (D6).

Pure data; read once per process (`registry()`). Adding a plugin: `make design-plugin-new KIND=<kind> NAME=<name>`
(docs/development/design-plugins.md).
"""

import json
import logging
import os
import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DESIGN_DIR = Path(__file__).resolve().parents[5] / "templates" / "design"
STARTER_DIR = DESIGN_DIR / "_starter"
Kind = Literal["shell", "list-view", "detail-view", "home", "filters", "card", "recipe", "font-pairing", "pattern"]
KINDS: tuple[str, ...] = (
    "shell",
    "list-view",
    "detail-view",
    "home",
    "filters",
    "card",
    "recipe",
    "font-pairing",
    "pattern",
)
KIT_KINDS: tuple[str, ...] = ("shell", "list-view", "detail-view", "home", "filters", "card")  # rendered by the kit
# What a plugin may need from the contract (one check each in `frontend/app/design.py`, D5).
NEEDS: tuple[str, ...] = (
    "imageField",  # an image field on the entity (a profile's picture)
    "mediaField",  # a media role: an image, a video or an audio field
    "playableField",  # a video or audio field (a watch page)
    "dateField",  # a date on the entity (a calendar, an agenda)
    "dateSort",  # a date the list can sort by (a feed, a featured record)
    "statusFlow",  # an enum with a transition rule, or one called status (a board)
    "groupField",  # an enum or a parent to group by (shelves)
    "enumOrReferenceFilter",  # a list filter on an enum, a boolean or a parent (chips, facets)
    "search",  # a search on the list (search first)
    "mainList",  # the main entity has a list operation (a home that shows it)
    "parentOrChildren",  # the record has a parent or children to show beside it (a split panel)
    "longTextField",  # a text field people read (a reader)
    "featured",  # a date sort or a boolean field to choose the featured record by
    # product patterns (Epic 32), checked in `frontend/app/patterns.py` (`pattern_fits`), not by the design checks
    "signIn",  # people sign in (the auth plugin): a consumer pattern is for people, not one person's tool
    "purchase",  # something to buy: a person's cart of the main entity, or a payment
)
Scripts = ("latin", "japanese")
# Product patterns (Epic 32, Story 32.2): how an area's screens behave for its people; no kit file, the planner reads it
MENU_ENTRIES: tuple[str, ...] = (
    "every",  # every entity with a list (a back-office's menu)
    "main",  # the area's main entity
    "mine",  # one entry for the role's own records, grouped on one page
    "cart",  # a shopper's cart
)
SHAPES: tuple[str, ...] = (
    "interaction",  # a person's one-row reaction to a record, nothing to fill in (a like, a bookmark, a view)
    "contribution",  # a person's text on a record (a comment, a review, a reply)
    "part",  # a line of the record (an order's item, a course's lesson)
)
PLACEMENTS: tuple[str, ...] = (
    "inline",  # an action and a short list on the parent's record
    "sheet",  # a sheet opened from the parent's record
    "tab",  # a tab of the parent's page (a back-office's)
    "page",  # a page of its own
)
NEVER: tuple[str, ...] = (
    "dashboard",  # a page of figures
    "edit-others",  # edit pages for records these roles do not create
    "own-interaction-tables",  # a menu table of the person's own reactions
)
UX_CHECKS: tuple[str, ...] = (  # `frontend/app/ux_checks.py` (Story 32.1); a pattern names the ones it must pass
    "no-unusable-page",
    "no-dashboard",
    "no-table",
    "no-own-interaction-menu",
    "no-edit-others",
    "home-is-feed",
    "interaction-on-record",
    "contribution-on-record",
    "contributions-readable",
    "add-to-cart-on-product",
    "cart-in-menu",
    "every-create-reachable",
)
NAME = re.compile(r"^[a-z][a-z0-9-]*$")


class DesignPluginDescriptor(BaseModel):
    """`plugin.json`. The kit kinds name their `exports` (the component the kit dispatches to) and either `builtin`
    (the component lives in the kit's core files) or `files` (copied into an app only when it uses the plugin, D4)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Kind
    name: str = Field(pattern=NAME.pattern, max_length=40)
    status: Literal["ready", "draft"] = "draft"
    label: str = Field(min_length=1, max_length=40)
    choose: str = Field(min_length=1, max_length=400)  # when to choose it, shown to the model
    archetypes: list[str] = []  # where it is a candidate (empty: a look, offered everywhere)
    needs: list[str] = []
    fallback: str | None = None  # a ready plugin of the same kind
    exports: list[str] = []
    # False: the kit renders it without a component lookup (a filters style inside AppList's controls, the dashboard
    # and bento homes in AppPage, the calendar's own data loading); the registry still offers and checks it
    dispatch: bool = True
    module: str | None = None  # a builtin's module in the kit (`./views`), imported by the generated registry
    files: list[str] = []  # kit files in the folder, copied as `src/components/design/<kind>/<name>/<file>`
    css: str | None = None  # a recipe's or a card's CSS file in the folder
    marker: str | None = None  # its `data-bga-*` value, for the report's fingerprints
    builtin: bool = False
    order: int = 100  # the position in the literal and the prompt (today's values keep their order)
    tags: list[str] = []  # free words other code selects by (`cards`: a list view of cards, Story 23.11's slots)
    # recipes
    family: Literal["quiet", "soft", "bold"] | None = None
    guards: list[str] = []  # words of products it must never be used for (health, finance, …)
    prefers: dict[str, str] = {}  # tie-breakers (Story 30.7): {"card": "overlay", "density": "compact", "view": …}
    # font pairings (Story 30.6): no kit file, the theme writes them
    heading: str | None = None
    body: str | None = None
    mono: str | None = None
    heading_weight: Literal[400, 500, 600, 700] | None = Field(default=None, alias="headingWeight")
    heading_case: Literal["normal", "upper"] | None = Field(default=None, alias="headingCase")
    tracking: Literal["tight", "normal", "wide"] | None = None
    ratio: Literal["tight", "default", "dramatic"] | None = None  # the theme's type-scale ratio (Epic 20)
    scripts: list[str] = ["latin"]
    recipes: list[str] = []  # the recipes a pairing suits (empty: any)
    # product patterns (Epic 32): the area's menu, where a record's children go by shape, which shapes are public on
    # their record, the home flow, what these people never get, the UX checks the pattern must pass
    menu: list[str] = []
    children: dict[str, str] = {}
    public: list[str] = []
    home: str | None = None
    never: list[str] = []
    checks: list[str] = []

    @model_validator(mode="after")
    def _shape(self):
        unknown = [need for need in self.needs if need not in NEEDS]
        if unknown:
            raise ValueError(f"unknown needs {unknown}; one of {list(NEEDS)}")
        if self.kind in KIT_KINDS and self.dispatch and not self.exports:
            raise ValueError(f"a {self.kind} plugin names the component it exports")
        if self.kind in KIT_KINDS and self.dispatch and not self.builtin and not self.files:
            raise ValueError(f"a {self.kind} plugin is builtin or lists its files")
        if self.kind in KIT_KINDS and self.dispatch and self.builtin and not self.module:
            raise ValueError(f"a builtin {self.kind} plugin names the kit module that exports it")
        if self.kind == "recipe" and (not self.css or not self.family):
            raise ValueError("a recipe has a css file and a family")
        if self.kind == "font-pairing" and not (self.heading and self.body):
            raise ValueError("a font pairing names its heading and body fonts")
        if any(script not in Scripts for script in self.scripts):
            raise ValueError(f"scripts are {Scripts}")
        if self.kind == "pattern":
            self._pattern_shape()
        elif self.menu or self.children or self.public or self.home or self.never or self.checks:
            raise ValueError("menu, children, public, home, never and checks are a pattern's")
        return self

    def _pattern_shape(self) -> None:
        bad = [m for m in self.menu if m not in MENU_ENTRIES]
        if not self.menu or bad:
            raise ValueError(f"a pattern's menu is a list of {MENU_ENTRIES}")
        if set(self.children) != set(SHAPES) or any(p not in PLACEMENTS for p in self.children.values()):
            raise ValueError(f"a pattern places every shape {SHAPES} as one of {PLACEMENTS}")
        if any(shape not in SHAPES for shape in self.public):
            raise ValueError(f"a pattern's public shapes are among {SHAPES}")
        if any(item not in NEVER for item in self.never):
            raise ValueError(f"a pattern's never list is among {NEVER}")
        if any(check not in UX_CHECKS for check in self.checks):
            raise ValueError(f"a pattern's checks are among {UX_CHECKS}")
        if len(self.archetypes) != 1 or self.archetypes[0] != self.name:
            raise ValueError("a pattern is named after the one archetype it serves")

    @property
    def folder(self) -> Path:
        return DESIGN_DIR / self.kind / self.name


class DesignRegistryError(ValueError):
    pass


class DesignRegistry:
    """The loaded plugins. A broken folder (a bad descriptor, a missing file, a fallback that is not ready) is recorded
    in `problems` and left out, so one draft in progress never breaks the app; `strict=True` (the tooling, the
    registry test) raises instead."""

    def __init__(self, root: Path = DESIGN_DIR, strict: bool = False):
        self.root = root
        self.plugins: dict[str, dict[str, DesignPluginDescriptor]] = {kind: {} for kind in KINDS}
        self.problems: list[str] = []
        for path in sorted(root.glob("*/*/plugin.json")):
            if path.parts[-3].startswith("_"):
                continue  # the starters
            try:
                plugin = DesignPluginDescriptor.model_validate(json.loads(path.read_text()))
            except (ValueError, json.JSONDecodeError) as exc:
                self.problems.append(f"{path.relative_to(root)}: {exc}")
                continue
            if plugin.kind != path.parts[-3] or plugin.name != path.parts[-2]:
                self.problems.append(f"{path.relative_to(root)}: kind and name do not match the folder")
                continue
            missing = [
                f for f in [*plugin.files, *([plugin.css] if plugin.css else [])] if not (path.parent / f).is_file()
            ]
            if missing:
                self.problems.append(f"{plugin.kind}/{plugin.name}: file {missing[0]} is missing")
                continue
            self.plugins[plugin.kind][plugin.name] = plugin
        for kind, plugins in self.plugins.items():
            for plugin in list(plugins.values()):
                if plugin.fallback is None:
                    continue
                target = plugins.get(plugin.fallback)
                if target is None or target.status != "ready":
                    self.problems.append(f"{kind}/{plugin.name}: fallback '{plugin.fallback}' is not a ready {kind}")
                    del plugins[plugin.name]
                elif target.needs and plugin.status == "ready":
                    chain = self.fallback_chain(kind, plugin.name)
                    if self.plugins[kind][chain[-1]].needs:
                        self.problems.append(f"{kind}/{plugin.name}: its fallbacks never reach a plugin without needs")
                        del plugins[plugin.name]
        if self.problems and strict:
            raise DesignRegistryError("design plugins: " + "; ".join(self.problems))

    # -- lookups ----------------------------------------------------------------------------------------------------

    def ready(self, kind: str) -> list[DesignPluginDescriptor]:
        """The plugins of a kind the drafter may choose, in order. `BGA_DESIGN_INCLUDE_DRAFTS=1` (the plugin check,
        Story 30.3; listed in docs/development/test-doubles.md) counts draft plugins in, so a draft can be built."""
        drafts = os.environ.get("BGA_DESIGN_INCLUDE_DRAFTS") == "1"
        return sorted(
            (p for p in self.plugins[kind].values() if p.status == "ready" or drafts), key=lambda p: (p.order, p.name)
        )

    def names(self, kind: str) -> tuple[str, ...]:
        return tuple(plugin.name for plugin in self.ready(kind))

    def get(self, kind: str, name: str | None) -> DesignPluginDescriptor | None:
        return self.plugins[kind].get(name or "")

    def fallback_chain(self, kind: str, name: str) -> list[str]:
        """The plugin and its fallbacks, in order, without repeats."""
        out: list[str] = []
        current: str | None = name
        while current and current not in out and current in self.plugins[kind]:
            out.append(current)
            current = self.plugins[kind][current].fallback
        return out

    def candidates(self, kind: str, archetype: str | None) -> list[DesignPluginDescriptor]:
        """The ready plugins offered for an archetype (Story 30.7): those naming it, or naming none."""
        return [p for p in self.ready(kind) if not archetype or not p.archetypes or archetype in p.archetypes]

    def choices(self, kind: str, archetype: str | None = None) -> list[tuple[str, str]]:
        """(name, when to choose it) for the prompt."""
        return [(p.name, p.choose) for p in self.candidates(kind, archetype)]

    def markers(self, kind: str) -> dict[str, str]:
        return {p.name: p.marker or p.name for p in self.plugins[kind].values()}

    def copied(self, kind: str, name: str) -> list[tuple[Path, str]]:
        """(source, target path in the app) of a folder plugin's files; nothing for a builtin."""
        plugin = self.get(kind, name)
        if plugin is None or plugin.builtin:
            return []
        files = [*plugin.files, *([plugin.css] if plugin.css and plugin.kind != "recipe" else [])]
        folder = self.root / kind / name
        return [(folder / file, f"src/components/design/{kind}/{name}/{file}") for file in files]

    def recipe_css(self, name: str) -> str:
        plugin = self.get("recipe", name)
        return (self.root / "recipe" / name / plugin.css).read_text() if plugin and plugin.css else ""

    def tagged(self, kind: str, tag: str) -> tuple[str, ...]:
        """The ready plugins of a kind carrying a tag (`cards`: list views laid out as cards, for the view slots)."""
        return tuple(p.name for p in self.ready(kind) if tag in p.tags)


@cache
def registry() -> DesignRegistry:
    loaded = DesignRegistry()
    for problem in loaded.problems:
        logging.getLogger(__name__).warning("design plugin left out: %s", problem)
    return loaded


def names(kind: str) -> tuple[str, ...]:
    """The ready names of a kind, for the literals (`Literal[names("shell")]`)."""
    return registry().names(kind)


def describe(kind: str, archetype: str | None = None) -> str:
    """One prompt line per candidate: `name` (when to choose it)."""
    return ", ".join(f"`{name}` ({choose.rstrip('.')})" for name, choose in registry().choices(kind, archetype))


def registry_digest() -> dict[str, Any]:
    """What the registry offers, per kind: for the engine list, the UI's design panel and the report's coverage."""
    return {
        kind: [
            {
                "name": p.name,
                "label": p.label,
                "choose": p.choose,
                "archetypes": p.archetypes,
                "needs": p.needs,
                "fallback": p.fallback,
                **({"family": p.family} if p.family else {}),
                **({"preview": f"design/{kind}/{p.name}/preview.png"} if (p.folder / "preview.png").is_file() else {}),
            }
            for p in registry().ready(kind)
        ]
        for kind in KINDS
    }
