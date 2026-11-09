"""Drafting a dynamic app (Epic 22, decision D1): the app flow, apart from the static sites' flow.

The model drafts what the app is (the BackendSpec and the app outline, `draft_app@v2`); code writes the rest: the
theme from the code-picked design direction (no model call), and the FrontendSpec's pages from the outline and the
contract. No direction cards, no designed pages, no Manage area. Every dynamic draft comes here (Story 22.8 removed the
legacy dynamic flow); static sites keep their own flow in `drafts.py`.
"""

import copy
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.configs import config
from src.engines.port import EngineResult, EngineStatus
from src.engines.prompts import PromptLibrary
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.backend_spec.media import PLAYABLE
from src.modules.shared.domain.entities import SpecDraftEntity
from src.modules.shared.domain.enums import GenerationMode
from src.modules.shared.domain.frontend_spec.app import outline_schema
from src.modules.shared.domain.schema_digest import schema_digest

from ..backend.planner import build_plan
from ..frontend.app.design import archetype_candidates, archetype_for, design_notes
from ..frontend.app.outline import complete_outline, humanize
from ..frontend.app.recipes import complete_looks, recommended_looks, style_words
from ..frontend.app.requested import follow_requested
from ..frontend.app.screens import app_frontend_spec, ensure_aggregates, without_references
from ..frontend.app.typesetting import locale_of
from ..integration.contract import build_contract
from .access import secure_access
from .answer_schema import app_answer_schema

# v6 (Epic 29): the media field types; v5: the requirement's own look (`design.requested`); v4 (Epic 25): the access
# rules; v3 (Story 23.6): the design brief and areas; v2 (22.8): sign-in, roles, plugins
PROMPT = ("draft_app", "v6")
OUTLINE_FILE = "app-outline.json"  # what the model drafts next to the BackendSpec (code folds it into the FrontendSpec)
# Outline examples shown in the prompt, relative to EXAMPLES_DIR; they fit `specs/flashcards.json`,
# `specs/two-entity.json` and `specs/workshop-bookings.json` (the fake engine drafts from them too).
OUTLINE_EXAMPLES = {
    "Flashcards (decks of cards reviewed with spaced repetition)": "app-outlines/flashcards.json",
    "Project tracker (projects and their tasks)": "app-outlines/project-tracker.json",
    "Workshop bookings (sign-in, roles, own bookings, a status flow, seats, a cover image, payment, tags)": (
        "app-outlines/workshop-bookings.json"
    ),
}
# Story 23.6: outlines with a design brief (real drafts of Story 23.0), shown by `draft_app@v3` after the others.
DESIGN_EXAMPLES = {
    "DevPulse, a news feed for developers (a feed home, posts as a feed, a top bar)": "app-outlines/news-feed.json",
    "Gather, event ticketing (attendees browse a catalogue, organizers run a back office: two areas)": (
        "app-outlines/event-tickets.json"
    ),
}
# The BackendSpec example of an app draft (Story 22.8): one that uses every plugin, so the model sees how sign-in,
# roles, ownership, rules, uploads, payments and links are written (`specs/shop.json` has none of them).
BACKEND_EXAMPLE = "specs/workshop-bookings.json"

Call = Callable[..., Awaitable[EngineResult]]  # (step, prompt, response_schema=None)
Progress = Callable[..., Awaitable[None]]


def app_flow(draft: SpecDraftEntity) -> bool:
    """A dynamic draft (always from a requirement: a draft from an imported site is a backend draft)."""
    return GenerationMode(draft.mode) == GenerationMode.DYNAMIC


@dataclass
class AppDraft:
    """What the app flow hands back to the draft runner: the last check, notes and the error that stopped it."""

    check: Any
    notes: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)  # operations the screens could not place
    error: str | None = None
    attempts: int = 0  # repair rounds


def app_inputs(examples_dir: Path, design: bool = False) -> dict[str, Any]:
    """The prompt context the app flow adds to the BackendSpec inputs: the outline's schema digest, its examples and
    the file to write. All text, so file and inline engines read the same."""
    examples = []
    for title, name in (OUTLINE_EXAMPLES | DESIGN_EXAMPLES if design else OUTLINE_EXAMPLES).items():
        source = examples_dir / name
        if source.is_file():
            examples.append({"title": title, "json": json.dumps(json.loads(source.read_text()), ensure_ascii=False)})
    digest = schema_digest(outline_schema(design), "AppOutline").split("\n", 2)[-1].strip()
    return {"output_app_path": OUTLINE_FILE, "outline_digest": digest, "outline_examples": examples}


def outline_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The model's notes on the outline point into `app-outline.json`; in the FrontendSpec it is `/app`."""
    out = []
    for note in notes:
        path = note.get("path") or ""
        if note.get("spec") == "frontend" and not path.startswith("/app"):
            note = {**note, "path": f"/app{path}" if path.startswith("/") or not path else f"/app/{path}"}
        out.append(note)
    return out


# What models write for "the current date or time"; the BackendSpec's word for it is `now` (seen live: `today`).
NOW_WORDS = frozenset({"today", "current_date", "current_timestamp", "now()", "current_time", "datetime.now"})


# Rule params and operation fields that name fields: a list, which models sometimes write as one string (seen live,
# Story 22.8: `"scope": "pitchId"`, which the validator then read letter by letter).
RULE_LISTS = {"noOverlap": ("scope",), "uniqueTogether": ("fields",), "immutableAfter": ("states",)}
OPERATION_LISTS = ("filters", "sort", "search", "rules")
# Epic 29 (Story 29.5): a `file` field that is really a media file, by its accepted types or its name
MEDIA_WORDS = {
    "video": ("video", "clip", "trailer", "movie", "film", "footage"),
    "audio": ("audio", "recording", "podcast", "episode", "sound", "voice"),
    "subtitles": ("subtitles", "subtitle", "captions", "caption", "transcript"),
}


def apply_access_rules(work: Path, backend_file: str) -> list[dict[str, Any]]:
    """Epic 25 (`drafting/access.py`): records tied to a person private, actions guarded by their role, a status with
    a flow changed only by its actions, records staff create for someone owned by that someone. Applied only when the
    BackendSpec stays valid; else the draft keeps its own policies, with a note saying why."""
    data = _load(work / backend_file)
    if not isinstance(data, dict):
        return []
    secured = copy.deepcopy(data)
    notes = secure_access(secured)
    if not notes:
        return []
    report = validate_spec_data(secured).report
    if not report.valid:
        first = report.errors[0].message if report.errors else "invalid"
        message = f"The access rules were left out: they would make the BackendSpec invalid ({first})"
        return [{"spec": "backend", "path": "/policies", "message": message, "suggestion": None}]
    (work / backend_file).write_text(json.dumps(secured, indent=2, ensure_ascii=False) + "\n")
    return notes


def fix_backend_defaults(work: Path, backend_file: str) -> list[dict[str, Any]]:
    """Code fixes to the drafted BackendSpec that need no model call (Stories 22.2, 22.8), each with a note:
    - a date or datetime default of the current time written another way becomes `now`;
    - a field list written as one string (a rule's `scope` / `fields` / `states`, an operation's `filters` / `sort` /
      `search` / `rules`) becomes a list of that one name;
    - an entity without a primary key gets `id` (uuid), as every example has;
    - a custom operation of an entity that names no response gets the entity's: `GET …/{id}` the record, another
      `GET` a list of records, an action on a record (`POST /…/{id}/…`) the record it changed. Without it the
      contract has no type for the answer, the backend answers `{"ok": true}` and the screens show "Ok: Yes"
      (a real HomeFix draft: the contractor's job list)."""
    data = _load(work / backend_file)
    if not isinstance(data, dict):
        return []
    notes: list[dict[str, Any]] = []

    def note(path: str, message: str) -> None:
        notes.append({"spec": "backend", "path": path, "message": message, "suggestion": None})

    for e_index, entity in enumerate(data.get("entities") or []):
        if not isinstance(entity, dict):
            continue
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        for f_index, item in enumerate(fields):
            default = item.get("default") if isinstance(item, dict) else None
            if item.get("type") in ("date", "datetime") and isinstance(default, str):
                if default.strip().lower() in NOW_WORDS:
                    item["default"] = "now"
                    message = f"{entity.get('name')}.{item.get('name')}: default '{default}' is written 'now'"
                    note(f"/entities/{e_index}/fields/{f_index}/default", message)
        if isinstance(entity.get("fields"), list) and not any(
            isinstance(item, dict) and item.get("primary") for item in fields
        ):
            named_id = next((item for item in fields if isinstance(item, dict) and item.get("name") == "id"), None)
            if named_id is not None:
                named_id["primary"] = True
            else:
                fields.insert(0, {"name": "id", "type": "uuid", "primary": True})
            note(f"/entities/{e_index}/fields", f"{entity.get('name')} had no primary key: 'id' is its key")
    for r_index, rule in enumerate(data.get("rules") or []):
        params = rule.get("params") if isinstance(rule, dict) else None
        for key in RULE_LISTS.get(rule.get("kind") if isinstance(rule, dict) else "", ()):
            if isinstance(params, dict) and isinstance(params.get(key), str):
                params[key] = [params[key]]
                note(f"/rules/{r_index}/params/{key}", f"Rule '{rule.get('id')}': '{key}' is a list of names")
    for o_index, operation in enumerate(data.get("operations") or []):
        for key in OPERATION_LISTS:
            if isinstance(operation, dict) and isinstance(operation.get(key), str):
                operation[key] = [operation[key]]
                note(f"/operations/{o_index}/{key}", f"{operation.get('operationId')}: '{key}' is a list of names")
    notes += fix_media_fields(data)
    entities = {e.get("name") for e in data.get("entities") or [] if isinstance(e, dict)}
    for o_index, operation in enumerate(data.get("operations") or []):
        if not isinstance(operation, dict) or operation.get("type") != "custom" or operation.get("response"):
            continue
        entity, method = operation.get("entity"), str(operation.get("method") or "").upper()
        path = str(operation.get("path") or "")
        if entity not in entities:
            continue
        if method == "GET":
            response = {"entity": entity} if path.rstrip("/").endswith("}") else {"entity": entity, "type": "array"}
        elif method in ("POST", "PATCH", "PUT") and "{" in path:
            response = {"entity": entity}
        else:
            continue
        operation["response"] = response
        kind = "a list of " + entity if response.get("type") == "array" else "the " + entity
        note(f"/operations/{o_index}/response", f"{operation.get('operationId')}: it answers {kind}")
    if notes:
        (work / backend_file).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return notes


def media_kind_of(field: dict[str, Any]) -> str | None:
    """Epic 29 (Story 29.5): the media kind a drafted `file` field really is: every accepted type in one kind's
    playable set, else the field's name (video, clip, recording, episode, subtitles, captions, …); None to keep it."""
    accept = [m for m in field.get("accept") or [] if isinstance(m, str)]
    if accept:
        for kind, types in PLAYABLE.items():
            if all(mime in types or mime == f"{kind}/*" for mime in accept):
                return kind
        return None  # an accept list outside the playable sets stays a file (a ZIP, a PDF)
    words = humanize(str(field.get("name") or "")).lower().split()
    for kind, names in MEDIA_WORDS.items():
        if any(word in names for word in words):
            return kind
    return None


def fix_media_fields(data: dict[str, Any]) -> list[dict[str, Any]]:
    """A `file` field that is a media file becomes `video`, `audio` or `subtitles` (one note each; an `accept` of
    `<kind>/*` is dropped, the kind's playable set applies); a media entity without an image field gets a note (no
    poster: the player shows the first frame)."""
    notes: list[dict[str, Any]] = []
    for e_index, entity in enumerate(data.get("entities") or []):
        if not isinstance(entity, dict) or not isinstance(entity.get("fields"), list):
            continue
        fields = [f for f in entity["fields"] if isinstance(f, dict)]
        for f_index, item in enumerate(entity["fields"]):
            if not isinstance(item, dict) or item.get("type") != "file":
                continue
            kind = media_kind_of(item)
            if kind is None:
                continue
            item["type"] = kind
            if item.get("accept") and any(str(m).endswith("/*") for m in item["accept"]):
                item.pop("accept")
            message = f"{entity.get('name')}.{item.get('name')}: a file people {MEDIA_VERBS[kind]} is `{kind}`"
            notes.append({"spec": "backend", "path": f"/entities/{e_index}/fields/{f_index}/type", "message": message,
                          "suggestion": None})  # fmt: skip
        has_video = any(f.get("type") == "video" for f in fields)
        if has_video and not any(f.get("type") == "image" for f in fields):
            message = (
                f"{entity.get('name')} has a video but no image field: its player shows the first frame as the poster"
            )
            notes.append(
                {"spec": "backend", "path": f"/entities/{e_index}/fields", "message": message, "suggestion": None}
            )
    return notes


MEDIA_VERBS = {"video": "watch", "audio": "listen to", "subtitles": "read along"}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _with_screen_operations(
    path: Path, backend: dict[str, Any], added: list[dict[str, Any]], removed: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The drafted BackendSpec file with the screens' operations added and the left-out aggregates removed, kept only
    when it stays valid (a removal can leave a rule or a policy without its operation): else the additions alone, else
    the spec as drafted. Returns the normalized spec and notes (2026-11-07: an invalid edit crashed a draft)."""
    drafted = _load(path)
    tries = [(added, removed), (added, set())] if removed else [(added, set())]
    errors: list[str] = []
    for adding, removing in tries:
        raw = copy.deepcopy(drafted)
        if removing:
            raw = without_references(raw, removing)
            raw["operations"] = [op for op in raw.get("operations") or [] if op.get("operationId") not in removing]
        raw["operations"] = [*(raw.get("operations") or []), *adding]
        result = validate_spec_data(raw)
        if result.normalized is not None:
            path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
            notes = []
            if errors:
                message = f"The left-out aggregates stay in the BackendSpec (removing them: {'; '.join(errors)})"
                notes.append({"spec": "backend", "path": "/operations", "message": message[:600], "suggestion": None})
            return result.normalized, notes
        errors = [f"{issue.path}: {issue.message}" for issue in result.report.errors[:3]]
    message = f"The screens' operations were not added: the BackendSpec would be invalid ({'; '.join(errors)})"
    return backend, [{"spec": "backend", "path": "/operations", "message": message[:600], "suggestion": None}]


def app_theme(chosen: dict[str, Any] | None) -> dict[str, Any]:
    """The direction's theme tokens only (decision D3): colours, fonts, radius and density; light and dark, the
    kit's own type scale. No surface, colour area, motion or icon style: the kit decides how screens look."""
    theme = (chosen or {}).get("theme") or {}
    typography = theme.get("typography") or {}
    out: dict[str, Any] = {"style": theme.get("style") or "dashboard", "colorScheme": "light-dark"}
    if theme.get("colors"):
        out["colors"] = dict(theme["colors"])
    fonts = {key: typography[key] for key in ("headingFont", "bodyFont") if typography.get(key)}
    if fonts:
        out["typography"] = fonts
    for key in ("radius", "density"):
        if theme.get(key):
            out[key] = theme[key]
    if theme.get("direction"):
        out["direction"] = dict(theme["direction"])
    return out


async def draft_app(
    work: Path,
    context: dict[str, Any],
    prompts: PromptLibrary,
    call: Call,
    progress: Progress,
    check_draft: Callable[[Path, GenerationMode], Any],
    chosen: dict[str, Any] | None,
    backend_file: str,
    frontend_file: str,
) -> AppDraft:
    """One engine call for the BackendSpec and the outline (plus repairs only when the BackendSpec is invalid), then
    the FrontendSpec by code: the outline completed from the BackendSpec and the contract, the screens planned."""
    await progress("drafting")
    # Story 22.8: an API engine answers in the shape of the three files (structured output); a CLI engine writes them
    inline = context.get("inline")
    schema = app_answer_schema(backend_file, OUTLINE_FILE, context["notes_path"], design=True) if inline else None
    requirement = context.get("requirement_text") or ""
    products = product_rows(requirement)
    product_types = [row.get("Product Type", "") for row in products]
    context = {  # Story 23.6: code's candidates for the brief, the data's looks, the requirement's style words
        **context,
        "archetype_candidates": ", ".join(archetype_candidates(requirement, product_types)),
        "recommended_looks": recommended_looks(products),
        "style_words": style_words(requirement),
    }
    result = await call("draft", prompts.render(*PROMPT, **context), response_schema=schema)
    if result.status != EngineStatus.OK:
        from .drafts import DraftFailed

        raise DraftFailed(f"The engine stopped: {result.error_message or result.status}")
    notes: list[dict[str, Any]] = fix_backend_defaults(work, backend_file)
    error: str | None = None
    check = check_draft(work, GenerationMode.BACKEND)
    attempts = 0
    while not check.ok and attempts < config.draft_repair_attempts_backend:
        attempts += 1
        await progress(f"repairing ({attempts}/{config.draft_repair_attempts_backend})", attempts_count=attempts)
        errors = check.repair_errors()
        documents = {backend_file: (work / backend_file).read_text()} if context.get("inline") else {}
        prompt = prompts.render(
            "repair_spec", "v3", files=[backend_file], errors=errors, inline=context.get("inline"), documents=documents
        )
        repaired = await call("repair", prompt)
        notes += fix_backend_defaults(work, backend_file)
        check = check_draft(work, GenerationMode.BACKEND)
        if repaired.status != EngineStatus.OK and not check.ok:
            error = f"Repair {attempts} stopped: {repaired.error_message or repaired.status}"
            break
    if check.ok:  # Epic 25: who may see and do what, correct by default (general rules, no model call)
        notes += apply_access_rules(work, backend_file)
        check = check_draft(work, GenerationMode.BACKEND)
    await progress("validating")
    backend = validate_spec_data(_load(work / backend_file)).normalized if check.ok else None
    if backend is None:
        return AppDraft(check=check, notes=notes, error=error, attempts=attempts)
    drafted = _load(work / OUTLINE_FILE)
    if not isinstance(drafted, dict):
        message = "The draft came without an app outline; every name and list comes from the BackendSpec"
        notes.append({"spec": "frontend", "path": "/app", "message": message, "suggestion": None})
    # Epic 23: code's archetype for a brief that names none (the requirement's words, then the direction's product)
    hint = archetype_for(requirement, [*product_types, (chosen or {}).get("productType") or ""])
    outline, outline_fixes = complete_outline(drafted, backend, build_contract(backend, build_plan(backend)), hint)
    outline_fixes += finish_looks(outline, requirement, products)
    if not outline.get("locale") and locale_of(requirement):  # Story 23.8: a Japanese requirement, a Japanese app
        outline["locale"] = locale_of(requirement)
    # Story 22.3: the dashboard's figures are aggregate operations, templated like CRUD; code adds the missing ones.
    extended, outline, aggregate_notes = ensure_aggregates(backend, outline)
    added = [op for op in extended["operations"] if op not in backend["operations"]]
    kept = {op["operationId"] for op in extended["operations"]}
    removed = {op["operationId"] for op in backend["operations"]} - kept  # Story 25.1: no room on the dashboard
    if added or removed:
        backend, edit_notes = _with_screen_operations(work / backend_file, backend, added, removed)
        notes += edit_notes
    contract = build_contract(backend, build_plan(backend))
    theme = app_theme(chosen)
    requested_notes = follow_requested(outline, theme)  # the requirement's own look over the design data's choice
    screens = app_frontend_spec(backend, outline, theme, contract)
    (work / frontend_file).write_text(json.dumps(screens.spec, indent=2, ensure_ascii=False) + "\n")
    notes += outline_fixes + aggregate_notes + requested_notes + screens.assumptions
    check = check_draft(work, GenerationMode.DYNAMIC)
    return AppDraft(check=check, notes=notes, unresolved=screens.unresolved, error=error, attempts=attempts)


def product_rows(requirement: str, count: int = 3) -> list[dict[str, str]]:
    """UI UX Pro Max's product types that best match the requirement (its rows: styles, dashboard style)."""
    from .design_direction import design_data, rank_products

    if not requirement.strip():
        return []
    data = design_data()
    return [data.products[index] for index, _ in rank_products(requirement, data)[:count]]


def finish_looks(outline: dict[str, Any], requirement: str, products: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Story 23.7: the brief's three looks completed (the requirement's words first, the data's styles, guards for
    sensitive products, a range); changes the outline's design in place and returns the notes."""
    types = [row.get("Product Type", "") for row in products]
    design = outline.setdefault("design", {})
    looks, notes = complete_looks(design.get("looks") or [], requirement, recommended_looks(products), types)
    design["looks"] = looks
    design["replaced"] = [*design.get("replaced", []), *notes]
    return design_notes(notes)
