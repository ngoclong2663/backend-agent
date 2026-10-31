"""Docker implementation of preview containers (Story 7.3).

Per generation:

    host 127.0.0.1:<port> ──▶ bga-preview-<gen>      image bga-gen-<gen>:latest, built from backend.zip
                                  │ network bga-preview-net-<gen>
                                  ▼
                              bga-preview-db-<gen>   postgres:18, volume bga-preview-db-<gen>

The image is built from the packaged ZIP (not the workspace), so a preview can be rebuilt after the workspace
is cleaned up, and every preview proves that the ZIP starts on its own. Credentials are derived from
JWT_SECRET + generation id: stable across restarts, different per preview, never stored.
"""

import asyncio
import hashlib
import hmac
import io
import json
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, BuildError, ImageNotFound, NotFound
from docker.models.containers import Container

from src.configs import config, get_logger
from src.libs.redaction import Redactor, default_redactor
from src.sandbox.docker_sandbox import INSTANCE_LABEL, ensure_egress_network, instance_id

from .port import IPreviewRuntime, PreviewError, PreviewHandle, PreviewRequest, PreviewState

logger = get_logger(__name__)
LABEL = "bga.preview"
ROLE_LABEL = "bga.role"
APP_PORT = 8000
DB_USER = "app"
SEED_PATH = "/app/seed.json"
HEALTH_PROBE = f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{APP_PORT}/health', timeout=2)"
PORT_TAKEN = ("port is already allocated", "address already in use", "bind for")


def _slug(generation_id: str) -> str:
    return generation_id.lower()


def names(generation_id: str) -> dict[str, str]:
    slug = _slug(generation_id)
    return {
        "image": f"bga-gen-{slug}:latest",
        "network": f"bga-preview-net-{slug}",
        "app": f"bga-preview-{slug}",
        "db": f"bga-preview-db-{slug}",
        "volume": f"bga-preview-db-{slug}",
    }


def secret(generation_id: str, purpose: str) -> str:
    return hmac.new(config.jwt_secret.encode(), f"{purpose}:{generation_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _labels(generation_id: str, role: str) -> dict[str, str]:
    return {LABEL: generation_id, INSTANCE_LABEL: instance_id(), ROLE_LABEL: role}


def _memory_bytes(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    value = value.strip().lower()
    return int(float(value[:-1]) * units[value[-1]]) if value[-1] in units else int(value)


def _host_port(container: Container) -> int | None:
    bindings = (container.attrs.get("HostConfig") or {}).get("PortBindings") or {}
    for binding in bindings.get(f"{APP_PORT}/tcp") or []:
        if binding.get("HostPort"):
            return int(binding["HostPort"])
    return None


def parse_request_lines(text: str, after: str | None) -> list[dict[str, Any]]:
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue  # uvicorn's own plain-text lines
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("message") != "request" or not entry.get("ts") or entry.get("method") == "OPTIONS":
            continue  # OPTIONS = browser CORS preflights, not calls the user made
        if after and entry["ts"] <= after:
            continue
        items.append(
            {
                "ts": entry["ts"],
                "method": entry.get("method"),
                "path": entry.get("path"),
                "route": entry.get("route"),
                "operationId": entry.get("operationId"),
                "status": entry.get("status"),
                "durationMs": entry.get("durationMs"),
            }
        )
    return items


class DockerPreviewRuntime(IPreviewRuntime):
    def __init__(self, client: docker.DockerClient | None = None):
        self.client = client or docker.from_env()

    def _redactor(self, generation_id: str) -> Redactor:
        return default_redactor().with_secrets(secret(generation_id, "db"), secret(generation_id, "jwt"))

    def _get(self, name: str) -> Container | None:
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    # -- deploy -------------------------------------------------------------------------------------------------

    async def deploy(self, request: PreviewRequest) -> PreviewHandle:
        return await asyncio.to_thread(self._deploy, request)

    def _deploy(self, request: PreviewRequest) -> PreviewHandle:
        n = names(request.generation_id)
        build_log = self._ensure_image(request.generation_id, request.source_zip)
        self._ensure_network(request.generation_id)
        db = self._ensure_db(request.generation_id)
        app = self._get(n["app"])
        cors = request.options.get("corsOrigins") or config.preview_cors_origins
        if app is not None and (app.labels or {}).get("bga.backend.cors") not in (None, cors):
            app.remove(force=True)
            app = None
        if app is None:
            app = self._create_app(request)
        elif app.status != "running":
            try:
                app.start()
            except APIError as exc:
                if not any(marker in str(exc).lower() for marker in PORT_TAKEN):
                    raise PreviewError(f"preview container failed to start: {exc}") from exc
                app.remove(force=True)  # its port was taken meanwhile: recreate on a free one
                app = self._create_app(request)
        self._wait_healthy(request.generation_id, app)
        app.reload()
        return PreviewHandle(
            container_id=app.id, db_container_id=db.id, host_port=_host_port(app) or 0, build_log=build_log
        )

    def _ensure_image(self, generation_id: str, source_zip: Path) -> str | None:
        tag = names(generation_id)["image"]
        try:
            self.client.images.get(tag)
            return None
        except ImageNotFound:
            pass
        with tempfile.TemporaryDirectory(prefix="bga-preview-") as directory:
            with zipfile.ZipFile(source_zip) as archive:
                for info in archive.infolist():
                    target = Path(directory, info.filename).resolve()
                    if Path(directory).resolve() not in target.parents:
                        raise PreviewError(f"unsafe path in source ZIP: {info.filename}")
                    archive.extract(info, directory)
                    mode = info.external_attr >> 16
                    if mode & 0o111:
                        target.chmod(0o755)
            if not Path(directory, "Dockerfile").is_file():
                raise PreviewError("the generated project has no Dockerfile (generateDockerfile=false)")
            lines: list[str] = []
            try:
                dockerfile_text = Path(directory, "Dockerfile").read_text(errors="replace")
                req_path = Path(directory, "requirements.txt")
                if req_path.is_file() and "as deps" in dockerfile_text.lower():
                    sha12 = hashlib.sha256(req_path.read_bytes()).hexdigest()[:12]
                    deps_tag = f"bga-be-deps:{sha12}"
                    try:
                        self.client.images.get(deps_tag)
                    except ImageNotFound:
                        _, deps_stream = self.client.images.build(
                            path=directory,
                            target="deps",
                            tag=deps_tag,
                            rm=True,
                            forcerm=True,
                            labels={LABEL: "deps", INSTANCE_LABEL: instance_id(), ROLE_LABEL: "deps"},
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
            except BuildError as exc:
                log = "".join(chunk.get("stream", "") or chunk.get("error", "") for chunk in exc.build_log)
                raise PreviewError(f"image build failed: {exc.msg}", log) from exc
            except APIError as exc:
                raise PreviewError(f"image build failed: {exc}") from exc
        return "".join(lines)

    def _ensure_network(self, generation_id: str) -> None:
        name = names(generation_id)["network"]
        if not self.client.networks.list(names=[name]):
            # Not internal: Docker only publishes ports from non-internal networks.
            self.client.networks.create(name, driver="bridge", labels=_labels(generation_id, "network"))

    def _ensure_db(self, generation_id: str) -> Container:
        n = names(generation_id)
        db = self._get(n["db"])
        if db is None:
            db = self.client.containers.run(
                config.sandbox_db_image,
                name=n["db"],
                detach=True,
                network=n["network"],
                labels=_labels(generation_id, "db"),
                environment={
                    "POSTGRES_USER": DB_USER,
                    "POSTGRES_PASSWORD": secret(generation_id, "db"),
                    "POSTGRES_DB": "app",
                },
                volumes={n["volume"]: {"bind": "/var/lib/postgresql", "mode": "rw"}},
                restart_policy={"Name": "unless-stopped"},
                mem_limit="512m",
                pids_limit=256,
            )
        elif db.status != "running":
            db.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if db.exec_run(["pg_isready", "-h", "127.0.0.1", "-U", DB_USER, "-d", "app"]).exit_code == 0:
                return db
            time.sleep(0.5)
        raise PreviewError("preview PostgreSQL did not become ready", self._tail(db))

    def _create_app(self, request: PreviewRequest) -> Container:
        n = names(request.generation_id)
        cors = request.options.get("corsOrigins") or config.preview_cors_origins
        environment = {
            "DB_URL": f"postgresql://{DB_USER}:{secret(request.generation_id, 'db')}@{n['db']}:5432/app",
            "JWT_SECRET": secret(request.generation_id, "jwt"),
            "CORS_ORIGINS": cors,
            "PORT": str(APP_PORT),
            "LOG_LEVEL": "INFO",
        }
        if request.seed is not None:
            environment["SEED_FILE"] = SEED_PATH
        labels = {**_labels(request.generation_id, "app"), "bga.backend.cors": cors}
        ensure_egress_network(self.client)
        last_error: Exception | None = None
        for port in request.ports:
            container = self.client.containers.create(
                n["image"],
                name=n["app"],
                network=n["network"],
                labels=labels,
                environment=environment,
                ports={f"{APP_PORT}/tcp": (config.preview_bind_host, port)},
                restart_policy={"Name": "unless-stopped"},
                nano_cpus=int(config.preview_cpus * 1e9),
                mem_limit=_memory_bytes(config.preview_memory),
                pids_limit=256,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
            )
            if request.seed is not None:
                container.put_archive("/app", _tar("seed.json", request.seed))
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
                    raise PreviewError(f"preview container failed to start: {exc}") from exc
                last_error = exc
        raise PreviewError(f"no free host port for the preview ({last_error})")

    def _wait_healthy(self, generation_id: str, app: Container) -> None:
        deadline = time.monotonic() + config.preview_health_timeout_seconds
        while time.monotonic() < deadline:
            app.reload()
            if app.status in ("exited", "dead"):
                raise PreviewError("the backend exited during startup", self._tail(app, generation_id))
            if app.status == "running" and app.exec_run(["python", "-c", HEALTH_PROBE]).exit_code == 0:
                return
            time.sleep(1)
        raise PreviewError("the backend did not answer GET /health in time", self._tail(app, generation_id))

    def _tail(self, container: Container, generation_id: str | None = None, lines: int = 80) -> str:
        try:
            text = container.logs(tail=lines).decode(errors="replace")
        except APIError:
            return ""
        return self._redactor(generation_id).redact(text) if generation_id else text

    # -- lifecycle ----------------------------------------------------------------------------------------------

    async def stop(self, generation_id: str) -> None:
        await asyncio.to_thread(self._stop, generation_id)

    def _stop(self, generation_id: str) -> None:
        n = names(generation_id)
        for name in (n["app"], n["db"]):
            container = self._get(name)
            if container is not None and container.status == "running":
                container.stop(timeout=10)

    async def remove_app(self, generation_id: str) -> None:
        await asyncio.to_thread(self._remove_container, names(generation_id)["app"])

    def _remove_container(self, name: str) -> None:
        container = self._get(name)
        if container is not None:
            logger.info("removing preview container", extra={"container": name, "status": container.status})
            try:
                container.remove(force=True)
            except NotFound:
                pass

    async def drop_database(self, generation_id: str) -> None:
        await asyncio.to_thread(self._drop_database, generation_id)

    def _drop_database(self, generation_id: str) -> None:
        n = names(generation_id)
        app = self._get(n["app"])
        if app is not None and app.status == "running":
            app.stop(timeout=10)
        self._remove_container(n["db"])
        try:
            self.client.volumes.get(n["volume"]).remove(force=True)
        except NotFound:
            pass

    async def remove(self, generation_id: str, keep_image: bool = False) -> None:
        await asyncio.to_thread(self._remove, generation_id, keep_image)

    def _remove(self, generation_id: str, keep_image: bool) -> None:
        n = names(generation_id)
        self._remove_container(n["app"])
        self._remove_container(n["db"])
        for network in self.client.networks.list(names=[n["network"]]):
            try:
                network.remove()
            except (NotFound, APIError):
                pass
        try:
            self.client.volumes.get(n["volume"]).remove(force=True)
        except NotFound:
            pass
        if not keep_image:
            try:
                self.client.images.remove(n["image"], force=True)
            except ImageNotFound:
                pass

    # -- observation --------------------------------------------------------------------------------------------

    async def logs(self, generation_id: str, tail: int) -> list[str]:
        def run() -> list[str]:
            app = self._get(names(generation_id)["app"])
            if app is None:
                return []
            text = app.logs(tail=tail, timestamps=True).decode(errors="replace")
            return self._redactor(generation_id).redact(text).splitlines()

        return await asyncio.to_thread(run)

    async def request_log(self, generation_id: str, after: str | None, limit: int) -> list[dict[str, Any]]:
        def run() -> list[dict[str, Any]]:
            app = self._get(names(generation_id)["app"])
            if app is None:
                return []
            since = None
            if after:
                try:
                    since = datetime.fromisoformat(after).timestamp() - 1
                except ValueError:
                    since = None
            text = app.logs(since=since, stdout=True, stderr=True) if since else app.logs()
            return parse_request_lines(text.decode(errors="replace"), after)[:limit]

        return await asyncio.to_thread(run)

    async def states(self) -> dict[str, PreviewState]:
        def run() -> dict[str, PreviewState]:
            selector = {"label": [LABEL, f"{INSTANCE_LABEL}={instance_id()}"]}
            result: dict[str, PreviewState] = {}
            for container in self.client.containers.list(all=True, filters=selector):
                labels = container.labels or {}
                state = result.setdefault(labels[LABEL], PreviewState(app=None, db=None))
                if labels.get(ROLE_LABEL) == "app":
                    state.app, state.host_port = container.status, _host_port(container)
                elif labels.get(ROLE_LABEL) == "db":
                    state.db = container.status
            return result

        return await asyncio.to_thread(run)

    async def probe(self, generation_id: str, method: str, path: str, body: Any = None) -> tuple[int, Any, bytes]:
        status, parsed, raw = await super().probe(generation_id, method, path, body)
        if status != 0:
            return status, parsed, raw

        def run_exec() -> tuple[int, Any, bytes]:
            app = self._get(names(generation_id)["app"])
            if app is None or app.status != "running":
                return 0, None, b""
            payload = json.dumps(body) if body is not None else "None"
            script = (
                "import json, sys, urllib.error, urllib.request\n"
                f"data = {payload!r}.encode() if {body is not None} else None\n"
                f"headers = {{'content-type': 'application/json'}} if data else {{}}\n"
                f"url = 'http://127.0.0.1:{APP_PORT}{path}'\n"
                f"req = urllib.request.Request(url, data=data, headers=headers, method={method!r})\n"
                "try:\n"
                "    with urllib.request.urlopen(req, timeout=10) as r:\n"
                "        sys.stdout.write(str(r.status) + '\\n' + r.read().decode('utf-8', 'replace'))\n"
                "except urllib.error.HTTPError as e:\n"
                "    sys.stdout.write(str(e.code) + '\\n' + e.read().decode('utf-8', 'replace'))\n"
                "except Exception:\n"
                "    sys.exit(1)\n"
            )
            res = app.exec_run(["python", "-c", script])
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


def _tar(name: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size, info.mode = len(data), 0o644
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()
