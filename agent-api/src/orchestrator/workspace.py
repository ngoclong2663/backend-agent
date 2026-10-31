import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.engines.workspace import ensure_inside

# safe.directory: sandbox containers (another uid) also write into the project.
_GIT = [
    "git",
    "-c",
    "user.name=bga",
    "-c",
    "user.email=bga@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "safe.directory=*",
]


# Rebuildable directories that do not count toward the workspace size limit.
SIZE_EXCLUDES = {".venv", "node_modules", ".next", "out", "test-results", "playwright-report"}


class DiskLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class JobWorkspace:
    root: Path

    @property
    def project(self) -> Path:
        return self.root / "project"

    @property
    def frontend(self) -> Path:
        """The generated frontend (Epic 13): its own git repository next to the backend project."""
        return self.root / "frontend"

    def repo(self, name: str = "project") -> Path:
        return self.frontend if name == "frontend" else self.project

    @property
    def spec_dir(self) -> Path:
        return self.root / "spec"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def state(self) -> Path:
        """Engine homes and logs: outside the project so they never end up in the generated code."""
        return self.root / "state"


class WorkspaceManager:
    def __init__(self, root: Path, max_mb: int):
        self.root = root
        self.max_mb = max_mb

    def path_for(self, generation_id: str) -> JobWorkspace:
        return JobWorkspace(ensure_inside(self.root / generation_id, self.root))

    def create(self, generation_id: str) -> JobWorkspace:
        workspace = self.path_for(generation_id)
        for directory in (workspace.project, workspace.spec_dir, workspace.reports, workspace.state):
            directory.mkdir(parents=True, exist_ok=True)
        workspace.root.chmod(0o700)
        if not (workspace.project / ".git").exists():
            self._git(workspace, "init", "-q", "-b", "main")
            self._git(workspace, "commit", "-q", "--allow-empty", "-m", "workspace created")
        return workspace

    def create_frontend(self, workspace: JobWorkspace) -> Path:
        """The frontend repository, created on first use (static and dynamic modes)."""
        workspace.frontend.mkdir(parents=True, exist_ok=True)
        if not (workspace.frontend / ".git").exists():
            self._git(workspace, "init", "-q", "-b", "main", repo="frontend")
            self._git(workspace, "commit", "-q", "--allow-empty", "-m", "frontend created", repo="frontend")
        return workspace.frontend

    def commit(
        self, workspace: JobWorkspace, message: str, repo: str = "project", paths: list[str] | None = None
    ) -> str:
        if paths:
            repo_dir = workspace.repo(repo)
            valid_paths: list[str] = []
            for p in paths:
                if p.startswith(":!"):
                    valid_paths.append(p)
                elif (repo_dir / p).exists():
                    res = subprocess.run([*_GIT, "check-ignore", "-q", "--", p], cwd=repo_dir, check=False)
                    if res.returncode != 0:
                        valid_paths.append(p)
                else:
                    status = self._git(workspace, "status", "--porcelain", "--", p, repo=repo).strip()
                    if status:
                        valid_paths.append(p)
            if valid_paths:
                self._git(workspace, "add", "-A", "--", *valid_paths, repo=repo)
        else:
            self._git(workspace, "add", "-A", repo=repo)
        self._git(workspace, "commit", "-q", "--allow-empty", "-m", message, repo=repo)
        return self._git(workspace, "rev-parse", "HEAD", repo=repo).strip()

    def reset_to(self, workspace: JobWorkspace, sha: str, repo: str = "project") -> None:
        """Drops anything a crashed node half-wrote, back to the last node that completed. In the frontend the
        ignored dependency and build output (node_modules, .next) is kept: it is slow to recreate."""
        self._git(workspace, "reset", "-q", "--hard", sha, repo=repo)
        self._git(workspace, "clean", "-q", "-fd" if repo == "frontend" else "-fdx", repo=repo)

    def repair_patches(
        self, workspace: JobWorkspace, repo: str = "project", node: str = "repair_code", prefix: str = "repair"
    ) -> list[tuple[str, str]]:
        """(name, diff) per `node:<node>` commit, oldest first: what each repair attempt changed."""
        if not (workspace.repo(repo) / ".git").exists():
            return []
        log = self._git(workspace, "log", "--reverse", "--format=%H %s", f"--grep=^node:{node} ", repo=repo)
        patches = []
        for line in log.splitlines():
            sha, _, subject = line.partition(" ")
            attempt = subject.rsplit("attempt:", 1)[-1]
            diff = self._git(workspace, "show", "--format=", "--binary", sha, repo=repo)
            patches.append((f"{prefix}-{attempt}.patch", diff))
        return patches

    def node_commit(self, workspace: JobWorkspace, pattern: str, repo: str = "project") -> str | None:
        """The latest commit whose subject matches `pattern` (e.g. `^node:scaffold$`), or None."""
        sha = self._git(workspace, "log", "-1", "--format=%H", "-E", f"--grep={pattern}", repo=repo).strip()
        return sha or None

    def file_at(self, workspace: JobWorkspace, sha: str, path: str, repo: str = "project") -> bytes | None:
        completed = subprocess.run(
            [*_GIT, "show", f"{sha}:{path}"], cwd=workspace.repo(repo), capture_output=True, check=False, timeout=120
        )
        return completed.stdout if completed.returncode == 0 else None

    def checkout_paths(self, workspace: JobWorkspace, sha: str, paths: list[str], repo: str = "project") -> None:
        """Puts `paths` back as they were at `sha` (content and mode)."""
        if paths:
            self._git(workspace, "checkout", sha, "--", *paths, repo=repo)

    def head_stats(self, workspace: JobWorkspace, repo: str = "project") -> dict[str, int]:
        """Files, insertions and deletions of the last commit (a repair attempt's diff stats, Story 8.2)."""
        stats = {"files": 0, "insertions": 0, "deletions": 0}
        for line in self._git(workspace, "show", "--numstat", "--format=", "HEAD", repo=repo).splitlines():
            added, deleted, _ = (line.split("\t", 2) + ["", ""])[:3]
            stats["files"] += 1
            stats["insertions"] += int(added) if added.isdigit() else 0
            stats["deletions"] += int(deleted) if deleted.isdigit() else 0
        return stats

    def check_size(self, workspace: JobWorkspace) -> int:
        size = sum(
            path.stat().st_size
            for path in workspace.root.rglob("*")
            if path.is_file() and not path.is_symlink() and not SIZE_EXCLUDES & set(path.parts)
        )
        megabytes = size // (1024 * 1024)
        if megabytes > self.max_mb:
            raise DiskLimitExceeded(f"Workspace uses {megabytes} MB (limit {self.max_mb} MB)")
        return megabytes

    def delete(self, generation_id: str) -> None:
        shutil.rmtree(self.path_for(generation_id).root, ignore_errors=True)

    def existing_ids(self) -> list[str]:
        return [path.name for path in self.root.iterdir() if path.is_dir()] if self.root.exists() else []

    @staticmethod
    def _git(workspace: JobWorkspace, *args: str, repo: str = "project") -> str:
        completed = subprocess.run(
            [*_GIT, *args], cwd=workspace.repo(repo), capture_output=True, text=True, check=False, timeout=120
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {completed.stderr.strip()[:500]}")
        return completed.stdout
