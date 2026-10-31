"""Component cache (Story 17.3): cache keys, the cached files, sample props for the render test, catalogue fallbacks.

A custom component is cached by what it was generated from, never by its name:

    key = sha256(canonical JSON of {props schema, uses, normalized description, base lock sha, overlay version,
                                     prompt version})

so a spec that names the same component differently reuses it, and a new base, overlay or prompt makes old entries
miss on their own. Files live at `ARTIFACT_ROOT/cache/components/<key>/<key>.tsx`; the rows (`component_cache`)
hold the source generation, engine, model, hits and the engine time one hit saves.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from src.configs import config

OVERLAY_JSON = Path(__file__).resolve().parents[2] / "templates" / "nextjs_overlay" / "overlay.json"
PROMPT_VERSION = "v3"  # generate_custom_component / repair_custom_component
CUSTOM_DIR = "src/components/custom"


def overlay_metadata() -> tuple[str, str]:
    """(base lock sha256, overlay version) from the overlay manifest."""
    data = json.loads(OVERLAY_JSON.read_text())
    return data["lockSha256"], str(data["version"])


def component_key(component: dict[str, Any], lock_sha256: str, overlay_version: str) -> str:
    canonical = {
        "description": " ".join((component.get("description") or "").split()),
        "lockSha256": lock_sha256,
        "overlayVersion": overlay_version,
        "promptVersion": PROMPT_VERSION,
        "propsSchema": component.get("propsSchema") or {},
        "uses": sorted(set(component.get("uses") or [])),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def component_file(key: str) -> str:
    """Where a custom component lives in the frontend project."""
    return f"{CUSTOM_DIR}/{key}.tsx"


def cache_dir(key: str) -> Path:
    return Path(config.artifact_root) / "cache" / "components" / key


def cached_file(key: str) -> Path:
    return cache_dir(key) / f"{key}.tsx"


def store_file(key: str, source: Path) -> None:
    target = cached_file(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def drop_files(key: str | None = None) -> None:
    """One entry's files, or the whole cache."""
    shutil.rmtree(cache_dir(key) if key else cache_dir("x").parent, ignore_errors=True)


def closest_section(section: dict[str, Any], component: dict[str, Any]) -> str:
    """The library section a custom component falls back to when it cannot be generated: chosen from how its
    first section is bound, so the fallback gets data it can render."""
    data = section.get("data") or {}
    name = component["name"].lower()
    uses = set(component.get("uses") or [])
    if data.get("kind") == "operation" and data.get("action") == "get":
        return "DetailView"
    if data.get("kind") == "content" or (data.get("kind") == "operation" and data.get("action") == "list"):
        if "table" in name or "table" in uses:
            return "DataTable"
        if "grid" in name or "card" in uses:
            return "CardGrid"
        return "List"
    return "RichText"


def sample_value(schema: dict[str, Any], depth: int = 0) -> Any:
    """A value that satisfies a JSON Schema property, for the isolated render test."""
    for keyword in ("default", "const"):
        if keyword in schema:
            return schema[keyword]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        return {
            "email": "user@example.com",
            "uri": "https://example.com",
            "date": "2026-10-29",
            "date-time": "2026-10-29T12:00:00Z",
        }.get(schema.get("format"), "Sample text")
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return schema.get("minimum", 1.5)
    if kind == "boolean":
        return True
    if kind == "array":
        items = schema.get("items")
        return [sample_value(items, depth + 1)] if isinstance(items, dict) and depth < 3 else []
    if kind == "object" and depth < 3:
        return sample_props(schema, depth + 1)
    return None


def sample_props(schema: dict[str, Any] | None, depth: int = 0) -> dict[str, Any]:
    props = {}
    for name, prop in ((schema or {}).get("properties") or {}).items():
        value = sample_value(prop, depth) if isinstance(prop, dict) else None
        if value is not None:
            props[name] = value
    return props
