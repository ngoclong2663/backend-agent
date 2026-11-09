"""Completing backend modules with the engine (Story 18.13).

What the templates do not cover in a module (`codegen_gaps`: custom operations, business rules, auth) goes to the
engine with the `complete_backend` prompt. Two things keep that call short:

    context pack   `module_context` puts what the module needs into the prompt: each custom operation's spec entry
                   and contract operation (schemas resolved), the module's generated files, its entity and model,
                   the entities and repository ports of the modules it touches, and the exception helpers; the
                   engine is told not to read other files (before: 45 reads and 53 turns per module)
    in parallel    `complete_modules` runs the modules at once (at most `ENGINE_CONCURRENCY` engine calls), each in
                   its own scratch copy of the project, and merges their changes back in plan order; a module whose
                   changes touch a file that an earlier module changed differently runs again, after the others,
                   in the project itself
"""

import asyncio
import contextlib
import copy
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.engines.prompts import RenderedPrompt
from src.modules.shared.domain.backend_spec.naming import to_snake

from ..context import JobContext
from ..integration.contract import contract_operations, resolve
from .codegen import engine_rules

logger = get_logger(__name__)

# The module's own files go in whole up to this size; past it, only the files the engine edits plus one example of
# each kind (the flashcards `cards` module is ~15 KB).
MODULE_FILES_LIMIT = 48 * 1024
LIBS = tuple(f"src/libs/exceptions/{name}.py" for name in ("__init__", "base_exception", "error_codes"))
# Contract details the engine does not need (mock plans, sample records)
CONTRACT_NOISE = ("mock", "sample", "fixtures")
SCRATCH_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".claude", ".agents"
)
# Files the engine adapters write into a workdir (rules), never merged back
ENGINE_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md"}

Render = Callable[[dict[str, Any]], RenderedPrompt]


# -- context pack ------------------------------------------------------------------------------------------------------


def _read(project: Path, relative: str) -> str | None:
    path = project / relative
    return path.read_text() if path.is_file() else None


def _inline(document: dict[str, Any], schema: Any, depth: int = 0) -> Any:
    """The schema with every local `$ref` replaced by what it points at (cycles stop at depth 16)."""
    schema = resolve(document, schema)
    if depth > 16:
        return schema
    if isinstance(schema, dict):
        return {key: _inline(document, value, depth + 1) for key, value in schema.items()}
    if isinstance(schema, list):
        return [_inline(document, item, depth + 1) for item in schema]
    return schema


def _contract_operation(contract: dict[str, Any] | None, operation_id: str) -> dict[str, Any] | None:
    found = contract_operations(contract).get(operation_id) if contract else None
    if found is None:
        return None
    operation = copy.deepcopy(found["operation"])
    meta = operation.get("x-bga")
    if isinstance(meta, dict):
        for key in CONTRACT_NOISE:
            meta.pop(key, None)
    return {"method": found["method"], "path": found["path"], **_inline(contract, operation)}


def _gap_operations(module: dict[str, Any]) -> list[dict[str, Any]]:
    """The module's operations the templates do not finish (what `codegen_gaps` names)."""
    return [
        op
        for op in module["operations"]
        if (op.get("type") not in ("crud", "aggregate")) or engine_rules(op)  # auth, policies: plugins (10.2, 10.3)
    ]


def related_entities(plan: dict[str, Any], spec: dict[str, Any], module: dict[str, Any]) -> list[str]:
    """Entities the module's custom code is likely to touch: foreign keys in both directions, and entities its
    operations or rules name."""
    entity = module["entity"]
    by_table = {model["table"]: model["entity"] for model in plan["models"]}
    related: set[str] = set()
    for model in plan["models"]:
        for column in model["columns"]:
            references = (column.get("foreignKey") or {}).get("references")
            target = by_table.get(str(references).partition(".")[0]) if references else None
            if target is None:
                continue
            if model["entity"] == entity:
                related.add(target)
            if target == entity and model.get("entity"):
                related.add(model["entity"])
    op_ids = {op["operationId"] for op in _gap_operations(module)}
    texts = [
        f"{op.get('summary') or ''} {op.get('description') or ''}"
        for op in spec.get("operations", [])
        if op.get("operationId") in op_ids
    ]
    texts += [rule.get("description") or "" for rule in spec.get("rules", []) if rule.get("entity") == entity]
    text = " ".join(texts)
    for model in plan["models"]:
        name = model.get("entity")
        if not name:
            continue  # a link table without an entity (gen_01M6Z6HPQQ0WMJ3ZSZGABM70NR, 2026-11-09: it crashed the lane)
        if re.search(rf"\b{re.escape(name)}s?\b", text) or re.search(rf"\b{re.escape(model['table'])}\b", text):
            related.add(name)
    related.discard(entity)
    return sorted(related)


def _module_files(project: Path, module: dict[str, Any], generated: list[str]) -> dict[str, str]:
    """The module's generated source files (not its tests): all of them, or past the limit the files the engine
    edits (router, packages' `__init__.py`) plus the port, the repository and one use case and one DTO."""
    files = {
        relative: text
        for relative in generated
        if relative.startswith("src/") and (text := _read(project, relative))  # empty packages say nothing
    }
    if sum(len(text) for text in files.values()) <= MODULE_FILES_LIMIT:
        return files
    keep = {module["router"]["file"], module["port"]["file"], module["port"]["implementationFile"]}
    keep |= {relative for relative in files if relative.endswith("__init__.py")}
    for kind in ("/usecases/", "/presenter/dtos/"):
        example = next((r for r in sorted(files) if kind in r and not r.endswith("__init__.py")), None)
        if example:
            keep.add(example)
    return {relative: text for relative, text in files.items() if relative in keep}


def _fence(relative: str, text: str) -> str:
    return f"### `{relative}`\n\n```python\n{text.rstrip()}\n```\n"


def module_context(
    project: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    contract: dict[str, Any] | None,
    module: dict[str, Any],
    generated: list[str],
) -> str:
    """The Markdown the `complete_backend` prompt carries for one module (read from the project as it is now)."""
    models = {model["entity"]: model for model in plan["models"]}
    modules = {m["entity"]: m for m in plan["modules"]}
    sections: list[str] = []

    operations = []
    by_id = {op.get("operationId"): op for op in spec.get("operations", [])}
    rules = {rule["id"]: rule for rule in spec.get("rules", []) if "id" in rule}
    for op in _gap_operations(module):
        entry: dict[str, Any] = {"plan": op, "spec": by_id.get(op["operationId"])}
        answers = {rule["id"]: rule for rule in op.get("customRules") or []}  # Story 10.4: the code it raises
        named = [rules[rule_id] | {"answer": answers[rule_id]} if rule_id in answers else rules[rule_id]
                 for rule_id in engine_rules(op) if rule_id in rules]  # fmt: skip
        if named:
            entry["rules"] = named
        contract_op = _contract_operation(contract, op["operationId"])
        if contract_op is not None:
            entry["contract"] = contract_op
        body = json.dumps(entry, indent=2, ensure_ascii=False)
        operations.append(f"### `{op['operationId']}`\n\n```json\n{body}\n```\n")
    sections.append("## Operations to complete\n\n" + "\n".join(operations))

    files = _module_files(project, module, generated)
    present = ""
    if "references" in module["port"]["methods"]:  # Story 10.0b: records show their parents by name
        dto, repo = f"{module['entity']}ResponseDto", f"self.{to_snake(module['entity'])}_repo"
        present = (
            f"Return records as `{dto}.from_entity(record, {repo}.references([record]))` (a list: load the "
            f"references once, `{repo}.references(records)`), so each response carries its parents' labels.\n\n"
        )
    sections.append(
        "## This module's generated files\n\nEdit these and add new use case and DTO files next to them.\n\n"
        + present
        + "\n".join(_fence(relative, text) for relative, text in sorted(files.items()))
    )

    own = models.get(module["entity"])
    shared = []
    if own is not None:
        for relative in (own["entityFile"], own["file"]):
            if (text := _read(project, relative)) is not None:
                shared.append(_fence(relative, text))
    for name in related_entities(plan, spec, module):
        model = models[name]
        if (text := _read(project, model["entityFile"])) is not None:
            shared.append(_fence(model["entityFile"], text))
        other = modules.get(name)
        if other is not None and (text := _read(project, other["port"]["file"])) is not None:
            dep = other["port"]["dep"]
            package = other["port"]["file"].rsplit("/", 1)[0].replace("/", ".")
            how = f"Inject it as `{dep}` (`from {package} import {dep}`).\n\n"
            shared.append(how + _fence(other["port"]["file"], text))
    if shared:
        sections.append("## Entities, models and the ports of related modules (read only)\n\n" + "\n".join(shared))

    # Story 10.1: what the plugins already wrote, so the engine calls their APIs instead of writing its own
    from ..plugins import plan_plugins

    notes = [note for plugin in plan_plugins(plan) if (note := plugin.engine_note(plan))]
    if notes:
        sections.append(
            "## Already in this project (read only)\n\nDo not edit `src/main.py`, `src/configs/` or `src/libs/`.\n\n"
            + "\n".join(f"- {note}" for note in notes)
        )

    libs = [_fence(relative, text) for relative in LIBS if (text := _read(project, relative)) is not None]
    if libs:
        sections.append(
            "## Exceptions (read only)\n\n"
            "`@Transactional` is `from src.libs.decorators.transactional_decorator import Transactional`.\n\n"
            + "\n".join(libs)
        )
    return "\n\n".join(sections)


# -- running the modules -----------------------------------------------------------------------------------------------


def _merged(relative: str) -> bool:
    parts = relative.split("/")
    return not parts[0].startswith(".") and "__pycache__" not in parts and relative not in ENGINE_FILES


def _digest(root: Path) -> dict[str, str]:
    found = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _merged(relative) and not any(part in (".venv", "node_modules") for part in relative.split("/")):
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _changes(base: dict[str, str], scratch: Path) -> dict[str, bytes | None]:
    """path → new content (`None`: deleted) of what the engine changed in the scratch copy."""
    after = _digest(scratch)
    changed: dict[str, bytes | None] = {
        relative: (scratch / relative).read_bytes() for relative, sha in after.items() if base.get(relative) != sha
    }
    changed |= {relative: None for relative in base.keys() - after.keys()}
    return changed


def _apply(project: Path, changes: dict[str, bytes | None]) -> None:
    for relative, content in changes.items():
        target = project / relative
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


async def complete_modules(ctx: JobContext, modules: list[dict[str, Any]], render: Render) -> dict[str, Any]:
    """Runs `complete_backend` for each module (plan order) and returns the step summary's fields. `render` builds
    a module's prompt from the project as it is when called."""
    project = ctx.workspace.project
    if len(modules) <= 1 or config.engine_concurrency <= 1:  # one engine call at a time: no scratch copies
        for module in modules:
            async with ctx.engine_slots:
                await ctx.run_engine("generate_backend", "complete_backend", render(module))
        return {"completedByEngine": [m["name"] for m in modules], "parallel": False}

    base = _digest(project)
    scratch_root = ctx.workspace.root / "scratch"
    prompts = {module["name"]: render(module) for module in modules}  # all from the same generated code

    async def one(module: dict[str, Any]) -> dict[str, bytes | None]:
        scratch = scratch_root / f"module-{module['name']}"
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.copytree(project, scratch, ignore=SCRATCH_IGNORE)
        try:
            async with ctx.engine_slots:
                await ctx.run_engine(
                    "generate_backend", "complete_backend", prompts[module["name"]], workdir_override=scratch
                )
            return _changes(base, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            with contextlib.suppress(OSError):
                scratch_root.rmdir()  # once the last scratch copy is gone (custom components share the folder)

    tasks = [asyncio.create_task(one(module)) for module in modules]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    merged: dict[str, bytes | None] = {}
    conflicts: list[str] = []
    for module, changes in zip(modules, results, strict=True):
        clash = sorted(r for r, content in changes.items() if r in merged and merged[r] != content)
        if clash:
            conflicts.append(module["name"])
            logger.info("complete_backend: %s conflicts on %s; it runs again after the others", module["name"], clash)
            continue
        _apply(project, changes)
        merged |= changes
        await ctx.emit("backend.completed", step="generate_backend", module=module["name"], files=len(changes))
    for module in modules:
        if module["name"] in conflicts:  # one after the other, on the merged code
            async with ctx.engine_slots:
                await ctx.run_engine("generate_backend", "complete_backend", render(module))
            await ctx.emit("backend.completed", step="generate_backend", module=module["name"], rerun=True)
    return {"completedByEngine": [m["name"] for m in modules], "parallel": True, "conflicts": conflicts}
