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
                        "points_for": {"type": ["number", "null"], "description": "Season-total PF column, not a single week's score."},
                        "points_against": {"type": ["number", "null"], "description": "Season-total PA column."},
                        "standing": {"type": ["integer", "null"], "description": "Standings rank position if shown."},
                        "streak": {
                            "type": ["string", "null"],
                            "description": (
                                "Current win/loss streak exactly as shown, e.g. 'W5', 'L3', 'W1'. "
                                "Visible in the STRK standings column and in parentheses next to the "
                                "record on the scoreboard."
                            ),
                        },
                        "playoff_pct": {
                            "type": ["number", "null"],
                            "description": "The PLAYOFF % standings column as a number (e.g. 98, 4). Omit if not shown.",
                        },
                        "division": {
                            "type": ["string", "null"],
                            "description": "Division heading this team is listed under, e.g. 'EAST'. Omit if standings aren't split by division.",
                        },
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
                        "score_a": {"type": ["number", "null"], "description": "The large actual score."},
                        "score_b": {"type": ["number", "null"], "description": "The large actual score."},
                        "projected_a": {
                            "type": ["number", "null"],
                            "description": (
                                "The smaller projected-points number shown directly beneath team_a's "
                                "actual score. Do NOT confuse it with the actual score -- the actual "
                                "score is the large bold number, the projection is the small one below it."
                            ),
                        },
                        "projected_b": {
                            "type": ["number", "null"],
                            "description": "The smaller projected-points number shown beneath team_b's actual score.",
                        },
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

Field-specific guidance for ESPN screenshots:
- SCOREBOARD cards show, per team: name, manager, record, streak in parentheses like (W5)/(L3),
  a large bold ACTUAL score, and a smaller PROJECTED score directly beneath it. Record the large
  number as the score and the small one as the projection -- never swap them.
- STANDINGS tables have columns that may be split across two screenshots (one showing
  RECORD/WIN%/GB/PF, another showing PF/PA/STRK/PLAYOFF %). Merge both views of the same team
  into one entry rather than creating duplicates.
- PF and PA in standings are SEASON TOTALS, not this week's points. Never put a weekly score in
  points_for.
- Standings may be grouped under division headings (EAST/WEST). Record which heading each team
  appeared under.
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
