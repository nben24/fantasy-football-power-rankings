import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import occurrences, rankings
from tests.mock_data import build_league_from_matchups


def _detect(league, week):
    ranked = rankings.compute_power_rankings(league, week)
    return occurrences.detect(league, week, ranked), ranked


def _kinds(detected, team):
    return {o["kind"] for o in detected["teams"].get(team, [])}


def test_quiet_team_gets_no_occurrences():
    """The empty list is the signal that drives short, dismissive writeups."""
    league = build_league_from_matchups("Quiet", {
        1: [
            ("A", 130.0, "B", 118.0),
            ("C", 124.0, "D", 112.0),
            ("E", 121.0, "F", 109.0),
        ],
    })
    detected, _ = _detect(league, 1)
    # No blowouts, no nail-biters. Only the week high (A) and week low (F)
    # should pick anything up; the middle of the field stays silent.
    quiet = [t for t, v in detected["teams"].items() if not v]
    assert set(quiet) == {"B", "C", "D", "E"}, f"unexpected occurrences: {detected['teams']}"


def test_blowout_detected_for_both_sides():
    league = build_league_from_matchups("Blowout", {
        1: [("A", 160.0, "B", 70.0), ("C", 100.0, "D", 99.0)],
    })
    detected, _ = _detect(league, 1)
    assert "blowout" in _kinds(detected, "A")
    assert "blowout" in _kinds(detected, "B")


def test_nailbiter_detected():
    league = build_league_from_matchups("Close", {
        1: [("A", 100.16, "B", 100.0), ("C", 130.0, "D", 90.0)],
    })
    detected, _ = _detect(league, 1)
    assert "nailbiter" in _kinds(detected, "A")


def test_outscored_everyone_except_their_own_opponent():
    """The cruellest real occurrence: you'd have beaten all 10 other teams and
    happened to draw the one that outscored you."""
    league = build_league_from_matchups("Cruel", {
        1: [
            ("A", 150.0, "B", 151.0),
            ("C", 120.0, "D", 110.0),
            ("E", 118.0, "F", 105.0),
        ],
    })
    detected, _ = _detect(league, 1)
    assert "high_score_loss" in _kinds(detected, "A")
    texts = " ".join(o["text"] for o in detected["teams"]["A"])
    assert "every other team" in texts


def test_projection_gap_detected_from_espn_numbers():
    league = build_league_from_matchups("Proj", {
        1: [("A", 100.0, "B", 95.0)],
    })
    m = league["weeks"]["1"]["matchups"][0]
    m["projected_a"], m["projected_b"] = 140.0, 96.0
    detected, _ = _detect(league, 1)
    assert "under_projection" in _kinds(detected, "A")


def test_lost_as_favorite_detected():
    league = build_league_from_matchups("Upset", {
        1: [("A", 90.0, "B", 95.0)],
    })
    m = league["weeks"]["1"]["matchups"][0]
    m["projected_a"], m["projected_b"] = 130.0, 100.0
    detected, _ = _detect(league, 1)
    assert "lost_as_favorite" in _kinds(detected, "A")


def _escalating(start_week):
    scores = [100.0, 104.0, 108.0, 102.0, 106.0, 140.0]
    return {start_week + i: [("A", s, "B", 90.0 + i)] for i, s in enumerate(scores)}


def test_partial_season_never_claims_a_season_high():
    """The app usually starts mid-season; calling a partial-history max a
    'season high' would be a fabricated fact."""
    league = build_league_from_matchups("Partial", _escalating(9))
    detected, _ = _detect(league, 14)
    texts = " ".join(o["text"] for o in detected["teams"]["A"])
    assert "high_water" in _kinds(detected, "A")
    assert "season" not in texts.lower()
    assert "in 6 weeks" in texts


def test_full_season_history_may_claim_season():
    league = build_league_from_matchups("Full", _escalating(1))
    detected, _ = _detect(league, 6)
    texts = " ".join(o["text"] for o in detected["teams"]["A"])
    assert "best score of the season" in texts


def test_thin_history_emits_no_extreme_at_all():
    """With only a few weeks on record, roughly 2/N of the league sets an
    'extreme' every week by chance -- that's noise, not an event."""
    league = build_league_from_matchups("Thin", {
        9: [("A", 100.0, "B", 90.0), ("C", 101.0, "D", 95.0)],
        10: [("A", 115.0, "B", 91.0), ("C", 102.0, "D", 96.0)],
        11: [("A", 130.0, "B", 92.0), ("C", 103.0, "D", 97.0)],
    })
    detected, _ = _detect(league, 11)
    all_kinds = set()
    for v in detected["teams"].values():
        all_kinds |= {o["kind"] for o in v}
    assert not (all_kinds & {"high_water", "low_water"})


def test_extreme_must_clear_the_old_mark_by_a_margin():
    """Beating a previous best by 0.2 is a rounding error, not a new ceiling."""
    league = build_league_from_matchups("Tie", {
        1: [("A", 120.0, "B", 90.0)],
        2: [("A", 110.0, "B", 91.0)],
        3: [("A", 111.0, "B", 92.0)],
        4: [("A", 112.0, "B", 93.0)],
        5: [("A", 113.0, "B", 94.0)],
        6: [("A", 120.2, "B", 95.0)],
    })
    detected, _ = _detect(league, 6)
    assert "high_water" not in _kinds(detected, "A")


def test_format_for_prompt_marks_empty_teams_explicitly():
    detected = {"teams": {"A": [], "B": [{"kind": "blowout", "text": "beat X by 50", "weight": 9}]},
                "league": []}
    assert "NOTHING NOTABLE" in occurrences.format_for_prompt(detected, "A")
    assert occurrences.format_for_prompt(detected, "B") == "beat X by 50"


def test_streak_read_from_extracted_standings():
    league = build_league_from_matchups("Streaky", {
        1: [("A", 100.0, "B", 90.0)],
        2: [("A", 105.0, "B", 91.0)],
    })
    for t in league["weeks"]["2"]["teams"]:
        if t["name"] == "A":
            t["streak"] = "W4"
    detected, _ = _detect(league, 2)
    assert "streak" in _kinds(detected, "A")
