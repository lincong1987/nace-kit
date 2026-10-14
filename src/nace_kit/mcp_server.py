"""MCP server exposing nace.ai classification and documents as agent tools.

Run with ``nace-kit-mcp`` (or ``uv --directory <path> run nace-kit-mcp``).
API keys come from the ``NACE_API_KEYS`` environment variable. The document
tools need the optional extra: ``pip install "nace-kit[docs]"``.
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
_docs: Any = None  # DocsClient, created lazily on first document call


def _get_client() -> NaceClient:
    global _client
    if _client is None:
        _client = NaceClient()
    return _client


def _get_docs() -> Any:
    global _docs
    if _docs is None:
        from .docs import DocsClient, require_docs

        require_docs()  # helpful error before touching keys
        _docs = DocsClient()
    return _docs


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=lambda o: o.model_dump(mode="json"))


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
    return _json(_get_client().classify(state, questions))


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
        return _json({"error": f"unknown kind '{kind}': use noul, score or choice"})
    return _json(_get_client().classify(state, q))


@mcp.tool()
def list_models() -> str:
    """List the Drex decision models available to this account, for choosing a
    model (drex-latest is the default). Works at any balance, so it also
    serves as a key health check."""
    return _json(_get_client().models())


@mcp.tool()
def parse_document(url: str, wait: float = 120, output_format: str = "markdown") -> str:
    """Parse a document (PDF, DOCX, XLSX, ...) from an https URL into Markdown,
    text or layout blocks. Needs the "docs" extra installed server-side.

    Args:
        url: https URL of the document; its last path segment must have a file extension.
        wait: seconds to hold the call until the job finishes (poll continues server-side).
        output_format: "markdown", "text" or "layout".

    Returns JSON of the finished job; markdown is in result.document.markdown.
    """
    docs = _get_docs()
    job = docs.parse(url, output={"formats": [output_format]}, wait=wait)
    return _json(job.model_dump(mode="json"))


@mcp.tool()
def extract_data(url: str, schema: dict[str, Any], instructions: str | None = None, wait: float = 120) -> str:
    """Extract structured fields from a document at an https URL, matching a
    JSON Schema. Needs the "docs" extra installed server-side.

    Args:
        url: https URL of the document.
        schema: JSON Schema object describing the fields to extract, e.g.
            {"type": "object", "properties": {"total": {"type": "number"}, "vendor": {"type": "string"}}}.
        instructions: optional extra guidance for the extractor.
        wait: seconds to hold the call until the job finishes.

    Returns JSON of the finished job; fields are in result.fields.
    """
    docs = _get_docs()
    job = docs.extract(url, schema=schema, instructions=instructions, wait=wait)
    return _json(job.model_dump(mode="json"))


@mcp.tool()
def get_document_job(job_id: str) -> str:
    """Fetch the current state of a document job by id (status, result, error)."""
    return _json(_get_docs().job(job_id).model_dump(mode="json"))


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
