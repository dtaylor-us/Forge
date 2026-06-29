"""Data models for Git repository state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GitStatus:
    is_git_repository: bool
    root: str | None = None
    branch: str | None = None
    commit: str | None = None
    clean: bool = True
    staged_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_git_repository": self.is_git_repository,
            "root": self.root,
            "branch": self.branch,
            "commit": self.commit,
            "clean": self.clean,
            "staged_files": self.staged_files,
            "modified_files": self.modified_files,
            "deleted_files": self.deleted_files,
            "untracked_files": self.untracked_files,
        }
