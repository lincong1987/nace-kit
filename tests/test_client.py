"""Unit tests with a mocked httpx transport (no network access)."""

from __future__ import annotations

import json

import httpx
import pytest

from nace_kit.client import (
    AsyncNaceClient,
    NaceAuthError,
    NaceBadRequest,
    NaceClient,
    check_key_format,
    normalize_questions,
)
from nace_kit import presets

UPSTREAM_OK = {
    "model": "drex-latest",
    "answers": {
        "is_urgent": {"type": "noul", "noul": 0.7161},
    },
    "usage": {"input_tokens": 26, "output_tokens": 24},
    "evaluation_time_ms": 122.6,
    "request_id": "req_test",
}

MODELS_OK = {
    "models": [
        {"name": "drex-v2.0", "alias_for": None, "release_date": "2026-10-06"},
        {"name": "drex-latest", "alias_for": "drex-v2.0", "release_date": "2026-10-06"},
    ],
    "request_id": "req_models",
}

# Fake keys that pass the nace_sk_ shape check, for tests that keep it on.
FAKE_KEY = "nace_sk_" + "a" * 43
FAKE_KEY_2 = "nace_sk_" + "b" * 43


def make_transport(responder, seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request, len(seen))

    return httpx.MockTransport(handler)


def ok_json(request, n):
    return httpx.Response(200, json=UPSTREAM_OK)


class TestPayload:
    def test_batching_sends_all_questions_and_first_key(self):
        seen: list[httpx.Request] = []
        client = NaceClient(keys=["k1", "k2"], check_keys=False, transport=make_transport(ok_json, seen))
        client.classify(
            "some text",
            [presets.urgency(), presets.score("How angry?", ["calm", "angry"], name="anger")],
        )
        body = json.loads(seen[0].content)
        assert body["model"] == "drex-latest"
        assert body["state"] == "some text"
        assert set(body["questions"]) == {"is_urgent", "anger"}
        assert body["questions"]["is_urgent"]["type"] == "noul"
        assert body["questions"]["anger"]["criteria"] == ["calm", "angry"]
        assert seen[0].headers["Authorization"] == "Bearer k1"
        assert seen[0].url.path == "/v1/systemone"

    def test_state_can_be_any_json(self):
        seen: list[httpx.Request] = []
        client = NaceClient(keys=["k1"], check_keys=False, transport=make_transport(ok_json, seen))
        state = {"ticket": "#42", "subject": "payout failure", "attempts": 3}
        client.classify(state, presets.urgency())
        body = json.loads(seen[0].content)
        assert body["state"] == state

    def test_normalize_accepts_mapping_single_and_list(self):
        q_map = {"a": {"type": "noul", "instructions": "x"}}
        q_single = {"name": "a", "type": "noul", "instructions": "x"}
        q_list = [{"name": "a", "type": "noul", "instructions": "x"}]
        assert normalize_questions(q_map) == q_map
        assert normalize_questions(q_single) == q_map
        assert normalize_questions(q_list) == q_map

    def test_duplicate_names_get_suffixed(self):
        out = normalize_questions(
            [{"name": "q", "type": "noul", "instructions": "1"},
             {"name": "q", "type": "noul", "instructions": "2"}]
        )
        assert set(out) == {"q", "q_2"}


class TestKeyValidation:
    def test_rejects_malformed_key(self):
        with pytest.raises(NaceAuthError, match="not a nace.ai API key"):
            NaceClient(keys=["nace_sk_short"])

    def test_rejects_wrong_length_key(self):
        with pytest.raises(NaceAuthError):
            NaceClient(keys=["nace_sk_" + "a" * 42])

    def test_accepts_valid_shape_and_strips(self):
        assert check_key_format(" " + FAKE_KEY + " ") == FAKE_KEY

    def test_check_keys_false_allows_fakes(self):
        client = NaceClient(keys=["k1"], check_keys=False, transport=make_transport(ok_json, []))
        assert client.classify("x", presets.urgency())["request_id"] == "req_test"


class TestFailover:
    def test_rotates_to_second_key_on_401(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            if n == 1:
                return httpx.Response(401, json={"error": {"type": "authentication_error",
                                                           "message": "Invalid API key."}})
            return httpx.Response(200, json=UPSTREAM_OK)

        client = NaceClient(keys=["dead", "live"], check_keys=False, transport=make_transport(responder, seen))
        result = client.classify("text", presets.urgency())
        assert result["answers"]["is_urgent"]["noul"] == 0.7161
        assert len(seen) == 2
        assert seen[0].headers["Authorization"] == "Bearer dead"
        assert seen[1].headers["Authorization"] == "Bearer live"
        assert "latency_ms" in result
        assert client.usage[client.hint("live")]["calls"] == 1
        assert client.usage[client.hint("dead")]["calls"] == 0

    def test_429_rotates_when_multiple_keys(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            if n == 1:
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
            return httpx.Response(200, json=UPSTREAM_OK)

        client = NaceClient(keys=["a", "b"], check_keys=False, transport=make_transport(responder, seen))
        client.classify("text", presets.urgency())
        assert len(seen) == 2  # rotated immediately, no same-key retries
        assert seen[0].headers["Authorization"] == "Bearer a"
        assert seen[1].headers["Authorization"] == "Bearer b"

    def test_all_keys_dead_raises_auth_error(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            return httpx.Response(401, json={"error": {"message": "Invalid API key."}})

        client = NaceClient(keys=["dead1", "dead2"], check_keys=False, transport=make_transport(responder, seen))
        with pytest.raises(NaceAuthError):
            client.classify("text", presets.urgency())
        assert len(seen) == 2

    def test_bad_request_does_not_rotate(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            return httpx.Response(400, json={"error": {"message": 'questions.q.type: must be "noul"'}})

        client = NaceClient(keys=["k1", "k2"], check_keys=False, transport=make_transport(responder, seen))
        with pytest.raises(NaceBadRequest, match="must be"):
            client.classify("text", presets.urgency())
        assert len(seen) == 1  # no rotation on payload errors


class TestRetries:
    def test_500_retried_on_same_key_then_succeeds(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            if n == 1:
                return httpx.Response(500, json={"error": {"message": "boom"}})
            return httpx.Response(200, json=UPSTREAM_OK)

        client = NaceClient(
            keys=["k1", "k2"],
            check_keys=False,
            backoff_initial=0,
            transport=make_transport(responder, seen),
        )
        result = client.classify("text", presets.urgency())
        assert result["request_id"] == "req_test"
        assert len(seen) == 2
        assert seen[0].headers["Authorization"] == seen[1].headers["Authorization"] == "Bearer k1"

    def test_network_error_retried_then_rotates(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            if n <= 3:  # max_retries=2 -> 3 attempts on k1, all network errors
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=UPSTREAM_OK)

        client = NaceClient(
            keys=["k1", "k2"],
            check_keys=False,
            backoff_initial=0,
            transport=make_transport(responder, seen),
        )
        result = client.classify("text", presets.urgency())
        assert result["request_id"] == "req_test"
        assert len(seen) == 4  # 3 failed attempts on k1, 1 on k2
        assert seen[0].headers["Authorization"] == "Bearer k1"
        assert seen[3].headers["Authorization"] == "Bearer k2"

    def test_single_key_429_is_retried_with_retry_after(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            if n == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"error": {"message": "rate limited"}},
                )
            return httpx.Response(200, json=UPSTREAM_OK)

        client = NaceClient(
            keys=["only"],
            check_keys=False,
            backoff_initial=0,
            transport=make_transport(responder, seen),
        )
        client.classify("text", presets.urgency())
        assert len(seen) == 2  # same key retried, not an auth failure
        assert seen[0].headers["Authorization"] == seen[1].headers["Authorization"] == "Bearer only"

    def test_5xx_exhausted_across_all_keys_raises(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            return httpx.Response(503, json={"error": {"message": "down"}})

        client = NaceClient(
            keys=["k1", "k2"],
            check_keys=False,
            max_retries=1,
            backoff_initial=0,
            transport=make_transport(responder, seen),
        )
        with pytest.raises(Exception, match="503"):
            client.classify("text", presets.urgency())
        assert len(seen) == 4  # 2 attempts per key


class TestModels:
    def test_models_get_request_shape(self):
        seen: list[httpx.Request] = []

        def responder(request, n):
            assert request.method == "GET"
            return httpx.Response(200, json=MODELS_OK)

        client = NaceClient(keys=["k1"], check_keys=False, transport=make_transport(responder, seen))
        result = client.models()
        assert [m["name"] for m in result["models"]] == ["drex-v2.0", "drex-latest"]
        assert result["models"][1]["alias_for"] == "drex-v2.0"
        assert "latency_ms" in result
        assert seen[0].url.path == "/v1/models"


class TestCache:
    def test_identical_calls_hit_cache_once(self):
        seen: list[httpx.Request] = []
        client = NaceClient(keys=["k1"], check_keys=False, transport=make_transport(ok_json, seen))
        r1 = client.classify("same text", presets.urgency())
        r2 = client.classify("same text", presets.urgency())
        assert r1 == r2
        assert len(seen) == 1
        # mutating a returned result must not poison the cache
        r1["answers"]["is_urgent"]["noul"] = 999
        r3 = client.classify("same text", presets.urgency())
        assert r3["answers"]["is_urgent"]["noul"] == 0.7161

    def test_different_state_misses_cache(self):
        seen: list[httpx.Request] = []
        client = NaceClient(keys=["k1"], check_keys=False, transport=make_transport(ok_json, seen))
        client.classify("text a", presets.urgency())
        client.classify("text b", presets.urgency())
        assert len(seen) == 2

    def test_cache_disabled(self):
        seen: list[httpx.Request] = []
        client = NaceClient(keys=["k1"], check_keys=False, cache_size=0, transport=make_transport(ok_json, seen))
        client.classify("same", presets.urgency())
        client.classify("same", presets.urgency())
        assert len(seen) == 2


class TestPresets:
    def test_shapes(self):
        u = presets.urgency()
        assert u["type"] == "noul" and u["name"] == "is_urgent"
        s = presets.severity()
        assert s["type"] == "score"
        assert s["criteria"] == ["minor", "moderate", "major", "critical"]
        assert presets.sentiment()["criteria"] == ["negative", "neutral", "positive"]

    def test_noul_criteria(self):
        q = presets.noul("Refund?", true="wants money back", false="no refund request")
        assert q["criteria"] == {"true": "wants money back", "false": "no refund request"}
        assert "criteria" not in presets.noul("Refund?")

    def test_choice_mapping_format(self):
        q = presets.choice(
            "What is this about?",
            {"billing": "payment issues", "technical": None},
        )
        assert q["type"] == "choice"
        assert q["criteria"] == {"billing": "payment issues", "technical": None}

    def test_priority_preset(self):
        p = presets.priority()
        assert p["type"] == "choice"
        assert set(p["criteria"]) == {"low", "medium", "high", "urgent"}


class TestAsync:
    def test_async_client_failover_and_cache(self):
        import asyncio

        seen: list[httpx.Request] = []

        def responder(request, n):
            if n == 1:
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
            return httpx.Response(200, json=UPSTREAM_OK)

        async def run():
            client = AsyncNaceClient(keys=["a", "b"], check_keys=False, backoff_initial=0,
                                     transport=make_transport(responder, seen))
            r1 = await client.classify("text", presets.urgency())
            r2 = await client.classify("text", presets.urgency())
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1["request_id"] == "req_test"
        assert r2 == r1
        assert len(seen) == 2  # 429 rotate + first real call; cache serves the rest

    def test_async_models(self):
        import asyncio

        seen: list[httpx.Request] = []

        async def run():
            client = AsyncNaceClient(keys=["k1"], check_keys=False,
                                     transport=make_transport(
                                         lambda r, n: httpx.Response(200, json=MODELS_OK), seen))
            return await client.models()

        result = asyncio.run(run())
        assert len(result["models"]) == 2
