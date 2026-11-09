"""The app design report (Story 23.1; Story 30.1: signed in): how alike the golden apps look, as their users see them,
and whether they still pass the quality floor. Dev tool, no model call: each golden app is planned from its recorded
draft (`examples/specs/<name>.json` + `examples/app-outlines/<name>.json`), built on the app kit in the Node sandbox
and screenshotted on its mock API, signed in as one demo user per area (the auth plugin's demo accounts).

    make app-design-report                       # every golden app → .data/reports/app-design/<date>/
    make app-design-report ARGS="--app news-feed --app plant-shop"
    make app-design-report ARGS="--baseline"     # also writes tests/fixtures/app-golden/baseline.json

Measures: per area the home, the main list and one record at 1440 and 375 px, light; the structural fingerprint of
each area (shell, home, main view, detail, card, filters, from `app.json` and the DOM markers `data-bga-*`), the
distinct fingerprints and the pairs that share one; the screens' similarity on edge maps (layout lines) and the
greyscale squint (Epic 20's thumbnails, kept for comparison); which registry values the golden set uses (and which
plugins none uses); the design-check failures; the brief's choices code replaced; each draft's recorded time, calls
and cost.
"""

import argparse
import asyncio
import json
import re
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

from .site_check import REPO, check_site

EXAMPLES = REPO / "examples"
GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "app-golden"
OUT = REPO / ".data" / "reports" / "app-design"
SYSTEM_FAMILIES = {"system-ui", "sans-serif", "serif", "monospace", "cursive", "Georgia", "Menlo", "Times New Roman"}
# The golden apps (Story 23.0's real drafts) plus Epic 22's every-plugin example.
APPS = [
    "news-feed",
    "video-library",
    "learning-platform",
    "agency-projects",
    "clinic-bookings",
    "plant-shop",
    "event-tickets",
    "workshop-bookings",
    "media-library",  # Epic 29: the synthetic media app (video lessons, caption tracks, a podcast)
    "ember-kitchen",  # Epic 30 (Story 30.8): a real antigravity draft, a cooking video school (learning, two areas)
    "lantern-audio",  # Epic 30 (Story 30.8): a real antigravity draft, a podcast network (catalogue)
]
# Hand-written examples (no recorded draft, no cost): Epic 22's every-plugin app and Epic 29's media app
HAND_WRITTEN = ("workshop-bookings", "media-library")
SCREENS = ("home", "list", "record")
# The axes of a fingerprint and where each comes from: the design, else the DOM marker (Story 30.1)
AXES = ("shell", "home", "view", "detail", "card", "filters")
ENTITY_DEFAULTS = {"detailView": "record", "filtersStyle": "toolbar"}  # what an entity design leaves unsaid
# A kind of the registry → the design's keys that name one of its plugins
KIND_KEYS = {
    "shell": ("shell",),
    "home": ("homeView",),
    "list-view": ("view",),
    "detail-view": ("detailView",),
    "filters": ("filtersStyle",),
    "card": ("card",),
    "recipe": ("recipe",),
    "font-pairing": ("fontPairing",),
}


def golden_app(name: str, locale: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The app as its draft makes it: the outline completed, the aggregates added, the screens planned, and the theme
    of the requirement's first design direction (as `draft_app` does)."""
    from src.modules.shared.domain.backend_spec import validate_spec_data
    from src.orchestrator.backend.planner import build_plan
    from src.orchestrator.drafting.app import app_theme, finish_looks, product_rows
    from src.orchestrator.drafting.design_direction import directions
    from src.orchestrator.frontend.app.design import archetype_for
    from src.orchestrator.frontend.app.outline import complete_outline
    from src.orchestrator.frontend.app.screens import app_frontend_spec, ensure_aggregates
    from src.orchestrator.integration.contract import build_contract

    backend = validate_spec_data(json.loads((EXAMPLES / "specs" / f"{name}.json").read_text())).normalized
    raw = json.loads((EXAMPLES / "app-outlines" / f"{name}.json").read_text())
    if locale:  # Story 23.8: the same app as a Japanese one (the kit's and the planner's words, the face)
        raw["locale"] = locale
    requirement = EXAMPLES / "requirements" / f"{name}.md"
    found = directions(requirement.read_text()) if requirement.is_file() else []
    hint = archetype_for(requirement.read_text(), [found[0].get("productType", "")]) if found else None
    outline, _ = complete_outline(raw, backend, build_contract(backend, build_plan(backend)), hint)
    if requirement.is_file():  # as `draft_app` does (Story 23.7)
        finish_looks(outline, requirement.read_text(), product_rows(requirement.read_text()))
    backend, outline, _ = ensure_aggregates(backend, outline)
    contract = build_contract(backend, build_plan(backend))
    spec = app_frontend_spec(backend, outline, app_theme(found[0] if found else None), contract).spec
    return spec, backend, contract


def areas(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The app's areas (Story 23.10), or the app itself as one area at `/`, each with its layout."""
    app = spec.get("app") or {}
    design = app.get("design") or {}
    found = app.get("areas") or []
    if not found:
        return [{"id": "app", "prefix": "/", "roles": [], "design": design}]
    out = []
    for area in found:
        own = area.get("design") or {}
        layout = {**design, **own, "entities": {**(design.get("entities") or {}), **(own.get("entities") or {})}}
        out.append(
            {"id": area["id"], "prefix": area.get("prefix") or "/", "roles": area.get("roles") or [], "design": layout}
        )
    return out


def demo_login(contract: dict[str, Any], area: dict[str, Any]) -> str | None:
    """`email:password` of one demo user of the area's roles (the auth plugin's), or None for an open app."""
    users = ((contract.get("x-bga") or {}).get("auth") or {}).get("demoUsers") or []
    for user in users:
        if not area["roles"] or user.get("role") in area["roles"]:
            return f"{user['login']}:{user.get('password') or 'demo12345'}"
    return None


def _list_pages(spec: dict[str, Any], prefix: str) -> list[tuple[str | None, str]]:
    others = [area["prefix"] for area in (spec.get("app") or {}).get("areas") or [] if area.get("prefix", "/") != "/"]
    out = []
    for page in spec["pages"]:
        route = page["route"]
        if "[" in route or route == prefix:
            continue
        inside = route == prefix or route.startswith(prefix.rstrip("/") + "/") if prefix != "/" else True
        if not inside or (prefix == "/" and any(route == p or route.startswith(p + "/") for p in others)):
            continue
        for section in page.get("sections") or []:
            content = section.get("content") or {}
            if section.get("component") == "AppList" and not content.get("tab") and content.get("variant") != "recent":
                out.append((content.get("entity"), route))
    return out


def main_list(spec: dict[str, Any], prefix: str = "/") -> str | None:
    """The route of the area's main list: the layout's main entity, else the first navigation item with a list."""
    app = spec.get("app") or {}
    layout = next((a["design"] for a in areas(spec) if a["prefix"] == prefix), app.get("design") or {})
    candidates = _list_pages(spec, prefix)
    for entity, route in candidates:
        if entity == layout.get("mainEntity"):
            return route
    for entity in [item.get("entity") for item in app.get("nav") or []]:
        for candidate, route in candidates:
            if candidate == entity:
                return route
    return candidates[0][1] if candidates else None


def record_route(spec: dict[str, Any], contract: dict[str, Any], list_route: str | None) -> str | None:
    """The record page under the main list, `[id]` filled with the first fixture of its entity."""
    if not list_route:
        return None
    fixtures = (contract.get("x-bga") or {}).get("fixtures") or {}
    for page in spec["pages"]:
        if page["route"] != f"{list_route}/[id]":
            continue
        entity = next(
            (s["content"]["entity"] for s in page.get("sections") or []
             if s.get("component") == "AppDetail" and (s.get("content") or {}).get("entity")),
            None,
        )  # fmt: skip
        rows = fixtures.get(entity or "") or []
        if rows:
            return re.sub(r"\[id\]", str(rows[0].get("id")), page["route"])
    return None


def area_routes(spec: dict[str, Any], contract: dict[str, Any], area: dict[str, Any]) -> dict[str, str]:
    """The area's screens by name: home, the main list, one record (those that exist)."""
    listed = main_list(spec, area["prefix"])
    out = {"home": area["prefix"]}
    if listed:
        out["list"] = listed
    record = record_route(spec, contract, listed)
    if record:
        out["record"] = record
    return out


def shot_name(route: str, width: int = 1440, scheme: str = "light") -> str:
    return f"{'home' if route == '/' else route.strip('/').replace('/', '-')}-{width}-{scheme}"


def frame(spec: dict[str, Any]) -> tuple[str, str, str]:
    """(shell, home, main list view): what tells two apps' frames apart at a glance (Story 23.1, kept)."""
    app = spec.get("app") or {}
    design = app.get("design") or {}
    home = design.get("homeView") or ("dashboard" if (app.get("home") or "dashboard") == "dashboard" else "list")
    main = design.get("mainEntity") or next((item.get("entity") for item in app.get("nav") or []), None)
    entity = (app.get("entities") or {}).get(main or "") or {}
    view = ((design.get("entities") or {}).get(main or "") or {}).get("view") or entity.get("listStyle") or "table"
    return design.get("shell") or "sidebar", home, view


def fingerprint(area: dict[str, Any], markers: dict[str, dict[str, list[str]]] | None = None) -> dict[str, str]:
    """The structure of an area's screens (Story 30.1): the layout's choices, the DOM markers filling what the design
    leaves open (the card anatomy, the detail view). `markers`: screen name → the design check's `markers`."""
    design = area["design"]
    main = design.get("mainEntity")
    entity = (design.get("entities") or {}).get(main or "") or {}
    markers = markers or {}

    def marker(screen: str, key: str) -> str | None:
        values = (markers.get(screen) or {}).get(key) or []
        return values[0] if values else None

    return {
        "shell": design.get("shell") or marker("home", "shell") or "sidebar",
        "home": design.get("homeView") or marker("home", "view") or "dashboard",
        "view": entity.get("view") or marker("list", "view") or "table",
        "detail": entity.get("detailView") or marker("record", "detail") or "record",
        "card": entity.get("card") or marker("list", "card") or "-",
        "filters": entity.get("filtersStyle") or marker("list", "filters") or "toolbar",
    }


def fingerprint_key(print_: dict[str, str]) -> str:
    return "|".join(f"{axis}={print_[axis]}" for axis in AXES)


def coverage(prints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Which registry values the golden set uses, per kind, and the ready plugins none of them uses."""
    from src.modules.shared.domain.frontend_spec.design_registry import KINDS, registry

    used: dict[str, set[str]] = {kind: set() for kind in KINDS}
    for area in prints.values():
        design = area["design"]
        for kind, keys in KIND_KEYS.items():
            for key in keys:
                if design.get(key):
                    used[kind].add(design[key])
            for entity in (design.get("entities") or {}).values():
                for key in keys:
                    value = entity.get(key) or ENTITY_DEFAULTS.get(key)
                    if value:
                        used[kind].add(value)
        for look in design.get("looks") or []:
            used["recipe"].add(look.get("recipe"))
    ready = {kind: set(registry().names(kind)) for kind in KINDS}
    return {
        "used": {kind: sorted(values & ready[kind]) for kind, values in used.items()},
        "unused": {kind: sorted(ready[kind] - values) for kind, values in used.items()},
    }


def app_failures(view: str, measured: dict[str, Any]) -> list[str]:
    """The quality floor of an app screen (the kit's rules, not a marketing page's): no sideways scroll, every font
    loaded, at most two families, forms without clipped or unlabelled controls or native date inputs."""
    found = []
    if measured.get("overflowX"):
        found.append(f"{view}: scrolls sideways")
    families = [family.strip('"') for family in measured.get("families") or []]
    webfonts = [family for family in families if family not in SYSTEM_FAMILIES and not family.startswith("ui-")]
    missing = [family for family in webfonts if family not in (measured.get("loadedFonts") or [])]
    if missing:
        found.append(f"{view}: fonts not loaded {missing}")
    if len(families) > 2:
        found.append(f"{view}: {len(families)} font families {families}")
    form = measured.get("form") or {}
    for key in ("clipped", "unlabelled"):
        if form.get(key):
            found.append(f"{view}: form controls {key} {form[key]}")
    if form.get("nativeDateInputs"):
        found.append(f"{view}: {form['nativeDateInputs']} native date inputs")
    return found


def similarity(thumbs: dict[str, list[int]], measure: Any = None) -> dict[str, Any]:
    """Mean and max similarity over every pair, and the most alike pair."""
    from src.orchestrator.drafting.design_diversity import image_similarity

    measure = measure or image_similarity
    pairs = {f"{a} / {b}": measure(thumbs[a], thumbs[b]) for a, b in combinations(sorted(thumbs), 2)}
    if not pairs:
        return {"mean": None, "max": None, "pairs": {}}
    worst = max(pairs, key=lambda key: pairs[key])
    return {
        "mean": round(sum(pairs.values()) / len(pairs), 4),
        "max": pairs[worst],
        "mostAlike": worst,
        "pairs": pairs,
    }


def replaced(spec: dict[str, Any]) -> list[str]:
    """The brief's choices code replaced (Story 23.6 writes them on the design as `replaced`)."""
    return list(((spec.get("app") or {}).get("design") or {}).get("replaced") or [])


def draft_cost(name: str) -> dict[str, Any]:
    path = GOLDEN / name / "draft.json"
    if not path.is_file():
        return {}
    draft = json.loads(path.read_text())
    return {
        "seconds": draft.get("seconds"),
        "calls": len(draft.get("calls") or []),
        "repairs": draft.get("repairs"),
        "costUsd": draft.get("costUsd"),
    }


def contact_sheet(images: dict[str, Path], target: Path, columns: int = 4) -> None:
    """The home pages side by side, scaled to a third, with the area's name under each."""
    from PIL import Image, ImageDraw

    width, height, label = 480, 300, 24
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, max(rows, 1) * (height + label)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (name, path) in enumerate(sorted(images.items())):
        x, y = (index % columns) * width, (index // columns) * (height + label)
        with Image.open(path) as image:
            top = image.crop((0, 0, min(image.width, 1440), min(image.height, 900))).convert("RGB")
            sheet.paste(top.resize((width, height)), (x, y))
        draw.text((x + 8, y + height + 5), name, fill="black")
    sheet.save(target)


def shared_fingerprints(prints: dict[str, dict[str, Any]]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for name, area in prints.items():
        groups.setdefault(fingerprint_key(area["fingerprint"]), []).append(name)
    return [sorted(names) for names in groups.values() if len(names) > 1]


def markdown(results: dict[str, Any]) -> str:
    edges = results["edges"]
    lines = [
        f"# App design report ({results['date']})",
        "",
        f"Apps: {len(results['apps'])}, areas: {len(results['areas'])}, signed in. Distinct fingerprints: "
        f"{results['distinctFingerprints']} of {len(results['areas'])} (frames: {results['distinctFrames']} of "
        f"{len(results['apps'])}). Edge similarity (signed-in, 1440 px): home mean {edges['home']['mean']}, max "
        f"{edges['home']['max']}; list mean {edges['list']['mean']}, max {edges['list']['max']}; record mean "
        f"{edges['record']['mean']}, max {edges['record']['max']}. Greyscale (kept for comparison): home mean "
        f"{results['home']['mean']}, max {results['home']['max']}; list mean {results['list']['mean']}, max "
        f"{results['list']['max']}.",
        "",
        "| Area | Fingerprint (shell, home, view, detail, card, filters) | Signed in as | Failures | Replaced | Draft |",  # noqa: E501
        "|---|---|---|---|---|---|",
    ]
    for name, area in sorted(results["areas"].items()):
        cost = results["apps"].get(area["app"], {}).get("draft") or {}
        draft = f"{cost.get('seconds')} s, {cost.get('calls')} call(s), ${cost.get('costUsd')}" if cost else "—"
        print_ = ", ".join(area["fingerprint"][axis] for axis in AXES)
        lines.append(
            f"| {name} | {print_} | {area.get('login') or 'nobody (open app)'} | {len(area['failures'])} | "
            f"{len(results['apps'].get(area['app'], {}).get('replaced') or [])} | {draft} |"
        )
    shared = results.get("sharedFingerprints") or []
    if shared:
        lines += ["", "## Areas that share a fingerprint", "", *[f"- {', '.join(group)}" for group in shared]]
    unused = {kind: names for kind, names in (results.get("coverage") or {}).get("unused", {}).items() if names}
    if unused:
        lines += ["", "## Plugins no golden app uses", "", *[f"- {kind}: {', '.join(n)}" for kind, n in unused.items()]]
    failures = [line for area in results["areas"].values() for line in area["failures"]]
    if failures:
        lines += ["", "## Failures", "", *[f"- {line}" for line in failures]]
    return "\n".join(lines) + "\n"


def fake_slots(project: Path, spec: dict[str, Any]) -> None:
    """Story 23.11 on the fake engine: every planned slot written as the fake writes it, registered, so the build
    proves slots compile on the kit."""
    from src.engines.fake_engine import write_view_slot
    from src.orchestrator.frontend.app.slots import (
        REGISTRY,
        SLOT_INPUT,
        planned_slots,
        refusal,
        registry_ts,
        slot_input,
    )

    accepted = []
    (project / ".bga").mkdir(exist_ok=True)
    for slot in planned_slots(spec):
        (project / SLOT_INPUT).write_text(json.dumps(slot_input(slot, spec)))
        written = write_view_slot(project, defect=False)
        if refusal((project / written).read_text()) is None:
            accepted.append(slot)
    (project / REGISTRY).write_text(registry_ts(accepted))


async def report(names: list[str], out: Path, locale: str | None = None, slots: bool = False) -> dict[str, Any]:
    from src.orchestrator.drafting.design_diversity import edge_signature, edge_similarity, first_screen

    apps: dict[str, Any] = {}
    prints: dict[str, Any] = {}
    homes: dict[str, list[int]] = {}
    lists: dict[str, list[int]] = {}
    edges: dict[str, dict[str, list[int]]] = {screen: {} for screen in SCREENS}
    home_shots: dict[str, Path] = {}
    for name in names:
        spec, backend, contract = golden_app(name, locale)
        passes = []
        for area in areas(spec):
            routes = area_routes(spec, contract, area)
            passes.append({"name": area["id"], "routes": list(routes.values()), "login": demo_login(contract, area),
                           "screens": routes, "area": area})  # fmt: skip
        print(f"building {name} ({', '.join(p['name'] + ': ' + ' '.join(p['routes']) for p in passes)})")
        measured = await check_site(
            spec, out / name, widths="1440,375", schemes="light", backend=backend,
            prepare=fake_slots if slots else None,
            passes=[{k: v for k, v in p.items() if k in ("name", "routes", "login")} for p in passes],
        )  # fmt: skip
        apps[name] = {"frame": list(frame(spec)), "replaced": replaced(spec), "draft": draft_cost(name)}
        if measured is None:
            apps[name]["failures"] = ["build failed"]
            for item in passes:
                prints[f"{name}/{item['name']}"] = {
                    "app": name,
                    "design": item["area"]["design"],
                    "login": item["login"],
                    "fingerprint": fingerprint(item["area"]),
                    "failures": ["build failed"],
                }
            continue
        for item in passes:
            key = f"{name}/{item['name']}"
            views = measured.get(item["name"]) or {}
            markers = {
                screen: (views.get(shot_name(route)) or {}).get("markers") or {}
                for screen, route in item["screens"].items()
            }
            folder = out / name / item["name"]
            for screen, route in item["screens"].items():
                shot = folder / f"{shot_name(route)}.png"
                if shot.is_file():
                    edges[screen][key] = edge_signature(shot)
                    if screen == "home":
                        homes[key], home_shots[key] = first_screen(shot), shot
                    if screen == "list":
                        lists[key] = first_screen(shot)
            prints[key] = {
                "app": name,
                "design": item["area"]["design"],
                "login": item["login"],
                "routes": item["screens"],
                "fingerprint": fingerprint(item["area"], markers),
                "markers": markers,
                "failures": [line for view, values in views.items() for line in app_failures(view, values)],
            }
    results = {
        "date": str(date.today()),
        "apps": apps,
        "areas": {key: {k: v for k, v in area.items() if k != "design"} for key, area in prints.items()},
        "home": similarity(homes),
        "list": similarity(lists),
        "edges": {screen: similarity(edges[screen], edge_similarity) for screen in SCREENS},
        "distinctFrames": len({tuple(app["frame"]) for app in apps.values()}),
        "distinctFingerprints": len({fingerprint_key(area["fingerprint"]) for area in prints.values()}),
        "sharedFingerprints": shared_fingerprints(prints),
        "coverage": coverage(prints),
    }
    if home_shots:
        contact_sheet({key.replace("/", " · "): path for key, path in home_shots.items()}, out / "contact-sheet.png")
    (out / "report.json").write_text(json.dumps(results, indent=2) + "\n")
    (out / "report.md").write_text(markdown(results))
    return results


def baseline(results: dict[str, Any]) -> dict[str, Any]:
    """What the next report is compared against (Story 30.1 step 5)."""
    keep: dict[str, Any] = {
        key: results[key] for key in ("date", "distinctFrames", "distinctFingerprints", "sharedFingerprints")
    }
    keep |= {key: {k: results[key][k] for k in ("mean", "max")} for key in ("home", "list")}
    keep["edges"] = {screen: {k: results["edges"][screen][k] for k in ("mean", "max")} for screen in SCREENS}
    keep["frames"] = {name: app["frame"] for name, app in results["apps"].items()}
    keep["fingerprints"] = {name: area["fingerprint"] for name, area in results["areas"].items()}
    keep["coverage"] = results["coverage"]
    return keep


async def main(args: argparse.Namespace) -> None:
    out = OUT / str(date.today())
    out.mkdir(parents=True, exist_ok=True)
    if args.locale or args.slots:  # a variant: its own folder, never the baseline
        out = out / "-".join(filter(None, [args.locale, "slots" if args.slots else None]))
        out.mkdir(parents=True, exist_ok=True)
    results = await report(args.app or APPS, out, args.locale, args.slots)
    print(markdown(results))
    if args.baseline:
        (GOLDEN / "baseline.json").write_text(json.dumps(baseline(results), indent=2) + "\n")
        print(f"baseline → {GOLDEN / 'baseline.json'}")
    print(f"report → {out / 'report.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", action="append", help="a golden app (default: all)")
    parser.add_argument("--baseline", action="store_true", help="write tests/fixtures/app-golden/baseline.json")
    parser.add_argument("--locale", help="build the apps in this locale (Story 23.8: ja)")
    parser.add_argument("--slots", action="store_true", help="with the fake engine's view slots (Story 23.11)")
    asyncio.run(main(parser.parse_args()))
