import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import espn_sync


def fake_team(name, **kw):
    base = dict(
        team_name=name, wins=5, losses=3, ties=0, points_for=812.345,
        points_against=790.1, standing=4, streak_type="WIN", streak_length=3,
        playoff_pct=67.4321, division_name="East", acquisitions=12, drops=11,
        trades=1, move_to_ir=2,
        owners=[{"firstName": "Sam", "lastName": "Reed", "displayName": "sreed99"}],
        # Per-week arrays: state at any past week is rebuilt from these.
        scores=[100.0, 110.0, 120.0, 90.0, 130.0, 80.0, 95.0, 87.345],
        outcomes=["W", "W", "W", "L", "W", "L", "W", "L"],
        mov=[10.0, 20.0, 30.0, -15.0, 25.0, -20.0, 5.0, -10.0],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def fake_player(name, position, slot, points, projected=10.0, injury="ACTIVE", bye=False,
                breakdown=None):
    return SimpleNamespace(
        name=name, position=position, slot_position=slot, points=points,
        projected_points=projected, injuryStatus=injury, on_bye_week=bye,
        breakdown={"receivingTargets": 1} if breakdown is None else breakdown,
    )


def fake_box(home, away, hs=120.5, as_=98.25, hp=115.0, ap=101.0, hl=None, al=None):
    return SimpleNamespace(
        home_team=home, away_team=away, home_score=hs, away_score=as_,
        home_projected=hp, away_projected=ap,
        home_lineup=hl or [], away_lineup=al or [],
    )


class FakeLeague:
    def __init__(self, teams, boxes):
        self.teams = teams
        self._boxes = boxes

    def box_scores(self, week):
        return self._boxes


# --- field mapping ----------------------------------------------------------

def test_streak_reads_the_trailing_run():
    assert espn_sync._streak_from_outcomes(["L", "W", "W", "W"]) == "W3"
    assert espn_sync._streak_from_outcomes(["W", "L", "L"]) == "L2"


def test_no_games_means_no_streak():
    assert espn_sync._streak_from_outcomes([]) is None
    assert espn_sync._streak_from_outcomes(["U"]) is None


def test_manager_name_prefers_the_real_name():
    assert espn_sync._manager_name(fake_team("A")) == "Sam Reed"


def test_manager_falls_back_to_display_name():
    t = fake_team("A", owners=[{"displayName": "ghost42"}])
    assert espn_sync._manager_name(t) == "ghost42"


def test_missing_owner_is_tolerated():
    assert espn_sync._manager_name(fake_team("A", owners=[])) is None


# --- week assembly ----------------------------------------------------------

def _week():
    a, b = fake_team("Alpha"), fake_team("Bravo")
    lineup = [fake_player("Star", "RB", "RB", 20.0), fake_player("Sub", "RB", "BE", 4.0)]
    # Week 8 is the latest decided week for this fixture, i.e. the "current" case.
    return espn_sync.build_week(FakeLeague([a, b], [fake_box(a, b, hl=lineup)]), 8)


def test_week_matches_the_extraction_schema():
    w = _week()
    assert set(w) >= {"week", "teams", "matchups", "lineups", "uncertain_notes"}
    assert w["week"] == 8
    assert set(w["teams"][0]) >= {
        "name", "manager", "record", "points_for", "points_against",
        "standing", "streak", "playoff_pct", "division",
    }
    assert set(w["matchups"][0]) == {
        "team_a", "team_b", "score_a", "score_b", "projected_a", "projected_b",
    }


def test_floats_are_rounded_to_cents():
    t = _week()["teams"][0]
    assert t["points_for"] == 812.35         # all eight weekly scores
    assert t["playoff_pct"] == 67.43         # week 8 is the latest decided


def test_no_uncertain_notes_because_there_is_no_ocr():
    assert _week()["uncertain_notes"] == []


def test_source_is_recorded_so_the_two_paths_are_distinguishable():
    assert _week()["source"] == "espn_api"


def test_season_long_manager_behaviour_is_carried_through():
    t = _week()["teams"][0]
    assert (t["acquisitions"], t["drops"], t["trades"], t["moves_to_ir"]) == (12, 11, 1, 2)


def test_lineups_are_emitted_per_team():
    w = _week()
    assert w["lineups"][0]["team"] == "Alpha"
    assert w["lineups"][0]["players"][0]["started"] is True
    assert w["lineups"][0]["players"][1]["started"] is False


def test_participation_comes_from_the_stat_line():
    assert espn_sync._player_row(fake_player("In", "TE", "TE", 0.0))["played"] is True
    assert espn_sync._player_row(fake_player("Out", "TE", "TE", 0.0, breakdown={}))["played"] is False


def test_live_injury_status_is_not_recorded():
    """It describes today, not the week pulled, so nothing downstream may use it."""
    row = espn_sync._player_row(fake_player("Hurt", "QB", "QB", 0.8, injury="INJURY_RESERVE"))
    assert "injury" not in row


def test_a_playoff_bye_is_skipped_rather_than_invented():
    """box_scores returns a matchup with one side absent during byes."""
    a = fake_team("Alpha")
    w = espn_sync.build_week(FakeLeague([a], [fake_box(a, None)]), 15)
    assert w["matchups"] == []


def test_credentials_are_required(monkeypatch):
    """Must raise before any network call. The environment is cleared because
    another test imports app.py, which calls load_dotenv() and would otherwise
    leak real credentials into this one and hit ESPN for real."""
    import pytest
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    with pytest.raises(ValueError):
        espn_sync.connect(1, 2026, espn_s2=None, swid=None)


# --- historical reconstruction ----------------------------------------------
# league.teams carries LIVE standings. Pulling week 1 during week 9 reported a
# 3-5 record beside week 1 scores until this was fixed.

def _seasoned(**kw):
    """A team eight weeks in: 5-3, with the last three lost."""
    base = dict(
        scores=[100.0, 110.0, 120.0, 90.0, 130.0, 80.0, 95.0, 85.0],
        outcomes=["W", "W", "W", "L", "W", "L", "W", "L"],
        mov=[10.0, 20.0, 30.0, -15.0, 25.0, -20.0, 5.0, -10.0],
    )
    base.update(kw)
    return fake_team("Seasoned", **base)


def test_record_is_reconstructed_as_of_the_week_asked_for():
    t = _seasoned()
    assert espn_sync.team_state_through(t, 1)["record"] == "1-0-0"
    assert espn_sync.team_state_through(t, 4)["record"] == "3-1-0"
    assert espn_sync.team_state_through(t, 8)["record"] == "5-3-0"


def test_points_for_is_cumulative_to_that_week_only():
    t = _seasoned()
    assert espn_sync.team_state_through(t, 1)["points_for"] == 100.0
    assert espn_sync.team_state_through(t, 3)["points_for"] == 330.0


def test_points_against_is_derived_from_margin():
    """ESPN gives margin of victory per week; opponent points follow from it."""
    t = _seasoned()
    # week 1: scored 100, won by 10, so conceded 90
    assert espn_sync.team_state_through(t, 1)["points_against"] == 90.0


def test_streak_is_as_of_that_week_not_now():
    t = _seasoned()
    assert espn_sync.team_state_through(t, 3)["streak"] == "W3"
    assert espn_sync.team_state_through(t, 8)["streak"] == "L1"


def test_undecided_weeks_are_not_counted_as_results():
    """ESPN marks a week still in progress 'U'."""
    t = fake_team("Live", scores=[100.0, 0.0], outcomes=["W", "U"], mov=[10.0, 0.0])
    assert espn_sync.team_state_through(t, 2)["record"] == "1-0-0"
    assert espn_sync.team_state_through(t, 2)["games"] == 1


def test_no_games_played_yet():
    t = fake_team("New", scores=[], outcomes=[], mov=[])
    s = espn_sync.team_state_through(t, 1)
    assert s["record"] == "0-0-0" and s["streak"] is None


def test_playoff_odds_are_withheld_for_past_weeks():
    """A playoff projection is a live simulation; ESPN keeps no history of what
    it said in week 3, so reporting one would be inventing it."""
    t = _seasoned()
    league = FakeLeague([t], [fake_box(t, fake_team("Other", scores=[], outcomes=[], mov=[]))])
    past = espn_sync.build_week(league, 3)["teams"][0]
    assert past["playoff_pct"] is None
    assert past["trades"] is None, "transaction counters are live-only too"


def test_live_figures_are_kept_for_the_latest_week():
    t = _seasoned()
    league = FakeLeague([t], [fake_box(t, fake_team("Other", scores=[], outcomes=[], mov=[]))])
    now = espn_sync.build_week(league, 8)["teams"][0]
    assert now["playoff_pct"] == 67.43
    assert now["trades"] == 1


def test_lineup_team_names_are_normalized_with_everything_else():
    """ESPN returned "Gridiron Gang " with a trailing space. Teams and matchups
    were cleaned; lineups weren't, so that team's lineup facts silently vanished."""
    from src import data_validation
    lg = {"name": "Norm", "teams": ["Doc"], "team_aliases": {}, "weeks": {}}
    ex = {"teams": [{"name": "Doc "}], "matchups": [], "lineups": [{"team": "Doc ", "players": []}]}
    data_validation.normalize_extracted_data(lg, ex)
    assert ex["lineups"][0]["team"] == ex["teams"][0]["name"]


def test_an_unmatched_lineup_is_warned_about():
    from src import data_validation
    ex = {"teams": [{"name": "Doc"}], "matchups": [], "lineups": [{"team": "Ghost", "players": []}]}
    assert any("Lineup for 'Ghost'" in w for w in data_validation.validate_extracted_data(ex))
