"""Turn a pile of ESPN fantasy football screenshots into structured data
using Claude's vision + forced tool-call output. No manual transcription."""

import base64
import io
import os

import anthropic
from PIL import Image

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

EXTRACT_TOOL = {
    "name": "record_league_data",
    "description": (
        "Record every team, standing, and matchup found across the provided "
        "fantasy football screenshots."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "week": {
                "type": ["integer", "null"],
                "description": "The current NFL/fantasy week number, if visible anywhere in the screenshots. Null if not determinable.",
            },
            "teams": {
                "type": "array",
                "description": "One entry per team visible in a standings screenshot. Omit fields you cannot actually see.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Team name exactly as shown."},
                        "manager": {"type": ["string", "null"], "description": "Owner/manager name if shown."},
                        "record": {"type": ["string", "null"], "description": "e.g. '3-1' or '3-1-0'."},
                        "points_for": {"type": ["number", "null"]},
                        "points_against": {"type": ["number", "null"]},
                        "standing": {"type": ["integer", "null"], "description": "Standings rank position if shown."},
                    },
                    "required": ["name"],
                },
            },
            "matchups": {
                "type": "array",
                "description": "One entry per head-to-head matchup visible for the current week.",
                "items": {
                    "type": "object",
                    "properties": {
                        "team_a": {"type": "string"},
                        "team_b": {"type": "string"},
                        "score_a": {"type": ["number", "null"]},
                        "score_b": {"type": ["number", "null"]},
                    },
                    "required": ["team_a", "team_b"],
                },
            },
            "rosters": {
                "type": "array",
                "description": "Only include if an actual roster/lineup screenshot was provided. One entry per team.",
                "items": {
                    "type": "object",
                    "properties": {
                        "team": {"type": "string"},
                        "notable_players": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Notable starters or bench players actually visible, e.g. 'Bijan Robinson (RB, bench)'.",
                        },
                    },
                    "required": ["team"],
                },
            },
            "uncertain_notes": {
                "type": "array",
                "description": (
                    "Anything you were not confident about: blurry numbers, ambiguous digits, "
                    "cut-off names, or conflicting data between screenshots. Be specific, e.g. "
                    "'Team A score may be 142.8 or 148.8'. Empty list if everything was clear."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["teams", "matchups", "uncertain_notes"],
    },
}

EXTRACTION_SYSTEM_PROMPT = """You are a meticulous data-entry assistant for a fantasy football app. \
You will be shown one or more screenshots from ESPN Fantasy Football (standings, matchups, \
box scores, or rosters). Extract ONLY what is actually visible in the images into the \
record_league_data tool call.

Rules:
- Never invent, guess, or estimate a number you cannot actually read. If a field isn't visible, omit it (use null).
- If the same team appears in multiple screenshots, merge what you learn about it into one entry.
- Use the team name exactly as displayed, don't paraphrase or abbreviate it.
- If a digit is blurry, cropped, or ambiguous, still make your best-effort extraction AND add a note to uncertain_notes describing the ambiguity precisely.
- Do not fabricate matchups or teams that are not shown.
"""


def _image_block(uploaded_file) -> dict:
    """uploaded_file: a Streamlit UploadedFile (has .read() / .type) or raw bytes."""
    if hasattr(uploaded_file, "getvalue"):
        raw = uploaded_file.getvalue()
        media_type = uploaded_file.type or "image/png"
    else:
        raw = uploaded_file
        media_type = "image/png"

    # Re-encode through Pillow to normalize format and cap size (keeps requests fast/cheap).
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    max_dim = 1568  # Claude's vision pipeline caps effective resolution near here anyway.
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": encoded},
    }


def extract_from_screenshots(uploaded_files: list, context_hint: str = "") -> dict:
    """Send all screenshots for one league/week in a single call so the model
    can cross-reference standings against matchups. Returns the parsed tool input dict."""
    if not uploaded_files:
        raise ValueError("No screenshots provided.")

    client = anthropic.Anthropic()

    content = [_image_block(f) for f in uploaded_files]
    instruction = "Extract the structured league data from these screenshots."
    if context_hint:
        instruction += f"\n\nFor context, the user mentioned: {context_hint}"
    content.append({"type": "text", "text": instruction})

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=EXTRACTION_SYSTEM_PROMPT,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "record_league_data"},
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use":
            return block.input

    raise RuntimeError("Model did not return structured data.")
