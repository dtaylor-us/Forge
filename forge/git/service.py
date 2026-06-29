"""Git repository inspection and controlled patch application service."""

from __future__ import annotations

import subprocess
from pathlib import Path

from forge.git.models import GitStatus


class GitServiceError(Exception):
    pass


class GitService:
    """Centralizes all git command execution. Never commits or creates branches."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = cwd or Path.cwd()

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._cwd,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.rstrip("\n")
        except subprocess.CalledProcessError as exc:
            raise GitServiceError(exc.stderr.strip() or str(exc)) from exc
        except FileNotFoundError as exc:
            raise GitServiceError("git executable not found") from exc

    def is_git_repository(self) -> bool:
        try:
            self._run("rev-parse", "--git-dir")
            return True
        except GitServiceError:
            return False

    def root(self) -> str:
        return self._run("rev-parse", "--show-toplevel")

    def branch(self) -> str:
        try:
            return self._run("symbolic-ref", "--short", "HEAD")
        except GitServiceError:
            return self._run("rev-parse", "--short", "HEAD")

    def commit(self) -> str:
        return self._run("rev-parse", "--short", "HEAD")

    def status(self) -> GitStatus:
        if not self.is_git_repository():
            return GitStatus(is_git_repository=False)

        try:
            root = self.root()
            branch = self.branch()
            commit = self.commit()
            raw = self._run("status", "--porcelain")
        except GitServiceError as exc:
            raise GitServiceError(str(exc)) from exc

        staged: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        untracked: list[str] = []

        for line in raw.splitlines():
            if len(line) < 3:
                continue
            index_status = line[0]
            worktree_status = line[1]
            path = line[3:]

            if index_status in ("A", "M", "R", "C"):
                staged.append(path)
            if worktree_status == "M":
                modified.append(path)
            elif worktree_status == "D":
                deleted.append(path)
            if index_status == "?" and worktree_status == "?":
                untracked.append(path)
            elif index_status == "D" and worktree_status == " ":
                deleted.append(path)

        clean = not (staged or modified or deleted or untracked)

        return GitStatus(
            is_git_repository=True,
            root=root,
            branch=branch,
            commit=commit,
            clean=clean,
            staged_files=staged,
            modified_files=modified,
            deleted_files=deleted,
            untracked_files=untracked,
        )

    def apply_check(self, patch_path: Path) -> None:
        """Dry-run git apply to verify a patch can be applied. Raises GitServiceError on failure."""
        self._run("apply", "--check", str(patch_path))

    def apply(self, patch_path: Path) -> None:
        """Apply a patch file to the working tree. Never commits."""
        self._run("apply", str(patch_path))
