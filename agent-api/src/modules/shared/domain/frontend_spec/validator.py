import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from src.modules.shared.domain.backend_spec.issues import Severity, SpecIssue, ValidationReport

from .app import APP_SECTIONS
from .assets import (
    ICON_NAME,
    MAX_GENERATED_ASSETS,
    MAX_PHOTOS,
    SVG_KINDS,
    UPLOAD_ID,
    VIDEO_SOURCES,
    lucide_icons,
    source_kind,
)
from .catalogue import BUILTIN_SECTIONS, SHADCN_PRIMITIVES, THEME_PRESETS
from .copy_rules import stock_copy
from .fonts import FONTS, closest_font
from .icons import closest_icon, resolve_icon
from .issues import FrontendIssueCode
from .normalizer import normalize_frontend_spec, page_id, route_params, walk_sections
from .registry import FRONTEND_SPEC_MODELS
from .schema_v1 import FrontendSpecV1, NavLink, Page, Section
from .section_props import LAYOUT_SECTIONS, MAX_DEPTH, SECTION_ITEMS, SECTION_PROPS, Props
from .trees import check_tree, css_problems, tree_collections

C = FrontendIssueCode
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_COLOR_FN = re.compile(r"^(rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\([^()]*\)$")
_ROUTE_REF = re.compile(r"^\$route\.([A-Za-z][A-Za-z0-9]*)$")
MIN_CONTRAST = 4.5  # WCAG AA for body text
# Design checklist (Story 17.7): a hero headline fits two lines on a 390 px phone up to about this many characters.
HERO_HEADLINE_CHARS = 50
# What a photo can stand in for (19.1): drafts turn placeholder images, illustrations and logos into photos.
PHOTO_KINDS = frozenset({"image", "illustration", "logo"})


@dataclass
class FrontendValidationResult:
    report: ValidationReport
    spec: FrontendSpecV1 | None = None
    normalized: dict[str, Any] | None = None


def validate_frontend_spec_text(raw: str | bytes) -> FrontendValidationResult:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        where = f" (line {exc.lineno}, column {exc.colno})" if isinstance(exc, json.JSONDecodeError) else ""
        issue = SpecIssue(code=C.JSON_MALFORMED, path="", message=f"Body is not valid JSON{where}: {exc}")
        return FrontendValidationResult(ValidationReport.from_issues([issue], None))
    return validate_frontend_spec_data(data)


def validate_frontend_spec_data(data: Any) -> FrontendValidationResult:
    if not isinstance(data, dict):
        issue = SpecIssue(code=C.SCHEMA_VIOLATION, path="", message="FrontendSpec must be a JSON object")
        return FrontendValidationResult(ValidationReport.from_issues([issue], None))

    version = data.get("specVersion")
    model = FRONTEND_SPEC_MODELS.get(version) if isinstance(version, str) else None
    if model is None:
        issue = SpecIssue(
            code=C.SPEC_VERSION_UNSUPPORTED,
            path="/specVersion",
            message=f"Unsupported specVersion {version!r}",
            hint=f"Supported versions: {', '.join(FRONTEND_SPEC_MODELS)}",
        )
        return FrontendValidationResult(ValidationReport.from_issues([issue], None))

    if "journeys" in data:  # Story 22.8: journeys left with the legacy dynamic flow; older specs carry an empty list
        data = {key: value for key, value in data.items() if key != "journeys"}
    try:
        spec = model.model_validate(data)
    except ValidationError as exc:
        issues = [_schema_issue(error) for error in exc.errors()]
        return FrontendValidationResult(ValidationReport.from_issues(issues, version))

    issues = _SemanticChecker(spec).run()
    report = ValidationReport.from_issues(issues, version)
    return FrontendValidationResult(report, spec, normalize_frontend_spec(spec) if report.valid else None)


def _schema_issue(error: dict[str, Any]) -> SpecIssue:
    path = "".join(f"/{part}" for part in error["loc"])
    message = "Unknown property" if error["type"] == "extra_forbidden" else error["msg"]
    return SpecIssue(code=C.SCHEMA_VIOLATION, path=path, message=message)


def valid_color(value: str) -> bool:
    return bool(_HEX.match(value) or _COLOR_FN.match(value))


def _luminance(hex_color: str) -> float | None:
    digits = hex_color.lstrip("#")
    if len(digits) in (3, 4):
        digits = "".join(ch * 2 for ch in digits[:3])
    elif len(digits) in (6, 8):
        digits = digits[:6]
    else:
        return None
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float | None:
    """WCAG contrast of two hex colours; None when either is not hex."""
    if not (_HEX.match(first) and _HEX.match(second)):
        return None
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def route_key(route: str) -> str:
    return re.sub(r"\[[^\]]+\]", "[]", route)


def route_matches(route: str, target: str) -> bool:
    """`/products/42` matches `/products/[id]`."""
    pattern = "^" + re.sub(r"\\\[[^\]]+\\\]", "[^/]+", re.escape(route)) + "/?$"
    return re.match(pattern, target) is not None


def route_refs(value: Any) -> Iterator[str]:
    """Names used as `$route.<name>` anywhere in a value."""
    if isinstance(value, str):
        match = _ROUTE_REF.match(value)
        if match:
            yield match.group(1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from route_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from route_refs(item)


def _asset_refs(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str) and value.startswith("asset:"):
        yield value[len("asset:") :], path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _asset_refs(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _asset_refs(item, f"{path}/{index}")


def _error_path(path: str, loc: tuple[Any, ...]) -> str:
    return path + "".join(f"/{part}" for part in loc)


def _unknown_props(model: Props, path: str) -> Iterator[str]:
    """Paths of keys a props model does not know (kept by `extra="allow"`), nested models included."""
    for key in model.model_extra or {}:
        yield f"{path}/{key}"
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        alias = field.alias or name
        if isinstance(value, Props):
            yield from _unknown_props(value, f"{path}/{alias}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Props):
                    yield from _unknown_props(item, f"{path}/{alias}/{index}")


def _layout_fallbacks(name: str, props: Any) -> list[tuple[str, str, str]]:
    """Story 20.2: layouts that need content the section lacks render as a simpler layout; say which."""
    found = []
    if name == "Hero" and props.variant == "collage":
        images = {image for image in [props.image, *(props.images or [])] if image}
        if len(images) < 2:
            found.append(
                (
                    "variant",
                    "The collage hero needs at least two images ('image' plus 'images'); it shows as 'split'",
                    "Add images to 'images', or pick another variant",
                )
            )
    if name == "Features" and props.form == "alternating" and props.items is not None:
        if not any(item.image for item in props.items):
            found.append(
                (
                    "form",
                    "The alternating form shows an image per item, but no item has one; it shows as 'list'",
                    "Give the items an 'image', or use the 'list' form",
                )
            )
    return found


def _icon_refs(value: Any, path: str) -> Iterator[tuple[str, str]]:
    """Story 20.5: (reference, JSON path) of every item `icon` in section content or a record."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "icon" and isinstance(item, str):
                yield item, f"{path}/icon"
            elif isinstance(item, (dict, list)):
                yield from _icon_refs(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _icon_refs(item, f"{path}/{index}")


def _page_refs(value: Any, path: str) -> Iterator[tuple[str, str, dict[str, Any] | None]]:
    """`{"page": "<id>"}` links inside free-form section content (e.g. a hero's call to action, or a section action)."""
    if isinstance(value, dict):
        if "page" in value and isinstance(value["page"], str):
            params = value.get("params") if isinstance(value.get("params"), dict) else None
            yield value["page"], f"{path}/page", params
        for key, item in value.items():
            if key != "page":
                yield from _page_refs(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _page_refs(item, f"{path}/{index}")


class _SemanticChecker:
    def __init__(self, spec: FrontendSpecV1):
        self.spec = spec
        self.issues: list[SpecIssue] = []
        self.static = spec.project.mode == "static"
        self.app = spec.project.flow == "app"  # Epic 22: app sections are accepted only in the app flow
        self.page_ids = [page.id or page_id(page.route) for page in spec.pages]
        self.pages = dict(zip(self.page_ids, spec.pages, strict=True))
        self.components = {component.name for component in spec.components} | set(BUILTIN_SECTIONS)
        if self.app and not self.static:
            self.components |= set(APP_SECTIONS)
        self.forms = {form.id: form for form in spec.forms}
        self.assets = {asset.id for asset in spec.assets}
        self.collections = {collection.collection for collection in spec.content}
        self.records = {collection.collection: collection.records for collection in spec.content}
        self.collection_index = {collection.collection: index for index, collection in enumerate(spec.content)}
        self.declared_kinds = {component.name: component.kind for component in spec.components}
        self.checked_records: set[tuple[str, str]] = set()
        self.sections_by_id: dict[str, Section] = {}
        for page in spec.pages:
            for section, _, _ in walk_sections(page.sections, ""):
                self.sections_by_id[section.id] = section

    def run(self) -> list[SpecIssue]:
        self._check_duplicates()
        self._check_theme()
        self._check_assets()
        self._check_layout()
        self._check_pages()
        self._check_components()
        self._check_forms()
        self._check_content()
        self._check_trees()
        self._check_app()
        if self.spec.auth is not None and self.spec.project.flow != "app":  # Story 22.7: apps sign in
            self._add(C.FE_UNSUPPORTED_FEATURE, "/auth", "Auth pages arrive with Epic 10; 'auth' is ignored", True)
        return self.issues

    def _check_app(self) -> None:
        """Epic 22: the app flow is a dynamic flow; its outline belongs to it."""
        if self.app and self.static:
            hint = 'Remove "flow", or set "mode": "dynamic"'
            self._add(
                C.FE_APP_FLOW, "/project/flow", "The app flow is for dynamic apps; a static site has none", hint=hint
            )
        if not self.app and not self.static:  # Story 22.8: the legacy dynamic flow is gone
            hint = "Draft the app again from its requirement (dynamic mode): code writes its pages"
            self._add(
                C.FE_APP_FLOW,
                "/project/flow",
                "A dynamic app is built by the app flow; this spec has no 'project.flow: \"app\"'",
                hint=hint,
            )
        if self.spec.app is not None and not self.app:
            hint = 'Set "project": {"flow": "app"} (dynamic apps), or remove "app"'
            self._add(C.FE_APP_FLOW, "/app", "The 'app' outline belongs to the app flow", hint=hint)

    def _check_trees(self) -> None:
        """Epic 21: designed pages and chrome follow the tree rules (`trees.py`)."""
        trees: list[tuple[Any, str]] = [
            (page.tree, f"/pages/{index}/tree") for index, page in enumerate(self.spec.pages) if page.tree is not None
        ]
        layout = self.spec.layout
        trees += [
            (node, f"/layout/{key}")
            for key, node in (("chrome", layout.chrome), ("footerTree", layout.footer_tree))
            if node
        ]
        if not trees:
            return
        collections = tree_collections(self.spec.model_dump(by_alias=True)) if self.static else None
        for node, path in trees:
            tree = node.model_dump(by_alias=True)
            for issue in check_tree(tree, path, set(self.page_ids), self.assets, collections):
                self._add(C(issue["code"]), issue["path"], issue["message"], issue["warning"], issue.get("hint"))
        for index, page in enumerate(self.spec.pages):
            if page.css and (problems := css_problems(page.css)):
                self._add(C.FE_DESIGN_RULE, f"/pages/{index}/css", "; ".join(problems), warning=True)

    def _add(self, code: FrontendIssueCode, path: str, message: str, warning: bool = False, hint: str | None = None):
        severity = Severity.WARNING if warning else Severity.ERROR
        self.issues.append(SpecIssue(code=code, path=path, message=message, hint=hint, severity=severity))

    def _unique(self, values: list[str], path: str, what: str, suffix: str = "") -> None:
        seen: dict[str, int] = {}
        for index, value in enumerate(values):
            if value in seen:
                where = f"{path}/{index}{suffix}"
                self._add(C.FE_DUPLICATE_ID, where, f"{what} '{value}' duplicates {path}/{seen[value]}")
            seen.setdefault(value, index)

    def _check_duplicates(self) -> None:
        spec = self.spec
        self._unique(self.page_ids, "/pages", "Page id", "/id")
        routes: dict[str, int] = {}
        for index, page in enumerate(spec.pages):
            key = route_key(page.route)
            if key in routes:
                self._add(
                    C.FE_DUPLICATE_ROUTE,
                    f"/pages/{index}/route",
                    f"Route {page.route} duplicates /pages/{routes[key]}",
                    hint="Routes that differ only in parameter names are the same route",
                )
            routes.setdefault(key, index)
            self._unique_sections(page.sections, f"/pages/{index}/sections")
            params = route_params(page.route)
            if len(params) != len(set(params)):
                self._add(C.SCHEMA_VIOLATION, f"/pages/{index}/route", "Route parameters must be unique")
        if "/" not in routes:
            self._add(C.FE_NO_HOME_PAGE, "/pages", "No page has the route '/'", warning=True)
        self._unique([c.name for c in spec.components], "/components", "Component", "/name")
        self._unique([f.id for f in spec.forms], "/forms", "Form id", "/id")
        self._unique([a.id for a in spec.assets], "/assets", "Asset id", "/id")
        self._unique([c.collection for c in spec.content], "/content", "Content collection", "/collection")
        for f_index, form in enumerate(spec.forms):
            self._unique([field.name for field in form.fields], f"/forms/{f_index}/fields", "Form field", "/name")

    def _unique_sections(self, sections: list[Section], path: str) -> None:
        """Section ids are unique within a page, nested ones included, so `<pageId>/<sectionId>` names one."""
        seen: dict[str, str] = {}
        for section, here, _ in walk_sections(sections, path):
            if section.id in seen:
                self._add(C.FE_DUPLICATE_ID, f"{here}/id", f"Section id '{section.id}' duplicates {seen[section.id]}")
            seen.setdefault(section.id, here)

    def _check_theme(self) -> None:
        theme = self.spec.theme
        for key, value in theme.typography.model_dump(by_alias=True).items():
            if key.endswith("Font") and value is not None and value not in FONTS:
                suggestion = closest_font(value)
                self._add(
                    C.FE_FONT_NOT_BUNDLED,
                    f"/theme/typography/{key}",
                    f"'{value}' is not a bundled font, so visitors without it installed see a fallback",
                    warning=True,
                    hint=f"Closest bundled font: {suggestion}",
                )
        if theme.icons is not None and theme.icons.set == "lucide" and theme.icons.weight in ("fill", "duotone"):
            self._add(
                C.FE_DESIGN_RULE,
                "/theme/icons/weight",
                f"Lucide icons have no '{theme.icons.weight}' weight; they are drawn bold",
                warning=True,
                hint="Use the phosphor set for filled or duotone icons",
            )
        preset = THEME_PRESETS[theme.style]["colors"]
        for key, value in theme.colors.model_dump().items():
            if value is not None and not valid_color(value):
                self._add(
                    C.FE_INVALID_COLOR,
                    f"/theme/colors/{key}",
                    f"'{value}' is not a CSS colour",
                    hint="Use #rgb, #rrggbb or rgb()/hsl()/oklch()",
                )
        foreground = theme.colors.foreground or preset["foreground"]
        background = theme.colors.background or preset["background"]
        ratio = contrast_ratio(foreground, background) if valid_color(foreground) and valid_color(background) else None
        if ratio is not None and ratio < MIN_CONTRAST:
            self._add(
                C.FE_LOW_CONTRAST,
                "/theme/colors/foreground",
                f"Foreground on background has contrast {ratio:.2f}:1, below {MIN_CONTRAST}:1 (WCAG AA)",
                warning=True,
            )

    def _check_assets(self) -> None:
        """Story 15.1: each asset's source, its alt text, and how many the engine has to draw."""
        generated = 0
        photos = 0
        for index, asset in enumerate(self.spec.assets):
            path = f"/assets/{index}"
            kind = source_kind(asset.source)
            if not asset.decorative and not (asset.alt or "").strip():
                self._add(
                    C.FE_ASSET_ALT_REQUIRED,
                    f"{path}/alt",
                    f"Asset '{asset.id}' needs an 'alt' text",
                    hint='Describe the image, or set "decorative": true if it carries no meaning',
                )
            if kind == "insecure":
                self._add(
                    C.FE_INSECURE_URL,
                    f"{path}/source",
                    f"Asset '{asset.id}': only https:// links are allowed",
                    hint="Use an https:// URL, an upload or a generated image",
                )
            elif kind == "unknown":
                self._add(
                    C.FE_UNSUPPORTED_ASSET_SOURCE,
                    f"{path}/source",
                    f"Asset '{asset.id}': unknown source '{asset.source}'",
                    hint="Use placeholder, generate, photo, upload:<id>, lucide:<Icon> or an https:// URL",
                )
            elif kind == "generate":
                generated += 1
                if asset.kind not in SVG_KINDS:
                    hint = "Icons come from lucide:<Name>" if asset.kind == "icon" else "Upload or link the file"
                    self._add(
                        C.FE_UNSUPPORTED_ASSET_SOURCE,
                        f"{path}/source",
                        f"Asset '{asset.id}': a {asset.kind} cannot be generated",
                        hint=hint,
                    )
            elif kind == "photo":
                photos += 1
                if asset.kind not in PHOTO_KINDS:
                    self._add(
                        C.FE_UNSUPPORTED_ASSET_SOURCE,
                        f"{path}/source",
                        f"Asset '{asset.id}': a {asset.kind} cannot be a photo",
                        hint="photos are for kinds image, illustration and logo; icons come from lucide:<Name>, "
                        "patterns are generated, videos are searched (Epic 31) or uploaded, files are uploaded",
                    )
            elif kind in VIDEO_SOURCES:  # Epic 31: a video found at draft time, or still to find
                if asset.kind != "video":
                    self._add(
                        C.FE_UNSUPPORTED_ASSET_SOURCE,
                        f"{path}/source",
                        f"Asset '{asset.id}': a {asset.kind} cannot be a video search",
                        hint='Videos are `"kind": "video"` with `"source": "search"`, a `query` and a `place`',
                    )
                elif kind == "search" and not (asset.query or asset.alt):
                    self._add(
                        C.FE_UNSUPPORTED_ASSET_SOURCE,
                        f"{path}/query",
                        f"Asset '{asset.id}': a video search needs a `query` (what the video shows)",
                        hint='e.g. "a potter centering clay on the wheel"',
                    )
                elif kind != "search" and asset.video is None:
                    self._add(
                        C.FE_UNSUPPORTED_ASSET_SOURCE,
                        f"{path}/source",
                        f"Asset '{asset.id}': source '{kind}' is written by the drafting code with its `video`",
                        hint='Draft a video as "source": "search" with a "query"; code resolves it',
                    )
            elif kind == "lucide":
                name = asset.source.removeprefix("lucide:")
                icons = lucide_icons()
                if not ICON_NAME.match(name) or (icons and name not in icons):
                    self._add(
                        C.FE_UNKNOWN_ICON,
                        f"{path}/source",
                        f"Asset '{asset.id}': lucide-react has no icon '{name}'",
                        hint="Icon names are PascalCase, as on lucide.dev (e.g. lucide:Mail)",
                    )
            elif kind == "upload":
                if not UPLOAD_ID.match(asset.source.removeprefix("upload:")):
                    self._add(
                        C.FE_UNKNOWN_UPLOAD,
                        f"{path}/source",
                        f"Asset '{asset.id}': '{asset.source}' is not an upload id",
                        hint="Upload the file in the Assets panel and use its upload:upl_… id",
                    )
                elif asset.prompt:
                    # Regenerable photo that became an upload (Story 19.1 step 2a)
                    photos += 1
        if generated > MAX_GENERATED_ASSETS:
            self._add(
                C.FE_TOO_MANY_GENERATED_ASSETS,
                "/assets",
                f"{generated} assets are generated; more than {MAX_GENERATED_ASSETS} makes the drawing step slow",
                warning=True,
                hint="Keep generated images to the ones a page really needs",
            )
        try:
            from src.configs import config

            max_photos = getattr(config, "frontend_max_photos", MAX_PHOTOS)
        except Exception:
            max_photos = MAX_PHOTOS
        if photos > max_photos:
            self._add(
                C.FE_TOO_MANY_PHOTOS,
                "/assets",
                f"{photos} assets are photos; more than {max_photos} is not recommended",
                warning=True,
                hint="keep photos for the images a page really needs; the rest stay placeholders",
            )

    def _check_link(self, link: NavLink, path: str, params: dict[str, Any] | None = None) -> None:
        if link.page is None:
            return
        page = self.pages.get(link.page)
        if page is None:
            self._add(C.FE_UNKNOWN_PAGE, f"{path}/page", f"Unknown page '{link.page}'", hint=self._known_pages())
        elif route_params(page.route):
            needed = set(route_params(page.route))
            provided = set(params.keys()) if params else set()
            if not needed.issubset(provided):
                self._add(
                    C.FE_ROUTE_PARAM_UNBOUND,
                    f"{path}/page",
                    f"Page '{link.page}' ({page.route}) needs route parameters a navigation link cannot fill",
                    hint=self._link_param_hint(page),
                )

    def _link_param_hint(self, page: Page) -> str:
        prefix_pages = [
            p.id
            for p in self.spec.pages
            if not route_params(p.route)
            and p.route not in ("", "/")
            and (page.route.rstrip("/") + "/").startswith(p.route.rstrip("/") + "/")
        ]
        candidates = prefix_pages or [p.id for p in self.spec.pages if not route_params(p.route)]
        candidates_str = ", ".join(f"'{cid}'" for cid in candidates) if candidates else "(none)"
        return (
            f"Link to a page without route parameters ({candidates_str}), "
            "or let a data section link each record to it (binding 'link')"
        )

    def _known_pages(self) -> str:
        return f"Known pages: {', '.join(self.page_ids)}"

    def _check_layout(self) -> None:
        layout = self.spec.layout
        for index, link in enumerate(layout.header.navigation):
            self._check_link(link, f"/layout/header/navigation/{index}")
        for index, link in enumerate(layout.footer.links):
            self._check_link(link, f"/layout/footer/links/{index}")
        if layout.header.logo:
            for asset, path in _asset_refs(layout.header.logo, "/layout/header/logo"):
                if asset not in self.assets:
                    self._add(C.FE_UNKNOWN_ASSET, path, f"Unknown asset '{asset}'")

    def _check_route_refs(self, value: Any, params: list[str], path: str, where: str) -> None:
        for name in route_refs(value):
            if name not in params:
                self._add(
                    C.FE_ROUTE_PARAM_UNBOUND,
                    path,
                    f"'$route.{name}' is not a parameter of {where}",
                    hint=f"Route parameters: {', '.join(params) or '(none)'}",
                )

    def _check_pages(self) -> None:
        for p_index, page in enumerate(self.spec.pages):
            params = route_params(page.route)
            for section, path, depth in walk_sections(page.sections, f"/pages/{p_index}/sections"):
                if section.component not in self.components:
                    self._add(
                        C.FE_UNKNOWN_COMPONENT,
                        f"{path}/component",
                        f"Component '{section.component}' is neither built in nor declared in 'components'",
                        hint=f"Built in: {', '.join(BUILTIN_SECTIONS)}",
                    )
                self._check_layout_node(section, path, depth)
                data = section.data
                if data is not None:
                    if data.operation_id is not None and self.static:
                        self._add(
                            C.FE_STATIC_HAS_BINDING,
                            f"{path}/data/operationId",
                            "Static sites have no backend; show data from 'content' instead",
                        )
                    if data.collection is not None and data.collection not in self.collections:
                        self._add(C.FE_UNKNOWN_CONTENT, f"{path}/data/collection", f"No content '{data.collection}'")
                    self._check_route_refs(data.params, params, f"{path}/data/params", page.route)
                if section.form is not None:
                    form = self.forms.get(section.form)
                    if form is None:
                        self._add(C.FE_UNKNOWN_FORM, f"{path}/form", f"Unknown form '{section.form}'")
                    else:
                        form_params = {**form.params, **{f.name: f.value for f in form.fields}}
                        self._check_route_refs(form_params, params, f"{path}/form", f"{page.route} (form '{form.id}')")
                states = section.states.model_dump(by_alias=True) if section.states else None
                refs = [*_asset_refs(section.content, f"{path}/content"), *_asset_refs(states, f"{path}/states")]
                for asset, asset_path in refs:
                    if asset not in self.assets:
                        self._add(C.FE_UNKNOWN_ASSET, asset_path, f"Unknown asset '{asset}'")
                for target, link_path, link_params in _page_refs(section.content, f"{path}/content"):
                    self._check_link(NavLink(label="link", page=target), link_path.removesuffix("/page"), link_params)
                if self._builtin(section.component):
                    self._check_props(section, path)

    def _builtin(self, name: str) -> bool:
        """A catalogue section the spec does not redeclare as its own component (then its content is free-form)."""
        return name in BUILTIN_SECTIONS and self.declared_kinds.get(name, "section") == "section"

    def _check_layout_node(self, section: Section, path: str, depth: int) -> None:
        layout = section.component in LAYOUT_SECTIONS and self._builtin(section.component)
        if depth > MAX_DEPTH:
            self._add(
                C.FE_INVALID_LAYOUT,
                path,
                f"Sections nest at most {MAX_DEPTH} levels deep",
                hint="Sections lay out their own content; layout nodes only arrange sections",
            )
        if section.children is not None and not layout:
            self._add(
                C.FE_INVALID_LAYOUT,
                f"{path}/children",
                f"'{section.component}' is not a layout node; only {', '.join(sorted(LAYOUT_SECTIONS))} have children",
            )
        if not layout:
            return
        if not section.children:
            self._add(C.FE_INVALID_LAYOUT, f"{path}/children", f"{section.component} needs at least one child section")
        if section.data is not None or section.form is not None:
            self._add(C.FE_INVALID_LAYOUT, path, "Layout nodes show their children, not data or forms")
        labels = section.content.get("labels") if section.component == "Tabs" else None
        if isinstance(labels, list) and section.children and len(labels) != len(section.children):
            self._add(
                C.FE_INVALID_PROPS,
                f"{path}/content/labels",
                f"Tabs has {len(section.children)} child section(s) but {len(labels)} label(s)",
            )

    def _check_props(self, section: Section, path: str) -> None:
        name = section.component
        try:
            props = SECTION_PROPS[name].model_validate(section.content)
        except ValidationError as exc:
            for error in exc.errors():
                self._add(C.FE_INVALID_PROPS, _error_path(f"{path}/content", error["loc"]), f"{name}: {error['msg']}")
        else:
            heading = getattr(props, "heading", "") if name == "Hero" else ""
            if len(heading) > HERO_HEADLINE_CHARS:
                self._add(
                    C.FE_DESIGN_RULE,
                    f"{path}/content/heading",
                    f"The hero headline has {len(heading)} characters; it wraps past two lines on a phone",
                    warning=True,
                    hint=f"Keep it to {HERO_HEADLINE_CHARS} characters or fewer and move the rest into 'body'",
                )
            for key, message, hint in _layout_fallbacks(name, props):
                self._add(C.FE_DESIGN_RULE, f"{path}/content/{key}", message, warning=True, hint=hint)
            self._check_icons(section.content, f"{path}/content")
            for copy_path, text, phrase in stock_copy(section.content, f"{path}/content"):
                self._add(
                    C.FE_DESIGN_RULE,
                    copy_path,
                    f"'{text}' is a stock phrase ({phrase}) that many generated sites use",
                    warning=True,
                    hint="Say this business's own action or point, e.g. 'Book a table' or 'See this week's menu'",
                )
            known = ", ".join(field.alias or key for key, field in SECTION_PROPS[name].model_fields.items())
            for unknown in _unknown_props(props, f"{path}/content"):
                self._add(
                    C.FE_UNKNOWN_PROP,
                    unknown,
                    f"{name} does not use '{unknown.rsplit('/', 1)[-1]}'",
                    warning=True,
                    hint=f"Known: {known}",
                )
        item = SECTION_ITEMS.get(name)
        if item is None:
            return
        data = section.data
        featured = name == "Video" and section.content.get("video") is not None  # Epic 31: one featured video
        if section.content.get("items") is None and data is None and not featured:
            self._add(
                C.FE_INVALID_PROPS,
                f"{path}/content/items",
                f"{name} needs 'content.items' or a 'data' binding",
            )
        if data is not None and data.collection in self.records and (data.collection, name) not in self.checked_records:
            self.checked_records.add((data.collection, name))
            base = f"/content/{self.collection_index[data.collection]}/records"
            for r_index, record in enumerate(self.records[data.collection]):
                try:
                    item.model_validate(record)
                except ValidationError as exc:
                    for error in exc.errors():
                        self._add(
                            C.FE_INVALID_PROPS,
                            _error_path(f"{base}/{r_index}", error["loc"]),
                            f"{name} (section '{section.id}') shows this record: {error['msg']}",
                        )

    def _check_components(self) -> None:
        known = SHADCN_PRIMITIVES | self.components
        for c_index, component in enumerate(self.spec.components):
            for u_index, name in enumerate(component.uses):
                if name not in known:
                    self._add(
                        C.FE_UNKNOWN_COMPONENT,
                        f"/components/{c_index}/uses/{u_index}",
                        f"'{name}' is not a shadcn primitive or a known component",
                    )

    def _check_forms(self) -> None:
        for f_index, form in enumerate(self.spec.forms):
            path = f"/forms/{f_index}"
            if form.operation_id is not None and self.static:
                self._add(
                    C.FE_STATIC_HAS_BINDING,
                    f"{path}/operationId",
                    "Static sites have no backend; a static form cannot call an operation",
                )
            for i, field in enumerate(form.fields):
                if field.type == "enum" and not field.values:
                    self._add(C.SCHEMA_VIOLATION, f"{path}/fields/{i}/values", "Enum fields need 'values'")
            navigate = form.on_success.navigate if form.on_success else None
            if navigate is None:
                continue
            if navigate.startswith("/"):
                if not any(route_matches(page.route, navigate) for page in self.spec.pages):
                    self._add(C.FE_UNKNOWN_PAGE, f"{path}/onSuccess/navigate", f"No page has the route {navigate}")
            elif navigate not in self.pages:
                self._add(
                    C.FE_UNKNOWN_PAGE,
                    f"{path}/onSuccess/navigate",
                    f"Unknown page '{navigate}'",
                    hint=self._known_pages(),
                )

    def _check_icons(self, value: Any, path: str) -> None:
        """Story 20.5: every item icon resolves to an icon of the site's set (intents through the icon index)."""
        icons = self.spec.theme.icons
        icon_set = icons.set if icons is not None else "lucide"
        if icon_set == "none":
            return
        for ref, ref_path in _icon_refs(value, path):
            if resolve_icon(ref, icon_set) is not None:
                continue
            name = ref.partition(":")[2]
            closest = closest_icon(name, icon_set) if not ref.startswith("intent:") else None
            hint = f"Closest icon: {icon_set}:{closest}" if closest else "Describe a concrete object, e.g. intent:truck"
            self._add(
                C.FE_UNKNOWN_ICON, ref_path, f"'{ref}' matches no {icon_set} icon, so the item shows none", True, hint
            )

    def _check_content(self) -> None:
        for c_index, collection in enumerate(self.spec.content):
            for r_index, record in enumerate(collection.records):
                self._check_icons(record, f"/content/{c_index}/records/{r_index}")
                for asset, path in _asset_refs(record, f"/content/{c_index}/records/{r_index}"):
                    if asset not in self.assets:
                        self._add(C.FE_UNKNOWN_ASSET, path, f"Unknown asset '{asset}'")
