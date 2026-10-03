"""Shared tool-call parser handles the response shapes both providers emit."""
from __future__ import annotations

from agentgymnasium.agents.parsing import parse_tool_calls


def test_direct_object():
    raw = '{"tool_calls": [{"tool": "create_body", "args": {"id": "b1"}}]}'
    calls = parse_tool_calls(raw)
    assert calls == [{"tool": "create_body", "args": {"id": "b1"}}]


def test_fenced_json():
    raw = 'Here you go:\n```json\n{"tool_calls": [{"tool": "add_ball", "args": {}}]}\n```'
    calls = parse_tool_calls(raw)
    assert calls == [{"tool": "add_ball", "args": {}}]


def test_prose_then_object():
    raw = 'I will build a bridge. {"tool_calls": [{"tool": "add_beam", "args": {}}]} Done.'
    calls = parse_tool_calls(raw)
    assert calls == [{"tool": "add_beam", "args": {}}]


def test_bare_list():
    raw = '[{"tool": "create_body", "args": {}}]'
    calls = parse_tool_calls(raw)
    assert calls == [{"tool": "create_body", "args": {}}]


def test_empty_and_garbage():
    assert parse_tool_calls("") == []
    assert parse_tool_calls("no json here at all") == []
    assert parse_tool_calls("{ not valid json") == []


def test_filters_non_dict_entries():
    raw = '{"tool_calls": [{"tool": "x"}, "garbage", 42]}'
    assert parse_tool_calls(raw) == [{"tool": "x"}]


def test_strips_qwen_think_block():
    # Qwen3 / R1-style reasoning before the answer, with stray braces inside.
    raw = (
        "<think>I should add a box. Maybe {id: b1}? Let me reason... "
        'consider {"foo": 1}</think>\n'
        '{"tool_calls": [{"tool": "create_body", "args": {"id": "b1", "shape": "box"}}]}'
    )
    assert parse_tool_calls(raw) == [
        {"tool": "create_body", "args": {"id": "b1", "shape": "box"}}
    ]


def test_strips_dangling_think_close_tag():
    # Streaming can drop the opening <think> tag, leaving only the closer.
    raw = 'reasoning about braces { and } here</think> {"tool_calls": [{"tool": "add_ball"}]}'
    assert parse_tool_calls(raw) == [{"tool": "add_ball"}]


def test_prefers_object_with_tool_calls():
    # A leading explanatory object must not shadow the real payload.
    raw = '{"note": "here is my plan"} {"tool_calls": [{"tool": "add_beam", "args": {}}]}'
    assert parse_tool_calls(raw) == [{"tool": "add_beam", "args": {}}]
