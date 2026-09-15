import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import data_validation
from tests.mock_data import build_league_from_matchups


def _league_through_week_2():
    return build_league_from_matchups(
        "Recon League",
        {
            1: [("A", 100.0, "B", 90.0), ("C", 120.0, "D", 80.0)],
            2: [("A", 110.0, "C", 105.0), ("B", 95.0, "D", 99.0)],
        },
    )


def _week_3_extraction(**overrides):
    """A clean week 3 consistent with the week-2 cumulative totals."""
    teams = [
        {"name": "A", "record": "3-0", "points_for": 310.0, "points_against": 285.0, "streak": "W3"},
        {"name": "B", "record": "1-2", "points_for": 275.0, "points_against": 299.0, "streak": "L1"},
        {"name": "C", "record": "1-2", "points_for": 315.0, "points_against": 290.0, "streak": "L2"},
        {"name": "D", "record": "1-2", "points_for": 269.0, "points_against": 295.0, "streak": "L1"},
    ]
    matchups = [
        {"team_a": "A", "team_b": "B", "score_a": 100.0, "score_b": 90.0},
        {"team_a": "C", "team_b": "D", "score_a": 90.0, "score_b": 90.0},
    ]
    extracted = {"teams": teams, "matchups": matchups, "uncertain_notes": []}
    extracted.update(overrides)
    return extracted


def test_first_stored_week_skips_rather_than_failing():
    league = build_league_from_matchups("Solo", {1: [("A", 100.0, "B", 90.0)]})
    results = data_validation.reconcile_week(league, 1, league["weeks"]["1"])
    assert results
    assert all(r["status"] != "fail" for r in results)


def test_clean_week_reconciles_with_no_failures():
    league = _league_through_week_2()
    # Replay week 2 against week 1 -- the fixture is internally consistent.
    results = data_validation.reconcile_week(league, 2, league["weeks"]["2"])
    ok, failed, _ = data_validation.reconciliation_summary(results)
    assert failed == 0
    assert ok > 0


def test_misread_score_fails_pf_check():
    league = _league_through_week_2()
    week = {k: list(v) if isinstance(v, list) else v for k, v in league["weeks"]["2"].items()}
    week["matchups"] = [dict(m) for m in week["matchups"]]
    week["matchups"][0]["score_a"] = 118.0  # actually 110.0

    results = data_validation.reconcile_week(league, 2, week)
    fails = [r for r in results if r["status"] == "fail"]
    assert any(r["check"] == "PF" for r in fails)


def test_wrong_record_direction_fails():
    league = _league_through_week_2()
    week = {k: v for k, v in league["weeks"]["2"].items()}
    week["teams"] = [dict(t) for t in week["teams"]]
    loser = next(t for t in week["teams"] if t["name"] == "C")
    loser["record"] = "2-0"  # C lost in week 2, so this can't be right

    results = data_validation.reconcile_week(league, 2, week)
    assert any(r["status"] == "fail" and r["check"] == "record" for r in results)


def test_streak_must_follow_from_result():
    league = _league_through_week_2()
    for t in league["weeks"]["1"]["teams"]:
        t["streak"] = "W1" if t["name"] in ("A", "C") else "L1"

    week = {k: v for k, v in league["weeks"]["2"].items()}
    week["teams"] = [dict(t) for t in week["teams"]]
    for t in week["teams"]:
        # A won both weeks, so W2 is correct; claim W5 instead.
        t["streak"] = "W5" if t["name"] == "A" else "L1"

    results = data_validation.reconcile_week(league, 2, week)
    streak_fails = [r for r in results if r["status"] == "fail" and r["check"] == "streak"]
    assert any(r["team"] == "A" for r in streak_fails)


def test_projection_score_swap_is_warned():
    extracted = {
        "teams": [{"name": "A"}, {"name": "B"}],
        "matchups": [{
            "team_a": "A", "team_b": "B",
            "score_a": 30.0, "projected_a": 120.0,  # implausible: likely swapped
            "score_b": 95.0, "projected_b": 99.0,
        }],
        "uncertain_notes": [],
    }
    warnings = data_validation.validate_extracted_data(extracted)
    assert any("swapped" in w for w in warnings)
