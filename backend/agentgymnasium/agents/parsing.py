from __future__ import annotations

import json
import re

__all__ = ["parse_tool_calls"]

# Reasoning models (Qwen3, DeepSeek-R1, etc.) emit a chain-of-thought block
# before their actual answer. That block routinely contains stray ``{ }`` and
# quoted JSON-looking fragments, which derail naive brace extraction — so strip
# it before anything else. Handles both closed ``<think>…</think>`` blocks and a
# dangling ``…</think>`` with no opening tag.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_PREFIX = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    text = _THINK_BLOCK.sub("", text)
    # A lone closing tag (opener emitted/streamed away) — drop everything up to it.
    if "</think>" in text.lower():
        text = _THINK_PREFIX.sub("", text)
    return text.strip()


def _balanced_objects(text: str) -> list[str]:
    """Every top-level ``{...}`` substring with balanced braces, in order.

    Unlike a first-``{`` to last-``}`` slice, this won't fuse two separate
    objects (or an object and trailing prose braces) into one unparseable blob,
    and it skips braces inside JSON strings.
    """
    objects: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    objects.append(text[start : i + 1])
    return objects


def parse_tool_calls(raw: str) -> list[dict]:
    """Defensively extract a ``tool_calls`` list from a model completion string.

    Agents return JSON of the form ``{"tool_calls": [{"tool": ..., "args": ...}]}``
    but real models wrap it in reasoning, prose, or code fences. This tries, in
    order:

    1. stripping any ``<think>…</think>`` reasoning block,
    2. a direct parse of the whole string,
    3. each ```` ```json ... ``` ```` fenced block,
    4. each balanced ``{...}`` object found in the text.

    Returns the list of dict tool calls, or ``[]`` if none could be parsed.
    Shared by the local runner and the OpenAI-compatible provider so both parse
    identically.
    """
    if not raw:
        return []
    text = _strip_reasoning(raw)
    if not text:
        return []

    candidates: list[str] = [text]
    # Fenced code blocks (```json ... ``` or ``` ... ```).
    candidates.extend(re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL))
    # Each balanced {...} object, preferring ones that mention tool_calls so a
    # leading explanatory object can't shadow the real payload.
    objects = _balanced_objects(text)
    candidates.extend(sorted(objects, key=lambda o: "tool_calls" not in o))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            calls = data.get("tool_calls")
            if isinstance(calls, list):
                return [c for c in calls if isinstance(c, dict)]
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
    return []
