"""nace-kit: community client, presets and MCP server for the nace.ai Drex API."""

from .client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AsyncNaceClient,
    NaceAuthError,
    NaceBadRequest,
    NaceClient,
    NaceError,
    check_key_format,
    normalize_questions,
)
from . import presets

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "AsyncNaceClient",
    "NaceAuthError",
    "NaceBadRequest",
    "NaceClient",
    "NaceError",
    "check_key_format",
    "normalize_questions",
    "presets",
    "__version__",
]
