import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import memory
from tests.mock_data import build_league_from_matchups


def _league(tmp_path):
    memory.LEAGUES_DIR = tmp_path
    lg = build_league_from_matchups("Redo", {
        1: [("A", 100.0, "B", 90.0)],
        2: [("A", 110.0, "B", 95.0)],
        3: [("A", 120.0, "B", 99.0)],
    })
    lg["current_week"] = 3
    return lg


def test_delete_week_leaves_other_weeks_intact(tmp_path):
    lg = _league(tmp_path)
    assert memory.delete_week(lg, 2) is True
    assert memory.sorted_week_numbers(lg) == [1, 3]
    assert memory.get_week(lg, 1) is not None
    assert memory.get_week(lg, 2) is None


def test_delete_missing_week_is_a_noop(tmp_path):
    lg = _league(tmp_path)
    assert memory.delete_week(lg, 9) is False
    assert memory.sorted_week_numbers(lg) == [1, 2, 3]


def test_delete_week_rolls_back_current_week(tmp_path):
    lg = _league(tmp_path)
    memory.delete_week(lg, 3)
    assert lg["current_week"] == 2


def test_delete_week_strips_only_that_weeks_storyline_events(tmp_path):
    lg = _league(tmp_path)
    s = memory.add_storyline(lg, "A's run", ["A"], 1, "won week 1")
    memory.append_storyline_event(lg, s["id"], 2, "won week 2")
    memory.append_storyline_event(lg, s["id"], 3, "won week 3")

    memory.delete_week(lg, 2)
    weeks = [e["week"] for e in memory.get_storylines(lg)[0]["events"]]
    assert weeks == [1, 3]


def test_storyline_with_no_surviving_events_is_dropped(tmp_path):
    lg = _league(tmp_path)
    memory.add_storyline(lg, "Week 2 only", ["A"], 2, "happened in week 2")
    memory.add_storyline(lg, "Week 1 too", ["B"], 1, "happened in week 1")

    memory.delete_week(lg, 2)
    titles = [s["title"] for s in memory.get_storylines(lg)]
    assert titles == ["Week 1 too"]


def test_rollback_is_idempotent_so_rewrites_dont_duplicate(tmp_path):
    """Regenerating a week repeatedly must not accumulate storyline events."""
    lg = _league(tmp_path)
    s = memory.add_storyline(lg, "Arc", ["A"], 1, "week 1")

    for _ in range(3):
        memory.remove_storyline_events_for_week(lg, 2)
        memory.append_storyline_event(lg, s["id"], 2, "week 2 again")

    events = memory.get_storylines(lg)[0]["events"]
    assert [e["week"] for e in events] == [1, 2]
