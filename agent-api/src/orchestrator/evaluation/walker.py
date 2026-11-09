"""The evaluation's browser (Story 26.5): `templates/evaluation/walk.mjs` in a `bga-runner-node` container, driven
by JSON lines.

playwright-core is installed once into a cache next to the workspaces (the runner's Chromium is in /ms-playwright).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from src.configs import config

from .api import EvaluationError

WALK_SCRIPT = Path(__file__).resolve().parents[3] / "templates" / "evaluation" / "walk.mjs"
SAMPLES = Path(__file__).resolve().parents[3] / "templates" / "samples"  # Story 28.6: what a required upload gets
PLAYWRIGHT = "1.64.1"  # the base's @playwright/test, whose Chromium the runner image has


class Walker:
    def __init__(self, shots: Path, tour: bool = False):
        cache = Path(config.workspace_root) / "_evaluation_walk"
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WALK_SCRIPT, cache / "walk.mjs")
        if SAMPLES.is_dir():
            shutil.copytree(SAMPLES, cache / "samples", dirs_exist_ok=True)
        package = {"name": "bga-evaluation-walk", "private": True, "type": "module",
                   "dependencies": {"playwright-core": PLAYWRIGHT}}  # fmt: skip
        (cache / "package.json").write_text(json.dumps(package))
        user = f"{os.getuid()}:{os.getgid()}"
        image = config.frontend_sandbox_image
        if not (cache / "node_modules" / "playwright-core").is_dir():
            subprocess.run(
                ["docker", "run", "--rm", "--user", user, "-e", "HOME=/tmp", "-v", f"{cache}:/walk", "-w", "/walk",
                 "--entrypoint", "npm", image, "install", "--no-audit", "--no-fund"],
                check=True, capture_output=True, timeout=600,
            )  # fmt: skip
        shots.mkdir(parents=True, exist_ok=True)
        tour_env = ["-e", "BGA_TOUR=1"] if tour else []  # the guided tour starts as it would for a new user
        self.proc = subprocess.Popen(
            ["docker", "run", "--rm", "-i", "--add-host", "host.docker.internal:host-gateway", "--user", user,
             "-e", "HOME=/tmp", "-e", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright", *tour_env, "-v", f"{cache}:/walk:ro",
             "-v", f"{shots}:/out", "-w", "/walk", "--entrypoint", "node", image, "walk.mjs", "host.docker.internal"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )  # fmt: skip

    def send(self, command: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise EvaluationError("the browser stopped")
        return json.loads(line)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.write('{"cmd":"quit"}\n')
                self.proc.stdin.flush()
            self.proc.wait(timeout=30)
        except Exception:
            self.proc.kill()
