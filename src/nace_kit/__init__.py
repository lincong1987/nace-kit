"""nace-kit: community toolkit for the nace.ai Drex API — key-pool client,
typed questions/answers, presets, CLI, MCP server, and (with the ``docs``
extra) the document pipeline over the official SDK."""

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
from . import docs as docs
from . import presets as presets
from . import types as types
from .docs import HAS_DOCS
from .types import (
    Choice,
    ChoiceAnswer,
    ClassifyResult,
    ModelInfo,
    ModelsResult,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
    Usage,
)

if HAS_DOCS:
    from .docs import AsyncDocsClient, DocsClient

__version__ = "0.3.0"

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "AsyncNaceClient",
    "Choice",
    "ChoiceAnswer",
    "ClassifyResult",
    "ModelInfo",
    "ModelsResult",
    "NaceAuthError",
    "NaceBadRequest",
    "NaceClient",
    "NaceError",
    "Noul",
    "NoulAnswer",
    "Score",
    "ScoreAnswer",
    "Usage",
    "check_key_format",
    "docs",
    "has_docs",
    "normalize_questions",
    "presets",
    "types",
    "__version__",
]


def has_docs() -> bool:
    """Whether the document pipeline is available (``pip install "nace-kit[docs]"``)."""
    return HAS_DOCS


if HAS_DOCS:
    __all__ += ["AsyncDocsClient", "DocsClient"]
