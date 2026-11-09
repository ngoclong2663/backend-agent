"""The design plugin registry (Epic 30, Story 30.2): one folder per value of the design space; the literals, the
prompt's choice lists, the checks and the kit's dispatch table come from it, and no hand-kept list of the values is
left in the code."""

import json
import re
import typing
from pathlib import Path

import pytest

from src.modules.shared.domain.frontend_spec import app as app_schema
from src.modules.shared.domain.frontend_spec.design_registry import (
    DESIGN_DIR,
    KINDS,
    KIT_KINDS,
    DesignRegistry,
    DesignRegistryError,
    registry,
    registry_digest,
)
from src.orchestrator.frontend.app.design import ARCHETYPES, design_choices
from src.orchestrator.frontend.app.files import design_plugins_used, design_registry_ts
from src.orchestrator.frontend.app.recipes import FAMILY, GUARDED, RECIPES, recipe_css

REPO = Path(__file__).resolve().parents[2]
API = REPO / "agent-api"
KIT = API / "templates" / "nextjs_overlay" / "files" / "dynamic" / "app" / "src" / "components" / "app"
LITERALS = {
    "shell": app_schema.Shell,
    "home": app_schema.HomeView,
    "list-view": app_schema.ListView,
    "detail-view": app_schema.DetailView,
    "filters": app_schema.FiltersStyle,
    "recipe": app_schema.Recipe,
}


def _write(root: Path, kind: str, name: str, **fields) -> None:
    folder = root / kind / name
    folder.mkdir(parents=True)
    data = {"kind": kind, "name": name, "status": "ready", "label": name.title(), "choose": "When it fits.", **fields}
    (folder / "plugin.json").write_text(json.dumps(data))


def test_the_checked_in_plugins_all_load():
    assert registry().problems == [], registry().problems
    DesignRegistry(strict=True)


def test_a_broken_folder_is_left_out_but_the_rest_loads(tmp_path):
    _write(tmp_path, "shell", "fine", exports=["Fine"], builtin=True, module="./shells")
    _write(tmp_path, "shell", "broken", exports=["Broken"], files=["Missing.tsx"])
    reg = DesignRegistry(tmp_path)
    assert reg.names("shell") == ("fine",) and reg.problems == ["shell/broken: file Missing.tsx is missing"]


def test_every_literal_is_the_registrys_ready_names():
    for kind, literal in LITERALS.items():
        assert typing.get_args(literal) == registry().names(kind), kind
    assert RECIPES == registry().names("recipe")
    assert set(FAMILY) == set(RECIPES) and set(GUARDED) == {"neon", "playful"}


def test_todays_values_are_all_plugin_folders():
    assert registry().names("shell") == ("sidebar", "topbar", "topbar-tabs", "rail")
    assert registry().names("list-view")[:6] == ("table", "cards", "media-grid", "feed", "board", "calendar")
    assert registry().names("detail-view")[:3] == ("record", "media", "profile")
    assert registry().names("home")[:5] == ("dashboard", "feed", "catalogue", "agenda", "bento")
    assert registry().names("filters") == ("toolbar", "chips", "facets", "search-first")
    assert len(registry().names("recipe")) >= 12
    for name in RECIPES:
        assert recipe_css(name).startswith(f"\n/* Style recipe: {name}"), name
    for archetype, defaults in ARCHETYPES.items():
        assert defaults["shell"] in registry().names("shell"), archetype
        assert defaults["homeView"] in registry().names("home"), archetype
        assert defaults["view"] in registry().names("list-view"), archetype


def test_a_builtin_plugin_names_a_component_its_kit_module_exports():
    for kind in KIT_KINDS:
        for plugin in registry().ready(kind):
            if not plugin.dispatch:
                continue
            if plugin.builtin:
                module = (KIT / (plugin.module.removeprefix("./") + ".tsx")).read_text()
                assert f"export function {plugin.exports[0]}" in module, f"{kind}/{plugin.name}"
            else:
                source = (plugin.folder / plugin.files[0]).read_text()
                assert f"export function {plugin.exports[0]}" in source, f"{kind}/{plugin.name}"
                assert (
                    f"data-bga-{'detail' if kind == 'detail-view' else kind.split('-')[0]}" in source
                    or plugin.marker in source
                )


def test_the_loader_refuses_a_missing_fallback_an_unknown_need_and_a_mismatched_folder(tmp_path):
    _write(tmp_path, "shell", "one", exports=["One"], builtin=True, module="./shells")
    _write(tmp_path, "shell", "two", exports=["Two"], builtin=True, module="./shells", fallback="three")
    with pytest.raises(DesignRegistryError, match="fallback 'three'"):
        DesignRegistry(tmp_path, strict=True)
    (tmp_path / "shell" / "two" / "plugin.json").unlink()
    _write(tmp_path, "list-view", "odd", exports=["Odd"], builtin=True, module="./views", needs=["magic"])
    with pytest.raises(DesignRegistryError, match="unknown needs"):
        DesignRegistry(tmp_path, strict=True)
    (tmp_path / "list-view" / "odd" / "plugin.json").unlink()
    _write(tmp_path, "list-view", "mismatch", exports=["X"], builtin=True, module="./views")
    data = json.loads((tmp_path / "list-view" / "mismatch" / "plugin.json").read_text()) | {"name": "other"}
    (tmp_path / "list-view" / "mismatch" / "plugin.json").write_text(json.dumps(data))
    with pytest.raises(DesignRegistryError, match="do not match the folder"):
        DesignRegistry(tmp_path, strict=True)


def test_a_draft_plugin_is_loaded_but_never_offered(tmp_path):
    _write(tmp_path, "shell", "steady", exports=["Steady"], builtin=True, module="./shells")
    _write(tmp_path, "shell", "trying", status="draft", exports=["Trying"], files=["Trying.tsx"], fallback="steady")
    (tmp_path / "shell" / "trying" / "Trying.tsx").write_text("export function Trying() {}")
    reg = DesignRegistry(tmp_path)
    assert reg.names("shell") == ("steady",) and reg.get("shell", "trying") is not None
    assert reg.fallback_chain("shell", "trying") == ["trying", "steady"]
    assert reg.copied("shell", "trying") == [
        (tmp_path / "shell" / "trying" / "Trying.tsx", "src/components/design/shell/trying/Trying.tsx")
    ]
    assert reg.copied("shell", "steady") == []


def test_a_ready_plugin_with_needs_falls_back_to_one_without(tmp_path):
    _write(tmp_path, "list-view", "needy", exports=["A"], builtin=True, module="./views", needs=["mediaField"],
           fallback="needier")  # fmt: skip
    _write(tmp_path, "list-view", "needier", exports=["B"], builtin=True, module="./views", needs=["groupField"],
           fallback="needy")  # fmt: skip
    with pytest.raises(DesignRegistryError, match="never reach a plugin without needs"):
        DesignRegistry(tmp_path, strict=True)


def test_the_prompt_lists_only_the_candidates_of_the_ranked_archetypes():
    choices = design_choices(["workspace"])
    assert "`rail`" in choices["shell"] and "`board`" in choices["list-view"]
    storefront = design_choices(["storefront"])
    assert "`rail`" not in storefront["shell"] and "`board`" not in storefront["list-view"]
    assert all(f"`{name}`" in storefront["recipe"] for name in RECIPES if not registry().get("recipe", name).archetypes)
    assert "`terminal`" not in storefront["recipe"], "a recipe for tools is not offered to a storefront"
    everything = design_choices(None)
    for kind in KINDS:
        for plugin in registry().ready(kind):
            assert f"`{plugin.name}` (" in everything[kind], (kind, plugin.name)


def test_the_generated_kit_registry_imports_only_the_plugins_an_app_uses():
    design = {"shell": "topbar", "homeView": "catalogue", "entities": {"Plant": {"view": "media-grid"}}}
    areas = [{"design": {"shell": "sidebar", "homeView": "dashboard", "entities": {"Plant": {"view": "table"}}}}]
    used = design_plugins_used(design, areas)
    assert used == {
        "shell": ["sidebar", "topbar"],
        "home": ["dashboard", "catalogue"],
        "list-view": ["table", "media-grid"],
    }
    text = design_registry_ts(used)
    assert 'import { SidebarShell, TopBarShell } from "./shells";' in text
    assert 'import { CatalogueRows, MediaGrid, TableRows } from "./views";' in text
    assert "Board" not in text and "RecordDetail" not in text, "nothing the app does not use"
    assert '"media-grid": MediaGrid' in text and "catalogue: CatalogueRows" in text
    assert "detailViews: {} as Record" in text


def test_the_digest_describes_every_ready_plugin_for_the_ui():
    digest = registry_digest()
    assert set(digest) == set(KINDS)
    assert [p["name"] for p in digest["shell"]] == list(registry().names("shell"))
    assert all({"name", "label", "choose", "archetypes", "needs", "fallback"} <= set(p) for p in digest["recipe"])
    assert all(p.get("family") for p in digest["recipe"])


# Story 30.2 step 5: no hand-kept list of a kind's names anywhere code or the kit decides from.
SCANNED = (
    API / "src",
    API / "prompts" / "draft_app" / "v7.md",
    API / "prompts" / "draft_app" / "v8.md",
    KIT,
    REPO / "agent-ui" / "src" / "features" / "specs",
)
EXEMPT = ("design_registry.py", "schema_v1.py")  # schema_v1: the theme presets share names with recipes


def _lines(path: Path):
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        return
    yield from enumerate(text.splitlines(), 1)


def test_no_hand_written_list_of_plugin_names_remains():
    # Epic 32: a pattern is named after its one archetype (the descriptor checks it), so the archetype vocabulary
    # (`frontend_spec/app.Archetype`, `design.ARCHETYPES`) is the source its names follow, not a copy of them
    quoted = {
        kind: [re.compile(rf"[\"'`]{re.escape(name)}[\"'`]") for name in registry().names(kind)]
        for kind in KINDS
        if kind != "pattern"
    }
    found = []
    for root in SCANNED:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.suffix in (".py", ".ts", ".tsx", ".md")]
        for path in files:
            if path.name in EXEMPT or "__pycache__" in path.parts:
                continue
            for number, line in _lines(path):
                for kind, patterns in quoted.items():
                    hits = sum(1 for pattern in patterns if pattern.search(line))
                    if hits >= 3 and len(patterns) >= 3:
                        found.append(f"{path.relative_to(REPO)}:{number} names {hits} {kind} plugins")
    assert not found, "\n".join(found)


def test_the_descriptor_folders_hold_what_they_name():
    for path in DESIGN_DIR.glob("*/*/plugin.json"):
        if path.parts[-3].startswith("_"):
            continue
        plugin = registry().get(path.parts[-3], path.parts[-2])
        assert plugin is not None, path
        for file in plugin.files:
            assert (plugin.folder / file).is_file(), f"{plugin.kind}/{plugin.name}: {file}"
        if plugin.css:
            assert (plugin.folder / plugin.css).is_file()


def test_every_plugin_passes_the_fast_checks():
    """Story 30.3 step 4: CI runs the check's fast part (descriptor, files, exports, marker, fixture) for every
    plugin."""
    from scripts.design_plugin import fast_checks

    failures = []
    for kind in KINDS:
        for plugin in registry().plugins[kind].values():
            failures += [f"{kind}/{plugin.name}: {name} {detail}" for name, ok, detail in fast_checks(plugin) if not ok]
    assert not failures, "\n".join(failures)
