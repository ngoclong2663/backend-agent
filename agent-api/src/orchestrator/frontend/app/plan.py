"""The frontend plan of an app (Epic 22): the same plan shape the scaffold, the checks and the previews read, with
`rendering: "app"` (the scaffold writes every file; no engine call) and the app kit's shell and primitives."""

import re
from pathlib import Path
from typing import Any

from src.modules.shared.domain.backend_spec.naming import pluralize, to_kebab
from src.modules.shared.domain.frontend_spec.app import APP_SECTIONS
from src.modules.shared.domain.frontend_spec.design_registry import registry

from ...samples import has_media
from ..planner import _UI_IMPORT, FRONTEND_PLAN_VERSION, _Planner, primitive_closure
from ..theme import build_theme
from .design import kit_design
from .files import design_plugins_used, frontend_plugins
from .recipes import first_recipe

KIT_ROOT = Path(__file__).resolve().parents[4] / "templates" / "nextjs_overlay" / "files" / "dynamic" / "app"
SHELL_FILE = "src/components/layout/SiteShell.tsx"  # the overlay's app shell, under the name the root layout imports
ALWAYS_PRIMITIVES = ("button", "skeleton", "sonner", "separator")


PLUGINS_ROOT = Path(__file__).resolve().parents[4] / "templates" / "plugins"


def plugin_frontend(name: str) -> Path:
    """Story 22.7: a plugin's frontend files (`templates/plugins/<name>/frontend/files/`), copied for apps using it."""
    return PLUGINS_ROOT / name / "frontend" / "files"


def kit_primitives(
    kit: Path = KIT_ROOT, plugins: list[str] | None = None, design: list[dict[str, str]] | None = None
) -> list[str]:
    """The shadcn primitives the app kit imports (it is copied whole), its plugins' files and the design plugins'
    copied files (Epic 30), with what they import."""
    wanted = set(ALWAYS_PRIMITIVES)
    roots = [kit, *(plugin_frontend(name) for name in plugins or [])]
    for root in roots:
        for path in sorted(root.rglob("*.ts*")):
            wanted |= set(_UI_IMPORT.findall(path.read_text()))
    for item in design or []:
        for source, _target in registry().copied(item["kind"], item["name"]):
            if source.suffix in (".ts", ".tsx"):
                wanted |= set(_UI_IMPORT.findall(source.read_text()))
    return primitive_closure(wanted)


def pairing_theme(theme: dict[str, Any], outline: dict[str, Any]) -> dict[str, Any]:
    """Story 30.6: the theme with the current look's font pairing written into its typography (the look the user
    picked, else the first look's, else the design's); a copy. Without a pairing the theme is returned as it is."""
    design = outline.get("design") or {}
    recipe = first_recipe(design) if design else None
    look = next((look for look in design.get("looks") or [] if look.get("recipe") == recipe), None)
    name = (look or {}).get("fontPairing") or design.get("fontPairing")
    plugin = registry().get("font-pairing", name)
    if plugin is None:
        return theme
    typography = {**(theme.get("typography") or {}), "headingFont": plugin.heading, "bodyFont": plugin.body}
    for key, value in (
        ("headingWeight", plugin.heading_weight),
        ("headingCase", plugin.heading_case),
        ("tracking", plugin.tracking),
        ("ratio", plugin.ratio),
    ):
        if value is not None:
            typography[key] = value
    return {**theme, "typography": typography}


def design_plugins(outline: dict[str, Any]) -> list[dict[str, str]]:
    """Epic 30 (D4): the folder design plugins the app's layouts use, copied into the app by the scaffold."""
    used = design_plugins_used(kit_design(outline), outline.get("areas") or [])
    return [
        {"kind": kind, "name": name}
        for kind, names in used.items()
        for name in names
        if (plugin := registry().get(kind, name)) is not None and not plugin.builtin
    ]


# A word of an entity's or a page's name → a Lucide icon, when the outline names none (2026-11-09: every item of the
# plant shop's management area showed the same fallback icon). Whole words of the kebab-case name, first match wins.
WORD_ICONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("order", "orders", "purchase", "purchases"), "Package"),
    (("cart", "basket", "checkout"), "ShoppingCart"),
    (("product", "products", "item", "items", "plant", "plants", "goods", "catalog", "catalogue"), "Tag"),
    (("collection", "collections", "category", "categories", "topic", "topics", "tag", "tags"), "Layers"),
    (("video", "videos", "lesson", "lessons", "episode", "episodes", "clip", "clips"), "SquarePlay"),
    (("course", "courses", "class", "classes", "module", "modules", "curriculum"), "BookOpen"),
    (("quiz", "quizzes", "exam", "exams", "test", "tests"), "ClipboardCheck"),
    (("post", "posts", "article", "articles", "news", "story", "stories", "blog"), "Newspaper"),
    (("comment", "comments", "message", "messages", "chat", "reply", "replies"), "MessageSquare"),
    (("task", "tasks", "todo", "todos", "ticket", "tickets", "issue", "issues"), "ListChecks"),
    (("project", "projects", "board", "boards", "sprint", "sprints"), "FolderKanban"),
    (("booking", "bookings", "appointment", "appointments", "reservation", "reservations", "slot", "slots"),
     "CalendarDays"),
    (("event", "events", "session", "sessions", "schedule", "shift", "shifts"), "Calendar"),
    (("room", "rooms", "venue", "venues", "location", "locations", "place", "places"), "MapPin"),
    (("customer", "customers", "client", "clients", "patient", "patients", "member", "members", "student",
      "students", "learner", "learners", "user", "users", "contact", "contacts", "attendee", "attendees"), "Users"),
    (("staff", "employee", "employees", "doctor", "doctors", "teacher", "teachers", "instructor", "instructors",
      "provider", "providers", "team"), "UserRound"),
    (("invoice", "invoices", "payment", "payments", "bill", "bills", "transaction", "transactions"), "Receipt"),
    (("report", "reports", "stat", "stats", "analytics", "metric", "metrics"), "ChartColumn"),
    (("photo", "photos", "image", "images", "gallery", "galleries", "picture", "pictures"), "Image"),
    (("file", "files", "document", "documents", "upload", "uploads", "attachment", "attachments"), "FileText"),
    (("review", "reviews", "rating", "ratings", "feedback"), "Star"),
    (("note", "notes", "memo", "memos", "journal"), "StickyNote"),
    (("supplier", "suppliers", "vendor", "vendors", "warehouse", "inventory", "stock"), "Warehouse"),
    (("deck", "decks", "card", "cards", "flashcard", "flashcards"), "GalleryVerticalEnd"),
    (("recipe", "recipes", "menu", "menus", "dish", "dishes", "meal", "meals"), "UtensilsCrossed"),
    (("playlist", "playlists", "album", "albums", "track", "tracks", "song", "songs", "podcast", "podcasts"),
     "ListMusic"),
    (("setting", "settings", "preference", "preferences"), "Settings"),
    (("favorite", "favorites", "favourite", "favourites", "bookmark", "bookmarks", "wishlist"), "Heart"),
)  # fmt: skip
# When no word matches, each item still gets its own icon (never the same one down the sidebar)
SPARE_ICONS = ("Box", "Layers", "Tag", "Folder", "Hexagon", "Circle", "Square", "Triangle")
DEFAULT_NAV_ICON = "ListFilter"


def word_icon(*names: str | None) -> str | None:
    """The icon one of the names' words suggests (the page id, the entity, the label), else None."""
    for name in names:
        words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w]
        for hints, icon in WORD_ICONS:
            if any(word in hints for word in words):
                return icon
    return None


def app_nav(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The sidebar: the spec's navigation (written by the screen planner) with the outline's icons. Pages of an area
    are named `<area>-<page>` (Story 23.10), so the lookup strips the area's id; an item the outline gave no icon takes
    one from its words, else a spare icon no other item has."""
    outline = spec.get("app") or {}
    icons = {to_kebab(pluralize(item["entity"])): item.get("icon") for item in outline.get("nav") or []}
    entities = {to_kebab(pluralize(name)): name for name in outline.get("entities") or {}}
    prefixes = sorted(
        (f"{area['id']}-" for area in outline.get("areas") or [] if area.get("id")), key=len, reverse=True
    )
    out = []
    spare = list(SPARE_ICONS)
    for link in ((spec.get("layout") or {}).get("header") or {}).get("navigation") or []:
        page = link.get("page")
        if not page:
            continue
        bare = next((page[len(prefix) :] for prefix in prefixes if page.startswith(prefix)), page)
        if bare in ("home", "dashboard"):
            icon = "LayoutDashboard"
        elif bare.endswith("-new"):
            icon = "Plus"
        else:
            icon = icons.get(bare) or word_icon(bare, entities.get(bare), link.get("label"))
        if not icon:
            used = {item["icon"] for item in out}
            icon = next((name for name in spare if name not in used), DEFAULT_NAV_ICON)
        out.append({"label": link["label"], "page": page, "icon": icon})
    return out


def plan_app(spec: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """`spec` is the normalized FrontendSpec of an app (`project.flow: "app"`); `contract` the API contract."""
    planner = _Planner(spec, contract)
    routes = planner.routes()
    forms = planner.plan_forms()
    outline = spec.get("app") or {}
    project = spec["project"]
    sections = sorted({s["component"] for route in routes for s in route["sections"] if s["component"] in APP_SECTIONS})
    return {
        "planVersion": FRONTEND_PLAN_VERSION,
        "project": {
            "name": project["name"],
            "slug": to_kebab(project["name"]) or "app",
            "mode": project["mode"],
            "locale": project["locale"],
            "flow": "app",
        },
        "conventions": {
            "skill": "nextjs-skills",
            "packageManager": "pnpm",
            "kit": "app screens are data (src/content/app.json) rendered by the app kit; no hand-written pages",
        },
        "shell": {
            "file": SHELL_FILE,
            "shell": "app",
            "logoText": outline.get("name") or project["name"],
            "logo": None,
            "navigation": [],
            "footer": {"text": None, "links": []},
            "themeToggle": spec["theme"]["colorScheme"] == "light-dark",
        },
        "rendering": "app",
        "rendererGaps": [],
        "trees": False,
        "app": {
            "sections": sections,
            "outline": outline,
            "nav": app_nav(spec),
            "plugins": frontend_plugins(contract),
            "media": has_media(contract),  # Epic 29: the sample media ship with the app
            "designPlugins": design_plugins(outline),  # Epic 30: folder design plugins to copy (D4)
        },
        "routes": routes,
        "components": [],
        "shadcn": kit_primitives(plugins=frontend_plugins(contract), design=design_plugins(outline)),
        "theme": build_theme(pairing_theme(spec["theme"], outline)),  # Story 30.6: the look's font pairing
        "data": planner.data(routes),
        "forms": forms,
        "content": [],
        "assets": planner.assets(routes),
        "tests": planner.tests(routes, forms),
    }
