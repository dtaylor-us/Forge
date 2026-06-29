"""Forge path computation — global and project-local."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_GLOBAL_DIR_NAME = ".forge"
_PROJECT_DIR_NAME = ".forge"

_SUBDIRS = (
    "worksets",
    "summaries",
    "context",
    "architecture",
    "sessions",
    "cache",
    "plans",
    "memory",
    "patches",
)


def global_forge_dir() -> Path:
    """Return ~/.forge — global Forge configuration directory."""
    return Path.home() / _GLOBAL_DIR_NAME


@dataclass(frozen=True)
class ForgePaths:
    """All significant Forge paths for a given repository root."""

    global_config_path: Path
    global_forge_dir: Path
    repo_root: Path
    project_forge_dir: Path
    worksets_dir: Path
    summaries_dir: Path
    context_dir: Path
    architecture_dir: Path
    sessions_dir: Path
    cache_dir: Path
    plans_dir: Path
    memory_dir: Path
    patches_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> ForgePaths:
        g = global_forge_dir()
        p = root / _PROJECT_DIR_NAME
        return cls(
            global_config_path=g / "config.yaml",
            global_forge_dir=g,
            repo_root=root,
            project_forge_dir=p,
            worksets_dir=p / "worksets",
            summaries_dir=p / "summaries",
            context_dir=p / "context",
            architecture_dir=p / "architecture",
            sessions_dir=p / "sessions",
            cache_dir=p / "cache",
            plans_dir=p / "plans",
            memory_dir=p / "memory",
            patches_dir=p / "patches",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "global_config_path": str(self.global_config_path),
            "global_forge_dir": str(self.global_forge_dir),
            "repo_root": str(self.repo_root),
            "project_forge_dir": str(self.project_forge_dir),
            "worksets_dir": str(self.worksets_dir),
            "summaries_dir": str(self.summaries_dir),
            "context_dir": str(self.context_dir),
            "architecture_dir": str(self.architecture_dir),
            "sessions_dir": str(self.sessions_dir),
            "cache_dir": str(self.cache_dir),
            "plans_dir": str(self.plans_dir),
            "memory_dir": str(self.memory_dir),
            "patches_dir": str(self.patches_dir),
        }
