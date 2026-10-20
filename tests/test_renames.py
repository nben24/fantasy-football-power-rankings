import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import memory, narratives, occurrences, rankings
from tests.mock_data import build_league_from_matchups


def _renamed_league(tmp_path):
    """A team playing as 'Old' for three weeks, then 'New' in week 4."""
    memory.LEAGUES_DIR = tmp_path
    lg = build_league_from_matchups("Renames", {
        1: [("Old", 100.0, "B", 90.0), ("C", 120.0, "D", 80.0)],
        2: [("Old", 110.0, "C", 95.0), ("B", 99.0, "D", 88.0)],
        3: [("Old", 130.0, "D", 99.0), ("B", 101.0, "C", 97.0)],
    })
    wk4 = {
        "teams": [
            {"name": "New", "record": "3-1", "points_for": 440.0, "points_against": 369.0},
            {"name": "B", "record": "1-3", "points_for": 380.0, "points_against": 420.0},
            {"name": "C", "record": "2-2", "points_for": 400.0, "points_against": 400.0},
            {"name": "D", "record": "2-2", "points_for": 390.0, "points_against": 410.0},
        ],
        "matchups": [
            {"team_a": "New", "team_b": "B", "score_a": 100.0, "score_b": 91.0},
            {"team_a": "C", "team_b": "D", "score_a": 88.0, "score_b": 123.0},
        ],
    }
    lg["weeks"]["4"] = wk4
    lg["current_week"] = 4
    return lg


def test_unlinked_rename_strands_the_history(tmp_path):
    """The bug this guards against: six weeks of history invisible because the
    label changed."""
    lg = _renamed_league(tmp_path)
    assert len(rankings._team_game_history(lg, "New", 4)) == 1
    assert len(rankings._team_game_history(lg, "Old", 4)) == 3


def test_linking_reconnects_the_history(tmp_path):
    lg = _renamed_league(tmp_path)
    memory.record_rename(lg, "Old", "New")
    weeks = [g["week"] for g in rankings._team_game_history(lg, "New", 4)]
    assert weeks == [1, 2, 3, 4]


def test_history_resolves_from_either_direction(tmp_path):
    lg = _renamed_league(tmp_path)
    memory.record_rename(lg, "Old", "New")
    assert len(rankings._team_game_history(lg, "Old", 4)) == 4


def test_previous_rank_survives_a_rename(tmp_path):
    lg = _renamed_league(tmp_path)
    lg["weeks"]["3"]["rankings"] = rankings.compute_power_rankings(lg, 3)
    memory.record_rename(lg, "Old", "New")
    ranked = rankings.compute_power_rankings(lg, 4)
    entry = next(r for r in ranked if r["name"] == "New")
    assert entry["previous_rank"] is not None, "renamed team should not read as unranked"


def test_past_weeks_keep_their_published_labels(tmp_path):
    """Linking must not rewrite columns that were already sent."""
    lg = _renamed_league(tmp_path)
    memory.record_rename(lg, "Old", "New")
    assert any(t["name"] == "Old" for t in lg["weeks"]["1"]["teams"])
    assert lg["weeks"]["1"]["matchups"][0]["team_a"] == "Old"


def test_recent_angles_follow_the_rename(tmp_path):
    lg = _renamed_league(tmp_path)
    lg["weeks"]["3"]["angles"] = [{"team": "Old", "comedy_type": "team-name joke"}]
    memory.record_rename(lg, "Old", "New")
    assert narratives.recent_angle_types(lg, "New", 4) == ["W3: team-name joke"]


def test_storylines_follow_the_rename(tmp_path):
    lg = _renamed_league(tmp_path)
    memory.add_storyline(lg, "The Old Era", ["Old"], 1, "started strong")
    memory.record_rename(lg, "Old", "New")
    titles = [s["title"] for s in memory.relevant_storylines_for_team(lg, "New", 4)]
    assert "The Old Era" in titles


def test_prior_streak_lookup_follows_the_rename(tmp_path):
    lg = _renamed_league(tmp_path)
    for t in lg["weeks"]["3"]["teams"]:
        if t["name"] == "Old":
            t["streak"] = "W3"
    memory.record_rename(lg, "Old", "New")
    assert occurrences._prev_streak(lg, 4, "New") == ("W", 3)


def test_chained_renames_collapse_to_one_identity(tmp_path):
    lg = _renamed_league(tmp_path)
    memory.record_rename(lg, "Old", "New")
    memory.record_rename(lg, "New", "Newest")
    assert memory.name_variants(lg, "Newest") == {"Old", "New", "Newest"}
    assert len(rankings._team_game_history(lg, "Newest", 4)) == 4


def test_self_rename_is_ignored(tmp_path):
    lg = _renamed_league(tmp_path)
    memory.record_rename(lg, "New", "New")
    assert not (lg.get("former_names") or {}).get("New")
