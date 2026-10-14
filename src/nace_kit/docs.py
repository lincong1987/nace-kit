"""Document pipeline (parse / split / classify / extract / ground + jobs).

This module wraps the **official** ``nace-sdk`` (MIT) — the API surface is
theirs; nace-kit adds the operational layer: an API-key pool with rotation on
auth failures and rate limits, shared ``NACE_API_KEYS`` configuration, and one
place to meter from.

Install the extra once::

    pip install "nace-kit[docs]"

Then::

    from nace_kit import DocsClient

    docs = DocsClient()                       # keys from env, one client per key
    job = docs.parse("https://example.com/report.pdf",
                     output={"formats": ["markdown"]}, wait=120)
    job.result["document"]["markdown"]        # DocumentJob (official types)

Operations return the official SDK's typed ``DocumentJob`` objects. A failed
key (``NaceAuthenticationError``) or an exhausted one (``NaceRateLimitError``)
rotates to the next key automatically; every create is idempotency-keyed by
the official SDK, so a retried call never starts or bills a second job.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .client import NaceAuthError, default_keys

try:
    from nace_sdk import (
        DocumentJob,
        NaceAuthenticationError,
        NaceRateLimitError,
    )

    HAS_DOCS = True
except ImportError:
    HAS_DOCS = False

__all__ = ["AsyncDocsClient", "DocsClient", "HAS_DOCS", "require_docs"]

if HAS_DOCS:
    _ROTATE_ERRORS: tuple[type[BaseException], ...] = (NaceAuthenticationError, NaceRateLimitError)


def require_docs() -> None:
    """Raise a helpful error when the ``docs`` extra is not installed."""
    if not HAS_DOCS:
        raise NaceAuthError(
            'document pipeline needs the official SDK: pip install "nace-kit[docs]"'
        )


class _Pool:
    """One official SDK client per key; cycle on auth/rate-limit failures."""

    def __init__(
        self,
        keys: list[str] | str | None,
        base_url: str | None,
        timeout: float | None,
        async_client: bool,
    ) -> None:
        require_docs()
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        keys = list(keys) if keys else default_keys()
        if not keys:
            raise NaceAuthError("no API keys: pass keys= or set NACE_API_KEYS")
        from nace_sdk import AsyncNaceClient, NaceClient

        cls = AsyncNaceClient if async_client else NaceClient
        self._clients = [
            cls(api_key=k, **({"base_url": base_url} if base_url else {}), **({"timeout": timeout} if timeout else {}))
            for k in keys
        ]
        self._cycle = itertools.cycle(self._clients)


def _split_wait(wait: float | None) -> int | None:
    """Inline hold for the create call, capped at the server's 60s maximum."""
    return min(int(wait), 60) if wait and int(wait) > 0 else None


class DocsClient:
    """Sync document operations over a pool of official SDK clients."""

    def __init__(
        self,
        keys: list[str] | str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._pool = _Pool(keys, base_url, timeout, async_client=False)

    def _run(self, op: Callable[[Any], Any]) -> Any:
        last: BaseException | None = None
        for _ in range(len(self._pool._clients)):
            client = next(self._pool._cycle)
            try:
                return op(client)
            except _ROTATE_ERRORS as exc:
                last = exc
        raise NaceAuthError(f"all keys exhausted: {last}") from last

    def _create(self, call: Callable[[Any, int | None], DocumentJob], wait: float | None) -> DocumentJob:
        """Create on the current key; when ``wait`` is set, poll to a terminal
        state on the same key, so billing stays on the key that started the job."""

        def op(client: Any) -> DocumentJob:
            inline = _split_wait(wait)
            job = call(client, inline)
            if wait and not job.is_terminal:
                job = client.jobs.wait(job.job_id, timeout=max(0.0, float(wait) - (inline or 0)))
            return job

        return self._run(op)

    # -- document operations ------------------------------------------------

    def parse(self, source: Any, *, wait: float | None = None, **options: Any) -> DocumentJob:
        """Convert a document to Markdown / text / layout blocks.

        ``wait`` (seconds) holds the call until the job finishes; without it,
        follow up with :meth:`wait`.
        """
        return self._create(
            lambda c, ws: c.documents.parse(source, **({"wait_seconds": ws} if ws else {}), **options),
            wait,
        )

    def split(self, source: Any, *, classes: Sequence[Mapping[str, Any]], wait: float | None = None, **options: Any) -> DocumentJob:
        """Split a multi-document file by ``classes`` (``{"id","label","description"}``)."""
        return self._create(
            lambda c, ws: c.documents.split(source, classes=list(classes), **({"wait_seconds": ws} if ws else {}), **options),
            wait,
        )

    def classify_document(self, source: Any, *, classes: Sequence[Mapping[str, Any]], wait: float | None = None, **options: Any) -> DocumentJob:
        """Classify a document into one of ``classes``."""
        return self._create(
            lambda c, ws: c.documents.classify(source, classes=list(classes), **({"wait_seconds": ws} if ws else {}), **options),
            wait,
        )

    def extract(self, source: Any, *, schema: Mapping[str, Any] | None = None, schema_id: str | None = None, instructions: str | None = None, wait: float | None = None, **options: Any) -> DocumentJob:
        """Extract structured fields matching a JSON Schema (inline or saved)."""
        return self._create(
            lambda c, ws: c.documents.extract(
                source,
                schema=schema,
                schema_id=schema_id,
                instructions=instructions,
                **({"wait_seconds": ws} if ws else {}),
                **options,
            ),
            wait,
        )

    def ground(self, source: Any, *, items: Sequence[Any], wait: float | None = None, **options: Any) -> DocumentJob:
        """Locate ``items`` in the document, with citations back to the source."""
        return self._create(
            lambda c, ws: c.documents.ground(source, items=list(items), **({"wait_seconds": ws} if ws else {}), **options),
            wait,
        )

    # -- jobs ----------------------------------------------------------------

    def job(self, job_id: Any) -> DocumentJob:
        """Fetch one job's current state."""
        return self._run(lambda c: c.jobs.get(job_id))

    def jobs(self, *, operation: str | None = None, status: str | None = None) -> list[DocumentJob]:
        """The most recent jobs, optionally filtered (first page)."""
        return self._run(lambda c: list(c.jobs.list(operation=operation, status=status)))

    def wait(self, job_id: Any, *, timeout: float = 600.0) -> DocumentJob:
        """Poll until the job is terminal; raises on failure after ``timeout`` s."""
        return self._run(lambda c: c.jobs.wait(job_id, timeout=timeout))

    def delete(self, job_id: Any) -> None:
        self._run(lambda c: c.jobs.delete(job_id))


class AsyncDocsClient:
    """Async mirror of :class:`DocsClient` (official ``AsyncNaceClient`` pool)."""

    def __init__(
        self,
        keys: list[str] | str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._pool = _Pool(keys, base_url, timeout, async_client=True)

    async def _run(self, op: Callable[[Any], Any]) -> Any:
        last: BaseException | None = None
        for _ in range(len(self._pool._clients)):
            client = next(self._pool._cycle)
            try:
                return await op(client)
            except _ROTATE_ERRORS as exc:
                last = exc
        raise NaceAuthError(f"all keys exhausted: {last}") from last

    async def _create(self, call: Callable[[Any, int | None], Any], wait: float | None) -> DocumentJob:
        async def op(client: Any) -> DocumentJob:
            inline = _split_wait(wait)
            job = await call(client, inline)
            if wait and not job.is_terminal:
                job = await client.jobs.wait(job.job_id, timeout=max(0.0, float(wait) - (inline or 0)))
            return job

        return await self._run(op)

    async def parse(self, source: Any, *, wait: float | None = None, **options: Any) -> DocumentJob:
        return await self._create(
            lambda c, ws: c.documents.parse(source, **({"wait_seconds": ws} if ws else {}), **options),
            wait,
        )

    async def extract(self, source: Any, *, schema: Mapping[str, Any] | None = None, schema_id: str | None = None, instructions: str | None = None, wait: float | None = None, **options: Any) -> DocumentJob:
        return await self._create(
            lambda c, ws: c.documents.extract(
                source,
                schema=schema,
                schema_id=schema_id,
                instructions=instructions,
                **({"wait_seconds": ws} if ws else {}),
                **options,
            ),
            wait,
        )

    async def job(self, job_id: Any) -> DocumentJob:
        return await self._run(lambda c: c.jobs.get(job_id))

    async def wait(self, job_id: Any, *, timeout: float = 600.0) -> DocumentJob:
        return await self._run(lambda c: c.jobs.wait(job_id, timeout=timeout))
