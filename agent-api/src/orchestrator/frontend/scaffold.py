"""Frontend base project = pinned `create-next-app` base + our overlay + generated files (Story 13.2, decision Q11).

`templates/nextjs_base/` is the output of `scripts/frontend-base.sh` (create-next-app exactly as nextjs-skills
prescribes, shadcn base-nova with every catalogue primitive, the skill's libraries; versions pinned by
`pnpm-lock.yaml`). `templates/nextjs_overlay/` adds providers, layout primitives, the runtime config, the API
client, the mock layer, test setup and Dockerfiles (`files/common` + `files/<mode>`). Its `overlay.json` records
the sha256 of every base file it replaces or removes; if the base ever differs, the job fails with
FRONTEND_TEMPLATE_DRIFT before anything is written.

Only the shadcn primitives the plan needs are copied. Overlay, generated and shadcn files are generator-owned:
their hashes go to `.bga/owned.json` and the conventions check fails when the engine changes them.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from .asset_registry import external_images_note
from .codegen import generated_files
from .renderer import library_files

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
BASE_DIR = TEMPLATES / "nextjs_base"
OVERLAY_DIR = TEMPLATES / "nextjs_overlay"
SAMPLES_DIR = TEMPLATES / "samples"  # Epic 29: the sample media (`public/samples/`) of apps with media fields
SCAFFOLD_INFO = ".bga/scaffold.json"
OWNED_INFO = ".bga/owned.json"
SKIP = {
    "node_modules", ".next", ".git", "out", "test-results", "playwright-report",
    "base.lock", "lucide-icons.txt", "icon-index.json",
}  # fmt: skip
UI_DIR = "src/components/ui"
APP_PART = "app"  # Epic 22: `files/dynamic/app/`, the app kit
SHELL_PLACEHOLDER = """import type { ReactNode } from "react";

type SiteShellProps = {
  children: ReactNode;
};

/** Placeholder written by the scaffold; the engine replaces it with the shell from FrontendSpec.layout. */
export function SiteShell({ children }: SiteShellProps) {
  return <main className="flex-1">{children}</main>;
}
"""
GITIGNORE_EXTRA = "\n# Fullstack Generation Agent\n/test-results/\n/playwright-report/\n/.bga/\n/.claude/\n/.agents/\n"
SCRIPTS = {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:e2e": "playwright test",
}


class FrontendTemplateDrift(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("Frontend base does not match the overlay manifest: " + "; ".join(problems[:10]))
        self.problems = problems


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(overlay: Path = OVERLAY_DIR) -> dict[str, Any]:
    return json.loads((overlay / "overlay.json").read_text())


def check_base(base: Path = BASE_DIR, overlay: Path = OVERLAY_DIR) -> list[str]:
    manifest = load_manifest(overlay)
    if not (base / "package.json").is_file():
        return [f"frontend base missing: {base}"]
    problems = []
    for relative, expected in manifest["replace"].items():
        path = base / relative
        if not path.is_file():
            problems.append(f"{relative}: missing")
        elif _sha256(path) != expected:
            problems.append(f"{relative}: changed")
    if _sha256(base / "pnpm-lock.yaml") != manifest["lockSha256"]:
        problems.append("pnpm-lock.yaml: changed (rebuild the runner image and update overlay.json)")
    for relative in manifest["remove"]:
        if not (base / relative).exists():
            problems.append(f"{relative}: expected to remove, not found")
    return problems


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and not SKIP & set(path.relative_to(root).parts))


def _copy(source: Path, target: Path, replacements: dict[str, str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = source.read_bytes()
    for placeholder, value in replacements.items():
        content = content.replace(placeholder.encode(), value.encode())
    target.write_bytes(content)
    target.chmod(source.stat().st_mode & 0o777)


def scaffold_frontend(
    project: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    contract: dict[str, Any] | None = None,
    base: Path = BASE_DIR,
    overlay: Path = OVERLAY_DIR,
) -> dict[str, Any]:
    problems = check_base(base, overlay)
    if problems:
        raise FrontendTemplateDrift(problems)
    manifest = load_manifest(overlay)
    mode = plan["project"]["mode"]
    wanted_ui = {f"{UI_DIR}/{name}.tsx" for name in plan["shadcn"]}
    removed = set(manifest["remove"])

    for source in _files(base):
        relative = source.relative_to(base).as_posix()
        if relative in removed or (relative.startswith(f"{UI_DIR}/") and relative not in wanted_ui):
            continue
        _copy(source, project / relative, {})
    replacements = {
        "{{PROJECT_NAME}}": plan["project"]["name"],
        "{{PROJECT_NAME_SLUG}}": plan["project"]["slug"],
        "{{EXTERNAL_IMAGES}}": external_images_note(plan),  # Story 15.4
    }
    overlay_files: list[str] = []
    rendering = plan.get("rendering")
    parts = (
        "common",
        mode,
        *(("renderer",) if rendering == "renderer" else ("dynamic/app",) if rendering == "app" else ()),
    )
    for part in parts:
        root = overlay / "files" / part
        sources = {source.relative_to(root).as_posix(): source for source in _files(root)}
        if part == "dynamic":  # Epic 22: the app kit is its own part, copied only for apps
            sources = {name: source for name, source in sources.items() if not name.startswith(f"{APP_PART}/")}
        # The section library (Stories 17.2, 17.4): the sections this site uses, the helpers and its shell.
        wanted = library_files(plan, list(sources)) if part == "renderer" else {name: name for name in sources}
        for target, source in wanted.items():
            _copy(sources[source], project / target, replacements)
            overlay_files.append(target)

    if rendering == "app":  # Story 22.7: the frontend files of the plugins the app uses
        from .app.plan import plugin_frontend

        for name in (plan.get("app") or {}).get("plugins") or []:
            root = plugin_frontend(name)
            for source in _files(root) if root.is_dir() else []:
                target = source.relative_to(root).as_posix()
                _copy(source, project / target, replacements)
                overlay_files.append(target)
        if (plan.get("app") or {}).get("media") and SAMPLES_DIR.is_dir():
            # Story 29.2: the sample media the mocks play (`/samples/…`), only for apps with media fields
            for source in _files(SAMPLES_DIR):
                if source.name == "README.md":
                    continue
                target = f"public/samples/{source.name}"
                _copy(source, project / target, {})
                overlay_files.append(target)

    for asset in plan.get("assets") or []:  # Epic 31: a Pixabay poster is a file of the site (never hotlinked)
        source = Path(asset["posterSource"]) if asset.get("posterSource") else None
        if source is not None and source.is_file() and asset.get("posterFile"):
            target = project / asset["posterFile"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    package_path = project / "package.json"
    package = json.loads(package_path.read_text())
    package["name"] = plan["project"]["slug"]
    package["scripts"] = SCRIPTS
    package_path.write_text(json.dumps(package, indent=2) + "\n")
    with (project / ".gitignore").open("a") as gitignore:
        gitignore.write(GITIGNORE_EXTRA)

    generated = generated_files(plan, spec, contract)
    for relative, content in generated.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    shell = project / plan["shell"]["file"]
    if not shell.exists():
        shell.parent.mkdir(parents=True, exist_ok=True)
        shell.write_text(SHELL_PLACEHOLDER)

    bga = project / ".bga"
    bga.mkdir(parents=True, exist_ok=True)
    (bga / "frontend-spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    if contract is not None:
        (bga / "contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    owned = sorted({*overlay_files, *generated, *(p for p in wanted_ui if (project / p).exists()), "package.json",
                    "pnpm-lock.yaml", "pnpm-workspace.yaml", "components.json", "src/lib/utils.ts"})  # fmt: skip
    record_owned(project, owned)
    info = {
        "base": manifest["baseLock"],
        "overlayVersion": manifest["version"],
        "mode": mode,
        "shadcn": plan["shadcn"],
        "generated": sorted(generated),
        "owned": len(owned),
    }
    (project / SCAFFOLD_INFO).write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    return info


def record_owned(project: Path, files: list[str]) -> dict[str, str]:
    hashes = {relative: _sha256(project / relative) for relative in files if (project / relative).is_file()}
    (project / OWNED_INFO).write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    return hashes


def update_owned(project: Path, files: list[str]) -> None:
    """Records the current content of generator-owned files the generator rewrote after the scaffold (the registry
    once the custom components are resolved, Story 17.3)."""
    path = project / OWNED_INFO
    hashes = json.loads(path.read_text()) if path.exists() else {}
    hashes |= {relative: _sha256(project / relative) for relative in files if (project / relative).is_file()}
    path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")


def drop_owned(project: Path, files: list[str]) -> None:
    """Forgets generator-owned files the generator itself removed (a drawing that fell back, Story 15.3)."""
    path = project / OWNED_INFO
    if path.exists():
        hashes = {k: v for k, v in json.loads(path.read_text()).items() if k not in set(files)}
        path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")


def changed_owned(project: Path) -> list[str]:
    """Generator-owned files the engine changed or removed since the scaffold."""
    path = project / OWNED_INFO
    if not path.exists():
        return []
    recorded: dict[str, str] = json.loads(path.read_text())
    return sorted(
        relative
        for relative, digest in recorded.items()
        if not (project / relative).is_file() or _sha256(project / relative) != digest
    )


def build_manifest(base: Path = BASE_DIR, overlay: Path = OVERLAY_DIR, version: str = "1") -> dict[str, Any]:
    """Recomputes `overlay.json` after `make frontend-base` (the replaced/removed base files and the lock hash)."""
    replaced = sorted(
        relative
        for part in ("common", "dynamic", "static")
        for relative in (p.relative_to(overlay / "files" / part).as_posix() for p in _files(overlay / "files" / part))
        if (base / relative).is_file()
    )
    generated_over_base = ["src/app/globals.css"]
    remove = ["src/app/page.tsx", "public/file.svg", "public/globe.svg", "public/next.svg", "public/vercel.svg",
              "public/window.svg"]  # fmt: skip
    base_lock = dict(line.split("=", 1) for line in (base / "base.lock").read_text().splitlines() if "=" in line)
    return {
        "version": version,
        "baseLock": base_lock,
        "lockSha256": _sha256(base / "pnpm-lock.yaml"),
        "replace": {relative: _sha256(base / relative) for relative in sorted({*replaced, *generated_over_base})},
        "remove": {relative: _sha256(base / relative) for relative in remove},
    }
