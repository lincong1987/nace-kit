"""Tests for the document pipeline wrapper (official SDK, mocked clients)."""

from __future__ import annotations

import itertools

import httpx
import pytest

from nace_kit.docs import DocsClient
from nace_kit.client import NaceAuthError

nace_sdk = pytest.importorskip("nace_sdk")
from nace_sdk import DocumentJob, NaceAuthenticationError, NaceRateLimitError  # noqa: E402

FAKE_KEY = "nace_sk_" + "a" * 43
FAKE_KEY_2 = "nace_sk_" + "b" * 43


def make_job(job_id="11111111-1111-1111-1111-111111111111", status="succeeded", result=None):
    return DocumentJob.model_validate({
        "job_id": job_id, "kind": "parse", "operation": "parse", "status": status,
        "result": result or {},
    })


class FakeOfficial:
    """Mimics the official sync client's documents/jobs surface."""

    def __init__(self, api_key: str, *, fail_times: int = 0, rate_limit: bool = False,
                 inline_returns_queued: bool = False):
        self.api_key = api_key
        self.fail_times = fail_times
        self.rate_limit = rate_limit
        self.inline_returns_queued = inline_returns_queued
        self.parse_calls: list[dict] = []
        self.wait_calls: list[dict] = []

    def _raise_if_configured(self):
        if self.fail_times > 0:
            self.fail_times -= 1
            if self.rate_limit:
                raise NaceRateLimitError(429, None, httpx.Headers())
            raise NaceAuthenticationError(401, None, httpx.Headers())

    def _parse(self, source, **kwargs):
        self.parse_calls.append({"source": source, **kwargs})
        self._raise_if_configured()
        if kwargs.get("wait_seconds") and not self.inline_returns_queued:
            return make_job(result={"document": {"markdown": "# hi"}})
        return make_job(status="queued")

    @property
    def documents(self):
        holder = self

        class Docs:
            def parse(self, source, **kw):
                return holder._parse(source, **kw)

            def extract(self, source, **kw):
                return holder._parse(source, **kw)

        return Docs()

    @property
    def jobs(self):
        holder = self

        class Jobs:
            def get(self, job_id):
                return make_job(job_id=str(job_id))

            def wait(self, job_id, timeout=600.0, **kw):
                holder.wait_calls.append({"job_id": str(job_id), "timeout": timeout})
                holder._raise_if_configured()
                return make_job(job_id=str(job_id), result={"document": {"markdown": "# hi"}})

        return Jobs()


def make_docs(*fakes: FakeOfficial) -> DocsClient:
    docs = DocsClient(keys=[FAKE_KEY] * len(fakes))
    docs._pool._clients = list(fakes)
    docs._pool._cycle = itertools.cycle(docs._pool._clients)
    return docs


class TestRotation:
    def test_auth_error_rotates_to_next_key(self):
        bad, good = FakeOfficial(FAKE_KEY, fail_times=1), FakeOfficial(FAKE_KEY_2)
        docs = make_docs(bad, good)
        job = docs.parse("https://example.com/a.pdf", wait=30)
        assert job.result["document"]["markdown"] == "# hi"
        assert len(bad.parse_calls) == 1
        assert len(good.parse_calls) == 1

    def test_rate_limit_error_rotates_to_next_key(self):
        limited, good = FakeOfficial(FAKE_KEY, fail_times=1, rate_limit=True), FakeOfficial(FAKE_KEY_2)
        docs = make_docs(limited, good)
        job = docs.parse("https://example.com/a.pdf", wait=30)
        assert job.status == "succeeded"
        assert len(good.parse_calls) == 1

    def test_all_keys_exhausted_raises_kit_error(self):
        docs = make_docs(
            FakeOfficial(FAKE_KEY, fail_times=5),
            FakeOfficial(FAKE_KEY_2, fail_times=5, rate_limit=True),
        )
        with pytest.raises(NaceAuthError, match="all keys exhausted"):
            docs.parse("https://example.com/a.pdf")

    def test_wait_inline_capped_and_topped_up_on_same_client(self):
        c = FakeOfficial(FAKE_KEY, inline_returns_queued=True)  # create alone can't finish it
        docs = make_docs(c)
        docs.parse("https://example.com/a.pdf", wait=90)
        assert c.parse_calls[0]["wait_seconds"] == 60          # server cap
        assert c.wait_calls[0]["timeout"] == pytest.approx(30)  # top-up poll

    def test_no_wait_returns_queued_job_and_wait_method_polls(self):
        c = FakeOfficial(FAKE_KEY)
        docs = make_docs(c)
        queued = docs.parse("https://example.com/a.pdf")
        assert queued.status == "queued"
        done = docs.wait(queued.job_id, timeout=10)
        assert done.status == "succeeded"
        assert c.wait_calls[0]["job_id"] == queued.job_id

    def test_job_get_passes_through(self):
        c = FakeOfficial(FAKE_KEY_2)
        docs = make_docs(c)
        assert docs.job("abc").job_id == "abc"
