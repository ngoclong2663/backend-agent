"""Tree pages (Epic 21): a page designed as an element tree, as Frontend-Agent's site JSON writes it.

A node is `{"type", "props", "children"}`: an HTML element, a shadcn primitive (`Tabs`, `Sheet`, `Card`, …), a
Lucide icon by name (`Sparkles`), a library section (`Faq`, with its content as props), a **data component**
(`CollectionBrowser`, `RecordField`, `Metric`, `Chart`, `RecordForm`, …) or a string. `props` are `className`
(Tailwind, theme tokens only), attributes, `animate` and the component's own props. A page may also carry its own
`css`, scoped to the page by code.

Everything here is code, no model: `classify` says what a type is; `check_tree` reports what breaks the rules;
`fix_trees` repairs what it can (unwraps unknown wrappers, drops dangerous elements, strips raw colours and
`fixed`, turns foreign image sources into placeholder assets, scopes the CSS) and notes each change; the renderer
(`frontend_renderer.tree_site`) then turns a clean tree into `site.json`.
"""

import re
from collections.abc import Iterator
from typing import Any

from .catalogue import BUILTIN_SECTIONS
from .icons import icon_index, kebab, lucide_current

MAX_NODES = 2000
MAX_DEPTH = 24

ELEMENTS = frozenset(
    "div section main header footer nav article aside h1 h2 h3 h4 h5 h6 p span a ul ol li img figure figcaption "
    "blockquote strong em b i small br hr table thead tbody tfoot tr th td button dl dt dd time address cite code "
    "pre sup sub mark abbr kbd q s u del ins label picture svg path circle rect line polyline polygon g".split()
)
VOID_ELEMENTS = frozenset({"img", "br", "hr", "path", "circle", "rect", "line", "polyline", "polygon"})
# Never rendered: scripts and frames, raw forms and inputs (RecordForm is the form), document metadata.
REMOVED = frozenset(
    "script iframe style link meta object embed form input textarea select option base noscript template "
    "video audio source canvas dialog".split()
)
# shadcn primitives the tree renderer imports (shadcn package → exports); Link and Container are the renderer's own.
PRIMITIVES: dict[str, str] = {
    "Link": "",
    "Container": "",
    "Tabs": "tabs",
    "TabsList": "tabs",
    "TabsTrigger": "tabs",
    "TabsContent": "tabs",
    "Sheet": "sheet",
    "SheetTrigger": "sheet",
    "SheetContent": "sheet",
    "SheetHeader": "sheet",
    "SheetTitle": "sheet",
    "SheetDescription": "sheet",
    "SheetFooter": "sheet",
    "Badge": "badge",
    "Button": "button",
    "Card": "card",
    "CardHeader": "card",
    "CardTitle": "card",
    "CardDescription": "card",
    "CardContent": "card",
    "CardFooter": "card",
    "Separator": "separator",
    "Accordion": "accordion",
    "AccordionItem": "accordion",
    "AccordionTrigger": "accordion",
    "AccordionContent": "accordion",
    "Table": "table",
    "TableHeader": "table",
    "TableBody": "table",
    "TableRow": "table",
    "TableHead": "table",
    "TableCell": "table",
    "Avatar": "avatar",
    "AvatarImage": "avatar",
    "AvatarFallback": "avatar",
}
TREE_SHADCN = frozenset(package for package in PRIMITIVES.values() if package)

DATA_CONTAINERS: dict[str, str] = {"CollectionBrowser": "list", "CollectionStrip": "list", "CollectionDetail": "get"}
DATA_LIST_CONTROLS = frozenset(
    {"SearchBox", "CategoryFilter", "FacetFilter", "SortControl", "Pagination", "ResultCount"}
)
DATA_RECORD = frozenset({"ItemList", "RecordField", "RecordImage", "RecordPrice", "RecordLink", "RecordStars"})
DATA_WRITE = frozenset({"RecordForm", "RecordAction"})
DATA_AGGREGATE = frozenset({"Metric", "Chart"})
DATA_STATES = frozenset({"Empty", "Loading", "Error"})
# Epic 31 (D8): the library's video pieces, bound to a `video` asset (`asset: "asset:<id>"`); raw `video` / `iframe`
# elements stay removed
DATA_MEDIA = frozenset({"VideoEmbed", "BackgroundVideo"})
DATA_COMPONENTS = (
    frozenset(DATA_CONTAINERS)
    | DATA_LIST_CONTROLS
    | DATA_RECORD
    | DATA_WRITE
    | DATA_AGGREGATE
    | DATA_STATES
    | DATA_MEDIA
)
AGGREGATE_FUNCTIONS = ("count", "sum", "avg", "min", "max")
CHART_KINDS = ("bar", "line", "area", "donut")
# Other words engines write for them; `fix_trees` maps them so one Metric does not cost the page its design.
# "total" sums a field when the Metric has one and counts the records otherwise.
AGGREGATE_SYNONYMS = {
    "average": "avg", "mean": "avg", "minimum": "min", "lowest": "min", "maximum": "max", "highest": "max",
    "number": "count", "length": "count", "size": "count", "total": "sum",
}  # fmt: skip
CHART_SYNONYMS = {"pie": "donut", "doughnut": "donut", "column": "bar", "histogram": "bar"}

# Classes that bypass the theme: Tailwind palette colours and arbitrary colour values. Theme tokens
# (`bg-primary/10`, `text-muted-foreground`, `border-border`) are the only colours a tree may use.
_PALETTE = re.compile(
    r"^(?:[a-z0-9-]+:)*(?:bg|text|border|from|via|to|ring|fill|stroke|shadow|outline|decoration|accent|caret|"
    r"divide|placeholder|border-[trblxy])-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|"
    r"violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}(?:/\d+)?$"
)
_ARBITRARY_COLOUR = re.compile(r"\[(?:#|rgba?\(|hsla?\(|oklch\(|color:)")
_FIXED = re.compile(r"^(?:[a-z0-9-]+:)*fixed$")
_CSS_BLOCKED = re.compile(r"@import|expression\(|behavior:|url\(\s*['\"]?(?:https?:|//|data:)", re.IGNORECASE)
_CSS_FIXED = re.compile(r"position\s*:\s*fixed\s*;?", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import[^;]*;?", re.IGNORECASE)
_CSS_BLOCKED_DECLARATION = re.compile(
    r"[^;{}]*(?:expression\(|behavior:|url\(\s*['\"]?(?:https?:|//|data:))[^;{}]*;?", re.IGNORECASE
)
_CSS_RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
_PAGE_REF = re.compile(r"^page:([a-z][a-z0-9]*(?:-[a-z0-9]+)*)$")
_ASSET_REF = re.compile(r"^asset:([a-z][a-z0-9-]*)$")

Kind = str  # element | primitive | icon | section | data | removed | unknown


def _lucide_names() -> set[str]:
    return set((icon_index().get("lucide") or {}).get("icons") or {})


_LUCIDE: set[str] | None = None


def classify(node_type: str) -> Kind:
    """What a node type is; elements, primitives, sections and data components win over an icon of the same name."""
    global _LUCIDE
    if node_type in REMOVED:
        return "removed"
    if node_type in ELEMENTS:
        return "element"
    if node_type in PRIMITIVES:
        return "primitive"
    if node_type in DATA_COMPONENTS:
        return "data"
    if node_type in BUILTIN_SECTIONS:
        return "section"
    if node_type[:1].isupper():
        if _LUCIDE is None:
            _LUCIDE = _lucide_names()
        if kebab(node_type) in _LUCIDE:
            return "icon"
    return "unknown"


def walk(node: Any, path: str = "", depth: int = 1) -> Iterator[tuple[dict[str, Any], str, int]]:
    """(node, JSON pointer, depth) for every object node, depth first; strings are skipped."""
    if not isinstance(node, dict):
        return
    yield node, path, depth
    for index, child in enumerate(node.get("children") or []):
        yield from walk(child, f"{path}/children/{index}", depth + 1)


def count_nodes(node: Any) -> tuple[int, int]:
    """(nodes, deepest level) of a tree."""
    nodes, deepest = 0, 0
    for _, _, depth in walk(node):
        nodes += 1
        deepest = max(deepest, depth)
    return nodes, deepest


def page_refs(node: Any) -> Iterator[tuple[str, str]]:
    """(page id, pointer) for every `Link to="page:…"` and `detailSlug`."""
    for item, path, _ in walk(node):
        props = item.get("props") or {}
        for key in ("to", "detailSlug", "href"):
            value = props.get(key)
            if isinstance(value, str) and (match := _PAGE_REF.match(value)):
                yield match.group(1), f"{path}/props/{key}"


def asset_refs(node: Any) -> Iterator[tuple[str, str]]:
    """(asset id, pointer) for every `img src="asset:…"` and every video component's `asset` (Epic 31)."""
    for item, path, _ in walk(node):
        props = item.get("props") or {}
        src = props.get("src")
        if isinstance(src, str) and (match := _ASSET_REF.match(src)):
            yield match.group(1), f"{path}/props/src"
        asset = props.get("asset")
        if item.get("type") in DATA_MEDIA and isinstance(asset, str) and (match := _ASSET_REF.match(asset)):
            yield match.group(1), f"{path}/props/asset"


def class_problems(class_name: Any) -> list[str]:
    """The classes of a `className` that bypass the theme or pin an element to the viewport."""
    if not isinstance(class_name, str):
        return []
    return [
        token
        for token in class_name.split()
        if _PALETTE.match(token) or _ARBITRARY_COLOUR.search(token) or _FIXED.match(token)
    ]


def css_problems(css: str) -> list[str]:
    problems = []
    if _CSS_BLOCKED.search(css):
        problems.append("imports, external or data URLs and expressions are not allowed")
    if _CSS_FIXED.search(css):
        problems.append("position: fixed is not allowed on a page")
    return problems


def scope_css(css: str, page_id: str) -> str:
    """Prefixes every top-level selector with the page's marker, keeps `@keyframes` as they are and recurses into
    `@media` / `@supports`; drops blocked declarations."""
    css = _CSS_FIXED.sub("", css)
    css = _CSS_IMPORT.sub("", css)
    css = _CSS_BLOCKED_DECLARATION.sub("", css)
    prefix = f'[data-page="{page_id}"]'
    return _scope_block(css, prefix)


def _split_rules(css: str) -> Iterator[tuple[str, str]]:
    """(selector, body) for each rule at this level, nesting-aware."""
    depth, start, selector_start = 0, 0, 0
    for index, char in enumerate(css):
        if char == "{":
            if depth == 0:
                selector_start = start
                body_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                yield css[selector_start : body_start - 1].strip(), css[body_start:index]
                start = index + 1


def _scope_block(css: str, prefix: str) -> str:
    out = []
    for selector, body in _split_rules(css):
        if not selector:
            continue
        if selector.startswith("@keyframes") or selector.startswith("@font-face"):
            out.append(f"{selector} {{{body}}}")
        elif selector.startswith("@"):
            out.append(f"{selector} {{\n{_scope_block(body, prefix)}\n}}")
        else:
            scoped = ", ".join(
                part.strip() if part.strip().startswith(prefix) else f"{prefix} {part.strip()}"
                for part in selector.split(",")
                if part.strip()
            )
            out.append(f"{scoped} {{{body}}}")
    return "\n".join(out)


# -- checks ------------------------------------------------------------------------------------------------------------


def check_tree(
    tree: Any,
    path: str,
    page_ids: set[str],
    asset_ids: set[str],
    collections: dict[str, set[str]] | None,
) -> list[dict[str, Any]]:
    """Issues as dicts `{code, path, message, warning, hint?}` (the validator turns them into SpecIssues).
    `collections` maps a static site's collection keys to their field names; None for a dynamic site, whose data
    components bind to the API contract (checked in the pair check)."""
    issues: list[dict[str, Any]] = []

    def add(code: str, where: str, message: str, warning: bool = True, hint: str | None = None) -> None:
        issues.append({"code": code, "path": where, "message": message, "warning": warning, "hint": hint})

    nodes, deepest = count_nodes(tree)
    if nodes > MAX_NODES:
        add("FE_INVALID_LAYOUT", path, f"The tree has {nodes} nodes (at most {MAX_NODES})", warning=False)
    if deepest > MAX_DEPTH:
        add("FE_INVALID_LAYOUT", path, f"The tree is {deepest} levels deep (at most {MAX_DEPTH})", warning=False)
    headings = 0
    containers: list[tuple[str, dict[str, Any]]] = []
    for node, where, _ in walk(tree):
        node_type = node.get("type")
        if not isinstance(node_type, str):
            add("SCHEMA_VIOLATION", f"{where}/type", "A node needs a 'type'", warning=False)
            continue
        kind = classify(node_type)
        props = node.get("props") or {}
        if kind == "removed":
            add("FE_UNSUPPORTED_FEATURE", f"{where}/type", f"'{node_type}' is not rendered; removed")
        elif kind == "unknown":
            add("FE_UNSUPPORTED_FEATURE", f"{where}/type", f"Unknown node type '{node_type}'; its children are kept")
        if node_type == "h1":
            headings += 1
        if node_type == "img":
            src = props.get("src")
            if not (isinstance(src, str) and _ASSET_REF.match(src)):
                add("FE_UNKNOWN_ASSET", f"{where}/props/src", "Images come from the spec's assets (`asset:<id>`)")
            if not isinstance(props.get("alt"), str):
                add("FE_ASSET_ALT_REQUIRED", f"{where}/props", "An image needs an alt text ('' when decorative)")
        for token in class_problems(props.get("className")):
            add("FE_DESIGN_RULE", f"{where}/props/className", f"'{token}' bypasses the theme or pins to the viewport")
        if kind == "data":
            issues.extend(_check_data_node(node_type, props, where, collections))
            if node_type in DATA_CONTAINERS:
                containers.append((where, props))
    if headings > 1:
        add("FE_DESIGN_RULE", path, f"{headings} h1 headings; a page has one")
    for page, where in page_refs(tree):
        if page not in page_ids:
            add("FE_UNKNOWN_PAGE", where, f"Unknown page '{page}'", warning=False)
    for asset, where in asset_refs(tree):
        if asset not in asset_ids:
            add("FE_UNKNOWN_ASSET", where, f"Unknown asset '{asset}'", warning=False)
    return issues


def _check_data_node(
    node_type: str, props: dict[str, Any], where: str, collections: dict[str, set[str]] | None
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, warning: bool = False) -> None:
        issues.append({"code": code, "path": where, "message": message, "warning": warning, "hint": None})

    collection = props.get("collection")
    if node_type in DATA_CONTAINERS or node_type in DATA_AGGREGATE or node_type in DATA_WRITE:
        if not isinstance(collection, str):
            # A site with one collection needs no name on its components (as the importer reads site JSON).
            if collections is not None and len(collections) != 1:
                add("FE_UNKNOWN_FIELD", f"{node_type} needs 'collection' (which records it shows)")
        elif collections is not None and collection not in collections:
            known = ", ".join(sorted(collections)) or "(none)"
            add("FE_UNKNOWN_FIELD", f"Unknown collection '{collection}'; known: {known}")
    if node_type == "Metric":
        if props.get("fn") not in AGGREGATE_FUNCTIONS:
            add("FE_INVALID_PROPS", f"Metric 'fn' is one of {', '.join(AGGREGATE_FUNCTIONS)}")
        elif props.get("fn") != "count" and not isinstance(props.get("field"), str):
            add("FE_INVALID_PROPS", f"Metric '{props.get('fn')}' needs 'field'")
    if node_type == "Chart":
        if props.get("kind") not in CHART_KINDS:
            add("FE_INVALID_PROPS", f"Chart 'kind' is one of {', '.join(CHART_KINDS)}")
        if not isinstance(props.get("groupBy"), str):
            add("FE_INVALID_PROPS", "Chart needs 'groupBy' (the field its bars or slices group on)")
    if node_type == "RecordForm" and props.get("mode", "create") not in ("create", "edit"):
        add("FE_INVALID_PROPS", "RecordForm 'mode' is 'create' or 'edit'")
    if node_type == "RecordAction" and props.get("action") not in ("delete", "set"):
        add("FE_INVALID_PROPS", "RecordAction 'action' is 'delete' or 'set'")
    if collections is not None and isinstance(collection, str) and collection in collections:
        fields = collections[collection]
        for key in ("field", "sortBy", "categoryField", "groupBy", "altField"):
            value = props.get(key)
            if isinstance(value, str) and fields and value not in fields:
                add("FE_UNKNOWN_FIELD", f"'{value}' is not a field of collection '{collection}'", warning=True)
    return issues


# -- fixes -------------------------------------------------------------------------------------------------------------


def fix_trees(spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Repairs every tree of a spec in place and returns (spec, notes). Only what the rules can decide alone:
    unknown wrappers are unwrapped, removed elements dropped, raw colours and `fixed` stripped, foreign image sources
    replaced by placeholder assets, missing alts filled, the page CSS scoped and cleaned, old Lucide icon names
    renamed, a Metric's `fn` and a Chart's `kind` mapped to the allowed ones (a Metric that stays unclear is dropped
    alone, so the page keeps its design)."""
    notes: list[dict[str, Any]] = []
    assets = spec.setdefault("assets", []) if isinstance(spec.get("assets"), list) else []
    asset_ids = {a.get("id") for a in assets if isinstance(a, dict)}
    pages = [page for page in spec.get("pages") or [] if isinstance(page, dict)]
    page_ids = {_page_marker(page, index) for index, page in enumerate(pages)}
    home = next((_page_marker(page, index) for index, page in enumerate(pages) if page.get("route") == "/"), None)
    for index, page in enumerate(spec.get("pages") or []):
        if not isinstance(page, dict) or not isinstance(page.get("tree"), dict):
            continue
        where = f"/pages/{index}/tree"
        page["tree"] = _fix_node(page["tree"], where, notes, assets, asset_ids, index)
        for ref, pointer in list(page_refs(page["tree"])):
            if ref not in page_ids:  # an unknown page: the link goes home rather than nowhere
                _set_pointer(page["tree"], pointer, f"page:{home}" if home else "/")
                notes.append(_note(pointer, f"Link to unknown page '{ref}' points at the home page"))
        css = page.get("css")
        if isinstance(css, str) and css.strip():
            problems = css_problems(css)
            if problems:
                notes.append(_note(f"/pages/{index}/css", "Page CSS cleaned: " + "; ".join(problems)))
            if _CSS_RAW_COLOUR.search(css):
                notes.append(
                    _note(
                        f"/pages/{index}/css",
                        "Page CSS uses raw colours; theme tokens (var(--primary)) keep light and dark in step",
                    )
                )
            page["css"] = scope_css(css, _page_marker(page, index))
    layout = spec.get("layout")
    if isinstance(layout, dict):
        for key in ("chrome", "footerTree"):
            if isinstance(layout.get(key), dict):
                layout[key] = _fix_node(layout[key], f"/layout/{key}", notes, assets, asset_ids, None, in_chrome=True)
    return spec, notes


def _set_pointer(tree: dict[str, Any], pointer: str, value: Any) -> None:
    """Sets the value at a JSON pointer inside a tree (`/children/0/props/to`)."""
    tokens = [t for t in pointer.split("/") if t]
    current: Any = tree
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    if tokens:
        current[tokens[-1]] = value


def _page_marker(page: dict[str, Any], index: int) -> str:
    from .normalizer import page_id

    return page.get("id") or (page_id(page["route"]) if isinstance(page.get("route"), str) else f"page-{index}")


def _note(path: str, message: str) -> dict[str, Any]:
    return {"spec": "frontend", "path": path, "message": message, "suggestion": None}


def _fix_node(
    node: Any,
    where: str,
    notes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_ids: set[str],
    page_index: int | None,
    in_chrome: bool = False,
) -> Any:
    if not isinstance(node, dict):
        return node
    node_type = node.get("type")
    if not isinstance(node_type, str):
        return None
    kind = classify(node_type)
    if kind == "unknown" and (current := lucide_current(node_type)):
        notes.append(_note(f"{where}/type", f"Icon '{node_type}' renamed to '{current}' (Lucide's current name)"))
        node_type, kind = current, "icon"
    props = dict(node.get("props") or {})
    children = [
        fixed
        for index, child in enumerate(node.get("children") or [])
        if (fixed := _fix_node(child, f"{where}/children/{index}", notes, assets, asset_ids, page_index, in_chrome))
        is not None
    ]
    if kind == "removed":
        notes.append(_note(f"{where}/type", f"'{node_type}' is not rendered; removed"))
        return None
    if kind == "unknown":
        notes.append(_note(f"{where}/type", f"Unknown node type '{node_type}' unwrapped; its children are kept"))
        return {"type": "div", "props": {k: v for k, v in props.items() if k == "className"}, "children": children}
    bad = class_problems(props.get("className"))
    bad = [token for token in bad if not (in_chrome and _FIXED.match(token))]  # the chrome may stick
    if bad:
        kept = [token for token in str(props["className"]).split() if token not in bad]
        props["className"] = " ".join(kept)
        notes.append(_note(f"{where}/props/className", f"Removed {', '.join(bad)}: theme tokens only, nothing fixed"))
    if node_type == "Metric" and not _fix_metric(props, where, notes):
        return None
    if node_type == "Chart":
        _fix_chart(props, where, notes)
    if node_type == "img":
        src = props.get("src")
        if not (isinstance(src, str) and _ASSET_REF.match(src) and _ASSET_REF.match(src).group(1) in asset_ids):
            asset_id = f"tree-image-{len(asset_ids) + 1}"
            alt = props.get("alt") if isinstance(props.get("alt"), str) else ""
            assets.append(
                {"id": asset_id, "kind": "image", "alt": alt or None, "source": "placeholder", "decorative": not alt}
            )
            asset_ids.add(asset_id)
            notes.append(
                _note(
                    f"{where}/props/src", f"Image source {str(src)[:60]!r} replaced by placeholder asset '{asset_id}'"
                )
            )
            props["src"] = f"asset:{asset_id}"
        if not isinstance(props.get("alt"), str):
            props["alt"] = ""
    out: dict[str, Any] = {"type": node_type, "props": props}
    if children or node_type not in VOID_ELEMENTS:
        out["children"] = children
    return out


def _fix_metric(props: dict[str, Any], where: str, notes: list[dict[str, Any]]) -> bool:
    """Maps a Metric's `fn` to an allowed function in place; False when it cannot be decided (drop the Metric)."""
    fn = props.get("fn")
    has_field = isinstance(props.get("field"), str)
    word = fn.strip().lower() if isinstance(fn, str) else ""
    fixed = word if word in AGGREGATE_FUNCTIONS else AGGREGATE_SYNONYMS.get(word)
    if fixed == "sum" and word == "total" and not has_field:
        fixed = "count"
    if fixed is None and not has_field:
        fixed = "count"  # with no field the only thing a Metric can show is how many records there are
    if fixed is None or (fixed != "count" and not has_field):
        reason = (
            f"'fn' {fn!r} is not one of {', '.join(AGGREGATE_FUNCTIONS)}"
            if fixed is None
            else f"'{fixed}' needs 'field'"
        )
        notes.append(_note(where, f"Metric dropped ({reason}); the rest of the page keeps its design"))
        return False
    if fixed != fn:
        props["fn"] = fixed
        notes.append(_note(f"{where}/props/fn", f"Metric 'fn' {fn!r} read as '{fixed}'"))
    return True


def _fix_chart(props: dict[str, Any], where: str, notes: list[dict[str, Any]]) -> None:
    kind = props.get("kind")
    word = kind.strip().lower() if isinstance(kind, str) else ""
    fixed = word if word in CHART_KINDS else CHART_SYNONYMS.get(word, "bar")
    if fixed != kind:
        props["kind"] = fixed
        notes.append(_note(f"{where}/props/kind", f"Chart 'kind' {kind!r} read as '{fixed}'"))


def tree_collections(spec: dict[str, Any]) -> dict[str, set[str]]:
    """A static site's collections with their field names (for the checks)."""
    out: dict[str, set[str]] = {}
    for item in spec.get("content") or []:
        if isinstance(item, dict) and isinstance(item.get("collection"), str):
            fields: set[str] = set()
            for record in item.get("records") or []:
                if isinstance(record, dict):
                    fields |= set(record)
            out[item["collection"]] = fields
    return out


def used_primitives(spec: dict[str, Any]) -> set[str]:
    """The shadcn packages the spec's trees need."""
    packages: set[str] = set()
    for tree in all_trees(spec):
        for node, _, _ in walk(tree):
            package = PRIMITIVES.get(str(node.get("type")))
            if package:
                packages.add(package)
    return packages


def all_trees(spec: dict[str, Any]) -> list[dict[str, Any]]:
    trees = [
        page["tree"]
        for page in spec.get("pages") or []
        if isinstance(page, dict) and isinstance(page.get("tree"), dict)
    ]
    layout = spec.get("layout") or {}
    trees += [layout[key] for key in ("chrome", "footerTree") if isinstance(layout.get(key), dict)]
    return trees


def allowed_types_markdown() -> str:
    """The node types a drafting prompt may use (for `draft_tree`)."""
    return (
        "- HTML elements: " + ", ".join(sorted(ELEMENTS)) + "\n"
        "- Primitives: " + ", ".join(PRIMITIVES) + ' (`Link` takes `to: "page:<page id>"` or `href`)\n'
        "- Lucide icons by name (e.g. `Sparkles`, `ArrowRight`, `Clock`), `size-4` classes for sizing\n"
        "- Library sections with their content as props: " + ", ".join(sorted(BUILTIN_SECTIONS)) + "\n"
        "- Data components: " + ", ".join(sorted(DATA_COMPONENTS))
    )
