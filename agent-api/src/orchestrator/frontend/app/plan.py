"""The frontend plan of an app (Epic 22): the same plan shape the scaffold, the checks and the previews read, with
`rendering: "app"` (the scaffold writes every file; no engine call) and the app kit's shell and primitives."""

from pathlib import Path
from typing import Any

from src.modules.shared.domain.backend_spec.naming import pluralize, to_kebab
from src.modules.shared.domain.frontend_spec.app import APP_SECTIONS

from ...samples import has_media
from ..planner import _UI_IMPORT, FRONTEND_PLAN_VERSION, _Planner, primitive_closure
from ..theme import build_theme
from .files import frontend_plugins

KIT_ROOT = Path(__file__).resolve().parents[4] / "templates" / "nextjs_overlay" / "files" / "dynamic" / "app"
SHELL_FILE = "src/components/layout/SiteShell.tsx"  # the overlay's app shell, under the name the root layout imports
ALWAYS_PRIMITIVES = ("button", "skeleton", "sonner", "separator")


PLUGINS_ROOT = Path(__file__).resolve().parents[4] / "templates" / "plugins"


def plugin_frontend(name: str) -> Path:
    """Story 22.7: a plugin's frontend files (`templates/plugins/<name>/frontend/files/`), copied for apps using it."""
    return PLUGINS_ROOT / name / "frontend" / "files"


def kit_primitives(kit: Path = KIT_ROOT, plugins: list[str] | None = None) -> list[str]:
    """The shadcn primitives the app kit imports (it is copied whole) and its plugins' files, with what they import."""
    wanted = set(ALWAYS_PRIMITIVES)
    roots = [kit, *(plugin_frontend(name) for name in plugins or [])]
    for root in roots:
        for path in sorted(root.rglob("*.ts*")):
            wanted |= set(_UI_IMPORT.findall(path.read_text()))
    return primitive_closure(wanted)


def app_nav(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The sidebar: the spec's navigation (written by the screen planner) with the outline's icons."""
    outline = spec.get("app") or {}
    icons = {to_kebab(pluralize(item["entity"])): item.get("icon") for item in outline.get("nav") or []}
    out = []
    for link in ((spec.get("layout") or {}).get("header") or {}).get("navigation") or []:
        page = link.get("page")
        if not page:
            continue
        icon = (
            "LayoutDashboard"
            if page in ("home", "dashboard")
            else icons.get(page) or ("Plus" if page.endswith("-new") else None)
        )
        out.append({"label": link["label"], "page": page, "icon": icon or "ListFilter"})
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
        },
        "routes": routes,
        "components": [],
        "shadcn": kit_primitives(plugins=frontend_plugins(contract)),
        "theme": build_theme(spec["theme"]),
        "data": planner.data(routes),
        "forms": forms,
        "content": [],
        "assets": planner.assets(routes),
        "tests": planner.tests(routes, forms),
    }
