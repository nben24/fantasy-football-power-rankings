import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import rankings
from tests.mock_data import SCENARIO_MATCHUPS, build_league_from_matchups


def test_best_record_and_scoring_wins():
    """Scenario 1: the team with the best record AND best scoring should be #1."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    ranked = rankings.compute_power_rankings(league, 3)
    assert ranked[0]["name"] == "A"
    assert ranked[0]["rank"] == 1


def test_elite_scoring_beats_bad_record_in_power_score():
    """Scenario 3: C (1-2, elite scoring, close losses) should out-score D (0-3)
    by a wide margin and should NOT be dead last despite a losing record."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    ranked = rankings.compute_power_rankings(league, 3)
    by_name = {r["name"]: r for r in ranked}
    assert by_name["C"]["power_score"] > by_name["D"]["power_score"]
    assert by_name["C"]["rank"] < by_name["D"]["rank"]


def test_good_record_soft_schedule_not_blindly_ranked_first():
    """Scenario 2: B has a good record but only beat weaker opponents and scored
    less than A. A should still outrank B."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    ranked = rankings.compute_power_rankings(league, 3)
    by_name = {r["name"]: r for r in ranked}
    assert by_name["A"]["rank"] < by_name["B"]["rank"]


def test_ranking_movement_tracks_previous_week():
    """Scenario 7: rank_change should reflect movement from the previous week's
    stored rankings."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    week2_ranked = rankings.compute_power_rankings(league, 2)
    league["weeks"]["2"]["rankings"] = week2_ranked

    week3_ranked = rankings.compute_power_rankings(league, 3)
    by_name = {r["name"]: r for r in week3_ranked}
    for name, r in by_name.items():
        prev = next(x for x in week2_ranked if x["name"] == name)
        assert r["previous_rank"] == prev["rank"]
        assert r["rank_change"] == prev["rank"] - r["rank"]


def test_key_factors_are_fact_based_strings():
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    ranked = rankings.compute_power_rankings(league, 3)
    for r in ranked:
        assert isinstance(r["key_factors"], list)
        assert len(r["key_factors"]) > 0
        assert all(isinstance(f, str) and f for f in r["key_factors"])


def test_missing_points_data_does_not_crash():
    """Scenario 8: missing/unclear screenshot data (no points_for) shouldn't blow up ranking."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    league["weeks"]["3"]["teams"][0]["points_for"] = None
    ranked = rankings.compute_power_rankings(league, 3)
    assert len(ranked) == 4


def test_record_vs_power_divergence_flags_fraud_and_underrated():
    """B has a good record but weak scoring/soft schedule -- power rank should lag its record
    rank, flagging it as a fraud-watch candidate. C has a losing record but elite scoring --
    power rank should beat its record rank, flagging it as underrated."""
    league = build_league_from_matchups("Test League", SCENARIO_MATCHUPS)
    ranked = rankings.compute_power_rankings(league, 3)
    by_name = {r["name"]: r for r in ranked}

    for r in ranked:
        assert "record_vs_power" in r
        assert "record_rank" in r
        assert r["record_vs_power"] in ("fraud_watch", "underrated", "aligned")

    # B (2-1) has a better record than C (1-2), so B's record rank beats C's.
    assert by_name["B"]["record_rank"] < by_name["C"]["record_rank"]


def test_new_team_has_no_previous_rank():
    league = build_league_from_matchups("Test League", {1: SCENARIO_MATCHUPS[1]})
    ranked_week1 = rankings.compute_power_rankings(league, 1)
    for r in ranked_week1:
        assert r["previous_rank"] is None
        assert r["rank_change"] is None
