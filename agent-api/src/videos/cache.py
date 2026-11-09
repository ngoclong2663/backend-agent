"""The video providers' shared cache (Epic 31 D4): searches by provider, phrase, language and place, kept on disk
under `ARTIFACT_ROOT/asset-cache/video/<provider>/`, each for at least a day (Pixabay asks for 24 h; YouTube's quota
is daily), plus each provider's own counters (YouTube's units spent today)."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from src.configs import config

DAY = 24 * 3600


def video_cache_dir(provider: str) -> Path:
    return Path(config.artifact_root) / "asset-cache" / "video" / provider


class JsonCache:
    """One JSON file per provider, written atomically: `searches` (key → {at, results}) and free `state`."""

    def __init__(self, path: Path, ttl_seconds: int = DAY):
        self.path = path
        self.ttl = ttl_seconds

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def search(self, key: str) -> list[dict[str, Any]] | None:
        entry = (self.read().get("searches") or {}).get(key)
        if not entry or time.time() - float(entry.get("at", 0)) > self.ttl:
            return None
        return list(entry.get("results") or [])

    def remember(self, key: str, results: list[dict[str, Any]]) -> None:
        data = self.read()
        data.setdefault("searches", {})[key] = {"at": time.time(), "results": results}
        self.write(data)

    def state(self) -> dict[str, Any]:
        return dict(self.read().get("state") or {})

    def set_state(self, **values: Any) -> None:
        data = self.read()
        data["state"] = {**(data.get("state") or {}), **values}
        self.write(data)
