"""FrontendSpec 1.0 (Story 12.1): pages, theme, layout, components, data bindings, forms, content.

Structural contract only; cross-references (pages, forms, components, route parameters, assets) live in
validator.py. `data.operationId` and `forms[].operationId` are the only links to the backend; Story 12.5 checks
them against the API contract.
"""

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from src.modules.shared.domain.backend_spec.schema_v1 import IDENTIFIER, OPERATION_ID, SpecModel

from .app import AppOutline
from .fonts import FONTS

SLUG = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
COMPONENT_NAME = r"^[A-Z][A-Za-z0-9]*$"
# "/" or segments that are kebab-case words or one `[param]`; no catch-all routes in 1.0
ROUTE = r"^/$|^(/([a-z0-9]+(-[a-z0-9]+)*|\[[a-z][A-Za-z0-9]*\]))+$"
LOCALE = r"^[a-z]{2,3}(-[A-Z]{2})?$"
FONT = r"^[A-Za-z0-9][A-Za-z0-9 ]{0,63}$"

ThemeStyle = Literal["minimal", "editorial", "playful", "corporate", "dashboard"]
FormFieldType = Literal[
    "string", "text", "email", "url", "tel", "password", "integer", "number", "decimal", "boolean", "date",
    "datetime", "enum",
]  # fmt: skip


class Project(SpecModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    mode: Literal["static", "dynamic"]
    locale: str = Field(default="en", pattern=LOCALE)
    locales: list[Annotated[str, Field(pattern=LOCALE)]] = []
    flow: Literal["app"] | None = None  # Epic 22: made by the dynamic app flow (pages from the `app` outline)


class ThemeColors(SpecModel):
    """CSS colours: hex, or rgb()/hsl()/oklch(); checked in the validator (FE_INVALID_COLOR)."""

    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None
    background: str | None = None
    foreground: str | None = None
    muted: str | None = None
    destructive: str | None = None


# The editor offers the bundled fonts (Story 17.7); other names stay valid but only show where installed.
BUNDLED_FONTS = {"examples": list(FONTS)}


class Typography(SpecModel):
    heading_font: str | None = Field(default=None, pattern=FONT, json_schema_extra=BUNDLED_FONTS)
    body_font: str | None = Field(default=None, pattern=FONT, json_schema_extra=BUNDLED_FONTS)
    scale: Literal["compact", "default", "large"] = "default"
    # Story 20.3, the type of a direction (absent: today's look, semibold headings with tight tracking). Weight of
    # the hero and section headings; their case (upper: display headings only, widely tracked); their tracking; and
    # how much bigger the display steps of the type scale are than the text.
    heading_weight: Literal[400, 500, 600, 700] | None = None
    heading_case: Literal["normal", "upper"] | None = None
    tracking: Literal["tight", "normal", "wide"] | None = None
    ratio: Literal["tight", "default", "dramatic"] | None = None


ToneLevel = Annotated[int, Field(ge=1, le=5)]


class Tone(SpecModel):
    """A direction's feel on five scales, 1–5 (Story 20.3, `orchestrator/drafting/design_tone.py`)."""

    energy: ToneLevel = 3
    finish: ToneLevel = 3
    density: ToneLevel = 3
    weight: ToneLevel = 3
    seriousness: ToneLevel = 3


class ThemeDirection(SpecModel):
    """Where a drafted theme came from (Story 12.6): the design data's product type, landing pattern, palette and
    font pairing. A record for the review and later revisions; the renderer ignores it."""

    product_type: str | None = Field(default=None, max_length=120)
    pattern: str | None = Field(default=None, max_length=200)
    palette: str | None = Field(default=None, max_length=200)
    font_pairing: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=120)
    # Story 20.4: a direction card's idea (one sentence), what kind of idea it is, its tone (five scales 1–5), what
    # carries the first screen, what the direction gives up, and the draft's seed.
    name: str | None = Field(default=None, max_length=80)
    concept: str | None = Field(default=None, max_length=300)
    engine: Literal["material", "scene", "character", "tradition", "medium", "convention"] | None = None
    tone: Tone | None = None
    key_visual: Literal["photo", "illustration", "type", "product", "pattern"] | None = None
    gives_up: str | None = Field(default=None, max_length=300)
    seed: int | None = Field(default=None, ge=0)


class IconStyle(SpecModel):
    """Story 20.5: the site's content icons: one set, a weight (Lucide draws thin to bold as stroke widths; fill and
    duotone need Phosphor) and a treatment (`tile`: a small rounded square in the muted tone). `none`: no content
    icons (lists show numbers)."""

    set: Literal["lucide", "phosphor", "none"] = "lucide"
    weight: Literal["thin", "light", "regular", "bold", "fill", "duotone"] = "regular"
    treatment: Literal["plain", "tile"] = "plain"


class MotionStyle(SpecModel):
    """Story 20.6: how the site moves. `feel` picks the timing and spring of buttons, the hero's entrance and the
    reveals of sections (`none`: still, as before); `signature` turns on one stronger moment on one section."""

    feel: Literal["none", "click", "slide", "flow", "drop", "bounce", "float", "cut"] = "none"
    signature: Literal["none", "countUp", "headlineRise", "imageUnmask", "indicator"] = "none"


class Theme(SpecModel):
    style: ThemeStyle = "minimal"
    color_scheme: Literal["light", "dark", "light-dark"] = "light"
    colors: ThemeColors = ThemeColors()
    typography: Typography = Typography()
    radius: Literal["none", "sm", "md", "lg", "full"] | None = None
    density: Literal["compact", "comfortable"] | None = None
    # Story 20.3 (absent: today's look). surface: cards and panels without border or shadow, with a hairline, or
    # raised with a soft shadow. colorArea: how much of the page carries colour: buttons and eyebrows only, plus one
    # anchor section in the primary colour, or also a coloured hero.
    surface: Literal["flat", "outline", "raised"] | None = None
    color_area: Literal["minimal", "block", "bold"] | None = None
    icons: IconStyle | None = None  # Story 20.5; absent: Lucide, regular, plain
    motion: MotionStyle | None = None  # Story 20.6; absent: still
    direction: ThemeDirection | None = None


class NavLink(SpecModel):
    label: str = Field(min_length=1, max_length=60)
    page: str | None = None
    href: str | None = Field(default=None, pattern=r"^(https?://|mailto:|tel:)")

    @model_validator(mode="after")
    def _one_target(self):
        if (self.page is None) == (self.href is None):
            raise ValueError("a link needs exactly one of 'page' or 'href'")
        return self


class Header(SpecModel):
    logo_text: str | None = None
    logo: str | None = None  # "asset:<id>"
    navigation: list[NavLink] = []


class Footer(SpecModel):
    text: str | None = None
    links: list[NavLink] = []


class TreeNode(SpecModel):
    """Epic 21: one node of a designed page: an HTML element, a shadcn primitive, a Lucide icon, a library section
    or a data component, with Tailwind classes and props; children are nodes or text."""

    type: str = Field(pattern=r"^[a-zA-Z][A-Za-z0-9-]*$", max_length=63)
    props: dict[str, Any] = {}
    children: list["TreeNode | str"] = []


class Layout(SpecModel):
    shell: Literal["header-footer", "sidebar", "blank"] = "header-footer"
    header: Header = Header()
    footer: Footer = Footer()
    # Epic 21: designed chrome and footer trees; when present they replace the header's and footer's own rendering.
    chrome: TreeNode | None = None
    footer_tree: TreeNode | None = Field(default=None, alias="footerTree")


class Seo(SpecModel):
    title: str | None = None
    description: str | None = None


class DataBinding(SpecModel):
    """Where a section's data comes from: an API operation (dynamic) or a `content` collection (both modes)."""

    operation_id: str | None = Field(default=None, pattern=OPERATION_ID)
    collection: str | None = Field(default=None, pattern=IDENTIFIER)
    params: dict[str, Any] = {}
    fields: list[str] = []  # record fields the section displays; checked against the response (12.5)

    @model_validator(mode="after")
    def _one_source(self):
        if (self.operation_id is None) == (self.collection is None):
            raise ValueError("a data binding needs exactly one of 'operationId' or 'collection'")
        return self


class SectionStates(SpecModel):
    loading: str | None = None
    empty: str | None = None
    error: str | None = None
    empty_image: str | None = Field(default=None, pattern=r"^asset:[a-z][a-z0-9-]*$")  # shown above `empty` (15.1)


class Section(SpecModel):
    id: str = Field(pattern=SLUG, max_length=63)
    component: str = Field(pattern=COMPONENT_NAME, max_length=63)
    data: DataBinding | None = None
    form: str | None = None
    content: dict[str, Any] = {}  # typed per built-in component (section_props.py, Story 17.1)
    states: SectionStates | None = None
    children: list["Section"] | None = None  # layout nodes only (Columns, Stack, Grid, Tabs)


class Page(SpecModel):
    id: str | None = Field(default=None, pattern=SLUG, max_length=63)
    route: str = Field(pattern=ROUTE, max_length=255)
    title: str = Field(min_length=1, max_length=120)
    purpose: str | None = None
    seo: Seo | None = None
    # Story 20.2: how sections follow each other. uniform: each section's own background; alternate: content sections
    # without a background alternate the page colour and the muted tone; dividers: a hairline between sections.
    rhythm: Literal["uniform", "alternate", "dividers"] = "uniform"
    sections: list[Section] = []
    # Epic 21: a page designed as an element tree (Frontend-Agent's site JSON), with its own scoped CSS. A page has
    # sections or a tree; with both, the tree is rendered and the sections are its content outline.
    tree: TreeNode | None = None
    css: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def _sections_or_tree(self):
        if not self.sections and self.tree is None:
            raise ValueError("a page needs sections or a tree")
        return self


class Component(SpecModel):
    name: str = Field(pattern=COMPONENT_NAME, max_length=63)
    kind: Literal["primitive", "composite", "section", "layout"] = "composite"
    uses: list[str] = []
    description: str | None = None
    props_schema: dict[str, Any] | None = Field(default=None, alias="propsSchema")


class FormFieldReference(SpecModel):
    """Epic 22 (app flow only): a reference picked by its name from the parent's list (`x-bga.ref`)."""

    entity: str = Field(max_length=63)
    list_operation: str = Field(pattern=OPERATION_ID)
    detail_operation: str | None = Field(default=None, pattern=OPERATION_ID)
    label_field: str | None = Field(default=None, max_length=63)
    search_param: str | None = Field(default=None, max_length=63)  # the list's search query (`q`), if it has one
    limit_param: str | None = Field(default=None, max_length=63)
    page_size: int | None = Field(default=None, ge=1, le=200)


class FormFieldUpload(SpecModel):
    """Epic 22 (app flow only, Story 22.7): a file or image uploaded through the storage plugin's presigned URL."""

    presign: str = Field(pattern=OPERATION_ID)
    entity: str = Field(max_length=63)
    field: str = Field(max_length=63)
    kind: Literal["file", "image", "video", "audio", "subtitles"] = "file"  # Epic 29: the media kinds
    accept: list[str] = []
    max_size: int | None = Field(default=None, ge=1)


class FormField(SpecModel):
    name: str = Field(pattern=IDENTIFIER, max_length=63)
    type: FormFieldType = "string"
    label: str | None = None
    required: bool = False
    hidden: bool = False
    value: Any = None  # fixed value or "$route.<param>" (hidden fields)
    values: list[str] | None = None  # enum
    min: float | None = None
    max: float | None = None
    max_length: int | None = Field(default=None, ge=1, le=65535)
    placeholder: str | None = None
    # Epic 22 (app flow only; not in the static schema): a hint under the field, a number's currency or unit
    help: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    unit: str | None = Field(default=None, max_length=12)
    reference: FormFieldReference | None = None  # Story 22.6: a picker instead of an id input
    upload: FormFieldUpload | None = None  # Story 22.7: an upload instead of a key input
    transition: bool | None = None  # Story 22.7: an enum limited to the record's `transition:<STATE>` actions


class OnSuccess(SpecModel):
    toast: str | None = None
    navigate: str | None = None  # a page id or a route


class FormLoad(SpecModel):
    operation_id: str = Field(alias="operationId", pattern=OPERATION_ID)
    params: dict[str, Any] = {}


class Form(SpecModel):
    id: str = Field(pattern=IDENTIFIER, max_length=63)
    operation_id: str | None = Field(default=None, pattern=OPERATION_ID)
    load: FormLoad | None = None
    params: dict[str, Any] = {}  # path parameters of the operation, e.g. {"id": "$route.id"}
    fields: list[FormField] = Field(min_length=1)
    submit_label: str | None = None
    on_success: OnSuccess | None = None


class ContentCollection(SpecModel):
    collection: str = Field(pattern=IDENTIFIER, max_length=63)
    records: list[dict[str, Any]] = []


AssetKind = Literal["image", "icon", "video", "file", "illustration", "pattern", "logo"]
AspectRatio = Literal["16:9", "4:3", "1:1", "3:4", "21:9"]


class AssetCredit(SpecModel):
    """Epic 27: a stock photo's credit, shown with it as the photo service requires ("Photo by <name> on Unsplash")."""

    provider: Literal["unsplash"] = "unsplash"
    name: str = Field(min_length=1, max_length=120)
    profile_url: str = Field(pattern=r"^https://", max_length=500)
    source_url: str = Field(pattern=r"^https://", max_length=500)
    photo_id: str | None = Field(default=None, max_length=64)


class Asset(SpecModel):
    """An image the site shows (Stories 15.1, 19.1). `source`: `placeholder` (a themed panel),
    `generate` (an SVG the code engine draws, 15.2), `photo` (an AI photograph, 19.2),
    `upload:<uploadId>` (15.4; may keep `prompt`/`style` for regenerable photos),
    `lucide:<IconName>`, or an `https://` URL. Checked in the validator (FE_INSECURE_URL,
    FE_UNKNOWN_ICON, FE_UNSUPPORTED_ASSET_SOURCE, FE_TOO_MANY_PHOTOS, FE_ASSET_ALT_REQUIRED)."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=63)
    kind: AssetKind = "image"
    alt: str | None = Field(default=None, max_length=300)
    source: str = Field(default="placeholder", max_length=2048)
    prompt: str | None = Field(default=None, max_length=600)  # what to draw (generate); defaults to `alt`
    style: str | None = Field(default=None, max_length=200)
    aspect_ratio: AspectRatio | None = None  # default per kind
    decorative: bool = False  # no alt needed; rendered aria-hidden
    credit: AssetCredit | None = None  # Epic 27: a stock photo (an `https://` source) and who took it


class FrontendSpecV1(SpecModel):
    model_config = ConfigDict(title="FrontendSpec 1.0")

    spec_version: Literal["1.0"]
    project: Project
    theme: Theme = Theme()
    layout: Layout = Layout()
    pages: list[Page] = Field(min_length=1)
    components: list[Component] = []
    forms: list[Form] = []
    content: list[ContentCollection] = []
    assets: list[Asset] = []
    app: AppOutline | None = None  # Epic 22: the app outline (dynamic, `project.flow: "app"` only)
    auth: dict[str, Any] | None = None  # reserved for Epic 10
    backend_spec: str | None = Field(default=None, alias="x-backendSpec")
