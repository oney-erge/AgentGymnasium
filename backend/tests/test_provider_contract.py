"""Provider contract tests for the OpenAI-compatible client.

Exercise the real failure modes a live/local LLM endpoint produces — auth, rate
limit, server error, malformed JSON, non-tool text, partial tool calls, timeout,
and retry/backoff — without a network or a real server, via httpx.MockTransport.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agentgymnasium.agents.openai_compatible import LLMError, OpenAICompatibleProvider
from agentgymnasium.core.schemas.model import ModelRequest

_EP = "http://llm.test/v1"


def _provider(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(transport=httpx.MockTransport(handler))


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}
    )


async def _complete(provider: OpenAICompatibleProvider, **kw) -> str:
    return await provider.complete(
        model="m", system="s", user="u", endpoint_url=_EP, api_key="k", **kw
    )


def test_happy_path_returns_content():
    def handler(_req: httpx.Request) -> httpx.Response:
        return _chat('{"tool_calls": [{"tool": "create_body", "args": {}}]}')

    out = asyncio.run(_complete(_provider(handler)))
    assert "create_body" in out


def test_non_tool_text_is_returned_for_the_parser():
    # The provider returns raw text; parsing happens downstream. Prose is valid.
    def handler(_req: httpx.Request) -> httpx.Response:
        return _chat("I think we should build a bridge.")

    out = asyncio.run(_complete(_provider(handler)))
    assert out == "I think we should build a bridge."


def test_partial_tool_calls_still_return_text():
    def handler(_req: httpx.Request) -> httpx.Response:
        return _chat('{"tool_calls": [{"tool": "create_body"')  # truncated JSON

    out = asyncio.run(_complete(_provider(handler)))
    assert "create_body" in out  # raw text passes through; parser tolerates it


def test_auth_error_is_terminal():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "auth"


def test_forbidden_error_is_terminal():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "auth"


def test_malformed_json_raises_malformed():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "malformed"


def test_unexpected_shape_raises_malformed():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "malformed"


def test_empty_content_raises_empty():
    def handler(_req: httpx.Request) -> httpx.Response:
        return _chat("   ")

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "empty"


def test_server_error_retries_then_fails(monkeypatch):
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "2")
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_BACKOFF_S", "0")  # no real sleeping
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "server"
    assert calls["n"] == 3  # initial + 2 retries


def test_server_error_then_success_recovers(monkeypatch):
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "2")
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_BACKOFF_S", "0")
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, json={"error": "starting"})
        return _chat("recovered")

    out = asyncio.run(_complete(_provider(handler)))
    assert out == "recovered"
    assert calls["n"] == 2


def test_timeout_retries_then_raises_timeout(monkeypatch):
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "1")
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_BACKOFF_S", "0")
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "timeout"
    assert calls["n"] == 2  # initial + 1 retry


def test_rate_limit_retries_then_fails(monkeypatch):
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "2")
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_BACKOFF_S", "0")
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": "slow down"})

    with pytest.raises(LLMError) as exc:
        asyncio.run(_complete(_provider(handler)))
    assert exc.value.kind == "rate_limit"
    assert calls["n"] == 3  # initial + 2 retries


def test_auth_does_not_retry(monkeypatch):
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "3")
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_BACKOFF_S", "0")
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "no"})

    with pytest.raises(LLMError):
        asyncio.run(_complete(_provider(handler)))
    assert calls["n"] == 1  # terminal — no retries


def test_test_connection_reports_auth_clearly():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "no"})

    provider = _provider(handler)
    status = asyncio.run(provider.test_connection(_EP, "badkey"))
    assert status.online is False
    assert "key" in status.detail.lower()


def test_test_connection_lists_models():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "llama-3"}, {"id": "qwen"}]})

    provider = _provider(handler)
    status = asyncio.run(provider.test_connection(_EP, "k"))
    assert status.online is True
    assert status.models == ["llama-3", "qwen"]


def test_test_connection_filters_non_chat_models():
    """Embeddings/audio/image/moderation models must not reach the Setup dropdown."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o-mini"},
                    {"id": "gpt-4o"},
                    {"id": "gpt-4o-search-preview"},  # real chat model — must survive
                    {"id": "text-embedding-3-small"},
                    {"id": "whisper-1"},
                    {"id": "tts-1"},
                    {"id": "dall-e-3"},
                    {"id": "text-moderation-latest"},
                    {"id": "gpt-4o-realtime-preview"},
                    {"id": "o1"},
                ]
            },
        )

    provider = _provider(handler)
    status = asyncio.run(provider.test_connection(_EP, "k"))
    assert status.online is True
    assert status.models == ["gpt-4o-mini", "gpt-4o", "gpt-4o-search-preview", "o1"]


def test_no_endpoint_is_config_error():
    with pytest.raises(LLMError) as exc:
        asyncio.run(
            OpenAICompatibleProvider().complete(
                model="m", system="s", user="u", endpoint_url=None, api_key=None
            )
        )
    assert exc.value.kind == "config"


def test_json_body_sent_to_chat_completions():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return _chat("ok")

    asyncio.run(_complete(_provider(handler), temperature=0.3))
    assert seen["url"].endswith("/chat/completions")
    assert seen["body"]["temperature"] == 0.3
    assert seen["body"]["messages"][0]["role"] == "system"


def test_generate_uses_native_tools_seed_and_normalizes_telemetry():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-123"},
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "create_body",
                                        "arguments": '{"id":"b1","shape":"box"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 21,
                    "completion_tokens": 7,
                    "prompt_tokens_details": {"cached_tokens": 4},
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
            },
        )

    result = asyncio.run(
        _provider(handler).generate(
            ModelRequest(
                provider="openai_compatible",
                model="m",
                system="s",
                user="u",
                endpoint_url=_EP,
                api_key="k",
                seed=42,
                tools=[
                    {
                        "name": "create_body",
                        "description": "Create one body",
                        "parameters": {"type": "object"},
                    }
                ],
            )
        )
    )

    assert seen["body"]["seed"] == 42
    assert seen["body"]["tools"][0]["function"]["name"] == "create_body"
    assert result.native_tool_calls is True
    assert result.tool_calls == [
        {"tool": "create_body", "args": {"id": "b1", "shape": "box"}}
    ]
    assert result.request_id == "req-123"
    assert result.finish_reason == "tool_calls"
    assert result.usage.input_tokens == 21
    assert result.usage.output_tokens == 7
    assert result.usage.cached_input_tokens == 4
    assert result.usage.reasoning_tokens == 2
