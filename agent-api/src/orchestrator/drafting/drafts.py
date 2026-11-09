"""Requirement drafting (Stories 2.4, 12.4): a requirement (or an imported site) → draft spec(s) for review.

A draft runs on the worker, outside the generation graph: one engine call in a scratch directory writes the spec
file(s) and `notes.json`; they are validated (BackendSpec 2.2, FrontendSpec 12.1) and repaired by the engine a bounded
number of times. Dynamic drafts take the app flow (`app.py`, Epic 22), which also checks the pair (12.5). A draft that
is still invalid ends as NEEDS_REVIEW with its errors; it is never submitted. Each engine call is recorded on the
draft (`usage`) and traced.

Static drafts from a requirement get a design direction (Story 12.6): the engine sees three ranked briefs
(`.bga/design.md`) and names one in its notes; the theme, the home page order and the hero layout are then filled from
the design data, and the three directions are kept on the draft (`design`) for the review. A dynamic app takes only
the first direction's theme, with no cards.

Drafts show no placeholders (Epic 15): an image the engine left as a placeholder is turned into a drawing
(`source: "generate"`, prompt from its alt text, style from the direction), up to the generated-image limit.
"""

import asyncio
import hashlib
import io
import json
import shutil
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from src.configs import config, get_logger
from src.configs.config import uploads_dir
from src.engines import EngineRegistry, PromptLibrary
from src.engines.port import EngineContext, EngineRequest, EngineResult, EngineStatus
from src.engines.prompts import RenderedPrompt
from src.images.factory import get_image_generator, get_stock_photos, photos_enabled
from src.images.service import generate_single_photo
from src.images.stock import stock_seed_photos, stock_site_photos
from src.libs.ids.ulid import new_upload_id
from src.modules.shared.domain.backend_spec import (
    SpecIssue,
    ValidationReport,
    spec_json_schema,
    validate_spec_data,
)
from src.modules.shared.domain.entities import ImageCallEntity, SpecDraftEntity, UploadEntity
from src.modules.shared.domain.enums import GenerationMode, GenerationStatus, SpecDraftStatus, SpecSource
from src.modules.shared.domain.frontend_spec import (
    BUILTIN_SECTIONS,
    LAYOUT_SECTIONS,
    SECTION_PROPS,
    autofix_frontend_spec,
    frontend_spec_json_schema,
    validate_frontend_spec_data,
)
from src.modules.shared.domain.frontend_spec.assets import MAX_GENERATED_ASSETS, SVG_KINDS, source_kind
from src.modules.shared.domain.frontend_spec.copy_rules import phrase_list
from src.modules.shared.domain.generation_modes import initial_lanes
from src.modules.shared.domain.schema_digest import schema_digest
from src.orchestrator.drafting import trees as tree_drafting
from src.videos.factory import providers_for, videos_enabled
from src.videos.stock import VideoSearch, stock_seed_videos, stock_site_videos

from .. import tracing
from ..checks.consistency import check_spec_pair
from ..store import JobStore
from .app import BACKEND_EXAMPLE as APP_BACKEND_EXAMPLE
from .app import app_flow, app_inputs, draft_app, outline_notes
from .business import DraftBusiness, business_on, draft_model, draft_provider
from .design_cards import (
    MAX_SEED,
    best_fit,
    brand_fixed,
    card_directions,
    code_fix,
    components,
    design_record,
    fact_pack,
    failing_card,
    home_pool,
    new_seed,
    problems,
    read_cards,
)
from .design_cards import (
    fields as direction_fields,
)
from .design_direction import (
    PHOTO_STYLES_BY_PRESET,
    apply_direction,
    design_notes,
    directions,
    pick,
)

logger = get_logger(__name__)

INPUTS = ".bga"
BACKEND_FILE = "backend-spec.json"
FRONTEND_FILE = "frontend-spec.json"
NOTES_FILE = "notes.json"
MAX_REPAIR_ERRORS = 50
# Story 20.4: rounds of asking the engine again for a direction card that fails the difference test.
DIRECTION_REPAIRS = 2
# Examples handed to the engine, relative to EXAMPLES_DIR (the repo's `examples/`).
EXAMPLES = {
    "backend": "specs/shop.json",
    "static": "frontend-specs/static-landing.json",
}


# Epic 27 photos are free and cached: the only bound on a draft is the hour's requests (50 for a demo app), so the
# stock flow takes every drafted photo up to this ceiling; FRONTEND_MAX_PHOTOS caps paid (Gemini) photos alone.
STOCK_PHOTO_LIMIT = 40


def crash_site(exc: BaseException) -> str:
    """Where an unexpected error was raised in the agent's own code (` (at drafting/app.py:120 in fix)`), so a failed
    draft says where to look even when the worker's log is gone."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "/src/" in f.filename.replace("\\", "/")]
    if not frames:
        return ""
    frame = frames[-1]
    where = frame.filename.replace("\\", "/").split("/src/", 1)[1].removeprefix("orchestrator/")
    return f" (at {where}:{frame.lineno} in {frame.name})"


class DraftFailed(Exception):
    pass


# -- inputs --------------------------------------------------------------------------------------------------------


def _content_fields(model: type) -> str:
    """A props model's content fields, with the choices of enum fields (Story 20.2: layouts and forms)."""
    fields = []
    for name, schema in model.model_json_schema(by_alias=True).get("properties", {}).items():
        choices = schema.get("enum") or next((s["enum"] for s in schema.get("anyOf", []) if "enum" in s), None)
        fields.append(f"{name} ({' | '.join(map(str, choices))})" if choices and len(choices) > 1 else name)
    return ", ".join(fields)


def section_catalogue() -> str:
    """The built-in sections the drafter should prefer (Story 17.1), with their typed content fields."""
    lines = [
        "# Built-in sections",
        "",
        'Use them as `{"id", "component": "<Name>", "content": {...}}`; the full content types are in the',
        "FrontendSpec schema (`$defs`). Data sections take `data` instead of (or as well as) `content`: in a static",
        "site `data.collection` names a `content` collection, in a dynamic app `data.operationId` names an API",
        "operation. These render without any model call; prefer them to custom components.",
        "",
    ]
    for name, model in SECTION_PROPS.items():
        if name in LAYOUT_SECTIONS:
            continue
        fields = _content_fields(model)
        lines.append(f"- **{name}**: {BUILTIN_SECTIONS[name]['description']}. Content: {fields or 'none'}.")
    lines += [
        "",
        "# Layout nodes",
        "",
        "They hold other sections in `children` (nesting depth 3 at most) and only arrange them.",
        "",
    ]
    for name in sorted(LAYOUT_SECTIONS):
        fields = _content_fields(SECTION_PROPS[name])
        lines.append(f"- **{name}**: {BUILTIN_SECTIONS[name]['description']}. Content: {fields or 'none'}.")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _copy_example(examples_dir: Path, name: str, target: Path) -> None:
    source = examples_dir / name
    if not source.is_file():
        raise DraftFailed(f"Example spec missing: {source} (set EXAMPLES_DIR)")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def write_inputs(
    work: Path,
    draft: SpecDraftEntity,
    examples_dir: Path,
    design: list[dict[str, Any]] | None = None,
    seed: int | None = None,
    app: bool = False,
) -> dict[str, str]:
    """Writes the engine's inputs under `.bga/` and returns the prompt context (paths relative to `work`). `app`:
    the dynamic app flow (Epic 22), which needs no FrontendSpec inputs (code writes its pages)."""
    inputs = work / INPUTS
    mode = GenerationMode(draft.mode)
    _write_json(
        inputs / "draft.json",
        {
            "source": draft.source,
            "mode": mode,
            "requirementFormat": draft.requirement_format,
            "requirementFileName": draft.requirement_file_name,
            **({"designSeed": seed} if design else {}),
            **({"flow": "app"} if app else {}),
        },
    )
    context: dict[str, Any] = {"mode": str(mode), "source": str(draft.source), "notes_path": NOTES_FILE}
    if draft.source == SpecSource.REQUIREMENT:
        name = "requirement.md" if draft.requirement_format == "markdown" else "requirement.txt"
        (inputs / name).write_text(draft.requirement_text or "")
        context |= {"requirement_text": draft.requirement_text, "requirement_format": draft.requirement_format}
    if mode in (GenerationMode.BACKEND, GenerationMode.DYNAMIC):
        _write_json(inputs / "backend-spec.schema.json", spec_json_schema())
        (inputs / "backend-spec.schema.md").write_text(schema_digest(spec_json_schema(), "BackendSpec"))
        example = APP_BACKEND_EXAMPLE if app else EXAMPLES["backend"]
        _copy_example(examples_dir, example, inputs / "examples" / "backend-spec.json")
        context |= {
            "schema_path": f"{INPUTS}/backend-spec.schema.json",
            "schema_digest_path": f"{INPUTS}/backend-spec.schema.md",
            "example_path": f"{INPUTS}/examples/backend-spec.json",
            "backend_schema_path": f"{INPUTS}/backend-spec.schema.json",
            "backend_schema_digest_path": f"{INPUTS}/backend-spec.schema.md",
            "backend_example_path": f"{INPUTS}/examples/backend-spec.json",
            "output_spec_path": BACKEND_FILE,
            "output_backend_path": BACKEND_FILE,
        }
    if app:
        context |= app_inputs(examples_dir, design=True)  # Story 23.6: `draft_app@v3` asks for the brief
    if mode == GenerationMode.STATIC:
        # Epic 22: without the app flow's fields, so static drafts read the schema they always did.
        site = frontend_spec_json_schema(app=False)
        _write_json(inputs / "frontend-spec.schema.json", site)
        (inputs / "frontend-spec.schema.md").write_text(schema_digest(site, "FrontendSpec"))
        _copy_example(examples_dir, EXAMPLES[str(mode)], inputs / "examples" / "frontend-spec.json")
        (inputs / "sections.md").write_text(section_catalogue())
        context |= {
            "frontend_schema_path": f"{INPUTS}/frontend-spec.schema.json",
            "frontend_schema_digest_path": f"{INPUTS}/frontend-spec.schema.md",
            "frontend_example_path": f"{INPUTS}/examples/frontend-spec.json",
            "sections_path": f"{INPUTS}/sections.md",
            "output_frontend_path": FRONTEND_FILE,
            "design_path": None,
            "stock_phrases": phrase_list(),
            "photos_enabled": photos_enabled(),
            "max_photos": config.frontend_max_photos,
            "videos_enabled": videos_enabled(),  # Epic 31: a Video section and hero background clips
        }
    if design:
        (inputs / "design.md").write_text(fact_pack(design[0], seed or 0, str(mode)))
        context["design_path"] = f"{INPUTS}/design.md"
    if draft.source == SpecSource.FRONTEND:
        _write_json(inputs / "base-spec.json", draft.inputs.get("baseSpec"))
        _write_json(inputs / "site.json", draft.inputs.get("siteJson"))
        context |= {"base_spec_path": f"{INPUTS}/base-spec.json", "site_json_path": f"{INPUTS}/site.json"}
    return context


def inline_inputs(work: Path, context: dict[str, Any]) -> dict[str, Any]:
    """Story 18.10: the prompt context for an engine without files (`inline_inputs`): the `.bga/` inputs as text."""
    inputs = work / INPUTS

    def text(name: str) -> str:
        path = inputs / name
        return path.read_text() if path.is_file() else ""

    added: dict[str, Any] = {"inline": True}
    if "frontend_schema_digest_path" in context:
        added |= {
            "frontend_schema_digest": text("frontend-spec.schema.md"),
            "frontend_example": text("examples/frontend-spec.json"),
            "sections": text("sections.md"),
        }
    if "backend_schema_digest_path" in context:
        added |= {
            "schema_digest": text("backend-spec.schema.md"),
            "backend_schema_digest": text("backend-spec.schema.md"),
            "example": text("examples/backend-spec.json"),
            "backend_example": text("examples/backend-spec.json"),
        }
    if context.get("design_path"):
        added["design"] = text("design.md")
    if "site_json_path" in context:
        added |= {"base_spec": text("base-spec.json"), "site_json": text("site.json")}
    return added


def spec_documents(work: Path, files: list[str]) -> dict[str, str]:
    """The current spec files, for an inline repair prompt (the patches point into them)."""
    return {name: (work / name).read_text() for name in files if (work / name).is_file()}


# -- checks --------------------------------------------------------------------------------------------------------


@dataclass
class DraftCheck:
    backend_spec: dict[str, Any] | None = None
    frontend_spec: dict[str, Any] | None = None
    reports: dict[str, ValidationReport] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(report.valid for report in self.reports.values())

    def repair_errors(self) -> list[dict[str, Any]]:
        """The errors to hand to `repair_spec`, each with the file it is in and a focused excerpt."""
        files = {"backend": BACKEND_FILE, "frontend": FRONTEND_FILE, "pair": FRONTEND_FILE}
        specs = {
            BACKEND_FILE: self.backend_spec,
            FRONTEND_FILE: self.frontend_spec,
        }
        errors = []
        for key, report in self.reports.items():
            filename = files[key]
            doc = specs.get(filename)
            for issue in report.errors:
                item = {"file": filename, **issue.model_dump(mode="json", exclude={"severity"}, exclude_none=True)}
                if doc is not None:
                    item["excerpt"] = build_excerpt(doc, issue.path)
                if key == "pair" and issue.backend_path and self.backend_spec is not None:
                    # Either side may be the one to change (a custom operation's undeclared response is a backend fix).
                    item["backendFile"] = BACKEND_FILE
                    item["backendExcerpt"] = build_excerpt(self.backend_spec, issue.backend_path)
                errors.append(item)
        return errors[:MAX_REPAIR_ERRORS]

    def validation(self) -> dict[str, Any]:
        return {key: report.model_dump(mode="json") for key, report in self.reports.items()}


def build_excerpt(doc: Any, path: str, max_chars: int = 1500) -> str:
    """Returns a JSON string containing the value at `path` and its parent, trimmed to ~max_chars."""
    if doc is None:
        return ""
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in path.strip("/").split("/") if t]
    current = doc
    parent = None
    matched_tokens: list[str] = []
    for token in tokens:
        if isinstance(current, dict) and token in current:
            parent = current
            current = current[token]
            matched_tokens.append(token)
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            parent = current
            current = current[int(token)]
            matched_tokens.append(token)
        else:
            parent = current
            current = None
            break
    data: dict[str, Any] = {}
    if parent is not None:
        if current is None:
            parent_path = "/" + "/".join(matched_tokens) if matched_tokens else "/"
        else:
            parent_path = "/" + "/".join(matched_tokens[:-1]) if len(matched_tokens) > 1 else "/"
        data[f"parent ({parent_path})"] = parent
    if current is not None:
        data[f"target ({path or '/'})"] = current
    if not data and doc is not None:
        data["root"] = doc
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text) > max_chars:
        return text[:max_chars] + "... [truncated]"
    return text


def _load(path: Path) -> tuple[Any, SpecIssue | None]:
    if not path.is_file():
        return None, SpecIssue(code="DRAFT_FILE_MISSING", path="", message=f"The draft has no {path.name}")
    try:
        return json.loads(path.read_text()), None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, SpecIssue(code="JSON_MALFORMED", path="", message=f"{path.name} is not valid JSON: {exc}")


def check_draft(work: Path, mode: GenerationMode) -> DraftCheck:
    check = DraftCheck()
    backend_normalized = frontend_normalized = None
    if mode in (GenerationMode.BACKEND, GenerationMode.DYNAMIC):
        data, issue = _load(work / BACKEND_FILE)
        if issue is not None:
            check.reports["backend"] = ValidationReport.from_issues([issue], None)
        else:
            result = validate_spec_data(data)
            check.backend_spec, check.reports["backend"] = data, result.report
            backend_normalized = result.normalized
    if mode in (GenerationMode.STATIC, GenerationMode.DYNAMIC):
        data, issue = _load(work / FRONTEND_FILE)
        if issue is not None:
            check.reports["frontend"] = ValidationReport.from_issues([issue], None)
        else:
            result = validate_frontend_spec_data(data)
            report = result.report
            declared = (data.get("project") or {}).get("mode") if isinstance(data, dict) else None
            if declared in ("static", "dynamic") and declared != mode:  # first, before what the wrong mode causes
                mismatch = SpecIssue(
                    code="MODE_MISMATCH",
                    path="/project/mode",
                    message=f"The draft is for a '{mode}' site but the spec says '{declared}'",
                    hint=f'Set "project": {{"mode": "{mode}"}}',
                )
                report = ValidationReport.from_issues([mismatch, *report.errors, *report.warnings], report.spec_version)
            check.frontend_spec, check.reports["frontend"] = data, report
            frontend_normalized = result.normalized if report.valid else None
    if mode == GenerationMode.DYNAMIC and backend_normalized is not None and frontend_normalized is not None:
        issues = check_spec_pair(frontend_normalized, backend_normalized)
        check.reports["pair"] = ValidationReport.from_issues(issues, check.reports["frontend"].spec_version)
    return check


def read_notes(work: Path, mode: GenerationMode) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`notes.json` → (assumptions, unresolved) as `{path, message, suggestion?, spec?}`; tolerant of what the
    engine wrote (`reason` for `message`, missing paths), since notes are advisory."""
    data, issue = _load(work / NOTES_FILE)
    if issue is not None or not isinstance(data, dict):
        missing = {"path": "", "message": "The draft came without notes; review every part of it", "spec": None}
        return [missing], []
    default_spec = {GenerationMode.BACKEND: "backend", GenerationMode.STATIC: "frontend"}.get(mode)

    def notes(key: str) -> list[dict[str, Any]]:
        out = []
        for item in data.get(key) or []:
            if isinstance(item, str):
                item = {"message": item}
            if not isinstance(item, dict):
                continue
            message = item.get("message") or item.get("reason")
            if not isinstance(message, str) or not message.strip():
                continue
            spec = item.get("spec") if item.get("spec") in ("backend", "frontend") else default_spec
            suggestion = item.get("suggestion")
            out.append(
                {
                    "path": str(item.get("path") or ""),
                    "message": message.strip(),
                    "suggestion": suggestion if isinstance(suggestion, str) else None,
                    "spec": spec,
                }
            )
        return out

    return notes("assumptions"), notes("unresolved")


def draft_directions(draft: SpecDraftEntity) -> list[dict[str, Any]]:
    """The ranked design directions for a static or dynamic draft from a requirement (none otherwise)."""
    mode = GenerationMode(draft.mode)
    if mode == GenerationMode.BACKEND or draft.source != SpecSource.REQUIREMENT or not draft.requirement_text:
        return []
    return directions(draft.requirement_text)


def draft_seed(draft: SpecDraftEntity) -> int:
    """The draft's direction seed (Story 20.4): given with the draft (`inputs.designSeed`, e.g. by the diversity
    report or "another direction"), else a new one; kept in `design.seed`."""
    given = (draft.inputs or {}).get("designSeed")
    return given if isinstance(given, int) and 0 < given < MAX_SEED else new_seed()


def stock_warnings(check: DraftCheck) -> list[dict[str, Any]]:
    """Story 20.9: the frontend's stock-phrase warnings, as repair items."""
    report = check.reports.get("frontend")
    if report is None:
        return []
    return [
        {"file": FRONTEND_FILE, **issue.model_dump(mode="json", exclude={"severity"}, exclude_none=True)}
        for issue in report.warnings
        if issue.code == "FE_DESIGN_RULE" and "stock phrase" in issue.message
    ]


def _design_choice(work: Path) -> dict[str, Any]:
    notes, _ = _load(work / NOTES_FILE)
    return notes.get("design") if isinstance(notes, dict) and isinstance(notes.get("design"), dict) else {}


def _drafted_spec(work: Path) -> dict[str, Any] | None:
    spec, issue = _load(work / FRONTEND_FILE)
    return spec if issue is None and isinstance(spec, dict) and isinstance(spec.get("pages"), list) else None


RepairDirection = Callable[[int, list[str], list[dict[str, Any]]], Awaitable[None]]


async def settle_directions(
    work: Path, found: list[dict[str, Any]], seed: int, repair: RepairDirection | None = None
) -> dict[str, Any]:
    """The draft's three directions (Story 20.4): the engine's cards (`notes.json` `design.cards`) checked and filled,
    with the requirement's brand colours and fonts on top; cards that fail the difference test are asked again
    (`repair`, at most `DIRECTION_REPAIRS` rounds), then fixed by code. Without cards, the UI UX Pro Max directions
    (12.6) the engine named by product type. Returns what the draft keeps (`design`); the spec is not changed here
    (`finish_design` applies the selected direction once the spec is final)."""
    choice = _design_choice(work)
    brand = {"colors": choice.get("brandColors"), "fonts": choice.get("brandFonts")}
    spec = _drafted_spec(work)
    pool = home_pool(spec) if spec is not None else []
    required = [i for i in choice.get("required") or [] if isinstance(i, str)]
    default = found[0]["homeOrder"]
    fixed = brand_fixed(brand)
    cards, notes = read_cards(choice)
    kept, more = card_directions(cards, found, pool, required, seed, brand)
    notes += more
    if not cards:
        selected = pick(kept, choice.get("productType"))
        return design_record(kept, selected, seed, pool, required) | {"notes": notes}
    rounds = 0
    while repair is not None and rounds < DIRECTION_REPAIRS and problems(kept, default, pool, fixed):
        index = failing_card(kept, fixed, pool)
        if index is None or index >= len(cards):
            break
        rounds += 1
        await repair(index, problems(kept, default, pool, fixed), kept)
        choice = _design_choice(work)
        new_cards, _ = read_cards(choice)
        if len(new_cards) == len(cards):
            cards = new_cards
            kept, _ = card_directions(cards, found, pool, required, seed, brand)
    left = problems(kept, default, pool, fixed)
    if left:
        notes += code_fix(kept, default, pool, required, fixed)
    if rounds:
        notes.insert(0, f"Directions asked again {rounds} time(s) to differ from each other")
    return design_record(kept, best_fit(kept), seed, pool, required) | {"notes": notes}


def finish_design(work: Path, design: dict[str, Any]) -> None:
    """Applies the selected direction to the final spec (after repairs): the theme, its home page composed from the
    drafted home sections (kept on the draft as `pool`, so switching restores them), hero layout, forms, rhythm."""
    spec = _drafted_spec(work)
    if spec is None:
        return
    pool = home_pool(spec)
    ids = [section["id"] for section in pool]
    # A section a repair added that no direction has yet joins every home page at the end.
    unplaced = [i for i in ids if not any(i in (d.get("home") or []) for d in design["directions"])]
    for direction in design["directions"]:
        home = [i for i in direction.get("home") or [] if i in ids]
        direction["home"] = home + unplaced if home else ids
        direction["homeOrder"] = components(direction["home"], pool)
    design["pool"] = pool
    chosen = design["directions"][design["selected"]]
    _write_json(work / FRONTEND_FILE, apply_direction(spec, chosen, pool))


def hero_images(spec: dict[str, Any]) -> set[str]:
    """Asset ids the home page's hero shows."""
    hero = next((s for s in home_pool(spec) if s.get("component") == "Hero"), None)
    content = (hero or {}).get("content") or {}
    refs = [content.get("image"), content.get("backgroundImage"), *(content.get("images") or [])]
    return {ref.removeprefix("asset:") for ref in refs if isinstance(ref, str) and ref.startswith("asset:")}


def draw_images(work: Path, chosen: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Turns the drafted FrontendSpec's placeholder images into photos (when enabled and under cap) or drawings
    (prompt from the alt text, style from the design direction), up to MAX_GENERATED_ASSETS; returns assumptions."""
    spec, issue = _load(work / FRONTEND_FILE)
    if issue is not None or not isinstance(spec, dict) or not isinstance(spec.get("assets"), list):
        return []
    assets = [asset for asset in spec["assets"] if isinstance(asset, dict)]
    drawn = sum(source_kind(str(asset.get("source") or "placeholder")) == "generate" for asset in assets)
    photos_on = photos_enabled()
    max_photos = STOCK_PHOTO_LIMIT if get_stock_photos() is not None else config.frontend_max_photos
    photos_count = sum(
        1
        for a in assets
        if a.get("source") == "photo" or (str(a.get("source") or "").startswith("upload:") and bool(a.get("prompt")))
    )
    photo_style = (chosen or {}).get("photoStyle") or PHOTO_STYLES_BY_PRESET.get(
        (chosen or {}).get("theme", {}).get("style", "minimal"), PHOTO_STYLES_BY_PRESET["minimal"]
    )
    style = f"{chosen['style']}, flat vector shapes" if chosen and "style" in chosen else None
    # Story 20.4: a direction whose key visual is a drawing keeps the hero's images drawn, never photographed.
    drawn_hero = hero_images(spec) if (chosen or {}).get("keyVisual") in ("illustration", "pattern") else set()
    converted_photos: list[str] = []
    converted_drawings: list[str] = []
    skipped: list[str] = []
    for asset in assets:
        if source_kind(str(asset.get("source") or "placeholder")) != "placeholder":
            continue
        if not isinstance(asset.get("id"), str):
            continue
        kind = asset.get("kind") or "image"
        photo_kind = kind in ("image", "logo", "illustration") and asset["id"] not in drawn_hero
        if photos_on and photo_kind and photos_count < max_photos:
            asset["source"] = "photo"
            asset["prompt"] = asset.get("prompt") or asset.get("alt") or asset["id"].replace("-", " ")
            if photo_style and not asset.get("style"):
                asset["style"] = photo_style
            photos_count += 1
            converted_photos.append(asset["id"])
        elif drawn < MAX_GENERATED_ASSETS and kind in SVG_KINDS:
            asset["source"] = "generate"
            asset["prompt"] = asset.get("prompt") or asset.get("alt") or asset["id"].replace("-", " ")
            if style and not asset.get("style"):
                asset["style"] = style
            drawn += 1
            converted_drawings.append(asset["id"])
        else:
            skipped.append(asset["id"])
    if not converted_photos and not converted_drawings and not skipped:
        return []
    _write_json(work / FRONTEND_FILE, spec)
    notes = []
    if converted_photos:
        message = f"Real photos drafted from their alt text instead of placeholders: {', '.join(converted_photos)}"
        notes.append({"spec": "frontend", "path": "/assets", "message": message, "suggestion": None})
    if converted_drawings:
        message = f"Drawn from their alt text instead of placeholders: {', '.join(converted_drawings)}"
        notes.append({"spec": "frontend", "path": "/assets", "message": message, "suggestion": None})
    if skipped:
        message = (
            f"Left as placeholders (at most {max_photos} photos, {MAX_GENERATED_ASSETS} drawings per site): "
            f"{', '.join(skipped)}; upload an image for them"
        )
        notes.append({"spec": "frontend", "path": "/assets", "message": message, "suggestion": None})
    return notes


def autofix_draft(work: Path) -> list[dict[str, Any]]:
    """Applies deterministic spec fixes (Story 18.3) to FRONTEND_FILE before validation; returns assumption notes."""
    spec, issue = _load(work / FRONTEND_FILE)
    if issue is not None or not isinstance(spec, dict) or not isinstance(spec.get("pages"), list):
        return []
    fixed_spec, notes = autofix_frontend_spec(spec)
    _write_json(work / FRONTEND_FILE, fixed_spec)
    return notes


# -- usage ---------------------------------------------------------------------------------------------------------


def usage_record(result: EngineResult, prompt: RenderedPrompt) -> dict[str, Any]:
    usage = result.usage
    return {
        "purpose": result.purpose,
        "engine": result.engine,
        "prompt": f"{prompt.ref.id}@{prompt.ref.version}",
        "promptSha256": prompt.ref.sha256,
        "status": str(result.status),
        "durationMs": result.duration_ms,
        "turns": result.turns,
        "model": (usage.model if usage else None) or next((c.model for c in result.model_calls if c.model), None),
        "inputTokens": (usage.input_tokens if usage else None) or 0,
        "outputTokens": (usage.output_tokens if usage else None) or 0,
        "cacheReadTokens": (usage.cache_read_tokens if usage else None) or 0,
        "cacheWriteTokens": (usage.cache_write_tokens if usage else None) or 0,
        "costUsd": usage.cost_usd if usage else None,
        "costSource": usage.cost_source if usage else None,
        "modelCalls": len(result.model_calls),
        **({"structured": result.structured} if result.structured is not None else {}),
    }


def usage_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    priced = [call["costUsd"] for call in calls if call["costUsd"] is not None]
    return {
        "calls": calls,
        "engineMs": sum(call["durationMs"] or 0 for call in calls),
        "modelCalls": sum(call["modelCalls"] for call in calls),
        "inputTokens": sum(call["inputTokens"] for call in calls),
        "outputTokens": sum(call["outputTokens"] for call in calls),
        "costUsd": round(sum(priced), 6),
        "unpriced": len(calls) - len(priced),
    }


# -- runner --------------------------------------------------------------------------------------------------------


class DraftCancelled(Exception):
    """Raised when a draft is cancelled while running."""


class DraftRunner:
    def __init__(
        self,
        registry: EngineRegistry,
        prompts: PromptLibrary,
        store: JobStore,
        workspace_root: Path,
        worker_id: str,
        examples_dir: Path | None = None,
        heartbeat_s: float | None = None,
        queue: Any | None = None,
        events: Any | None = None,
        redis: Any | None = None,
        llm_provider: Any | None = None,
    ):
        self.registry = registry
        # Epic 26: the provider of the business steps; None: the draft's own (`drafting/business.draft_provider`)
        self.llm_provider = llm_provider
        self.prompts = prompts
        self.store = store
        self.root = workspace_root / "drafts"
        self.worker_id = worker_id
        self.examples_dir = examples_dir or Path(config.examples_dir)
        self.heartbeat_s = heartbeat_s if heartbeat_s is not None else config.worker_heartbeat_seconds
        self.queue = queue
        self.events = events
        self.redis = redis

    async def _is_cancelled(self, draft: SpecDraftEntity) -> bool:
        if self.redis is not None:
            try:
                flag = await self.redis.get(f"bga:cancel:draft:{draft.id}")
                if flag:
                    return True
            except Exception:
                pass
        curr_draft = self.store.draft(draft.id)
        if curr_draft is not None and curr_draft.status == SpecDraftStatus.CANCELLED:
            return True
        if draft.generation_id:
            gen = self.store.generation(draft.generation_id)
            if gen is not None and (gen.status == GenerationStatus.CANCELLED or gen.cancel_requested):
                return True
        return False

    async def _chain_generation(self, draft: SpecDraftEntity, errors: list[dict[str, Any]] | None = None) -> None:
        if not draft.generation_id:
            return
        latest = self.store.draft(draft.id)
        if latest is None:
            return
        if latest.status == SpecDraftStatus.SUCCEEDED:
            # Conditional: a cancel committed while drafting / attaching wins, and the generation is not started.
            generation = self.store.start_draft_generation(draft.generation_id, latest)
            if generation is None:
                logger.info("generation left DRAFTING; not starting it", extra={"generation_id": draft.generation_id})
                return
            # The generation's own engine, not the draft's: drafts may run on a drafts-only engine (Story 18.10).
            if self.events is not None:
                await self.events.publish(
                    draft.generation_id,
                    "status.changed",
                    status=GenerationStatus.PENDING,
                    payload={"engine": generation.engine, "mode": latest.mode, "lanes": initial_lanes(latest.mode)},
                )
            if self.queue is not None:
                await self.queue.enqueue(draft.generation_id, generation.engine)
        elif latest.status == SpecDraftStatus.NEEDS_REVIEW:
            moved = self.store.update_generation_if_status(
                draft.generation_id, GenerationStatus.DRAFTING, status=GenerationStatus.NEEDS_REVIEW
            )
            if moved is not None and self.events is not None:
                await self.events.publish(
                    draft.generation_id,
                    "status.changed",
                    status=GenerationStatus.NEEDS_REVIEW,
                    payload={"errors": errors or (latest.validation or {}).get("errors", [])},
                )

    async def run(self, draft_id: str) -> None:
        try:
            draft = self.store.claim_draft(uuid.UUID(draft_id), self.worker_id)
        except ValueError:
            logger.warning("ignoring a malformed draft id", extra={"draft_id": draft_id})
            return
        if draft is None:
            return  # finished, or taken by another worker
        if await self._is_cancelled(draft):
            return
        heartbeat = asyncio.create_task(self._heartbeat(draft.id))
        directory = self.root / str(draft.id)
        try:
            await self._run(draft, directory)
            if not await self._is_cancelled(draft):
                await self._chain_generation(draft)
        except DraftCancelled:
            self.store.update_draft(
                draft.id,
                status=SpecDraftStatus.CANCELLED,
                error="Cancelled",
                progress=None,
                finished_at=datetime.now(UTC),
            )
            if draft.generation_id:
                self.store.update_generation(
                    draft.generation_id,
                    status=GenerationStatus.CANCELLED,
                    finished_at=datetime.now(UTC),
                )
        except asyncio.CancelledError:
            raise  # shutdown: the reaper fails the draft once its heartbeat stops
        except Exception as exc:
            message = str(exc) if isinstance(exc, DraftFailed) else f"{type(exc).__name__}: {exc}{crash_site(exc)}"
            if not isinstance(exc, DraftFailed):
                logger.exception("draft failed", extra={"draft_id": str(draft.id)})
            self.store.update_draft(
                draft.id,
                status=SpecDraftStatus.FAILED,
                error=message[:2000],
                progress=None,
                finished_at=datetime.now(UTC),
            )
            if draft.generation_id:
                self.store.update_generation(
                    draft.generation_id,
                    status=GenerationStatus.FAILED,
                    error_summary=f"DRAFT_FAILED: {message}",
                    finished_at=datetime.now(UTC),
                )
                if self.events is not None:
                    await self.events.publish(
                        draft.generation_id,
                        "status.changed",
                        status=GenerationStatus.FAILED,
                        payload={"code": "DRAFT_FAILED", "error": message},
                    )
        finally:
            heartbeat.cancel()
            shutil.rmtree(directory, ignore_errors=True)

    async def _heartbeat(self, draft_id: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_s)
            try:
                self.store.update_draft(draft_id)  # bumps updated_at
            except Exception as exc:
                logger.warning("draft heartbeat failed", extra={"draft_id": str(draft_id), "error": str(exc)})

    async def _run(self, draft: SpecDraftEntity, directory: Path) -> None:
        try:
            engine = self.registry.get(draft.engine)
        except LookupError as exc:
            raise DraftFailed(str(exc)) from exc
        mode = GenerationMode(draft.mode)
        shutil.rmtree(directory, ignore_errors=True)
        work, state = directory / "work", directory / "state"
        work.mkdir(parents=True)
        state.mkdir(parents=True)
        found = draft_directions(draft)
        seed = draft_seed(draft) if found else None
        app = app_flow(draft)  # Epic 22: the dynamic app flow; the direction gives only the theme, without cards
        context = write_inputs(work, draft, self.examples_dir, None if app else found, seed, app=app)
        inline = engine.inline_inputs  # Story 18.10: an API engine reads no files
        context["inline"] = inline
        if inline:
            context |= inline_inputs(work, context)
        frontend = mode != GenerationMode.BACKEND
        purpose, version = ("draft_frontend_spec", "v11") if frontend else ("draft_spec", "v5")
        max_repairs = config.draft_repair_attempts_frontend if frontend else config.draft_repair_attempts_backend
        calls: list[dict[str, Any]] = []
        trace = tracing.GenerationTrace.open(
            str(draft.id),
            trace_id=None,
            parent=None,
            inputs={"mode": str(mode), "source": str(draft.source), "engine": engine.name},
            metadata={"draft_id": str(draft.id), "engine": engine.name, "mode": str(mode)},
            tags=["spec-draft", f"mode:{mode}", f"engine:{engine.name}"],
            name="spec-draft",
        )

        async def update_progress(prog: str, attempts_count: int | None = None) -> None:
            fields: dict[str, Any] = {"progress": prog}
            if attempts_count is not None:
                fields["attempts"] = attempts_count
            self.store.update_draft(draft.id, **fields)
            if draft.generation_id and self.events is not None:
                await self.events.publish(
                    draft.generation_id,
                    "draft.progress",
                    payload={"progress": prog, "attempts": attempts_count or 0},
                )

        fast_model = draft_model(draft, engine.name)

        async def call(
            step: str, prompt: RenderedPrompt, response_schema: dict[str, Any] | None = None
        ) -> EngineResult:
            if await self._is_cancelled(draft):
                raise DraftCancelled("Draft cancelled")
            await engine.prepare_workspace(work, EngineContext(conventions=self.prompts.draft_conventions()))
            span = trace.root.child(
                f"engine:{engine.name}",
                "tool",
                inputs={"purpose": prompt.ref.id, "prompt": f"{prompt.ref.id}@{prompt.ref.version}"},
                metadata={"engine": engine.name, "purpose": prompt.ref.id},
            )
            request = EngineRequest(
                purpose=prompt.ref.id,
                workdir=work,
                state_dir=state,
                prompt=prompt.text,
                prompt_ref=prompt.ref,
                response_schema=response_schema,
                model=fast_model,  # a fast draft (draftSpeed / DRAFT_SPEED); None: the engine's own model
            )
            try:
                result = await engine.run(request)
            except BaseException as exc:
                span.end(error=f"{type(exc).__name__}: {exc}"[:500])
                raise
            if await self._is_cancelled(draft):
                raise DraftCancelled("Draft cancelled")
            record = usage_record(result, prompt)
            calls.append(record)
            span.end(
                outputs={"step": step, **record},
                error=None if result.ok else f"{result.status}: {result.error_message or result.error_reason}",
            )
            self.store.update_draft(draft.id, usage=usage_summary(calls))
            return result

        if app:
            # Epic 26: the business workflows before the draft (the brief) and bound to it after
            provider = (self.llm_provider or draft_provider(draft, engine.name)) if business_on(draft) else None
            business = DraftBusiness(provider, self.prompts, state, fast_model) if provider is not None else None
            app_context = context
            if business is not None:
                await update_progress("discovering workflows")
                described = await business.before(draft.requirement_text or "")
                calls.extend(business.calls)
                self.store.update_draft(draft.id, usage=usage_summary(calls))
                if described:
                    app_context = {**context, "requirement_text": described}
            try:
                outcome = await draft_app(
                    work,
                    context=app_context,
                    prompts=self.prompts,
                    call=call,
                    progress=update_progress,
                    check_draft=check_draft,
                    chosen=found[0] if found else None,
                    backend_file=BACKEND_FILE,
                    frontend_file=FRONTEND_FILE,
                )
            except BaseException as exc:
                trace.close({"status": "failed"}, error=f"{type(exc).__name__}: {exc}"[:500])
                raise
            check = outcome.check
            if check.backend_spec is None:
                trace.close({"status": "failed"}, error="no spec written")
                report = check.reports.get("backend")
                why = report.errors[0].message if report is not None and report.errors else "The engine wrote no spec"
                raise DraftFailed(outcome.error or f"{why} (after {outcome.attempts} repair(s))")
            assumptions, unresolved = (outline_notes(notes) for notes in read_notes(work, mode))
            if found:  # the direction's theme only: its first note says where it came from
                assumptions += design_notes(found[0])[:1]
            notes = assumptions + outcome.notes
            stock = get_stock_photos() if check.ok else None
            if stock is not None:  # Epic 27: the seeded records' photos from Unsplash, credited in the app
                raw_backend, _ = _load(work / BACKEND_FILE)
                raw_frontend, _ = _load(work / FRONTEND_FILE)
                if isinstance(raw_backend, dict) and isinstance(raw_frontend, dict):
                    await update_progress("photos")
                    # FRONTEND_MAX_PHOTOS caps paid photos; stock photos are bounded by the hour's requests (2026-11-09)
                    photo_assets, stock_notes = await stock_seed_photos(raw_backend, stock, STOCK_PHOTO_LIMIT)
                    if photo_assets:
                        raw_frontend["assets"] = [*(raw_frontend.get("assets") or []), *photo_assets]
                        _write_json(work / BACKEND_FILE, raw_backend)
                        _write_json(work / FRONTEND_FILE, raw_frontend)
                        check = check_draft(work, mode)
                    notes += stock_notes
            if check.ok and videos_enabled():  # Epic 31 (Story 31.4): the seeded records' videos, credited in the app
                raw_backend, _ = _load(work / BACKEND_FILE)
                raw_frontend, _ = _load(work / FRONTEND_FILE)
                if isinstance(raw_backend, dict) and isinstance(raw_frontend, dict):
                    await update_progress("videos")
                    language = str((raw_frontend.get("project") or {}).get("locale") or "en")[:2]
                    video_assets, video_notes = await stock_seed_videos(
                        raw_backend, VideoSearch(providers_for, language)
                    )
                    if video_assets:
                        raw_frontend["assets"] = [*(raw_frontend.get("assets") or []), *video_assets]
                        _write_json(work / BACKEND_FILE, raw_backend)
                        _write_json(work / FRONTEND_FILE, raw_frontend)
                        check = check_draft(work, mode)
                    notes += video_notes
            if business is not None:
                before = len(business.calls)
                await update_progress("binding workflows")
                await business.after(check.backend_spec, check.frontend_spec)
                calls.extend(business.calls[before:])
                notes += business.notes()
                self.store.update_draft(draft.id, business=business.data)
            await self._save(draft, check, notes, unresolved + outcome.unresolved, None, calls, outcome.error, trace)
            return

        error: str | None = None
        try:
            await update_progress("drafting")
            result = await call("draft", self.prompts.render(purpose, version, **context))
            if result.status != EngineStatus.OK:
                raise DraftFailed(f"The {engine.name} engine stopped: {result.error_message or result.status}")
            design = None
            if found and seed is not None:
                await update_progress("directions")

                async def repair_direction(index: int, found_problems: list[str], kept: list[dict[str, Any]]) -> None:
                    others = [
                        {"card": k + 1, "name": d["name"], **direction_fields(d)}
                        for k, d in enumerate(kept)
                        if k != index
                    ]
                    extra: dict[str, Any] = {}
                    if inline:
                        notes_doc, _ = _load(work / NOTES_FILE)
                        cards = (notes_doc.get("design") or {}).get("cards") if isinstance(notes_doc, dict) else None
                        card_doc = cards[index] if isinstance(cards, list) and index < len(cards) else {}
                        extra = {
                            "card_json": json.dumps(card_doc, indent=2, ensure_ascii=False),
                            "design": context.get("design", ""),
                        }
                    prompt = self.prompts.render(
                        "repair_direction",
                        "v2",
                        notes_path=NOTES_FILE,
                        design_path=context["design_path"],
                        card=index + 1,
                        problems=found_problems,
                        others=others,
                        inline=inline,
                        **extra,
                    )
                    await call("repair_direction", prompt)

                design = await settle_directions(work, found, seed, repair_direction)
            chosen = design["directions"][design["selected"]] if design else None
            autofix_notes = autofix_draft(work) if frontend else []
            image_notes = draw_images(work, chosen) if frontend else []
            await update_progress("validating")
            check = check_draft(work, mode)
            attempts = 0
            stock_round = False
            last_signature: list[tuple[str, str, str]] | None = None
            while attempts < max_repairs:
                stock = stock_warnings(check) if frontend and check.ok and not stock_round else []
                if check.ok and not stock:
                    break
                # Story 20.9: one round for stock phrases once the spec is valid; errors use the usual budget.
                stock_round = stock_round or bool(stock)
                attempts += 0 if stock else 1
                label = "copy" if stock else f"{attempts}/{max_repairs}"
                await update_progress(f"repairing ({label})", attempts_count=attempts)
                errors = stock or check.repair_errors()
                signature = sorted((e["code"], e["path"], e["message"]) for e in errors)
                if signature == last_signature:
                    # Story 18.10: the same errors after a round: another round would buy the same answer; stop (a
                    # generator-side problem the engine cannot fix, or an engine that gave up).
                    error = f"Repair {attempts - 1} changed nothing: the same {len(errors)} error(s) remain"
                    break
                last_signature = signature
                files = sorted(
                    {error["file"] for error in errors} | {e["backendFile"] for e in errors if "backendFile" in e}
                )
                documents = spec_documents(work, files) if inline else {}
                prompt = self.prompts.render(
                    "repair_spec", "v3", files=files, errors=errors, inline=inline, documents=documents
                )
                result = await call("repair", prompt)
                if result.status != EngineStatus.OK:
                    check = check_draft(work, mode)
                    if not check.ok:
                        error = f"Repair {attempts} stopped: {result.error_message or result.status}"
                        break
                if frontend:
                    autofix_notes += autofix_draft(work)
                check = check_draft(work, mode)
            if design is not None:
                finish_design(work, design)
                check = check_draft(work, mode)
            if check.ok and frontend and config.frontend_trees:
                # Epic 21: design each page as an element tree, one engine call per page (in parallel on an API
                # engine); the chrome too. The tree rules repair what they can; a page whose tree still fails keeps
                # its sections.
                await update_progress("designing pages")
                spec_now, _ = _load(work / FRONTEND_FILE)
                requests = tree_drafting.tree_requests(spec_now) if isinstance(spec_now, dict) else []
                (work / tree_drafting.TREES_DIR).mkdir(exist_ok=True)

                async def design_page(request: dict[str, Any]) -> None:
                    _write_json(work / INPUTS / f"tree-{request['id']}.json", request)  # the fake engine reads it
                    context_page = tree_drafting.prompt_context(spec_now, request, inline)
                    await call(f"tree:{request['id']}", self.prompts.render("draft_tree", "v1", **context_page))

                if inline:
                    limit = asyncio.Semaphore(config.frontend_tree_concurrency)

                    async def bounded(request: dict[str, Any]) -> None:
                        async with limit:
                            await design_page(request)

                    await asyncio.gather(*(bounded(request) for request in requests))
                else:
                    for request in requests:
                        await design_page(request)
                tree_notes = tree_drafting.apply_tree_files(work, work / FRONTEND_FILE)
                check = check_draft(work, mode)
                if not check.ok:  # the designed pages must not cost the draft: back to the section pages
                    tree_notes.append(
                        {
                            "spec": "frontend",
                            "path": "/pages",
                            "message": "Designed pages dropped: the draft no longer validated with them",
                            "suggestion": None,
                        }
                    )
                    spec_plain = {
                        **spec_now,
                        "pages": [{k: v for k, v in p.items() if k not in ("tree", "css")} for p in spec_now["pages"]],
                    }
                    spec_plain["layout"] = {
                        k: v for k, v in (spec_now.get("layout") or {}).items() if k not in ("chrome", "footerTree")
                    }
                    _write_json(work / FRONTEND_FILE, spec_plain)
                    check = check_draft(work, mode)
                autofix_notes += tree_notes
        except BaseException as exc:
            trace.close({"status": "failed"}, error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        if check.backend_spec is None and check.frontend_spec is None:
            trace.close({"status": "failed"}, error="no spec written")
            raise DraftFailed(error or "The engine wrote no spec")
        photo_notes: list[dict[str, Any]] = []
        if check.ok and frontend and photos_enabled():
            if await self._is_cancelled(draft):
                raise DraftCancelled("Draft cancelled")
            spec, issue = _load(work / FRONTEND_FILE)
            if issue is None and isinstance(spec, dict) and isinstance(spec.get("assets"), list):
                photo_assets = [a for a in spec["assets"] if isinstance(a, dict) and a.get("source") == "photo"]
                # Hard cap on paid calls per draft: photos past FRONTEND_MAX_PHOTOS stay `photo` (a placeholder).
                # Stock photos (Epic 27) are bounded by the hour's requests and the cache instead (2026-11-09).
                cap = STOCK_PHOTO_LIMIT if get_stock_photos() is not None else config.frontend_max_photos
                over_cap = photo_assets[cap:]
                photo_assets = photo_assets[:cap]
                if over_cap:
                    ids = ", ".join(str(a.get("id")) for a in over_cap)
                    msg = (
                        f"Not made (at most {config.frontend_max_photos} photos per draft): {ids}; "
                        "they show as placeholders, upload an image for them"
                    )
                    photo_notes.append({"spec": "frontend", "path": "/assets", "message": msg, "suggestion": None})
                stock = get_stock_photos()
                if photo_assets and stock is not None:  # Epic 27: found on Unsplash, hotlinked and credited
                    await update_progress("photos")
                    photo_notes += await stock_site_photos(photo_assets, stock)
                    _write_json(work / FRONTEND_FILE, spec)
                    check = check_draft(work, mode)
                    photo_assets = []
                searched = [a for a in spec["assets"] if isinstance(a, dict) and a.get("source") == "search"]
                if searched:  # Epic 31 (Story 31.3): videos found at draft time, embedded or hotlinked, credited
                    await update_progress("videos")
                    language = str((spec.get("project") or {}).get("locale") or "en")[:2]
                    photo_notes += await stock_site_videos(searched, VideoSearch(providers_for, language), posters={})
                    _write_json(work / FRONTEND_FILE, spec)
                    check = check_draft(work, mode)
                if photo_assets:
                    await update_progress("photos")
                    semaphore = asyncio.Semaphore(config.image_concurrency)
                    generator = get_image_generator()

                    async def make_photo(
                        asset: dict[str, Any],
                    ) -> tuple[dict[str, Any], bool, ImageCallEntity, str | None]:
                        target_path = work / f"photo_{asset['id']}.webp"
                        success, record, reason = await generate_single_photo(
                            asset,
                            target_path,
                            generator=generator,
                            draft_id=draft.id,
                            semaphore=semaphore,
                        )
                        return asset, success, record, reason

                    results = await asyncio.gather(*(make_photo(a) for a in photo_assets))
                    records = []
                    for asset, success, record, reason in results:
                        records.append(record)
                        if success:
                            webp_file = work / f"photo_{asset['id']}.webp"
                            webp_bytes = webp_file.read_bytes()
                            sha256 = hashlib.sha256(webp_bytes).hexdigest()
                            existing = self.store.upload_by_sha256(draft.owner_id, sha256)
                            if existing is not None:
                                upload_id = existing.id
                            else:
                                with Image.open(io.BytesIO(webp_bytes)) as im:
                                    width, height = im.size
                                upload = UploadEntity(
                                    id=new_upload_id(),
                                    owner_id=draft.owner_id,
                                    filename=f"{asset['id']}.webp",
                                    mime="image/webp",
                                    bytes=len(webp_bytes),
                                    width=width,
                                    height=height,
                                    sha256=sha256,
                                    origin="photo",
                                    prompt=asset.get("prompt"),
                                )
                                target_file = Path(uploads_dir()) / upload.relative_path
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                target_file.write_bytes(webp_bytes)
                                self.store.create_upload(upload)
                                upload_id = upload.id
                            asset["source"] = f"upload:{upload_id}"
                        else:
                            msg = (
                                f"Photo for '{asset['id']}' could not be generated "
                                f"({reason or 'failed'}); it shows as a placeholder, upload an image for it"
                            )
                            photo_notes.append(
                                {
                                    "spec": "frontend",
                                    "path": f"/assets/{asset['id']}",
                                    "message": msg,
                                    "suggestion": None,
                                }
                            )
                    self.store.add_image_calls(records)
                    _write_json(work / FRONTEND_FILE, spec)
                    check = check_draft(work, mode)
        assumptions, unresolved = read_notes(work, mode)
        if design is not None:
            assumptions += design_notes(design["directions"][design["selected"]], design.pop("notes", []))
        assumptions += image_notes
        assumptions += autofix_notes
        assumptions += photo_notes
        await self._save(draft, check, assumptions, unresolved, design, calls, error, trace)

    async def _save(
        self,
        draft: SpecDraftEntity,
        check: DraftCheck,
        assumptions: list[dict[str, Any]],
        unresolved: list[dict[str, Any]],
        design: dict[str, Any] | None,
        calls: list[dict[str, Any]],
        error: str | None,
        trace: Any,
    ) -> None:
        status = SpecDraftStatus.SUCCEEDED if check.ok else SpecDraftStatus.NEEDS_REVIEW
        usage = usage_summary(calls)
        image_calls_records = self.store.draft_image_calls(draft.id)
        if image_calls_records:
            img_count = len(image_calls_records)
            img_cached = sum(1 for c in image_calls_records if c.status == "cached")
            img_cost = round(sum(c.cost_usd for c in image_calls_records if c.cost_usd is not None), 6)
            usage["images"] = {"count": img_count, "cached": img_cached, "costUsd": img_cost}
            if img_cost > 0:
                usage["costUsd"] = round((usage.get("costUsd") or 0.0) + img_cost, 6)
        self.store.update_draft(
            draft.id,
            status=status,
            progress=None,
            backend_spec=check.backend_spec,
            frontend_spec=check.frontend_spec,
            assumptions=assumptions,
            unresolved=unresolved,
            design=design,
            validation=check.validation(),
            usage=usage,
            error=error,
            finished_at=datetime.now(UTC),
        )
        trace.close({"status": str(status), "repairs": len(calls) - 1})
        await tracing.GenerationTrace.flush()
