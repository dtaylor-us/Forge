"""Project identity, path resolution, and metadata."""

from forge.project.paths import ForgePaths, global_forge_dir
from forge.project.resolver import ResolvedRoot, resolve_root

__all__ = ["ForgePaths", "ResolvedRoot", "global_forge_dir", "resolve_root"]
