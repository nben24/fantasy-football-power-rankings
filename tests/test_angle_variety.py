import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narratives, occurrences, rankings
from tests.mock_data import build_league_from_matchups


def _league_with_angles(angles_by_week):
    lg = build_league_from_matchups("Variety", {
        w: [("A", 100.0 + w, "B", 90.0)] for w in sorted(angles_by_week)
    })
    for w, ctype in angles_by_week.items():
        lg["weeks"][str(w)]["angles"] = [{"team": "A", "comedy_type": ctype, "best_angle": "x"}]
    return lg


def test_recent_angles_are_surfaced_oldest_first():
    lg = _league_with_angles({1: "team-name joke", 2: "collapse", 3: "unlucky loss"})
    assert narratives.recent_angle_types(lg, "A", 4) == [
        "W1: team-name joke", "W2: collapse", "W3: unlucky loss",
    ]


def test_lookback_window_excludes_older_weeks():
    lg = _league_with_angles({1: "oldest", 2: "b", 3: "c", 4: "d"})
    got = narratives.recent_angle_types(lg, "A", 5, lookback=3)
    assert "W1: oldest" not in got
    assert got == ["W2: b", "W3: c", "W4: d"]


def test_current_week_is_not_included():
    """The angle for this week hasn't been chosen yet; including it would be
    circular."""
    lg = _league_with_angles({1: "a", 2: "b"})
    assert narratives.recent_angle_types(lg, "A", 2) == ["W1: a"]


def test_team_with_no_angle_history_returns_empty():
    lg = _league_with_angles({1: "a"})
    assert narratives.recent_angle_types(lg, "Nonexistent", 2) == []


def test_repeated_angle_is_visible_to_the_caller():
    """The real failure this guards against: one team drew the same device six
    weeks running and nothing in the pipeline could see it."""
    lg = _league_with_angles({1: "team-name joke", 2: "team-name joke", 3: "team-name joke"})
    used = narratives.recent_angle_types(lg, "A", 4)
    assert all("team-name joke" in u for u in used)
    assert len(used) == 3


def test_occurrences_are_capped_per_team():
    """By mid-season a team can trip five detectors at once and earn a paragraph
    it did nothing to deserve."""
    lg = build_league_from_matchups("Capped", {
        w: [("A", 100.0, "B", 90.0), ("C", 120.0, "D", 80.0),
            ("E", 118.0, "F", 95.0), ("G", 110.0, "H", 99.0)]
        for w in range(1, 8)
    })
    for wk in lg["weeks"].values():
        for t in wk.get("teams", []):
            t["streak"] = "W7" if t["name"] in ("A", "C", "E", "G") else "L7"
            t["playoff_pct"] = 2.0
    ranked = rankings.compute_power_rankings(lg, 7)
    det = occurrences.detect(lg, 7, ranked)
    assert det["teams"], "expected occurrences to be detected"
    assert all(len(v) <= occurrences.MAX_OCCURRENCES_PER_TEAM for v in det["teams"].values())


def test_cap_keeps_the_highest_weighted_items():
    lg = build_league_from_matchups("Weighted", {
        1: [("A", 170.0, "B", 80.0), ("C", 100.0, "D", 99.0)],
    })
    det = occurrences.detect(lg, 1, rankings.compute_power_rankings(lg, 1))
    for items in det["teams"].values():
        weights = [o["weight"] for o in items]
        assert weights == sorted(weights, reverse=True)
