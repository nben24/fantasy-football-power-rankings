import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import memory


def test_multiple_leagues_stay_isolated(tmp_path, monkeypatch):
    """Scenario 10: League A's history must never leak into League B's."""
    monkeypatch.setattr(memory, "LEAGUES_DIR", tmp_path)

    league_a_id = memory.create_league("League A")
    league_b_id = memory.create_league("League B")

    league_a = memory.load_league(league_a_id)
    memory.save_week(league_a, 1, {"teams": [{"name": "Team A1", "record": "1-0"}], "matchups": [], "events": []})
    memory.add_event(league_a, 1, {"type": "trade", "week": 1, "details": "A-only trade"})
    memory.save_league(league_a)

    league_b = memory.load_league(league_b_id)
    assert memory.sorted_week_numbers(league_b) == []
    assert league_b.get("weeks", {}) == {}

    reloaded_a = memory.load_league(league_a_id)
    assert reloaded_a["weeks"]["1"]["events"][0]["details"] == "A-only trade"

    ids = {lg["id"] for lg in memory.list_leagues()}
    assert {league_a_id, league_b_id} <= ids


def test_delete_league_removes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "LEAGUES_DIR", tmp_path)
    league_id = memory.create_league("Temp League")
    assert memory.load_league(league_id) is not None
    memory.delete_league(league_id)
    assert memory.load_league(league_id) is None


def test_event_logging_scenario():
    """Scenario 6: a logged trade event should be retrievable for narrative callbacks."""
    league = {"weeks": {}}
    memory.add_event(league, 3, {"type": "trade", "week": 3, "manager": "Mike", "details": "Mike traded Bijan Robinson"})
    events = league["weeks"]["3"]["events"]
    assert len(events) == 1
    assert events[0]["type"] == "trade"
    assert "Bijan" in events[0]["details"]
