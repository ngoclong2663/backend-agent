"""The app design report (Story 23.1): how alike the golden apps look, and whether they still pass the quality floor.
Dev tool, no model call: each golden app is planned from its recorded draft (`examples/specs/<name>.json` +
`examples/app-outlines/<name>.json`), built on the app kit in the Node sandbox and screenshotted on its mock API.

    make app-design-report                       # every golden app → .data/reports/app-design/<date>/
    make app-design-report ARGS="--app news-feed --app plant-shop"
    make app-design-report ARGS="--baseline"     # also writes tests/fixtures/app-golden/baseline.json

Measures (the epic's table): greyscale first-screen similarity between every pair of home pages and of main lists
(Epic 20's thumbnails), the distinct (shell, home, main list view) frames, the design-check failures at 1440 px light,
the brief's choices code replaced, and each draft's recorded time, calls and cost.
"""

import argparse
import asyncio
import json
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
]
# Hand-written examples (no recorded draft, no cost): Epic 22's every-plugin app and Epic 29's media app
HAND_WRITTEN = ("workshop-bookings", "media-library")


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


def main_list(spec: dict[str, Any]) -> str | None:
    """The route of the app's main list: the design's main entity, else the first navigation item with a list."""
    app = spec.get("app") or {}
    main = (app.get("design") or {}).get("mainEntity")
    candidates = []
    prefixes = [area["prefix"] for area in app.get("areas") or [] if area.get("prefix", "/") != "/"]
    for page in spec["pages"]:
        if "[" in page["route"] or page["route"] == "/" or any(page["route"].startswith(p) for p in prefixes):
            continue  # the first area's lists (Story 23.10)
        for section in page.get("sections") or []:
            content = section.get("content") or {}
            if section.get("component") == "AppList" and not content.get("tab") and content.get("variant") != "recent":
                candidates.append(((section.get("content") or {}).get("entity"), page["route"]))
    for entity, route in candidates:
        if entity == main:
            return route
    nav = [item.get("entity") for item in app.get("nav") or []]
    for entity in nav:
        for candidate, route in candidates:
            if candidate == entity:
                return route
    return candidates[0][1] if candidates else None


def frame(spec: dict[str, Any]) -> tuple[str, str, str]:
    """(shell, home, main list view): what tells two apps' frames apart at a glance."""
    app = spec.get("app") or {}
    design = app.get("design") or {}
    home = design.get("homeView") or ("dashboard" if (app.get("home") or "dashboard") == "dashboard" else "list")
    main = design.get("mainEntity") or next((item.get("entity") for item in app.get("nav") or []), None)
    entity = (app.get("entities") or {}).get(main or "") or {}
    view = ((design.get("entities") or {}).get(main or "") or {}).get("view") or entity.get("listStyle") or "table"
    return design.get("shell") or "sidebar", home, view


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


def similarity(thumbs: dict[str, list[int]]) -> dict[str, Any]:
    """Mean and max similarity over every pair, and the most alike pair."""
    from src.orchestrator.drafting.design_diversity import image_similarity

    pairs = {f"{a} / {b}": image_similarity(thumbs[a], thumbs[b]) for a, b in combinations(sorted(thumbs), 2)}
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
    """The home pages side by side, scaled to a third, with the app's name under each."""
    from PIL import Image, ImageDraw

    width, height, label = 480, 300, 24
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * (height + label)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (name, path) in enumerate(sorted(images.items())):
        x, y = (index % columns) * width, (index // columns) * (height + label)
        with Image.open(path) as image:
            top = image.crop((0, 0, min(image.width, 1440), min(image.height, 900))).convert("RGB")
            sheet.paste(top.resize((width, height)), (x, y))
        draw.text((x + 8, y + height + 5), name, fill="black")
    sheet.save(target)


def markdown(results: dict[str, Any]) -> str:
    lines = [
        f"# App design report ({results['date']})",
        "",
        f"Apps: {len(results['apps'])}. Home similarity mean {results['home']['mean']}, max {results['home']['max']} "
        f"({results['home'].get('mostAlike')}). Main list similarity mean {results['list']['mean']}, max "
        f"{results['list']['max']}. Distinct frames: {results['distinctFrames']} of {len(results['apps'])}.",
        "",
        "| App | Frame (shell, home, main view) | Failures | Replaced | Draft |",
        "|---|---|---|---|---|",
    ]
    for name, app in sorted(results["apps"].items()):
        cost = app.get("draft") or {}
        draft = f"{cost.get('seconds')} s, {cost.get('calls')} call(s), ${cost.get('costUsd')}" if cost else "—"
        lines.append(
            f"| {name} | {', '.join(app['frame'])} | {len(app['failures'])} | {len(app['replaced'])} | {draft} |"
        )
    failures = [line for app in results["apps"].values() for line in app["failures"]]
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
    from src.orchestrator.drafting.design_diversity import first_screen

    apps: dict[str, Any] = {}
    homes: dict[str, list[int]] = {}
    lists: dict[str, list[int]] = {}
    home_shots: dict[str, Path] = {}
    for name in names:
        spec, backend, _ = golden_app(name, locale)
        listed = main_list(spec)
        routes = ["/", *([listed] if listed else [])]
        print(f"building {name} ({', '.join(routes)})")
        measured = await check_site(
            spec, out / name, routes=routes, widths="1440", schemes="light", backend=backend,
            prepare=fake_slots if slots else None,
        )  # fmt: skip
        if measured is None:
            apps[name] = {"frame": list(frame(spec)), "failures": ["build failed"], "replaced": replaced(spec)}
            continue
        home = out / name / "home-1440-light.png"
        homes[name], home_shots[name] = first_screen(home), home
        if listed:
            lists[name] = first_screen(out / name / f"{listed.strip('/').replace('/', '-')}-1440-light.png")
        apps[name] = {
            "frame": list(frame(spec)),
            "routes": routes,
            "failures": [line for view, values in measured.items() for line in app_failures(view, values)],
            "replaced": replaced(spec),
            "draft": draft_cost(name),
        }
    results = {
        "date": str(date.today()),
        "apps": apps,
        "home": similarity(homes),
        "list": similarity(lists),
        "distinctFrames": len({tuple(app["frame"]) for app in apps.values()}),
    }
    if home_shots:
        contact_sheet(home_shots, out / "contact-sheet.png")
    (out / "report.json").write_text(json.dumps(results, indent=2) + "\n")
    (out / "report.md").write_text(markdown(results))
    return results


async def main(args: argparse.Namespace) -> None:
    out = OUT / str(date.today())
    out.mkdir(parents=True, exist_ok=True)
    if args.locale or args.slots:  # a variant: its own folder, never the baseline
        out = out / "-".join(filter(None, [args.locale, "slots" if args.slots else None]))
        out.mkdir(parents=True, exist_ok=True)
    results = await report(args.app or APPS, out, args.locale, args.slots)
    print(markdown(results))
    if args.baseline:
        keep = {key: results[key] for key in ("date", "distinctFrames")}
        keep |= {key: {k: results[key][k] for k in ("mean", "max")} for key in ("home", "list")}
        keep["frames"] = {name: app["frame"] for name, app in results["apps"].items()}
        (GOLDEN / "baseline.json").write_text(json.dumps(keep, indent=2) + "\n")
        print(f"baseline → {GOLDEN / 'baseline.json'}")
    print(f"report → {out / 'report.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", action="append", help="a golden app (default: all)")
    parser.add_argument("--baseline", action="store_true", help="write tests/fixtures/app-golden/baseline.json")
    parser.add_argument("--locale", help="build the apps in this locale (Story 23.8: ja)")
    parser.add_argument("--slots", action="store_true", help="with the fake engine's view slots (Story 23.11)")
    asyncio.run(main(parser.parse_args()))
