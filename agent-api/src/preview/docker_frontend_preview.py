"""Docker implementation of frontend preview containers (Story 13.5).

Per generation:

    host 127.0.0.1:<port> ──▶ bga-preview-fe-<gen>    image bga-fe-<gen>:latest, built from frontend.zip
                               static:  nginx serving the export (port 8080)
                               dynamic: Next.js standalone server (port 3000), MOCK_TEST_API / API_BASE_URL

The image is built with the project's own Dockerfile from the packaged ZIP, like backend previews, so every
preview proves that the ZIP builds on its own. No database. Containers carry their own label, so the backend
preview runtime never sees (or removes) them.
"""

import asyncio
import hashlib
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, BuildError, ImageNotFound, NotFound
from docker.models.containers import Container

from src.configs import config, get_logger
from src.sandbox.docker_sandbox import INSTANCE_LABEL, ensure_egress_network, instance_id

from .port import IPreviewRuntime, PreviewError, PreviewHandle, PreviewRequest, PreviewState

logger = get_logger(__name__)
LABEL = "bga.preview.frontend"
ROLE_LABEL = "bga.role"
PORTS = {"static": 8080, "dynamic": 3000}
PORT_TAKEN = ("port is already allocated", "address already in use", "bind for")
NODE_PROBE = (
    "fetch('http://127.0.0.1:3000/api/runtime-config').then(r => process.exit(r.ok ? 0 : 1))"
    ".catch(() => process.exit(1))"
)


def names(generation_id: str) -> dict[str, str]:
    slug = generation_id.lower()
    return {"image": f"bga-fe-{slug}:latest", "app": f"bga-preview-fe-{slug}"}


def _labels(generation_id: str, role: str, mode: str | None = None) -> dict[str, str]:
    labels = {LABEL: generation_id, INSTANCE_LABEL: instance_id(), ROLE_LABEL: role}
    if mode:
        labels["bga.frontend.mode"] = mode
    return labels


def _memory_bytes(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    value = value.strip().lower()
    return int(float(value[:-1]) * units[value[-1]]) if value[-1] in units else int(value)


def _host_port(container: Container) -> int | None:
    bindings = (container.attrs.get("HostConfig") or {}).get("PortBindings") or {}
    for spec in bindings.values():
        for binding in spec or []:
            if binding.get("HostPort"):
                return int(binding["HostPort"])
    return None


class DockerFrontendPreviewRuntime(IPreviewRuntime):
    def __init__(self, client: docker.DockerClient | None = None):
        self.client = client or docker.from_env()

    def _get(self, name: str) -> Container | None:
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    async def deploy(self, request: PreviewRequest) -> PreviewHandle:
        return await asyncio.to_thread(self._deploy, request)

    def _deploy(self, request: PreviewRequest) -> PreviewHandle:
        mode = request.options.get("mode", "dynamic")
        build_log = self._ensure_image(request.generation_id, request.source_zip)
        app = self._get(names(request.generation_id)["app"])
        if app is not None and (app.labels or {}).get("bga.frontend.env") != self._env_key(request):
            app.remove(force=True)  # MOCK_TEST_API / API_BASE_URL changed: recreate with the new environment
            app = None
        if app is None:
            app = self._create_app(request, mode)
        elif app.status != "running":
            try:
                app.start()
            except APIError as exc:
                if not any(marker in str(exc).lower() for marker in PORT_TAKEN):
                    raise PreviewError(f"frontend preview failed to start: {exc}") from exc
                app.remove(force=True)
                app = self._create_app(request, mode)
        self._wait_ready(app, mode)
        app.reload()
        return PreviewHandle(
            container_id=app.id, db_container_id="", host_port=_host_port(app) or 0, build_log=build_log
        )

    @staticmethod
    def _env_key(request: PreviewRequest) -> str:
        return f"{request.options.get('mockApi', True)}|{request.options.get('apiBaseUrl', '')}"

    def _ensure_image(self, generation_id: str, source_zip: Path) -> str | None:
        tag = names(generation_id)["image"]
        try:
            self.client.images.get(tag)
            return None
        except ImageNotFound:
            pass
        with tempfile.TemporaryDirectory(prefix="bga-fe-preview-") as directory:
            with zipfile.ZipFile(source_zip) as archive:
                for info in archive.infolist():
                    target = Path(directory, info.filename).resolve()
                    if Path(directory).resolve() not in target.parents:
                        raise PreviewError(f"unsafe path in frontend ZIP: {info.filename}")
                    archive.extract(info, directory)
            if not Path(directory, "Dockerfile").is_file():
                raise PreviewError("the generated frontend has no Dockerfile")
            lines: list[str] = []
            try:
                dockerfile_text = Path(directory, "Dockerfile").read_text(errors="replace")
                lock_path = Path(directory, "pnpm-lock.yaml")
                workspace_path = Path(directory, "pnpm-workspace.yaml")
                if lock_path.is_file() and "as deps" in dockerfile_text.lower():
                    hasher = hashlib.sha256()
                    hasher.update(lock_path.read_bytes())
                    if workspace_path.is_file():
                        hasher.update(workspace_path.read_bytes())
                    sha12 = hasher.hexdigest()[:12]
                    deps_tag = f"bga-fe-deps:{sha12}"
                    try:
                        self.client.images.get(deps_tag)
                    except ImageNotFound:
                        _, deps_stream = self.client.images.build(
                            path=directory,
                            target="deps",
                            tag=deps_tag,
                            rm=True,
                            forcerm=True,
                            labels={
                                "bga.preview": "deps",
                                LABEL: "deps",
                                INSTANCE_LABEL: instance_id(),
                                ROLE_LABEL: "deps",
                            },
                            timeout=config.preview_build_timeout_seconds,
                        )
                        lines.extend(chunk.get("stream", "") for chunk in deps_stream if isinstance(chunk, dict))

                _, stream = self.client.images.build(
                    path=directory,
                    tag=tag,
                    rm=True,
                    forcerm=True,
                    labels=_labels(generation_id, "image"),
                    timeout=config.preview_build_timeout_seconds,
                )
                lines.extend(chunk.get("stream", "") for chunk in stream if isinstance(chunk, dict))
                return "".join(lines)
            except BuildError as exc:
                log = "".join(chunk.get("stream", "") or chunk.get("error", "") for chunk in exc.build_log)
                raise PreviewError(f"frontend image build failed: {exc.msg}", log) from exc
            except APIError as exc:
                raise PreviewError(f"frontend image build failed: {exc}") from exc

    def _create_app(self, request: PreviewRequest, mode: str) -> Container:
        n = names(request.generation_id)
        port = PORTS.get(mode, 3000)
        environment = {}
        if mode == "dynamic":
            environment = {
                "MOCK_TEST_API": "true" if request.options.get("mockApi", True) else "false",
                "API_BASE_URL": request.options.get("apiBaseUrl", ""),
            }
        labels = {**_labels(request.generation_id, "app", mode), "bga.frontend.env": self._env_key(request)}
        ensure_egress_network(self.client)
        last_error: Exception | None = None
        for host_port in request.ports:
            container = self.client.containers.create(
                n["image"],
                name=n["app"],
                labels=labels,
                environment=environment,
                ports={f"{port}/tcp": (config.preview_bind_host, host_port)},
                restart_policy={"Name": "unless-stopped"},
                nano_cpus=int(config.preview_cpus * 1e9),
                mem_limit=_memory_bytes(config.preview_memory),
                pids_limit=256,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
            )
            try:
                container.start()
                try:
                    self.client.networks.get(config.sandbox_egress_network).connect(container)
                except APIError:
                    pass
                return container
            except APIError as exc:
                container.remove(force=True)
                if not any(marker in str(exc).lower() for marker in PORT_TAKEN):
                    raise PreviewError(f"frontend preview failed to start: {exc}") from exc
                last_error = exc
        raise PreviewError(f"no free host port for the frontend preview ({last_error})")

    def _wait_ready(self, app: Container, mode: str) -> None:
        probe = (
            ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"]
            if mode == "static"
            else ["node", "-e", NODE_PROBE]
        )
        deadline = time.monotonic() + config.preview_health_timeout_seconds
        while time.monotonic() < deadline:
            app.reload()
            if app.status in ("exited", "dead"):
                raise PreviewError("the frontend exited during startup", self._tail(app))
            if app.status == "running" and app.exec_run(probe).exit_code == 0:
                return
            time.sleep(1)
        raise PreviewError("the frontend did not answer in time", self._tail(app))

    @staticmethod
    def _tail(container: Container, lines: int = 80) -> str:
        try:
            return container.logs(tail=lines).decode(errors="replace")
        except APIError:
            return ""

    async def stop(self, generation_id: str) -> None:
        def run() -> None:
            app = self._get(names(generation_id)["app"])
            if app is not None and app.status == "running":
                app.stop(timeout=10)

        await asyncio.to_thread(run)

    async def remove_app(self, generation_id: str) -> None:
        def run() -> None:
            app = self._get(names(generation_id)["app"])
            if app is not None:
                try:
                    app.remove(force=True)
                except NotFound:
                    pass

        await asyncio.to_thread(run)

    async def drop_database(self, generation_id: str) -> None:
        """Frontends have no database."""

    async def remove(self, generation_id: str, keep_image: bool = False) -> None:
        await self.remove_app(generation_id)
        if not keep_image:

            def run() -> None:
                try:
                    self.client.images.remove(names(generation_id)["image"], force=True)
                except ImageNotFound:
                    pass

            await asyncio.to_thread(run)

    async def logs(self, generation_id: str, tail: int) -> list[str]:
        def run() -> list[str]:
            app = self._get(names(generation_id)["app"])
            if app is None:
                return []
            return app.logs(tail=tail, timestamps=True).decode(errors="replace").splitlines()

        return await asyncio.to_thread(run)

    async def request_log(self, generation_id: str, after: str | None, limit: int) -> list[dict[str, Any]]:
        return []  # browsers talk to the frontend directly; API calls are logged by the backend preview

    async def states(self) -> dict[str, PreviewState]:
        def run() -> dict[str, PreviewState]:
            selector = {"label": [LABEL, f"{INSTANCE_LABEL}={instance_id()}"]}
            result: dict[str, PreviewState] = {}
            for container in self.client.containers.list(all=True, filters=selector):
                labels = container.labels or {}
                if labels.get(ROLE_LABEL) == "app":
                    result[labels[LABEL]] = PreviewState(app=container.status, db=None, host_port=_host_port(container))
            return result

        return await asyncio.to_thread(run)

    async def probe(self, generation_id: str, method: str, path: str, body: Any = None) -> tuple[int, Any, bytes]:
        status, parsed, raw = await super().probe(generation_id, method, path, body)
        if status != 0:
            return status, parsed, raw

        def run_exec() -> tuple[int, Any, bytes]:
            import json

            app = self._get(names(generation_id)["app"])
            if app is None or app.status != "running":
                return 0, None, b""
            mode = (app.labels or {}).get("bga.frontend.mode", "dynamic")
            port = PORTS.get(mode, 3000)
            script = (
                f"fetch('http://127.0.0.1:{port}{path}', {{method: {method!r}}}).then(async r => {{"
                "const t = await r.text(); process.stdout.write(r.status + '\\n' + t);"
                "}).catch(() => process.exit(1))"
            )
            res = app.exec_run(["node", "-e", script])
            if res.exit_code != 0 or not res.output:
                return 0, None, b""
            code_line, _, rest = res.output.partition(b"\n")
            try:
                code = int(code_line.strip())
            except ValueError:
                return 0, None, b""
            try:
                doc = json.loads(rest.decode("utf-8", "replace"))
            except Exception:
                doc = rest.decode("utf-8", "replace")
            return code, doc, rest

        return await asyncio.to_thread(run_exec)
