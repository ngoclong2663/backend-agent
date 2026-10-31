import json
import shutil
from pathlib import Path
from typing import Literal

from src.libs.redaction import Redactor

from ..cli_engine import CliEngine, Invocation
from ..port import EngineContext, EngineHealth, EngineRequest
from ..process import SubprocessRunner, base_env
from ..workspace import install_skills, remove_path, write_managed_section
from .stream import AntigravityStreamParser

# Headless agy already soft-denies shell commands; the deny rules make it explicit and also cover
# network and MCP. Workspace file reads/writes are scoped strictly to the request's workdir (Story 18.4).
DENY_PERMISSIONS = ["command(*)", "read_url(*)", "execute_url(*)", "mcp(*)", "write_file(.agents/)"]
UNTRUSTED_WORKSPACE_CONFIG = [".agents/hooks.json", ".agents/rules"]
# Marker files of a container runtime: the agy account login lives in the host's OS keyring.
CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))


def _in_container() -> bool:
    return any(marker.exists() for marker in CONTAINER_MARKERS)


class AntigravityEngine(CliEngine):
    """Antigravity CLI (`agy`) in stream-json stdin mode — the documented way to drive it from a process."""

    name = "antigravity"

    def __init__(
        self,
        *,
        binary: str,
        auth: Literal["gemini_api_key", "adc", "account"],
        gemini_api_key: str | None,
        google_application_credentials: str | None,
        model: str | None,
        allowed_root: Path,
        redactor: Redactor,
        default_timeout_s: float,
        default_max_turns: int,
        max_output_bytes: int,
        purpose_models: dict[str, str] | None = None,
        runner: SubprocessRunner | None = None,
    ):
        super().__init__(allowed_root, redactor, default_timeout_s, default_max_turns, max_output_bytes, runner)
        self.binary = binary
        self.auth = auth
        self.gemini_api_key = gemini_api_key
        self.google_application_credentials = google_application_credentials
        self.model = model
        self.purpose_models = purpose_models or {}

    async def health(self) -> EngineHealth:
        if shutil.which(self.binary) is None:
            return EngineHealth(name=self.name, available=False, reason=f"'{self.binary}' not found on PATH")
        if self.auth == "gemini_api_key" and not self.gemini_api_key:
            return EngineHealth(name=self.name, available=False, reason="Set GEMINI_API_KEY (or ANTIGRAVITY_AUTH=adc)")
        if self.auth == "adc" and not self.google_application_credentials:
            return EngineHealth(name=self.name, available=False, reason="Set GOOGLE_APPLICATION_CREDENTIALS for ADC")
        if self.auth == "account":
            # `agy` signed in with a Google account keeps its token in the OS keyring (D-Bus secret service), which
            # only exists on the host. Use it for a host dev worker; containers need GEMINI_API_KEY or ADC.
            if _in_container():
                reason = "ANTIGRAVITY_AUTH=account needs the host keyring; use GEMINI_API_KEY or ADC in Docker"
                return EngineHealth(name=self.name, available=False, reason=reason)
            return EngineHealth(name=self.name, available=True, reason="Uses the agy account login on this machine")
        return EngineHealth(name=self.name, available=True)

    async def prepare_workspace(self, workdir: Path, context: EngineContext) -> None:
        install_skills(context.skill_dirs, workdir / ".agents" / "skills")
        body = context.conventions
        if (workdir / "CLAUDE.md").exists():
            body += "\n\nThe project guide in `CLAUDE.md` (repository root) applies to you as well; read it first."
        write_managed_section(workdir / "AGENTS.md", body)

    def build_invocation(self, request: EngineRequest, home: Path, max_turns: int, timeout_s: float) -> Invocation:
        for relative in UNTRUSTED_WORKSPACE_CONFIG:
            remove_path(request.workdir / relative)
        workdir = str(request.workdir.resolve())
        permissions = {
            "allow": [f"read_file({workdir})", f"write_file({workdir})"],
            "deny": list(DENY_PERMISSIONS),
        }
        settings: dict = {"permissions": permissions, "enableTerminalSandbox": True}
        if self.auth == "gemini_api_key":
            settings["modelProvider"] = "gemini"  # GEMINI_API_KEY alone is ignored without this

        argv = [
            self.binary,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--mode",
            "accept-edits",
            "--print-timeout",
            f"{int(timeout_s)}s",
        ]
        model = request.model or self.purpose_models.get(request.purpose) or self.model
        if model:
            argv += ["--model", model]
        if self.auth == "account":
            # The account login belongs to the user's real home (on macOS a scratch HOME fails with "authentication
            # required"), so keep HOME and pass the settings for this session only, leaving the user's own alone.
            argv += ["--settings", json.dumps(settings)]
            home = Path.home()
        else:
            settings_dir = home / ".gemini" / "antigravity-cli"
            settings_dir.mkdir(parents=True, exist_ok=True)
            (settings_dir / "settings.json").write_text(json.dumps(settings, indent=2))
        env = base_env(
            HOME=str(home),
            GEMINI_API_KEY=self.gemini_api_key if self.auth == "gemini_api_key" else None,
            AGY_ADC_AUTH="true" if self.auth == "adc" else None,
            GOOGLE_APPLICATION_CREDENTIALS=self.google_application_credentials if self.auth == "adc" else None,
        )
        message = {"event": "user", "message": {"content": request.prompt}}
        stdin = (json.dumps(message) + "\n").encode()  # stdin is closed after this one turn, so agy exits
        return Invocation(argv=argv, env=env, stdin=stdin, parser=AntigravityStreamParser(max_turns, model))

    def redact_argv(self, argv: list[str]) -> list[str]:
        return list(argv)
