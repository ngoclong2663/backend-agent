"""Design plugin tooling (Epic 30, Story 30.3): start a plugin from its kind's starter and check it the way the
gates (decision D6) require. Dev tool, no model call.

    make design-plugin-new KIND=card NAME=try            # templates/design/card/try/ from the _starter/card/ files
    make design-plugin-check NAME=try                    # the gates: the fixture app built on the mocks, in the sandbox
    make design-plugin-check NAME=try ARGS="--fast"      # the fast part only (descriptor, fallback, exports, fixture)

The check builds the kind's fixture app (`fixture.json`: the example app and the design values that select the plugin)
once, with every ready recipe's CSS scoped under `:root[data-recipe=…]`, and shoots home, the main list and one record
per area, signed in, at 375 / 1440 px, light / dark, in every recipe; then the mock API's empty, error and loading
states; the keyboard pass and the contrast of every text element. The result is a pass / fail table, `check.json`
and `preview.png` in the plugin's folder (shown by the review's Design panel). A plugin becomes `ready` by hand, after
a clean table (docs/development/design-plugins.md).
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from src.modules.shared.domain.frontend_spec.design_registry import (
    DESIGN_DIR,
    KINDS,
    KIT_KINDS,
    STARTER_DIR,
    DesignPluginDescriptor,
    DesignRegistry,
    DesignRegistryError,
)

from .site_check import REPO, check_site

EXAMPLES = REPO / "examples"
OUT = REPO / ".data" / "shots" / "design-plugin"
SYSTEM_FAMILIES = {"system-ui", "sans-serif", "serif", "monospace", "cursive", "Georgia", "Menlo", "Times New Roman"}
STATES = ("empty", "error", "loading")


def _pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-z0-9]+", name.lower()) if part)


def new_plugin(kind: str, name: str) -> Path:
    """`templates/design/<kind>/<name>/` from the kind's starter, placeholders filled; refuses an existing folder."""
    if kind not in KINDS:
        raise SystemExit(f"kind must be one of {list(KINDS)}")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise SystemExit("name: kebab-case (a pattern many products share, never a product's name)")
    source = STARTER_DIR / kind
    target = DESIGN_DIR / kind / name
    if target.exists():
        raise SystemExit(f"{target} exists")
    if not source.is_dir():
        raise SystemExit(f"no starter for {kind} ({source})")
    values = {
        "{{name}}": name,
        "{{Name}}": _pascal(name),
        "{{Label}}": name.replace("-", " ").capitalize(),
        "{{kind}}": kind,
    }
    target.mkdir(parents=True)
    for path in source.iterdir():
        text = path.read_text()
        for key, value in values.items():
            text = text.replace(key, value)
        file_name = path.name
        for key, value in values.items():
            file_name = file_name.replace(key, value)
        (target / file_name).write_text(text)
    return target


def find_plugin(name: str, kind: str | None) -> DesignPluginDescriptor:
    try:
        reg = DesignRegistry()
    except DesignRegistryError as exc:
        raise SystemExit(str(exc)) from exc
    found = [
        p for k, plugins in reg.plugins.items() for p in plugins.values() if p.name == name and (not kind or k == kind)
    ]
    if not found:
        raise SystemExit(f"no design plugin named {name}" + (f" of kind {kind}" if kind else ""))
    if len(found) > 1:
        raise SystemExit(f"{name} exists in several kinds ({[p.kind for p in found]}): pass KIND=")
    return found[0]


def fast_checks(plugin: DesignPluginDescriptor) -> list[tuple[str, bool, str]]:
    """The checks CI runs for every plugin: the descriptor, its files, its exports and its fixture."""
    out: list[tuple[str, bool, str]] = []
    folder = plugin.folder
    for file in plugin.files:
        out.append((f"file {file}", (folder / file).is_file(), ""))
    if plugin.css:
        out.append((f"css {plugin.css}", (folder / plugin.css).is_file(), ""))
    if plugin.kind in KIT_KINDS and plugin.dispatch and not plugin.builtin:
        texts = "\n".join((folder / f).read_text() for f in plugin.files if (folder / f).is_file())
        for export in plugin.exports:
            found = re.search(rf"export (?:function|const) {re.escape(export)}\b", texts) is not None
            out.append((f"exports {export}", found, "" if found else "not exported by the plugin's files"))
        marker = plugin.marker or plugin.name
        found = f'"{marker}"' in texts
        out.append(("marker", found, "" if found else f"data-bga-* value {marker!r} not in the component"))
    fixture = folder / "fixture.json"
    if plugin.kind in ("shell", "list-view", "detail-view", "home", "filters", "card", "recipe", "font-pairing"):
        ok = fixture.is_file()
        detail = ""
        if ok:
            try:
                data = json.loads(fixture.read_text())
                app = data.get("app") or "media-library"
                ok = isinstance(data.get("design"), dict) and (EXAMPLES / "specs" / f"{app}.json").is_file()
                detail = "" if ok else f"fixture.json needs a `design` object and a known `app` ({app})"
            except json.JSONDecodeError as exc:
                ok, detail = False, f"fixture.json: {exc}"
        out.append(("fixture", ok, detail or ("" if ok else "fixture.json missing")))
    return out


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def fixture_spec(plugin: DesignPluginDescriptor) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The fixture app planned with the plugin's design values over its outline's design."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.frontend.app.outline import complete_outline
    from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
    from src.orchestrator.integration.contract import build_contract

    fixture = json.loads((plugin.folder / "fixture.json").read_text())
    app = fixture.get("app") or "media-library"
    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / f"{app}.json").read_text())).normalized
    raw = json.loads((EXAMPLES / "app-outlines" / f"{app}.json").read_text())
    raw["design"] = _merge(raw.get("design") or {}, fixture.get("design") or {})
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    theme = {"style": "dashboard", "colorScheme": "light-dark", "density": "comfortable"}
    return app_frontend_spec(backend, outline, theme, contract).spec, backend, contract


def chosen(spec: dict[str, Any], plugin: DesignPluginDescriptor) -> bool:
    """Whether the completed design kept the plugin (its `needs` met by the fixture), anywhere in the layouts."""
    app = spec.get("app") or {}
    layouts = [app.get("design") or {}, *[(a.get("design") or {}) for a in app.get("areas") or []]]
    keys = {"shell": "shell", "home": "homeView", "list-view": "view", "detail-view": "detailView",
            "filters": "filtersStyle", "card": "card", "font-pairing": "fontPairing"}  # fmt: skip
    for layout in layouts:
        if plugin.kind == "recipe":
            if layout.get("recipe") == plugin.name or any(
                look.get("recipe") == plugin.name for look in layout.get("looks") or []
            ):
                return True
            continue
        key = keys[plugin.kind]
        if layout.get(key) == plugin.name:
            return True
        if any((e or {}).get(key) == plugin.name for e in (layout.get("entities") or {}).values()):
            return True
    return False


def scoped_recipes(names: list[str]):
    """The `prepare` hook: every recipe's CSS appended to the build's `globals.css` under `:root[data-recipe=…]`."""
    from src.orchestrator.frontend.app.recipes import recipe_css

    def prepare(project: Path, _spec: dict[str, Any]) -> None:
        css = project / "src" / "app" / "globals.css"
        css.write_text(css.read_text() + "".join(recipe_css(name, scope=name) for name in names))

    return prepare


def gates(report: dict[str, dict[str, Any]], recipes: list[str], routes: list[str]) -> list[tuple[str, int, list[str]]]:
    """(gate, failures, details) over every measured view."""
    found: dict[str, list[str]] = {
        "no sideways scroll": [],
        "fonts loaded": [],
        "AA contrast on the composite": [],
        "focus ring on every focused element": [],
        "empty / error / loading states render": [],
        "every recipe shot": [],
    }
    for view, measured in report.items():
        if measured.get("overflowX"):
            found["no sideways scroll"].append(view)
        families = [f.strip('"') for f in measured.get("families") or []]
        missing = [
            f
            for f in families
            if f not in SYSTEM_FAMILIES and not f.startswith("ui-") and f not in (measured.get("loadedFonts") or [])
        ]
        if missing:
            found["fonts loaded"].append(f"{view}: {missing}")
        for item in (measured.get("contrast") or {}).get("failing") or []:
            found["AA contrast on the composite"].append(
                f"{view}: {item['text']!r} {item['ratio']} ({item['color']}, {item['size']}px)"
            )
        for label in (measured.get("keyboard") or {}).get("withoutRing") or []:
            found["focus ring on every focused element"].append(f"{view}: {label}")
    shots = set(report)
    for route in routes:
        base = "home" if route == "/" else route.strip("/").replace("/", "-")
        for recipe in recipes or [None]:
            suffix = f"-{recipe}" if recipe else ""
            for width in ("375", "1440"):
                for scheme in ("light", "dark"):
                    name = f"{base}-{width}-{scheme}{suffix}"
                    if name not in shots:
                        found["every recipe shot"].append(name)
                    for state in STATES:
                        if f"{name}-{state}" not in shots:
                            found["empty / error / loading states render"].append(f"{name}-{state}")
    return [(gate, len(items), items[:8]) for gate, items in found.items()]


def table(rows: list[tuple[str, bool, str]]) -> str:
    width = max(len(name) for name, _, _ in rows)
    return "\n".join(
        f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}".rstrip() for name, ok, detail in rows
    )


async def check(plugin: DesignPluginDescriptor, fast: bool, out: Path, recipes_arg: list[str] | None) -> bool:
    from .app_design_report import area_routes, areas, demo_login

    rows = fast_checks(plugin)
    print(f"{plugin.kind}/{plugin.name} ({plugin.status})\n" + table(rows))
    if not all(ok for _, ok, _ in rows):
        return False
    if fast or plugin.kind == "font-pairing":
        return True
    spec, backend, contract = fixture_spec(plugin)
    if not chosen(spec, plugin):
        replaced = ((spec.get("app") or {}).get("design") or {}).get("replaced") or []
        print(f"  FAIL  chosen on the fixture  code replaced it: {replaced[-3:]}")
        return False
    print("  PASS  chosen on the fixture")
    reg = DesignRegistry()
    recipes = (
        [plugin.name]
        if plugin.kind == "recipe"
        else (recipes_arg or [p.name for p in reg.ready("recipe") if p.status == "ready"])
    )
    passes = []
    for area in areas(spec):
        routes = area_routes(spec, contract, area)
        passes.append({"name": area["id"], "routes": list(routes.values()), "login": demo_login(contract, area)})
    env = {"DESIGN_CHECK_RECIPES": ",".join(recipes), "DESIGN_CHECK_STATES": ",".join(STATES), "DESIGN_CHECK_A11Y": "1"}
    print(f"  building the fixture ({len(passes)} area(s), {len(recipes)} recipe(s)) …")
    measured = await check_site(
        spec, out, widths="375,1440", schemes="light,dark", backend=backend, passes=passes,
        prepare=scoped_recipes(recipes), extra_env=env,
    )  # fmt: skip
    if measured is None:
        print("  FAIL  the fixture did not build or the check did not run")
        return False
    merged: dict[str, Any] = {}
    all_routes: list[str] = []
    for item in passes:
        for view, values in (measured.get(item["name"]) or {}).items():
            merged[f"{item['name']}/{view}"] = values
        all_routes += item["routes"]
    results = gates({k.split("/", 1)[1]: v for k, v in merged.items()}, recipes, all_routes)
    rows = [(gate, failures == 0, "; ".join(details) if failures else "") for gate, failures, details in results]
    print(table(rows))
    (out / "check.json").write_text(
        json.dumps({"plugin": f"{plugin.kind}/{plugin.name}", "gates": results, "recipes": recipes}, indent=2) + "\n"
    )
    # the preview: the first area's main list (else its home) at 1440 light in the first recipe
    first = passes[0]
    route = first["routes"][1] if len(first["routes"]) > 1 else first["routes"][0]
    base = "home" if route == "/" else route.strip("/").replace("/", "-")
    shot = out / first["name"] / f"{base}-1440-light-{recipes[0]}.png"
    if shot.is_file():
        shutil.copy(shot, plugin.folder / "preview.png")
        print(f"  preview → {plugin.folder / 'preview.png'}")
    print(f"  shots → {out}")
    return all(ok for _, ok, _ in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="start a plugin from its kind's starter")
    new.add_argument("kind", choices=KINDS)
    new.add_argument("name")
    chk = sub.add_parser("check", help="run the gates on a plugin")
    chk.add_argument("name")
    chk.add_argument("--kind", choices=KINDS)
    chk.add_argument("--fast", action="store_true", help="the descriptor, files, exports and fixture only")
    chk.add_argument("--recipe", action="append", help="check in these recipes only (default: every ready recipe)")
    chk.add_argument("--out", help=f"where the shots go (default: {OUT}/<name>)")
    args = parser.parse_args()
    os.environ.setdefault("BGA_DESIGN_INCLUDE_DRAFTS", "1")  # a draft plugin must be buildable to be checked
    if args.command == "new":
        target = new_plugin(args.kind, args.name)
        print(
            f"started {target.relative_to(REPO)}: fill plugin.json (`choose`, `needs`, `fallback`), the component "
            f"and fixture.json, then\n  make design-plugin-check NAME={args.name}"
        )
        return 0
    plugin = find_plugin(args.name, args.kind)
    out = Path(args.out) if args.out else OUT / plugin.name
    out.mkdir(parents=True, exist_ok=True)
    ok = asyncio.run(check(plugin, args.fast, out, args.recipe))
    print("all gates pass" if ok else "some gates fail: the plugin stays a draft")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
