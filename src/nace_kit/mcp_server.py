"""MCP server exposing nace.ai classification as agent tools (stdio transport).

Run with ``nace-kit-mcp`` (or ``uv --directory <path> run nace-kit-mcp``).
API keys come from the ``NACE_API_KEYS`` environment variable.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .client import NaceClient
from . import presets

mcp = _Server("nace")

_client: NaceClient | None = None


def _get_client() -> NaceClient:
    global _client
    if _client is None:
        _client = NaceClient()
    return _client


@mcp.tool()
def classify(state: Any, questions: dict[str, Any]) -> str:
    """Score text or JSON data with the nace.ai Drex classifier, calibrated probabilities out.

    Args:
        state: the text — or any JSON value — to analyse.
        questions: mapping of question name -> question spec (up to 512 per call).
            Three types, all answered in ONE upstream call:
            {"type": "noul", "instructions": "<yes/no question>",
             "criteria"? : {"true": "what counts as yes", "false": "..."}}
              -> {"noul": 0..1} (probability of yes)
            {"type": "choice", "instructions": "<question>",
             "criteria": {"label1": "what fits this label", "label2": null}}
              -> {"choice": "<label>", "probabilities": {...}, "confidence": ...}
            {"type": "score", "instructions": "<rating question>",
             "criteria": ["low", "medium", "high"]}
              -> {"score": float (index into criteria), "probabilities", "confidence"}
            Example: {"is_urgent": {"type": "noul", "instructions": "Does this convey urgency?"}}

    Returns JSON: {"model", "answers", "usage", "evaluation_time_ms", "latency_ms", "request_id"}.
    Choose your own threshold on the probabilities rather than treating them as a verdict.
    """
    result = _get_client().classify(state, questions)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def ask(
    state: Any,
    question: str = "Does this convey urgency?",
    kind: str = "noul",
    levels: list[str] | None = None,
    options: dict[str, str] | None = None,
) -> str:
    """Ask ONE simple question about a text; convenience wrapper over `classify`.

    Args:
        state: the text — or any JSON value — to analyse.
        question: what to judge, e.g. "Is the user angry?".
        kind: "noul" (0..1 yes-score), "score" (ordered levels) or "choice" (pick a label).
        levels: ordered level labels for kind="score", e.g. ["calm", "annoyed", "angry"].
        options: {label: description} for kind="choice", e.g. {"billing": "payment issues", "technical": "bugs"}.

    Returns JSON with the answer (noul score, or choice/score + probabilities).
    """
    if kind == "noul":
        q = presets.noul(question)
    elif kind == "score":
        q = presets.score(question, levels or ["low", "medium", "high"])
    elif kind == "choice":
        q = presets.choice(question, options or {"yes": None, "no": None})
    else:
        return json.dumps({"error": f"unknown kind '{kind}': use noul, score or choice"})
    result = _get_client().classify(state, q)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_models() -> str:
    """List the Drex decision models available to this account, for choosing a
    model (drex-latest is the default). Works at any balance, so it also
    serves as a key health check."""
    result = _get_client().models()
    return json.dumps(result, ensure_ascii=False)


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
