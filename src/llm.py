"""One place that talks to the Messages API for structured output.

Every model call in this app exists to get schema-shaped JSON back, so they all
go through `call_tool`. It used to force the call with
`tool_choice={"type": "tool"}`; claude-opus-5-5 rejects forced tool choice
with a 400, so the call is now requested in the prompt, the schema is made
strict so the arguments are guaranteed to match it, and a missing call is
retried rather than assumed impossible.
"""

import copy
import os

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"

# Set ANTHROPIC_MODEL=claude-opus-5 to roll back. Read at call time so a
# changed .env takes effect without a code edit.
def model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)


# Thinking can't be turned off on Opus 5.5 and it counts toward max_tokens,
# so the limit has to leave room for it as well as the JSON. Only tokens
# actually produced are billed; this is a ceiling, not a cost.
MAX_TOKENS = 16000
ATTEMPTS = 2


def strict_schema(schema: dict) -> dict:
    """Return a copy with additionalProperties: false on every object,
    which strict mode requires. The source dicts are left untouched."""
    out = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(out)
    return out


def strict_tool(tool: dict) -> dict:
    return {**tool, "input_schema": strict_schema(tool["input_schema"]), "strict": True}


def _instruction(tool_name: str) -> dict:
    return {"type": "text",
            "text": f"Respond only by calling the {tool_name} tool, exactly once."}


def call_tool(system: str, content, tool: dict, *, usage_log: list | None = None,
              client=None) -> dict:
    """Ask for one call to `tool` and return its input.

    `content` is a user message's content: a string, or a list of blocks
    (images for extraction). The system prompt carries a cache breakpoint;
    caching matches a prefix in tools -> system -> messages order, so it
    covers the tool schema too, and the per-week content after it is not
    cached, as it shouldn't be.
    """
    client = client or anthropic.Anthropic()
    blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
              else list(content))
    blocks.append(_instruction(tool["name"]))

    last_stop = None
    for _ in range(ATTEMPTS):
        response = client.messages.create(
            model=model(),
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[strict_tool(tool)],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": blocks}],
        )
        if usage_log is not None:
            u = response.usage
            usage_log.append({
                "input": u.input_tokens,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "output": u.output_tokens,
            })
        for block in response.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return block.input
        last_stop = response.stop_reason
        # A refusal or a truncated reply won't change on a resend.
        if last_stop in ("refusal", "max_tokens"):
            break

    raise RuntimeError(
        f"Model did not call {tool['name']} (stop_reason: {last_stop})."
    )
