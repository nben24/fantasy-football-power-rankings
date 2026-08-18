"""Tests for the pure-logic rendering helpers in app.py (tier grouping, iMessage-
formatted export). Imports app.py in Streamlit's "bare mode" -- st.stop() raises
past the API-key check, which is fine since the functions we test are defined
before it."""

import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_app_module():
    spec = importlib.util.spec_from_file_location("app_under_test", "app.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # st.stop() (no API key) raises past the point we need -- expected.
    return mod


WEEK_DATA = {
    "rankings": [
        {"name": "A", "rank": 1, "record": "3-0", "power_score": 91.2, "previous_rank": 2, "rank_change": 1, "key_factors": ["3-0"], "confidence": "high"},
        {"name": "B", "rank": 2, "record": "2-1", "power_score": 70.1, "previous_rank": 1, "rank_change": -1, "key_factors": ["2-1"], "confidence": "high"},
        {"name": "C", "rank": 3, "record": "1-2", "power_score": 60.5, "previous_rank": None, "rank_change": None, "key_factors": ["1-2"], "confidence": "low"},
    ],
    "writeups": {
        "week_theme": "Test Theme",
        "tiers": [
            {"tier_name": "Top Tier", "tier_subtitle": "the goats", "team_names": ["A"]},
            {"tier_name": "Mid Tier", "team_names": ["B", "C"]},
        ],
        "team_writeups": [
            {"name": "A", "narrative": "A narrative"},
            {"name": "B", "narrative": "B narrative"},
            {"name": "C", "narrative": "C narrative"},
        ],
        "awards": [{"title": "Biggest Fraud", "team": "B", "reason": "because"}],
        "recap": "A recap.",
    },
}


def test_tier_grouping_covers_every_team_in_order():
    mod = _load_app_module()
    groups = mod._ordered_teams_with_tiers(WEEK_DATA)
    assert [g[0] for g in groups] == ["Top Tier", "Mid Tier"]
    assert [t["name"] for t in groups[0][2]] == ["A"]
    assert [t["name"] for t in groups[1][2]] == ["B", "C"]


def test_tier_grouping_falls_back_to_flat_list_without_tiers():
    mod = _load_app_module()
    legacy = {
        "rankings": WEEK_DATA["rankings"],
        "writeups": {"team_writeups": WEEK_DATA["writeups"]["team_writeups"], "awards": [], "recap": ""},
    }
    groups = mod._ordered_teams_with_tiers(legacy)
    assert len(groups) == 1
    assert groups[0][0] is None
    assert [t["name"] for t in groups[0][2]] == ["A", "B", "C"]


def test_imessage_export_includes_theme_and_tier_headers():
    mod = _load_app_module()
    text = mod.format_rankings_imessage("Test League", 5, WEEK_DATA)
    assert "Test Theme" in text
    assert "TOP TIER" in text
    assert "MID TIER" in text
    assert "A narrative" in text
    assert "Biggest Fraud" in text


def test_imessage_export_contains_no_markdown_syntax():
    """iMessage doesn't render markdown headers/bold/rules -- they'd show up as
    literal characters, so the export must not use that syntax. A bare '#' as a
    rank designator ("Previous: #2") is fine -- it's only a problem as a
    line-leading markdown header, which this checks for directly."""
    mod = _load_app_module()
    text = mod.format_rankings_imessage("Test League", 5, WEEK_DATA)
    assert not any(line.startswith("#") for line in text.splitlines())
    assert "**" not in text
    assert "---" not in text
    assert "⸻" in text  # the plain-text divider used instead
