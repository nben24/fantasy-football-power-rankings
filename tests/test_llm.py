import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src import llm

TOOL = {
    "name": "rec",
    "description": "d",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {"type": "array",
                      "items": {"type": "object", "properties": {"a": {"type": "string"}},
                                "required": ["a"]}},
        },
        "required": ["items"],
    },
}


def _resp(blocks, stop="end_turn"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                            cache_read_input_tokens=7, cache_creation_input_tokens=0)
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


def _tool_use(name="rec", data=None):
    return SimpleNamespace(type="tool_use", name=name, input=data or {"items": []})


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


def test_every_object_is_closed_for_strict_mode():
    s = llm.strict_tool(TOOL)
    assert s["strict"] is True
    assert s["input_schema"]["additionalProperties"] is False
    assert s["input_schema"]["properties"]["items"]["items"]["additionalProperties"] is False


def test_strict_copy_leaves_the_original_alone():
    llm.strict_tool(TOOL)
    assert "additionalProperties" not in TOOL["input_schema"]


def test_never_forces_tool_choice():
    """claude-opus-5-5 returns a 400 for tool_choice any/tool."""
    c = FakeClient([_resp([_tool_use()])])
    llm.call_tool("sys", "hi", TOOL, client=c)
    assert c.requests[0]["tool_choice"] == {"type": "auto"}


def test_returns_the_tool_input():
    c = FakeClient([_resp([SimpleNamespace(type="thinking"), _tool_use(data={"items": [{"a": "x"}]})])])
    assert llm.call_tool("sys", "hi", TOOL, client=c) == {"items": [{"a": "x"}]}


def test_a_missing_call_is_retried():
    c = FakeClient([_resp([SimpleNamespace(type="text", text="sure")]), _resp([_tool_use()])])
    assert llm.call_tool("sys", "hi", TOOL, client=c) == {"items": []}
    assert len(c.requests) == 2


def test_gives_up_after_the_retry():
    text = _resp([SimpleNamespace(type="text", text="no")])
    c = FakeClient([text, text])
    with pytest.raises(RuntimeError, match="did not call rec"):
        llm.call_tool("sys", "hi", TOOL, client=c)


def test_a_refusal_is_not_resent():
    c = FakeClient([_resp([], stop="refusal")])
    with pytest.raises(RuntimeError, match="refusal"):
        llm.call_tool("sys", "hi", TOOL, client=c)
    assert len(c.requests) == 1


def test_image_content_is_passed_through_with_the_instruction_last():
    img = {"type": "image", "source": {}}
    c = FakeClient([_resp([_tool_use()])])
    llm.call_tool("sys", [img], TOOL, client=c)
    blocks = c.requests[0]["messages"][0]["content"]
    assert blocks[0] is img and "rec" in blocks[-1]["text"]


def test_usage_is_recorded_per_attempt():
    log = []
    c = FakeClient([_resp([]), _resp([_tool_use()])])
    llm.call_tool("sys", "hi", TOOL, client=c, usage_log=log)
    assert len(log) == 2 and log[0]["cache_read"] == 7


def test_model_can_be_rolled_back_from_the_environment(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert llm.model() == "claude-opus-5-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    assert llm.model() == "claude-opus-5"
