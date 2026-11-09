"""The dynamic app flow (Epic 22): the app outline and the app sections, accepted only in dynamic mode.

A FrontendSpec made by the app flow has `project.flow: "app"` and an `app` outline: what the app is (its name,
navigation, home), drafted by the model. Its pages are written by code (the screen planner, Story 22.3) from the
outline and the API contract, as ordinary pages whose sections are the app kit's sections. Static sites and the
legacy dynamic flow never see any of this (decision D1): `site_schema` removes it from the schema their drafts get.
"""

from typing import Annotated, Any, Literal

from pydantic import Field

from src.modules.shared.domain.backend_spec.schema_v1 import ENTITY_NAME, IDENTIFIER, SpecModel

ICON = r"^[A-Z][A-Za-z0-9]*$"  # a Lucide icon name, e.g. "BookOpen"

# The app kit's sections (`templates/nextjs_overlay/files/dynamic/app/`), by FrontendSpec component name.
APP_SECTIONS: dict[str, str] = {
    "AppList": "The records of an entity: a table or cards, with search, filters, sort and pages",
    "AppDetail": "One record: its fields, its actions and a tab per child entity",
    "AppForm": "A create or edit form on the operation's request",
    "AppDashboard": "Figures and charts from aggregates, and recent records",
    "AppActions": "Buttons for operations on a record or a collection",
    # Story 22.7: the plugins' screens (their components live in `templates/plugins/<name>/frontend/files/`)
    "AppAuth": "Sign-in or sign-up on the auth operations (auth-jwt)",
    "AppLinks": "A record's many-to-many links: chips, added with a picker and removed (relations)",
    "AppPayment": "The return from the checkout: the payment's status, polled until it settles (payments)",
}


MAX_LIST_FIELDS = 5  # the fields a list shows
MAX_DASHBOARD = 6  # figures and charts on the dashboard
Aggregate = Literal["count", "sum", "avg", "min", "max"]
Scalar = str | int | float | bool


class AppNavItem(SpecModel):
    entity: str = Field(pattern=ENTITY_NAME, max_length=63)
    label: str | None = Field(default=None, max_length=40)
    icon: str | None = Field(default=None, pattern=ICON, max_length=63)


class AppEntity(SpecModel):
    """How an entity is named and shown; every field is optional (code fills it from the BackendSpec)."""

    label: str | None = Field(default=None, max_length=40)
    plural: str | None = Field(default=None, max_length=40)
    display_field: str | None = Field(default=None, pattern=IDENTIFIER, max_length=63)  # names a record
    list_fields: list[Annotated[str, Field(pattern=IDENTIFIER)]] = Field(default=[], max_length=MAX_LIST_FIELDS)
    list_style: Literal["table", "cards"] | None = None
    detail_fields: list[Annotated[str, Field(pattern=IDENTIFIER)]] = []  # their order on the detail page
    field_labels: dict[str, Annotated[str, Field(max_length=60)]] = {}
    help: dict[str, Annotated[str, Field(max_length=200)]] = {}  # a hint under a form field


class AppDashboardItem(SpecModel):
    """A figure (`kind: figure`) or a chart of an aggregate of an entity's records (Epic 21's aggregates)."""

    label: str = Field(min_length=1, max_length=80)
    kind: Literal["figure", "bar", "line", "area", "pie"] = "figure"
    entity: str = Field(pattern=ENTITY_NAME, max_length=63)
    fn: Aggregate = "count"
    field: str | None = Field(default=None, pattern=IDENTIFIER)  # a number field; none for `count`
    filter: dict[str, Scalar] = {}  # equality on the entity's fields
    period: Literal["day", "week", "month", "year"] | None = None  # records of the current period
    date_field: str | None = Field(default=None, pattern=IDENTIFIER)  # the date `period` reads; default: creation
    group_by: str | None = Field(default=None, pattern=IDENTIFIER)  # a chart's categories


class AppHighlight(SpecModel):
    title: str = Field(min_length=1, max_length=60)
    text: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, pattern=ICON, max_length=63)


class AppLanding(SpecModel):
    """An optional public first page (off unless the requirement asks for one): a headline, a short text, up to
    three highlights and a button into the app."""

    headline: str = Field(min_length=1, max_length=120)
    text: str | None = Field(default=None, max_length=400)
    highlights: list[AppHighlight] = Field(default=[], max_length=3)
    cta: str | None = Field(default=None, max_length=40)


# -- Epic 23: the design space (how the app is presented; code checks every choice against the contract) -----------

Archetype = Literal["back-office", "catalogue", "feed", "workspace", "booking", "learning", "storefront"]
Shell = Literal["sidebar", "topbar", "topbar-tabs", "rail"]
MobileNav = Literal["drawer", "bottom-tabs"]
Frame = Literal["narrow", "standard", "wide", "full"]
Density = Literal["compact", "comfortable", "spacious"]
HomeView = Literal["dashboard", "feed", "catalogue", "agenda", "bento"]
ListView = Literal["table", "cards", "media-grid", "feed", "board", "calendar"]
DetailView = Literal["record", "media", "profile"]
FiltersStyle = Literal["toolbar", "chips", "facets", "search-first"]
Recipe = Literal[
    "minimal", "swiss", "material", "enterprise", "soft", "clay",
    "glass", "aurora", "brutalist", "neon", "playful", "editorial",
]  # fmt: skip
FieldName = Annotated[str, Field(pattern=IDENTIFIER, max_length=63)]
MAX_META = 3  # short fields on a card's meta line


class AppFieldRoles(SpecModel):
    """Which field plays which part on a card or a row (Story 23.3); code checks each against the field's type."""

    media: FieldName | None = None  # an image, or (Epic 29) a video or audio field played by the kit
    title: FieldName | None = None
    subtitle: FieldName | None = None
    meta: list[FieldName] = Field(default=[], max_length=MAX_META)  # a date, a duration, a source
    badge: FieldName | None = None  # a status or a category
    stat: FieldName | None = None  # a count: views, upvotes
    price: FieldName | None = None
    avatar: FieldName | None = None  # a small image of who or what the record is from
    duration: FieldName | None = None  # Epic 29: a number of seconds (or minutes), shown as m:ss on cards


class AppEntityDesign(SpecModel):
    """How one entity's records are shown (Stories 23.3–23.5)."""

    view: ListView | None = None
    detail_view: DetailView | None = None
    roles: AppFieldRoles = AppFieldRoles()
    filters_style: FiltersStyle | None = None
    group_by: FieldName | None = None  # a board's column field (a status)
    date_field: FieldName | None = None  # a calendar's or an agenda's date
    end_field: FieldName | None = None  # a calendar's end


class AppLook(SpecModel):
    """One look the user can pick (Story 23.7): a style recipe and why it fits."""

    recipe: Recipe
    reason: str | None = Field(default=None, max_length=200)


HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class AppRequestedStyle(SpecModel):
    """What the requirement itself says about the look, as values (2026-11-07): the requirement comes before the
    design data's choice for its kind of product. Only what it states; code applies it and keeps the contrast."""

    accent: HexColor | None = None  # the colour it names for buttons, links and highlights ("a bright orange accent")
    background: HexColor | None = None  # "on white", "a cream background"
    text: HexColor | None = None  # "deep brown text"
    scheme: Literal["light", "dark"] | None = None  # "a dark theme"
    heading_font: Literal["serif", "sans", "geometric", "rounded", "display", "mono"] | None = None
    corners: Literal["sharp", "rounded", "pill"] | None = None
    photos: Literal["prominent"] | None = None  # "photo-first", "big pictures", "large posters"
    words: str | None = Field(default=None, max_length=200)  # the requirement's own words these come from


class AppDesign(SpecModel):
    """The design brief (Epic 23): the model chooses from these values, code checks them against the contract and
    replaces what does not fit (`replaced`, one line each)."""

    archetype: Archetype | None = None
    shell: Shell | None = None
    mobile_nav: MobileNav | None = None
    frame: Frame | None = None
    density: Density | None = None
    home_view: HomeView | None = None
    main_entity: Annotated[str, Field(pattern=ENTITY_NAME, max_length=63)] | None = None
    entities: dict[str, AppEntityDesign] = {}
    looks: list[AppLook] = Field(default=[], max_length=3)
    requested: AppRequestedStyle | None = None  # what the requirement says about the look (2026-11-07)
    recipe: Recipe | None = None  # the look the user picked in the review (Story 23.7); none: the first look
    reason: str | None = Field(default=None, max_length=300)
    replaced: list[str] = []


class AppArea(SpecModel):
    """A group of roles with its own layout (Story 23.10): its own routes (`prefix`), shell, home and views."""

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=40)]
    label: str = Field(min_length=1, max_length=40)
    roles: list[str] = Field(min_length=1)
    prefix: str = Field(default="/", pattern=r"^/[a-z0-9-]*$", max_length=40)
    design: AppDesign = AppDesign()


class AppOutline(SpecModel):
    """What the app is, as the model drafts it: entities, navigation, labels and figures, never layout, routes,
    operations or parameters (code binds every screen, Story 22.3)."""

    name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, pattern=ICON, max_length=63)
    nav: list[AppNavItem] = []
    home: Literal["dashboard"] | Annotated[str, Field(pattern=ENTITY_NAME)] = "dashboard"
    entities: dict[str, AppEntity] = {}  # by entity name; unknown names are dropped by code
    dashboard: list[AppDashboardItem] = Field(default=[], max_length=MAX_DASHBOARD)
    landing: AppLanding | None = None
    design: AppDesign | None = None  # Epic 23: how the app is presented
    # Story 23.8: the language of the app's labels and the kit's own strings (`en`, `ja`); none: English
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")] | None = None
    areas: list[AppArea] = []  # Story 23.10: a layout per group of roles; none: one area
    # Story 26.4: the guided tour of the core business workflows (written by code from the draft's binding, never by
    # the model): `{"version", "tours": [{"id", "name", "roles", "steps": [...]}]}`; none: no tour
    workflows: dict[str, Any] | None = None


def is_app_spec(spec: dict[str, Any]) -> bool:
    """A FrontendSpec made by the app flow (normalized or raw)."""
    return (spec.get("project") or {}).get("flow") == "app"


# Schema parts only the app flow uses: removed from the schema static and legacy dynamic drafts read.
_APP_ONLY_PROPERTIES = {
    "FrontendSpecV1": ("app",),
    "Project": ("flow",),
    "FormField": ("help", "currency", "unit", "reference", "upload", "transition"),
    "Asset": ("credit",),  # Epic 27: written by code from the photo service, never drafted
}
_APP_ONLY_DEFS = (
    "AppOutline",
    "AppNavItem",
    "AppEntity",
    "AppDashboardItem",
    "AppLanding",
    "AppHighlight",
    "FormFieldReference",
    "FormFieldUpload",
)
DESIGN_DEFS = ("AppDesign", "AppEntityDesign", "AppFieldRoles", "AppLook", "AppArea", "AppRequestedStyle")  # Epic 23
_APP_ONLY_DEFS += DESIGN_DEFS
_APP_ONLY_DEFS += ("AssetCredit",)
# Epic 23: the outline's parts the `draft_app@v2` prompt does not explain; its outline digest and answer schema leave
# them out, so v2 reads as before (`draft_app@v3` asks for them).
DESIGN_PARTS = ("design", "areas")


CODE_PARTS = ("workflows",)  # Story 26.4: outline parts only code writes; no drafting prompt or schema shows them


def outline_schema(design: bool = True) -> dict[str, Any]:
    """The AppOutline JSON schema (camelCase), without the design parts unless asked."""
    schema = AppOutline.model_json_schema(by_alias=True)
    schema = {**schema, "properties": {k: v for k, v in schema["properties"].items() if k not in CODE_PARTS}}
    if design:
        return schema
    out = {**schema, "properties": {k: v for k, v in schema["properties"].items() if k not in DESIGN_PARTS}}
    defs = {k: v for k, v in (schema.get("$defs") or {}).items() if k not in DESIGN_DEFS}
    if defs:
        out["$defs"] = defs
    else:
        out.pop("$defs", None)
    return out


def site_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The FrontendSpec JSON schema without the app flow's fields (a copy), so the static and legacy drafting prompts
    stay as they were."""
    out = {**schema, "properties": dict(schema.get("properties") or {}), "$defs": dict(schema.get("$defs") or {})}
    for name in _APP_ONLY_PROPERTIES["FrontendSpecV1"]:
        out["properties"].pop(name, None)
    for model, names in _APP_ONLY_PROPERTIES.items():
        if model == "FrontendSpecV1" or model not in out["$defs"]:
            continue
        definition = {**out["$defs"][model], "properties": dict(out["$defs"][model].get("properties") or {})}
        for name in names:
            definition["properties"].pop(name, None)
        out["$defs"][model] = definition
    for name in _APP_ONLY_DEFS:
        out["$defs"].pop(name, None)
    return out
