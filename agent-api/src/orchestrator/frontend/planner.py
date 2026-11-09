"""Deterministic frontend planner (Story 13.1): normalized FrontendSpec (+ API contract) → frontend plan.

No LLM. The same inputs always give a byte-identical plan (`dump_frontend_plan`). The scaffold, the generation
prompts, the conventions check and the route/test checks all read this plan.

Naming follows nextjs-skills: components are PascalCase files under `src/features/<domain>/components/`, logic
lives in companion `use-<name>.ts` hooks, standalone types are `T`-prefixed, prop types are `<Name>Props`.
"""

import json
import re
from pathlib import Path
from typing import Any

from src.modules.shared.domain.backend_spec.naming import pluralize, to_camel, to_kebab, to_pascal, to_snake
from src.modules.shared.domain.frontend_spec import BUILTIN_SECTIONS, all_trees, iter_sections, route_params
from src.modules.shared.domain.frontend_spec.assets import aspect_ratio, render_mode
from src.modules.shared.domain.frontend_spec.trees import TREE_SHADCN
from src.videos.cache import video_cache_dir

from ..integration.contract import contract_operations, resolve
from .renderer import custom_components, library_primitives, renderer_gaps
from .theme import build_theme

FRONTEND_PLAN_VERSION = "1"
BASE_DIR = Path(__file__).resolve().parents[3] / "templates" / "nextjs_base"
SHELL_FILE = "src/components/layout/SiteShell.tsx"
ALWAYS_PRIMITIVES = ("button", "skeleton", "sonner", "separator")
FORM_PRIMITIVES = {"string": "input", "text": "textarea", "enum": "select", "boolean": "checkbox"}
_UI_IMPORT = re.compile(r'from "@/components/ui/([a-z0-9-]+)"')
CONTENT_DIR = "src/content"
SECTIONS_DIR = "src/components/sections"


def _ui_dependencies() -> dict[str, set[str]]:
    """Primitive → primitives it imports (from the pinned base), so installing one installs what it needs."""
    deps: dict[str, set[str]] = {}
    ui = BASE_DIR / "src" / "components" / "ui"
    if ui.is_dir():
        for path in sorted(ui.glob("*.tsx")):
            deps[path.stem] = set(_UI_IMPORT.findall(path.read_text())) - {path.stem}
    return deps


UI_DEPENDENCIES = _ui_dependencies()


def primitive_closure(names: set[str]) -> list[str]:
    found: set[str] = set()
    stack = list(names)
    while stack:
        name = stack.pop()
        if name in found:
            continue
        found.add(name)
        stack.extend(UI_DEPENDENCIES.get(name, set()) - found)
    return sorted(found)


def route_file(route: str) -> str:
    """`/` → `src/app/page.tsx`; `/products/[id]` → `src/app/products/[id]/page.tsx`."""
    segments = [segment for segment in route.split("/") if segment]
    return "/".join(["src/app", *segments, "page.tsx"])


def operation_function(operation_id: str, action: str | None) -> str:
    """`product.list` → `listProducts`; `cartItem.create` → `createCartItem`; `order.checkout` → `checkoutOrder`."""
    *resource, verb = operation_id.split(".")
    subject = "_".join(to_snake(part) for part in resource)
    if action == "list":
        head, _, last = subject.rpartition("_")
        subject = f"{head}_{pluralize(last)}" if head else pluralize(last)
    return to_camel(f"{to_snake(verb)}_{subject}")


def hook_name(function: str) -> str:
    return f"use{function[:1].upper()}{function[1:]}"


def resource_keys(operation_id: str) -> str:
    """Query-key factory name: `product.list` → `productKeys`."""
    return f"{to_camel(operation_id.rsplit('.', 1)[0].replace('.', '_'))}Keys"


def _concrete_route(route: str, values: dict[str, Any]) -> str | None:
    parts = []
    for segment in route.split("/"):
        if segment.startswith("[") and segment.endswith("]"):
            value = values.get(segment[1:-1])
            if value is None:
                return None
            parts.append(str(value))
        else:
            parts.append(segment)
    return "/".join(parts) or "/"


class _Planner:
    def __init__(self, spec: dict[str, Any], contract: dict[str, Any] | None):
        self.spec = spec
        self.contract = contract
        self.operations = contract_operations(contract) if contract else {}
        self.forms = {form["id"]: form for form in spec.get("forms", [])}
        self.content = {item["collection"]: item["records"] for item in spec.get("content", [])}
        self.declared = {component["name"]: component for component in spec.get("components", [])}
        self.fixtures = ((contract or {}).get("x-bga") or {}).get("fixtures") or {}

    # -- assets (Story 15.1) -------------------------------------------------------------------------------------

    def assets(self, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each asset with how it renders, where its file goes and the routes that show it (the header logo shows
        on every route; content collections count where a section is bound to them)."""
        logo = (self.spec.get("layout") or {}).get("header", {}).get("logo")
        used: dict[str, list[str]] = {}
        visible: dict[str, list[str]] = {}  # always on the page: what the smoke test asserts (Story 15.3)
        for route in routes:
            refs = set(_asset_ids(logo))
            for section in iter_sections(route["sections"]):
                refs |= set(_asset_ids(section.get("content"))) | set(_asset_ids(section.get("states")))
                data = section.get("data") or {}
                if data.get("kind") == "content":
                    refs |= set(_asset_ids(self.content.get(data.get("collection"), [])))
            for ref in refs:
                used.setdefault(ref, []).append(route["route"])
            for ref in self.visible_assets(route["sections"]) | set(_asset_ids(logo)):
                visible.setdefault(ref, []).append(route["route"])
        planned = []
        for asset in self.spec.get("assets", []):
            mode = render_mode(asset)
            source = asset.get("source") or "placeholder"
            entry: dict[str, Any] = {
                "id": asset["id"],
                "kind": asset.get("kind") or "image",
                "source": source,
                "render": mode,
                "alt": asset.get("alt"),
                "decorative": bool(asset.get("decorative")),
                "aspectRatio": aspect_ratio(asset),
                "routes": sorted(used.get(asset["id"], [])),
                "visibleRoutes": sorted(visible.get(asset["id"], [])),
            }
            if isinstance(asset.get("credit"), dict):  # Epic 27: shown with the photo
                entry["credit"] = asset["credit"]
            if mode == "svg-component":
                entry |= {
                    "prompt": asset.get("prompt") or asset.get("alt") or asset["id"],
                    "style": asset.get("style"),
                    "file": f"src/assets/svg/{asset['id']}.svg",
                    "component": f"src/components/assets/generated/{asset_component(asset['id'])}.tsx",
                }
            elif mode == "photo":
                entry |= {
                    "prompt": asset.get("prompt") or asset.get("alt") or asset["id"],
                    "style": asset.get("style"),
                    "file": f"public/assets/{asset['id']}.webp",
                    "src": f"/assets/{asset['id']}.webp",
                    "generated": False,
                }
            elif mode == "public-file":
                entry |= {"upload": source.removeprefix("upload:"), "file": f"public/assets/{asset['id']}"}
                if asset.get("prompt"):
                    entry["prompt"] = asset["prompt"]
                if asset.get("style"):
                    entry["style"] = asset["style"]
            elif mode == "remote":
                entry["url"] = source
            elif mode == "icon":
                entry["icon"] = source.removeprefix("lucide:")
            elif mode in ("video-embed", "video-file") and isinstance(asset.get("video"), dict):
                # Epic 31: the provider's hit; a Pixabay poster is a file of the site (its images are not hotlinked)
                video = dict(asset["video"])
                poster = video.get("poster")
                if mode == "video-file" and isinstance(poster, str) and poster.startswith("/assets/"):
                    entry["posterFile"] = f"public{poster}"
                    entry["posterSource"] = str(video_cache_dir("pixabay") / "posters" / f"{video['id']}.jpg")
                entry["video"] = video
                if video.get("url"):
                    entry["url"] = video["url"]
            planned.append(entry)
        return planned

    def visible_assets(self, sections: list[dict[str, Any]]) -> set[str]:
        """Assets a page always shows: in section content and static collections, not in a data state (shown only
        when a list is empty) and not inside Tabs (only the open tab is in the page)."""
        found: set[str] = set()
        for section in sections:
            if section["component"] == "Tabs":
                continue
            found |= set(_asset_ids(section.get("content")))
            data = section.get("data") or {}
            if data.get("kind") == "content":
                found |= set(_asset_ids(self.content.get(data.get("collection"), [])))
            found |= self.visible_assets(section.get("children") or [])
        return found

    # -- operations ---------------------------------------------------------------------------------------------

    def operation(self, operation_id: str) -> dict[str, Any]:
        found = self.operations[operation_id]
        meta = found["operation"].get("x-bga") or {}
        function = operation_function(operation_id, meta.get("action"))
        return {
            "operationId": operation_id,
            "method": found["method"],
            "path": found["path"],
            "entity": meta.get("entity"),
            "action": meta.get("action"),
            "module": meta.get("module"),
            "function": function,
            "hook": hook_name(function),
            "keys": resource_keys(operation_id),
            "mutation": found["method"] != "GET",
        }

    # -- sections -----------------------------------------------------------------------------------------------

    def section(self, page: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
        planned: dict[str, Any] = {"id": section["id"], "component": section["component"]}
        data = section.get("data")
        if data and data.get("operationId"):
            op = self.operation(data["operationId"])
            planned["data"] = {
                "kind": "operation",
                "operationId": op["operationId"],
                "function": op["function"],
                "hook": op["hook"],
                "queryKey": f"{op['keys']}.{'list' if op['action'] == 'list' else 'detail'}(params)",
                "action": op["action"],
                "params": data.get("params") or {},
                "fields": data.get("fields") or [],
            }
        elif data and data.get("collection"):
            planned["data"] = {
                "kind": "content",
                "collection": data["collection"],
                "file": f"{CONTENT_DIR}/{to_kebab(data['collection'])}.json",
                "params": data.get("params") or {},
                "fields": data.get("fields") or [],
                "records": len(self.content.get(data["collection"], [])),
            }
        if section.get("form"):
            planned["form"] = section["form"]
        if section.get("content"):
            planned["content"] = section["content"]
        if section.get("states"):
            planned["states"] = section["states"]
        if section.get("children"):
            planned["children"] = [self.section(page, child) for child in section["children"]]
        return planned

    def routes(self) -> list[dict[str, Any]]:
        routes = []
        for page in self.spec["pages"]:
            routes.append(
                {
                    "pageId": page["id"],
                    "route": page["route"],
                    "file": route_file(page["route"]),
                    "params": route_params(page["route"]),
                    "title": page["title"],
                    "purpose": page.get("purpose"),
                    "seo": page.get("seo") or {},
                    "sections": [self.section(page, section) for section in page["sections"]],
                }
            )
            if page.get("rhythm", "uniform") != "uniform":
                routes[-1]["rhythm"] = page["rhythm"]  # Story 20.2; absent for the default, so old plans stay equal
            if page.get("tree"):  # Epic 21: a designed page, with its scoped CSS
                routes[-1]["tree"] = page["tree"]
                if page.get("css"):
                    routes[-1]["css"] = page["css"]
        return routes

    # -- components ---------------------------------------------------------------------------------------------

    def components(self, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        usages: dict[str, list[dict[str, Any]]] = {}
        pages: dict[str, list[str]] = {}
        for route in routes:
            for section in iter_sections(route["sections"]):
                usage = dict(section)
                if section.get("form") in self.forms:
                    usage["formOperationId"] = self.forms[section["form"]].get("operationId")
                usages.setdefault(section["component"], []).append(usage)
                if route["pageId"] not in pages.setdefault(section["component"], []):
                    pages[section["component"]].append(route["pageId"])
        planned = []
        for name in sorted(usages):
            declared = self.declared.get(name) or {}
            # The normalizer lists the built-ins it used as `kind: section`; redeclaring one as composite opts out.
            is_builtin = name in BUILTIN_SECTIONS and declared.get("kind", "section") == "section"
            builtin = BUILTIN_SECTIONS[name] if is_builtin else {}
            has_form = any(u.get("form") for u in usages[name])
            if builtin:
                # Built-in sections are shared and presentational: pages pass their data or form in.
                domain, file = "sections", f"{SECTIONS_DIR}/{name}.tsx"
            else:
                domain = "site"  # a static site's own components (apps have none: Epic 22)
                file = f"src/features/{domain}/components/{name}.tsx"
            component = {
                "name": name,
                "kind": declared.get("kind") or ("section" if builtin else "composite"),
                "domain": domain,
                "file": file,
                "propsType": f"{name}Props",
                "uses": sorted(set(declared.get("uses") or builtin.get("uses") or [])),
                "usedBy": pages[name],
                "description": declared.get("description") or builtin.get("description"),
            }
            if not builtin and has_form:
                hook_file = f"src/features/{domain}/hooks/use-{to_kebab(name)}.ts"
                component["hook"] = {"name": f"use{name}", "file": hook_file}
            planned.append(component)
        return planned

    def shadcn(self, components: list[dict[str, Any]], library: set[str] | None = None) -> list[str]:
        wanted = set(ALWAYS_PRIMITIVES) | (library or set())  # what the section library's files import
        for component in components:
            wanted |= {name for name in component["uses"] if name not in self.declared and name not in BUILTIN_SECTIONS}
        for form in self.spec.get("forms", []):
            wanted |= {"field", "label"} | {
                FORM_PRIMITIVES.get(f.get("type", "string"), "input") for f in form["fields"]
            }
        layout = self.spec.get("layout", {})
        if layout.get("shell") == "sidebar":
            wanted |= {"sidebar"}
        if layout.get("header", {}).get("navigation"):
            wanted |= {"navigation-menu", "sheet"}
        if all_trees(self.spec):  # Epic 21: the tree renderer imports every primitive a tree may name
            wanted |= set(TREE_SHADCN) | {"input", "chart"}
        return primitive_closure(wanted)

    # -- forms ---------------------------------------------------------------------------------------------------

    def plan_forms(self) -> list[dict[str, Any]]:
        planned = []
        for form in self.spec.get("forms", []):
            pascal = to_pascal(form["id"])
            entry: dict[str, Any] = {
                "id": form["id"],
                "schema": f"{to_camel(form['id'])}Schema",
                "valuesType": f"T{pascal}Values",
                "file": "src/lib/forms.ts",
                "fields": form["fields"],
                "params": form.get("params") or {},
                "submitLabel": form.get("submitLabel"),
                "onSuccess": form.get("onSuccess") or {},
            }
            operation_id = form.get("operationId")
            if operation_id and operation_id in self.operations:
                op = self.operation(operation_id)
                entry["operationId"] = operation_id
                entry["function"] = op["function"]
                entry["hook"] = op["hook"]
                body = (self.operations[operation_id]["operation"].get("requestBody") or {}).get("content") or {}
                schema = resolve(self.contract, (body.get("application/json") or {}).get("schema", {}))
                entry["requestSchema"] = (body.get("application/json") or {}).get("schema", {}).get("$ref", "")
                entry["requestFields"] = sorted((schema.get("properties") or {}).keys())
            planned.append(entry)
        return planned

    def data(self, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bindings = []
        for route in routes:
            for section in iter_sections(route["sections"]):
                data = section.get("data")
                if data and data["kind"] == "operation":
                    bindings.append({"pageId": route["pageId"], "section": section["id"], **data})
        return bindings

    # -- tests ---------------------------------------------------------------------------------------------------

    def example_path(self, route: dict[str, Any]) -> tuple[str | None, str | None]:
        """A concrete URL for a route with parameters: from the contract fixtures or the content records."""
        if not route["params"]:
            return route["route"], None
        values: dict[str, Any] = {}
        for section in iter_sections(route["sections"]):
            data = section.get("data") or {}
            for name, value in (data.get("params") or {}).items():
                if not (isinstance(value, str) and value.startswith("$route.")):
                    continue
                param = value.removeprefix("$route.")
                if data.get("kind") == "operation":
                    entity = (self.operations[data["operationId"]]["operation"].get("x-bga") or {}).get("entity")
                    records = self.fixtures.get(entity) or []
                    field = "id" if name == "id" else name
                    if records and field in records[0]:
                        values.setdefault(param, records[0][field])
                elif data.get("kind") == "content":
                    records = self.content.get(data["collection"]) or []
                    if records and name in records[0]:
                        values.setdefault(param, records[0][name])
        path = _concrete_route(route["route"], values)
        return path, None if path else "no example value for the route parameters"

    def tests(self, routes: list[dict[str, Any]], forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tests = []
        for route in routes:
            path, skip = self.example_path(route)
            test = {
                "id": f"route:{route['pageId']}",
                "kind": "route",
                "pageId": route["pageId"],
                "path": path,
                "expect": route["title"],
                "file": "tests/e2e/smoke.spec.ts",
            }
            if skip:
                test["skip"] = skip
            tests.append(test)
        by_form = {form["id"]: form for form in forms}
        for route in routes:
            for section in iter_sections(route["sections"]):
                form = by_form.get(section.get("form") or "")
                if form is None or any(t.get("formId") == form["id"] for t in tests):
                    continue
                path = next(t["path"] for t in tests if t["pageId"] == route["pageId"])
                tests.append(
                    {
                        "id": f"form:{form['id']}",
                        "kind": "form",
                        "formId": form["id"],
                        "pageId": route["pageId"],
                        "path": path,
                        "file": "tests/e2e/forms.spec.ts",
                        **({"skip": "no example value for the route parameters"} if path is None else {}),
                    }
                )
        return tests

    def build(self) -> dict[str, Any]:
        spec = self.spec
        routes = self.routes()
        components = self.components(routes)
        forms = self.plan_forms()
        gaps = renderer_gaps(spec, routes, forms)
        custom = {} if gaps else custom_components(spec, routes)
        shell = (spec.get("layout") or {}).get("shell", "header-footer")
        layout = spec.get("layout") or {}
        pages = {route["pageId"]: route["route"] for route in routes}

        def link(item: dict[str, Any]) -> dict[str, Any]:
            if item.get("page"):
                return {"label": item["label"], "href": pages[item["page"]], "page": item["page"]}
            return {"label": item["label"], "href": item["href"], "external": True}

        trees = bool(all_trees(spec))  # Epic 21: designed pages or chrome; the tree renderer is copied
        library = {"routes": routes, "shell": {"shell": shell}, "customComponents": custom, "trees": trees}
        plan = {
            "planVersion": FRONTEND_PLAN_VERSION,
            "project": {
                "name": spec["project"]["name"],
                "slug": to_kebab(spec["project"]["name"]) or "site",
                "mode": spec["project"]["mode"],
                "locale": spec["project"]["locale"],
            },
            "conventions": {
                "skill": "nextjs-skills",
                "packageManager": "pnpm",
                "types": "standalone types T-prefixed (TProduct); props <Name>Props; `type` over `interface`",
                "reactImports": "named imports only, never `import * as React`",
                "colors": "design tokens from globals.css only (bg-primary, text-muted-foreground)",
                "data": "React Query hooks from @/lib/api/queries only; no other network access",
                "forms": "React Hook Form + zodResolver with the schemas in @/lib/forms",
                "hooks": "logic over ~30 lines moves to the component's companion use-*.ts hook",
            },
            "shell": {
                "file": SHELL_FILE,
                "shell": layout.get("shell", "header-footer"),
                "logoText": (layout.get("header") or {}).get("logoText"),
                "logo": (layout.get("header") or {}).get("logo"),
                "navigation": [link(item) for item in (layout.get("header") or {}).get("navigation", [])],
                "footer": {
                    "text": (layout.get("footer") or {}).get("text"),
                    "links": [link(item) for item in (layout.get("footer") or {}).get("links", [])],
                },
                "themeToggle": spec["theme"]["colorScheme"] == "light-dark",
            },
            "rendering": "engine" if gaps else "renderer",
            "rendererGaps": gaps,
            "trees": bool(all_trees(spec)),  # Epic 21: designed pages or chrome; the tree renderer is copied
            "routes": routes,
            "components": components,
            "shadcn": self.shadcn(components, None if gaps else library_primitives(library)),
            "theme": build_theme(spec["theme"]),
            "data": self.data(routes),
            "forms": forms,
            "content": [
                {"collection": name, "file": f"{CONTENT_DIR}/{to_kebab(name)}.json", "records": len(records)}
                for name, records in sorted(self.content.items())
            ],
            "assets": self.assets(routes),
            "tests": self.tests(routes, forms),
        }
        if custom:
            plan["customComponents"] = custom  # Story 17.3: generated one by one, fallbacks registered first
        return plan


def _asset_ids(value: Any):
    if isinstance(value, str) and value.startswith("asset:"):
        yield value.removeprefix("asset:")
    elif isinstance(value, dict):
        for item in value.values():
            yield from _asset_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _asset_ids(item)


def asset_component(asset_id: str) -> str:
    """The React component name of a generated SVG: `work-1` → `Work1Asset`."""
    return to_pascal(asset_id.replace("-", "_")) + "Asset"


def plan_frontend(spec: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """`spec` is the normalized FrontendSpec; `contract` is required in dynamic mode. A dynamic spec is an app
    (`project.flow: "app"`, Epic 22): the app flow plans its own screens; static sites plan here."""
    if spec["project"]["mode"] == "dynamic":
        if contract is None:
            raise ValueError("dynamic frontends are planned against the API contract")
        if spec["project"].get("flow") != "app":
            raise ValueError("a dynamic frontend is an app (project.flow: app); the legacy dynamic flow is gone")
        from .app.plan import plan_app

        return plan_app(spec, contract)
    return _Planner(spec, None).build()


def dump_frontend_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
