"""Provider errors."""

from __future__ import annotations


class ModelProviderError(RuntimeError):
    """Raised when a provider cannot complete a request."""
