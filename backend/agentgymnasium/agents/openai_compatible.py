from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time

import httpx
from dotenv import load_dotenv

from agentgymnasium.agents.base import (
    AgentProvider,
    ProviderStatus,
    StructuredOutputResult,
)
from agentgymnasium.agents.parsing import parse_tool_calls
from agentgymnasium.core.env import env
from agentgymnasium.core.schemas.model import ModelRequest, ModelResult, TokenUsage

# Connection probes are health checks — keep them short. Generation calls can take
# much longer and are configurable via env so real/local deployments can tune them.
_PROBE_TIMEOUT = 3.0
_DOTENV_LOADED = False


def _gen_timeout() -> float:
    try:
        return float(env("LLM_TIMEOUT_S", "120"))
    except ValueError:
        return 120.0


def _max_retries() -> int:
    try:
        return max(0, int(env("LLM_RETRIES", "2")))
    except ValueError:
        return 2


def _backoff_base() -> float:
    try:
        return max(0.0, float(env("LLM_BACKOFF_S", "0.5")))
    except ValueError:
        return 0.5


# Substrings that mark a model id as non-chat (embeddings, audio, image, moderation,
# rerank, etc.) — these show up in real OpenAI-compatible /models responses alongside
# chat models but can never serve a tool-calling agent, so the Setup dropdown must not
# offer them. Conservative: only known-non-chat families are dropped; anything
# unrecognized (a user's local/custom chat model) is kept.
_NON_CHAT_MARKERS = (
    "embedding",
    "whisper",
    "tts",
    "audio",
    "dall-e",
    "dalle",
    "image",
    "moderation",
    "realtime",
    "rerank",
    "similarity",
    "edit",
    "davinci-002",
    "babbage-002",
    "clip",
)


def _is_chat_model(model_id: str) -> bool:
    """True unless ``model_id`` matches a known non-chat model family."""
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


_STRUCTURED_PROMPT = (
    "Respond ONLY with a JSON object of the form "
    '{"tool_calls": [{"tool": "create_body", "args": {}}]}. '
    "Include exactly two tool calls. Do not add explanation."
)


class LLMError(RuntimeError):
    """A generation failure with a machine-readable ``kind`` for clear messaging.

    kinds: ``auth`` (401/403), ``rate_limit`` (429), ``server`` (5xx),
    ``timeout``, ``connection``, ``bad_request`` (other 4xx), ``malformed``
    (unparseable/unexpected response), ``empty`` (no content), ``config``.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _load_dotenv_once() -> None:
    """Load repo-local .env values without overriding the process environment."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    candidates = [pathlib.Path.cwd() / ".env", repo_root / ".env"]
    seen: set[pathlib.Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            load_dotenv(resolved, override=False)
            break
    _DOTENV_LOADED = True


def mask_secret(secret: str | None) -> str | None:
    """Return a UI-safe preview that never includes the full secret."""
    if not secret:
        return None
    suffix = secret[-4:] if len(secret) > 4 else ""
    prefix = "sk-" if secret.startswith("sk-") else ""
    masked = "*" * max(8, min(12, len(secret) - len(prefix) - len(suffix)))
    return f"{prefix}{masked}{suffix}"


def openai_env_key() -> str | None:
    """The OPENAI_API_KEY from the process environment or repo .env, if set."""
    _load_dotenv_once()
    key = os.environ.get("OPENAI_API_KEY")
    return key or None


def _classify_status(status: int) -> tuple[str, bool]:
    """Map an HTTP status to (error_kind, is_retryable)."""
    if status in (401, 403):
        return "auth", False
    if status == 429:
        return "rate_limit", True
    if status >= 500:
        return "server", True
    return "bad_request", False


class OpenAICompatibleProvider(AgentProvider):
    name = "openai_compatible"
    default_endpoint: str | None = None

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # An injectable transport lets the provider-contract tests drive the
        # client with httpx.MockTransport (no real network / server needed).
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _resolve_endpoint(self, endpoint_url: str | None) -> str | None:
        return endpoint_url or self.default_endpoint

    def _resolve_api_key(self, api_key: str | None) -> str | None:
        """Fall back to OPENAI_API_KEY from the env for the hosted OpenAI provider.

        Only the generic ``openai_compatible`` provider reads the env key;
        LocalDeploy (a subclass) needs no key and must not pick it up.
        """
        if api_key:
            return api_key
        if self.name == "openai_compatible":
            return openai_env_key()
        return api_key

    async def test_connection(
        self, endpoint_url: str | None, api_key: str | None
    ) -> ProviderStatus:
        endpoint = self._resolve_endpoint(endpoint_url)
        if not endpoint:
            return ProviderStatus(online=False, detail="No endpoint_url provided")
        api_key = self._resolve_api_key(api_key)
        try:
            async with self._client(_PROBE_TIMEOUT) as client:
                response = await client.get(
                    f"{endpoint.rstrip('/')}/models", headers=_headers(api_key)
                )
        except Exception as exc:  # noqa: BLE001 - report any failure as offline
            return ProviderStatus(online=False, detail=str(exc))

        if response.status_code != 200:
            kind, _ = _classify_status(response.status_code)
            detail = (
                "API key rejected"
                if kind == "auth"
                else f"HTTP {response.status_code} from {endpoint}/models"
            )
            return ProviderStatus(online=False, detail=detail)

        models: list[str] = []
        try:
            data = response.json()
            entries = data.get("data") if isinstance(data, dict) else None
            if isinstance(entries, list):
                models = [
                    str(item["id"])
                    for item in entries
                    if isinstance(item, dict) and "id" in item
                ]
        except Exception:  # noqa: BLE001 - models list is best-effort
            models = []
        models = [m for m in models if _is_chat_model(m)]

        return ProviderStatus(online=True, detail="Reachable", models=models)

    async def test_structured_output(
        self, model: str, endpoint_url: str | None, api_key: str | None
    ) -> StructuredOutputResult:
        endpoint = self._resolve_endpoint(endpoint_url)
        if not endpoint:
            return StructuredOutputResult(ok=False, detail="No endpoint_url provided")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You output only JSON tool calls."},
                {"role": "user", "content": _STRUCTURED_PROMPT},
            ],
            "temperature": 0.0,
        }
        try:
            async with self._client(_PROBE_TIMEOUT) as client:
                response = await client.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    headers=_headers(api_key),
                    json=payload,
                )
        except Exception as exc:  # noqa: BLE001
            return StructuredOutputResult(ok=False, detail=str(exc))

        if response.status_code != 200:
            return StructuredOutputResult(
                ok=False,
                detail=f"HTTP {response.status_code} from {endpoint}/chat/completions",
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return StructuredOutputResult(
                ok=False, detail=f"Unexpected response shape: {exc}"
            )

        sample = parse_tool_calls(content or "")
        if not sample:
            return StructuredOutputResult(
                ok=False, detail="Response did not contain parseable tool calls"
            )
        return StructuredOutputResult(
            ok=True, detail="Parsed tool calls from response", sample=sample
        )

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        endpoint_url: str | None,
        api_key: str | None,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        response, _ = await self._request_completion(
            payload, endpoint_url=endpoint_url, api_key=api_key
        )
        return self._extract_content(response)

    async def generate(self, request: ModelRequest) -> ModelResult:
        """Use native function calling when the endpoint supports it.

        Text-only OpenAI-compatible servers remain supported: when no native
        calls are returned, the existing tolerant JSON parser reads ``content``.
        """
        payload: dict = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object"}),
                    },
                }
                for tool in request.tools
            ]

        started = time.perf_counter()
        response, retry_count = await self._request_completion(
            payload,
            endpoint_url=request.endpoint_url,
            api_key=request.api_key,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError("malformed", f"Unexpected LLM response shape: {exc}") from exc

        content = str(message.get("content") or "")
        native_calls: list[dict] = []
        for item in message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                continue
            raw_args = function.get("arguments", {})
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            native_calls.append(
                {
                    "tool": str(function["name"]),
                    "args": args if isinstance(args, dict) else {},
                }
            )

        tool_calls = native_calls or parse_tool_calls(content)
        if not content and not tool_calls:
            raise LLMError("empty", "LLM returned an empty completion")

        usage_data = data.get("usage") if isinstance(data, dict) else {}
        usage_data = usage_data if isinstance(usage_data, dict) else {}
        prompt_details = usage_data.get("prompt_tokens_details")
        prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
        completion_details = usage_data.get("completion_tokens_details")
        completion_details = (
            completion_details if isinstance(completion_details, dict) else {}
        )
        return ModelResult(
            provider=request.provider,
            model=request.model,
            raw_text=content,
            tool_calls=tool_calls,
            native_tool_calls=bool(native_calls),
            finish_reason=choice.get("finish_reason"),
            request_id=response.headers.get("x-request-id"),
            latency_ms=latency_ms,
            retries=retry_count,
            usage=TokenUsage(
                input_tokens=int(usage_data.get("prompt_tokens") or 0),
                output_tokens=int(usage_data.get("completion_tokens") or 0),
                cached_input_tokens=int(prompt_details.get("cached_tokens") or 0),
                reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
            ),
        )

    async def _request_completion(
        self,
        payload: dict,
        *,
        endpoint_url: str | None,
        api_key: str | None,
    ) -> tuple[httpx.Response, int]:
        endpoint = self._resolve_endpoint(endpoint_url)
        if not endpoint:
            raise LLMError("config", "No endpoint_url provided")
        api_key = self._resolve_api_key(api_key)
        url = f"{endpoint.rstrip('/')}/chat/completions"

        timeout = _gen_timeout()
        retries = _max_retries()
        backoff = _backoff_base()
        last_error: LLMError | None = None

        for attempt in range(retries + 1):
            try:
                async with self._client(timeout) as client:
                    response = await client.post(
                        url, headers=_headers(api_key), json=payload
                    )
            except httpx.TimeoutException:
                last_error = LLMError(
                    "timeout", f"LLM generation timed out after {timeout}s"
                )
                exc_retryable = True
            except httpx.HTTPError as exc:  # connect/transport errors
                last_error = LLMError("connection", f"LLM request failed: {exc}")
                exc_retryable = True
            else:
                if response.status_code == 200:
                    return response, attempt
                kind, retryable = _classify_status(response.status_code)
                detail = {
                    "auth": "LLM endpoint rejected the API key (HTTP "
                    f"{response.status_code})",
                    "rate_limit": "LLM endpoint rate-limited the request (HTTP 429)",
                    "server": f"LLM endpoint server error (HTTP {response.status_code})",
                    "bad_request": f"LLM endpoint error (HTTP {response.status_code})",
                }[kind]
                last_error = LLMError(kind, detail)
                if not retryable:
                    raise last_error
                exc_retryable = True

            # Retry transient failures with exponential backoff.
            if attempt < retries and exc_retryable:
                await asyncio.sleep(backoff * (2**attempt))
                continue
            break

        assert last_error is not None
        raise last_error

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise LLMError("malformed", f"LLM returned non-JSON response: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                "malformed", f"Unexpected LLM response shape: {exc}"
            ) from exc
        if content is None or str(content).strip() == "":
            raise LLMError("empty", "LLM returned an empty completion")
        return str(content)
