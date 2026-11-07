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


def test_a_projection_miss_says_who_was_favored():
    """'projected 117, lost' was written up as 'projected to cruise' about a team
    projected 117 against 126. The occurrence now says which side was favored."""
    lg = build_league_from_matchups("Odds", {1: [("Furia", 88.42, "Echo", 99.68)]})
    lg["weeks"]["1"]["matchups"][0].update(projected_a=117.08, projected_b=126.5)
    ranked = rankings.compute_power_rankings(lg, 1)
    texts = [o["text"] for o in occurrences.detect(lg, 1, ranked)["teams"].get("Furia", [])]
    miss = [t for t in texts if "under" in t]
    assert miss and "the underdog against Echo" in miss[0]


def _three_games():
    lg = build_league_from_matchups("Sup", {1: [
        ("Alpha", 87.0, "Bravo", 181.22), ("Charlie", 87.7, "Delta", 119.38),
        ("Furia", 88.42, "Echo", 99.68)]})
    projs = [(131.88, 125.92), (120.52, 113.74), (117.08, 126.48)]
    for m, (pa, pb) in zip(lg["weeks"]["1"]["matchups"], projs):
        m.update(projected_a=pa, projected_b=pb)
    return lg


def test_only_the_true_leader_is_called_the_biggest_miss():
    """Charlie missed by 32.8 and was written up as 'the worst miss of the week';
    Alpha had missed by 44.9."""
    lg = _three_games()
    ranked = rankings.compute_power_rankings(lg, 1)
    det = occurrences.detect(lg, 1, ranked)
    assert any("biggest miss of projection: Alpha" in o["text"] for o in det["league"])
    charlie = " ".join(o["text"] for o in det["teams"]["Charlie"])
    assert "biggest" not in charlie


def test_the_bench_gap_leader_is_named_league_wide():
    lg = _three_games()
    lg["weeks"]["1"]["lineups"] = [
        {"team": "Alpha", "players": [
            {"name": "Goedert", "position": "TE", "slot": "TE", "started": True, "points": 1.4, "played": True},
            {"name": "Kittle", "position": "TE", "slot": "BE", "started": False, "points": 18.0, "played": True}]},
        {"team": "Charlie", "players": [
            {"name": "Puka", "position": "WR", "slot": "WR", "started": True, "points": 0.0, "played": False},
            {"name": "Waddle", "position": "WR", "slot": "BE", "started": False, "points": 21.8, "played": True}]},
    ]
    ranked = rankings.compute_power_rankings(lg, 1)
    det = occurrences.detect(lg, 1, ranked)
    assert any(o["text"].startswith("biggest bench gap: Charlie") for o in det["league"])
    assert "biggest bench gap" not in " ".join(o["text"] for o in det["teams"]["Alpha"])


def test_a_tie_at_the_top_gets_no_superlative():
    lg = build_league_from_matchups("Tie", {1: [("A", 80.0, "B", 120.0), ("C", 80.0, "D", 120.0)]})
    for m in lg["weeks"]["1"]["matchups"]:
        m.update(projected_a=110.0, projected_b=110.0)
    det = occurrences.detect(lg, 1, rankings.compute_power_rankings(lg, 1))
    assert not any("biggest miss" in o["text"] for o in det["league"])


def _bench_league(margin_loss, gap_points):
    """Team A loses by `margin_loss` with a bench gap of `gap_points`; C has a
    bigger gap so A is never the league leader."""
    lg = build_league_from_matchups("Bench", {1: [
        ("A", 100.0, "B", 100.0 + margin_loss), ("C", 90.0, "D", 150.0)]})
    lg["weeks"]["1"]["lineups"] = [
        {"team": "A", "players": [
            {"name": "Starter", "position": "WR", "slot": "WR", "started": True, "points": 2.0, "played": True},
            {"name": "Benched", "position": "WR", "slot": "BE", "started": False, "points": 2.0 + gap_points, "played": True}]},
        {"team": "C", "players": [
            {"name": "S", "position": "WR", "slot": "WR", "started": True, "points": 1.0, "played": True},
            {"name": "B", "position": "WR", "slot": "BE", "started": False, "points": 31.0, "played": True}]},
    ]
    det = occurrences.detect(lg, 1, rankings.compute_power_rankings(lg, 1))
    return [o for o in det["teams"]["A"] if o["kind"] == "bench_disaster"]


def test_an_ordinary_bench_gap_is_not_a_story():
    """Week 3 had a bench line in 8 of 12 writeups because any 10-point gap
    qualified; most rosters leave that much most weeks."""
    assert _bench_league(margin_loss=30.0, gap_points=14.0) == []


def test_a_bench_gap_that_would_have_won_is_kept_and_says_so():
    found = _bench_league(margin_loss=5.0, gap_points=12.0)
    assert found and "enough to have won the game" in found[0]["text"]


def test_a_big_bench_gap_in_a_loss_says_it_would_not_have_mattered():
    found = _bench_league(margin_loss=40.0, gap_points=22.0)
    assert found and "would still have lost" in found[0]["text"]


def _many_bench_gaps(n):
    """n games, each loser leaving 25 on the bench."""
    games = [(f"L{i}", 100.0, f"W{i}", 140.0) for i in range(n)]
    lg = build_league_from_matchups("Many", {1: games})
    lg["weeks"]["1"]["lineups"] = [
        {"team": f"L{i}", "players": [
            {"name": f"s{i}", "position": "WR", "slot": "WR", "started": True, "points": 1.0, "played": True},
            {"name": f"b{i}", "position": "WR", "slot": "BE", "started": False, "points": 26.0 + i, "played": True}]}
        for i in range(n)]
    return lg


def test_never_more_than_three_bench_lines_a_week():
    """The user's ceiling for the whole column."""
    lg = _many_bench_gaps(6)
    det = occurrences.detect(lg, 1, rankings.compute_power_rankings(lg, 1))
    lines = [o for occ in det["teams"].values() for o in occ
             if o["kind"] in ("bench_disaster", "lineup_reversal")]
    assert len(lines) == 3
    # the biggest gaps are the ones kept
    assert {o["players"][1] for o in lines} == {"b5", "b4", "b3"}


def test_a_reversal_keeps_the_no_show_it_replaced():
    """Gridiron Gang benched Waddle for 21.8 in week 2 behind Puka Nacua, who
    didn't play, after starting Waddle for 1.2 in week 1."""
    lg = build_league_from_matchups("Rev", {1: [("Doc", 116.0, "X", 113.0)],
                                            2: [("Doc", 133.0, "X", 113.0)]})
    lg["weeks"]["1"]["lineups"] = [{"team": "Doc", "players": [
        {"name": "Waddle", "position": "WR", "slot": "WR", "started": True, "points": 1.2, "played": True},
        {"name": "Diggs", "position": "WR", "slot": "BE", "started": False, "points": 15.5, "played": True}]}]
    lg["weeks"]["2"]["lineups"] = [{"team": "Doc", "players": [
        {"name": "Puka", "position": "WR", "slot": "WR", "started": True, "points": 0.0, "played": False},
        {"name": "Waddle", "position": "WR", "slot": "BE", "started": False, "points": 21.8, "played": True}]}]
    det = occurrences.detect(lg, 2, rankings.compute_power_rankings(lg, 2))
    kinds = {o["kind"] for o in det["teams"]["Doc"]}
    assert {"lineup_reversal", "started_did_not_play"} <= kinds
    assert "bench_disaster" not in kinds
