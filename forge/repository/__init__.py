"""Deterministic repository inspection services."""

from forge.repository.detect import RepositoryDetection, detect_repository
from forge.repository.files import list_relevant_files
from forge.repository.grep import GrepMatch, search_repository
from forge.repository.tree import generate_tree

__all__ = [
    "GrepMatch",
    "RepositoryDetection",
    "detect_repository",
    "generate_tree",
    "list_relevant_files",
    "search_repository",
]
