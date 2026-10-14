"""Client for the nace.ai Drex API (SystemOne classification + model listing).

What this adds over the official ``nace-sdk``:

- **API-key pool**: several keys with automatic rotation — 401/403 (dead or
  bad key) and 429 (out of quota on this key) move to the next key at once.
- **In-key retries with backoff**: transient failures (408/5xx, network and
  timeout errors) are retried on the same key with exponential backoff and
  jitter, honouring ``Retry-After`` headers, inside a total time budget.
  With a single configured key, 429 is also retried this way.
- **LRU response cache**: upstream answers are deterministic for identical
  input, so repeats are served for free.
- **Per-key usage accounting**: calls / input / output tokens per key.
- **Key format validation** at construction time (``nace_sk_`` + 43 chars).

Keys come from the ``keys`` argument, or the ``NACE_API_KEYS`` environment
variable (comma-separated); ``NACE_API_KEY`` is also accepted.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import os
import random
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://console.nace.ai/v1"
DEFAULT_MODEL = "drex-latest"
VALID_TYPES = ("noul", "choice", "score")

#: Keys with these statuses are dead for this request; try the next key.
ROTATE_STATUSES = frozenset({401, 403})
#: Transient statuses retried on the same key (429 rotates unless it is the only key).
RETRY_STATUSES = frozenset({408, *range(500, 600)})

#: nace.ai's own key shape (seen in the official SDK): nace_sk_ + 43 base64url chars.
API_KEY_PATTERN = re.compile(r"^nace_sk_[A-Za-z0-9_-]{43}$")


class NaceError(RuntimeError):
    """Base error; message carries the upstream detail."""


class NaceAuthError(NaceError):
    """All keys failed auth, or no usable key was configured."""


class NaceBadRequest(NaceError):
    """Upstream rejected the request payload (non-retryable)."""


def check_key_format(key: str) -> str:
    """Return the key when it matches the nace.ai shape, else raise.

    A malformed key usually means a truncated copy or a key from another
    product; failing at construction beats failing (and confusing) on the
    first request.
    """
    k = key.strip()
    if not API_KEY_PATTERN.match(k):
        raise NaceAuthError(
            f"not a nace.ai API key: expected 'nace_sk_' + 43 characters, got {key[:18]}… "
            f"({len(key)} chars)"
        )
    return k


def default_keys() -> list[str]:
    raw = os.environ.get("NACE_API_KEYS") or os.environ.get("NACE_API_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def normalize_questions(questions: Any) -> dict[str, dict[str, Any]]:
    """Accept a ``{name: question}`` mapping, a single question, or a list.

    Builders in :mod:`nace_kit.presets` return questions carrying a ``name``
    key; plain upstream-format dicts are also accepted (name defaults to
    ``"answer"``).
    """
    if isinstance(questions, Mapping):
        if "type" in questions:
            q = dict(questions)
            name = q.pop("name", None) or "answer"
            return {name: q}
        return json.loads(json.dumps(dict(questions)))  # deep copy, json-safe
    if isinstance(questions, (list, tuple)):
        out: dict[str, dict[str, Any]] = {}
        for item in questions:
            q = dict(item)
            if "type" not in q:
                raise NaceBadRequest(f"question missing 'type': {q!r}")
            name = q.pop("name", None) or "answer"
            base = name
            i = 2
            while name in out:
                name = f"{base}_{i}"
                i += 1
            out[name] = q
        return out
    raise NaceBadRequest(f"unsupported questions format: {type(questions).__name__}")


def plan_for_status(status: int, *, single_key: bool) -> str:
    """What to do with a non-200: ``rotate`` to the next key, ``retry`` this
    one, or ``raise`` (payload errors nothing will fix)."""
    if status in ROTATE_STATUSES:
        return "rotate"
    if status == 429:
        # Several keys: another key likely has quota. One key: wait it out.
        return "retry" if single_key else "rotate"
    if status in RETRY_STATUSES:
        return "retry"
    if 400 <= status < 500:
        return "raise"
    return "retry"


def error_for_status(resp: httpx.Response) -> NaceError:
    try:
        err = resp.json().get("error", {})
        msg = err.get("message") or resp.text[:300]
    except Exception:
        msg = resp.text[:300]
    text = f"HTTP {resp.status_code}: {msg}"
    if resp.status_code in ROTATE_STATUSES:
        return NaceAuthError(text)
    if 400 <= resp.status_code < 500:
        return NaceBadRequest(text)
    return NaceError(text)


def retry_after_seconds(resp: httpx.Response) -> float | None:
    """Seconds the server asked us to wait, from ``Retry-After`` (seconds) or
    ``retry-after-ms`` (milliseconds); ``None`` when absent or unparsable."""
    for header, scale in (("retry-after-ms", 0.001), ("Retry-After", 1.0)):
        value = resp.headers.get(header)
        if value is None:
            continue
        try:
            seconds = float(value) * scale
        except ValueError:
            continue
        if seconds >= 0:
            return seconds
    return None


def backoff_delay(attempt: int, initial: float, maximum: float, jitter: float) -> float:
    """Exponential backoff with jitter: ``initial * 2**(attempt-1)``, capped at
    ``maximum``, a random ``jitter`` fraction subtracted. Zero ``initial``
    disables waiting (tests)."""
    if initial <= 0:
        return 0.0
    exponential = min(initial * (2 ** (attempt - 1)), maximum)
    return max(0.0, exponential * (1.0 - random.random() * jitter))


class _Base:
    def __init__(
        self,
        keys: list[str] | str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 8.0,
        cache_size: int = 256,
        transport: Any = None,
        check_keys: bool = True,
        max_retries: int = 2,
        backoff_initial: float = 0.5,
        backoff_max: float = 5.0,
        backoff_jitter: float = 0.25,
        retry_budget: float = 30.0,
    ) -> None:
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        self._keys = list(keys) if keys else default_keys()
        if not self._keys:
            raise NaceAuthError("no API keys: pass keys= or set NACE_API_KEYS")
        if check_keys:
            self._keys = [check_key_format(k) for k in self._keys]
        self._cycle = itertools.cycle(range(len(self._keys)))
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.cache_size = cache_size
        self.max_retries = max_retries
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.backoff_jitter = backoff_jitter
        self.retry_budget = retry_budget
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._transport = transport
        self.usage = {
            self.hint(k): {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            for k in self._keys
        }

    def hint(self, key: str) -> str:
        return key[:12] + "…"

    def _next_key(self) -> tuple[int, str]:
        idx = next(self._cycle)
        return idx, self._keys[idx]

    def _single_key(self) -> bool:
        return len(set(self._keys)) == 1

    def _payload(self, state: Any, questions: Any) -> dict[str, Any]:
        return {
            "model": self.model,
            "state": state,
            "questions": normalize_questions(questions),
        }

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if not self.cache_size:
            return None
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return copy.deepcopy(hit)
        return None

    def _cache_put(self, key: str, value: dict[str, Any]) -> None:
        if not self.cache_size:
            return
        self._cache[key] = copy.deepcopy(value)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _record(self, key_idx: int, result: dict[str, Any]) -> None:
        stats = self.usage[self.hint(self._keys[key_idx])]
        stats["calls"] += 1
        u = result.get("usage") or {}
        stats["input_tokens"] += int(u.get("input_tokens") or 0)
        stats["output_tokens"] += int(u.get("output_tokens") or 0)

    def _next_delay(self, attempt: int, resp: httpx.Response | None) -> float:
        """Seconds to wait before retrying this key: the server's word when it
        gave one, else backoff. Capped at ``backoff_max``."""
        if resp is not None:
            asked = retry_after_seconds(resp)
            if asked is not None:
                return min(asked, self.backoff_max)
        return backoff_delay(attempt, self.backoff_initial, self.backoff_max, self.backoff_jitter)


class NaceClient(_Base):
    """Synchronous client."""

    def classify(self, state: Any, questions: Any) -> dict[str, Any]:
        """Classify ``state`` (any JSON value — text, an object, a list) with
        up to 512 batched questions; returns the upstream JSON plus
        ``latency_ms``."""
        payload = self._payload(state, questions)
        cache_key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        hit = self._cache_get(cache_key)
        if hit is not None:
            return hit
        return self._send("POST", "/systemone", payload, cache_key)

    def models(self) -> dict[str, Any]:
        """List the decision models the account can call (works at any balance;
        handy as a key health check). Returns the upstream JSON plus ``latency_ms``."""
        return self._send("GET", "/models", None, None)

    def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        cache_key: str | None,
    ) -> dict[str, Any]:
        content = json.dumps(body) if body is not None else None
        single = self._single_key()
        last_error: Exception | None = None
        started = time.monotonic()
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
            transport=self._transport,
        ) as http:
            for _ in range(len(self._keys)):
                idx, key = self._next_key()
                attempt = 0
                while True:
                    attempt += 1
                    start = time.perf_counter()
                    resp: httpx.Response | None = None
                    try:
                        resp = http.request(
                            method,
                            path,
                            content=content,
                            headers={"Authorization": f"Bearer {key}"},
                        )
                    except httpx.HTTPError as exc:
                        last_error = NaceError(f"network error: {exc}")
                        plan = "retry"
                    if resp is not None:
                        latency_ms = round((time.perf_counter() - start) * 1000, 1)
                        if resp.status_code == 200:
                            result = resp.json()
                            result["latency_ms"] = latency_ms
                            self._record(idx, result)
                            if cache_key is not None:
                                self._cache_put(cache_key, result)
                            return result
                        plan = plan_for_status(resp.status_code, single_key=single)
                        last_error = error_for_status(resp)
                        if plan == "raise":
                            raise last_error
                    if plan == "rotate":
                        break
                    # retry this key, unless the retry budget says stop waiting
                    if attempt > self.max_retries:
                        break
                    delay = self._next_delay(attempt, resp)
                    if time.monotonic() - started + delay >= self.retry_budget:
                        break
                    time.sleep(delay)
        raise last_error or NaceAuthError("all keys exhausted")


class AsyncNaceClient(_Base):
    """Async client; same behaviour as :class:`NaceClient`."""

    async def classify(self, state: Any, questions: Any) -> dict[str, Any]:
        payload = self._payload(state, questions)
        cache_key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        hit = self._cache_get(cache_key)
        if hit is not None:
            return hit
        return await self._send("POST", "/systemone", payload, cache_key)

    async def models(self) -> dict[str, Any]:
        return await self._send("GET", "/models", None, None)

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        cache_key: str | None,
    ) -> dict[str, Any]:
        content = json.dumps(body) if body is not None else None
        single = self._single_key()
        last_error: Exception | None = None
        started = time.monotonic()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
            transport=self._transport,
        ) as http:
            for _ in range(len(self._keys)):
                idx, key = self._next_key()
                attempt = 0
                while True:
                    attempt += 1
                    start = time.perf_counter()
                    resp: httpx.Response | None = None
                    try:
                        resp = await http.request(
                            method,
                            path,
                            content=content,
                            headers={"Authorization": f"Bearer {key}"},
                        )
                    except httpx.HTTPError as exc:
                        last_error = NaceError(f"network error: {exc}")
                        plan = "retry"
                    if resp is not None:
                        latency_ms = round((time.perf_counter() - start) * 1000, 1)
                        if resp.status_code == 200:
                            result = resp.json()
                            result["latency_ms"] = latency_ms
                            self._record(idx, result)
                            if cache_key is not None:
                                self._cache_put(cache_key, result)
                            return result
                        plan = plan_for_status(resp.status_code, single_key=single)
                        last_error = error_for_status(resp)
                        if plan == "raise":
                            raise last_error
                    if plan == "rotate":
                        break
                    if attempt > self.max_retries:
                        break
                    delay = self._next_delay(attempt, resp)
                    if time.monotonic() - started + delay >= self.retry_budget:
                        break
                    await asyncio.sleep(delay)
        raise last_error or NaceAuthError("all keys exhausted")
