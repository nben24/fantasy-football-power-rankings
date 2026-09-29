import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narratives

BS = chr(92)  # avoids escaping ambiguity in the literals below


def test_literal_escape_becomes_the_real_character():
    """A model wrote the six characters \\u2014 into a recap instead of an
    em-dash, and it reached the paste-ready export verbatim."""
    text = f"dropped 189.3 {BS}u2014 the highest score"
    assert narratives._decode_literal_escapes(text) == "dropped 189.3 — the highest score"


def test_real_characters_are_left_alone():
    text = "CORAZÓN ❤️ — already fine"
    assert narratives._decode_literal_escapes(text) == text


def test_sanitize_walks_nested_tool_output():
    payload = {
        "week_theme": f"Week 3 {BS}u2014 The Reckoning",
        "team_writeups": [
            {"name": "A", "narrative": f"lost by 40 {BS}u2014 badly"},
            {"name": "B", "narrative": "clean already"},
        ],
        "awards": [{"title": "Best", "team": "A", "reason": f"scored {BS}u2014 a lot"}],
        "count": 12,
    }
    out = narratives.sanitize_model_output(payload)
    assert out["week_theme"] == "Week 3 — The Reckoning"
    assert out["team_writeups"][0]["narrative"] == "lost by 40 — badly"
    assert out["team_writeups"][1]["narrative"] == "clean already"
    assert out["awards"][0]["reason"] == "scored — a lot"
    assert out["count"] == 12


def test_handles_accented_and_emoji_escapes():
    assert narratives._decode_literal_escapes(f"CORAZ{BS}u00d3N") == "CORAZÓN"


def test_non_escape_backslashes_survive():
    text = f"a windows path C:{BS}users and a {BS}unrelated word"
    # Neither is a valid 4-hex-digit escape, so both stay put.
    assert narratives._decode_literal_escapes(text) == text
