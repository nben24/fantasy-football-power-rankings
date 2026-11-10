import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import espn_sync, occurrences


def p(name, position, slot, points, played=True, on_bye=False, projected=10.0, **extra):
    return {
        "name": name, "position": position, "slot": slot,
        "started": slot not in ("BE", "IR"),
        "points": points, "projected": projected,
        "played": played, "on_bye": on_bye, **extra,
    }


def kinds(players):
    return {o["kind"] for o in occurrences.lineup_occurrences(players)}


def text_for(players, kind):
    return next(o["text"] for o in occurrences.lineup_occurrences(players) if o["kind"] == kind)


# --- slot eligibility -------------------------------------------------------

def test_flex_slot_accepts_each_listed_position():
    assert espn_sync.slot_eligibility("RB/WR/TE") == {"RB", "WR", "TE"}


def test_defence_slot_is_not_treated_as_a_flex():
    """D/ST contains a slash but is one position; splitting it would yield
    {'D','ST'} and match nothing."""
    assert espn_sync.slot_eligibility("D/ST") == {"D/ST"}


def test_single_position_slot():
    assert espn_sync.slot_eligibility("QB") == {"QB"}


# --- bench disaster ---------------------------------------------------------

def test_bench_disaster_detected_at_same_position():
    players = [p("Starter", "RB", "RB", 5.0), p("Benched", "RB", "BE", 30.0)]
    assert "bench_disaster" in kinds(players)


def test_bench_disaster_crosses_into_a_flex_slot():
    """The real case: a tight end on the bench out-scoring a receiver who was
    started in the RB/WR/TE flex. Position-only matching misses this."""
    players = [p("FlexWR", "WR", "RB/WR/TE", 0.0), p("BenchTE", "TE", "BE", 12.4)]
    assert "bench_disaster" in kinds(players)
    assert "BenchTE" in text_for(players, "bench_disaster")


def test_small_gap_is_not_worth_saying():
    players = [p("Starter", "RB", "RB", 12.0), p("Benched", "RB", "BE", 15.0)]
    assert "bench_disaster" not in kinds(players)


def test_injured_reserve_is_not_a_choice_the_manager_had():
    """A player on IR could not have been started, so leaving him there is not
    a mistake."""
    players = [p("Starter", "RB", "RB", 2.0), p("Stashed", "RB", "IR", 40.0)]
    assert "bench_disaster" not in kinds(players)


def test_bench_player_on_bye_is_not_a_missed_opportunity():
    players = [p("Starter", "RB", "RB", 2.0), p("Resting", "RB", "BE", 0.0, on_bye=True)]
    assert "bench_disaster" not in kinds(players)


def test_only_the_worst_startable_option_counts():
    """Two RBs started; the benched player replaces the weaker one."""
    players = [
        p("Good", "RB", "RB", 25.0),
        p("Bad", "RB", "RB", 3.0),
        p("Benched", "RB", "BE", 20.0),
    ]
    assert "Bad" in text_for(players, "bench_disaster")


def test_position_mismatch_is_not_a_bench_disaster():
    players = [p("Starter", "QB", "QB", 2.0), p("Benched", "WR", "BE", 30.0)]
    assert "bench_disaster" not in kinds(players)


def test_only_the_single_biggest_miss_is_reported():
    players = [
        p("BadA", "RB", "RB", 1.0), p("BadB", "WR", "WR", 1.0),
        p("BenchRB", "RB", "BE", 20.0), p("BenchWR", "WR", "BE", 30.0),
    ]
    found = [o for o in occurrences.lineup_occurrences(players) if o["kind"] == "bench_disaster"]
    assert len(found) == 1
    assert "BenchWR" in found[0]["text"]


# --- starters who didn't play ----------------------------------------------
# ESPN's injury status is as of today, not kickoff. It made "started a guy on IR"
# out of a QB who was hurt during the game (0.8 points, real passing stats) and a
# TE who played and simply didn't score. Only the stat line is a game-time fact.

def test_hurt_during_the_game_is_not_a_no_show():
    players = [p("Dart", "QB", "QB", 0.8, played=True, injury="INJURY_RESERVE")]
    assert "started_did_not_play" not in kinds(players)


def test_played_and_scored_zero_is_not_a_no_show():
    players = [p("Ferguson", "TE", "TE", 0.0, played=True)]
    assert "started_did_not_play" not in kinds(players)


def test_no_stat_line_is_reportable():
    found = occurrences.lineup_occurrences([p("Ghost", "RB", "RB", 0.0, played=False)])
    assert [o["kind"] for o in found] == ["started_did_not_play"]
    assert "no stats recorded" in found[0]["text"]


def test_the_text_never_guesses_why():
    text = occurrences.lineup_occurrences([p("Ghost", "RB", "RB", 0.0, played=False)])[0]["text"]
    for word in ("injur", "IR", "out", "reserve", "suspend"):
        assert word not in text


def test_the_text_does_not_claim_he_never_played():
    """Ladd McConkey got hurt during the game with no stats recorded; the fact
    said "didn't play" and the column called him inactive."""
    text = occurrences.lineup_occurrences([p("Ghost", "RB", "RB", 0.0, played=False)])[0]["text"]
    assert "didn't play" not in text and "can't say" in text


def test_unknown_participation_is_not_reported():
    """Weeks stored before this field existed carry no 'played' key."""
    row = p("Old", "QB", "QB", 0.0)
    del row["played"]
    assert "started_did_not_play" not in kinds([row])


def test_a_bye_is_reported_as_a_bye_not_a_no_show():
    found = kinds([p("Rested", "WR", "WR", 0.0, played=False, on_bye=True)])
    assert "started_on_bye" in found and "started_did_not_play" not in found


# --- bye weeks --------------------------------------------------------------

def test_starting_a_player_on_bye_is_flagged():
    players = [p("Absent", "WR", "WR", 0.0, on_bye=True)]
    assert "started_on_bye" in kinds(players)


# --- integration guard ------------------------------------------------------

def test_screenshot_path_is_unaffected():
    """No lineup data means no lineup occurrences -- the screenshot path must
    keep working exactly as before."""
    assert occurrences.lineup_occurrences([]) == []


def test_a_no_show_with_a_better_bench_option_is_one_fact():
    """Puka Nacua started and didn't play while Waddle scored 21.8 on the bench.
    That is one story; spending two of three slots on it crowded others out."""
    found = occurrences.lineup_occurrences([
        p("Puka", "WR", "WR", 0.0, played=False),
        p("Waddle", "WR", "BE", 21.8),
    ])
    assert [o["kind"] for o in found] == ["bench_disaster"]
    assert "no stats recorded" in found[0]["text"] and "Waddle" in found[0]["text"]


# --- the same player called wrong both ways ---------------------------------

def _wk(*players):
    return list(players)


def test_benched_when_he_went_off_then_started_when_he_didnt():
    """LA FURIA benched Coker for his 36.8 in week 1, started him for 3.8 in week 3."""
    week1 = _wk(p("Lloyd", "RB", "RB/WR/TE", 3.7), p("Coker", "WR", "BE", 36.8))
    week3 = _wk(p("Coker", "WR", "WR", 3.8), p("Robinson", "WR", "BE", 18.7))
    rev = occurrences.lineup_reversal(week3, [(1, week1)])
    assert rev and "Coker" in rev["text"] and "week 1" in rev["text"]
    assert rev["text"].startswith("started Coker this week for 3.8")


def test_the_reverse_direction_is_caught_too():
    """Sedan started Burden for 9.5 over Monangai's 23.4, then benched him for 19.8."""
    week1 = _wk(p("Burden", "WR", "RB/WR/TE", 9.5), p("Monangai", "RB", "BE", 23.4))
    week3 = _wk(p("Jefferson", "WR", "WR", 5.2), p("Burden", "WR", "BE", 19.8))
    rev = occurrences.lineup_reversal(week3, [(1, week1)])
    assert rev and rev["text"].startswith("benched Burden this week")


def test_no_reversal_without_a_swing_in_his_own_score():
    """Started for 10.5, benched for 15.1: two ordinary gaps that share a name."""
    week1 = _wk(p("Mac", "WR", "WR", 10.5), p("Big", "WR", "BE", 25.0))
    week2 = _wk(p("Other", "WR", "WR", 2.0), p("Mac", "WR", "BE", 15.1))
    assert occurrences.lineup_reversal(week2, [(1, week1)]) is None


def test_no_reversal_when_one_call_was_right():
    week1 = _wk(p("Coker", "WR", "BE", 4.0), p("Starter", "WR", "WR", 20.0))
    week3 = _wk(p("Coker", "WR", "WR", 3.8), p("Robinson", "WR", "BE", 18.7))
    assert occurrences.lineup_reversal(week3, [(1, week1)]) is None


def test_a_reversal_mentions_the_weeks_in_between():
    """Coker was also started in week 2. Without that, the writer said EL
    FURIA 'finally trusted' him in week 3 -- an invented fact."""
    week1 = _wk(p("Lloyd", "RB", "RB/WR/TE", 3.7), p("Coker", "WR", "BE", 36.8))
    week2 = _wk(p("Coker", "WR", "WR", 14.6), p("Robinson", "WR", "BE", 9.0))
    week3 = _wk(p("Coker", "WR", "WR", 3.8), p("Robinson", "WR", "BE", 18.7))
    rev = occurrences.lineup_reversal(week3, [(1, week1), (2, week2)])
    assert rev and "week 1" in rev["text"]
    assert "also started him in week 2, 14.6" in rev["text"]
