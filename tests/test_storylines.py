import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import memory, narratives


def test_add_storyline_creates_entry_with_first_event():
    league = {}
    s = memory.add_storyline(league, "Mike's Bijan regret", ["Mike", "John"], 3, "Mike traded Bijan to John")
    assert league["storylines"] == [s]
    assert s["status"] == "ongoing"
    assert s["events"] == [{"week": 3, "description": "Mike traded Bijan to John"}]


def test_append_storyline_event_adds_to_existing():
    league = {}
    s = memory.add_storyline(league, "Mike's Bijan regret", ["Mike", "John"], 3, "Mike traded Bijan to John")
    ok = memory.append_storyline_event(league, s["id"], 4, "Bijan scored 31 for John")
    assert ok is True
    assert len(league["storylines"][0]["events"]) == 2
    assert league["storylines"][0]["events"][1]["week"] == 4


def test_append_storyline_event_returns_false_for_unknown_id():
    league = {"storylines": []}
    assert memory.append_storyline_event(league, "nonexistent", 4, "x") is False


def test_set_storyline_status_marks_resolved():
    league = {}
    s = memory.add_storyline(league, "title", ["A"], 1, "event")
    assert memory.set_storyline_status(league, s["id"], "resolved") is True
    assert league["storylines"][0]["status"] == "resolved"


def test_relevant_storylines_for_team_filters_by_team_and_week():
    league = {}
    memory.add_storyline(league, "Mike's arc", ["Mike"], 3, "trade")
    memory.add_storyline(league, "John's arc", ["John"], 5, "waiver pickup")

    mike_storylines = memory.relevant_storylines_for_team(league, "Mike", up_to_week=10)
    assert len(mike_storylines) == 1
    assert mike_storylines[0]["title"] == "Mike's arc"

    # A storyline whose only event is in a future week isn't relevant yet.
    none_yet = memory.relevant_storylines_for_team(league, "John", up_to_week=4)
    assert none_yet == []


def test_relevant_storylines_sorted_most_recent_first_and_limited():
    league = {}
    memory.add_storyline(league, "old", ["Mike"], 1, "e1")
    memory.add_storyline(league, "newer", ["Mike"], 5, "e2")
    memory.add_storyline(league, "newest", ["Mike"], 9, "e3")

    top2 = memory.relevant_storylines_for_team(league, "Mike", up_to_week=10, limit=2)
    assert [s["title"] for s in top2] == ["newest", "newer"]


def test_apply_storyline_updates_creates_new_storyline():
    league = {}
    updates = [{"storyline_id": None, "title": "Doctor's Orders collapse", "teams": ["Charles"], "event_description": "Scored 49.86", "status": "ongoing"}]
    narratives.apply_storyline_updates(league, 12, updates)
    assert len(league["storylines"]) == 1
    assert league["storylines"][0]["title"] == "Doctor's Orders collapse"


def test_apply_storyline_updates_appends_to_existing_by_id():
    league = {}
    s = memory.add_storyline(league, "arc", ["Mike"], 3, "started")
    updates = [{"storyline_id": s["id"], "title": "arc", "teams": ["Mike"], "event_description": "continued", "status": "ongoing"}]
    narratives.apply_storyline_updates(league, 4, updates)
    assert len(league["storylines"]) == 1  # no duplicate created
    assert len(league["storylines"][0]["events"]) == 2


def test_apply_storyline_updates_marks_resolved():
    league = {}
    s = memory.add_storyline(league, "arc", ["Mike"], 3, "started")
    updates = [{"storyline_id": s["id"], "title": "arc", "teams": ["Mike"], "event_description": "final chapter", "status": "resolved"}]
    narratives.apply_storyline_updates(league, 5, updates)
    assert league["storylines"][0]["status"] == "resolved"


def test_build_facts_bundle_includes_storylines_section_when_present():
    league = {"weeks": {}, "storylines": []}
    memory.add_storyline(league, "Mike's arc", ["A"], 1, "traded Bijan")
    rankings = [{"name": "A", "rank": 1, "previous_rank": None, "rank_change": None, "record": "1-0", "power_score": 90.0, "key_factors": ["1-0 record"], "record_vs_power": "aligned"}]
    league["weeks"]["1"] = {"teams": [], "matchups": [], "rankings": rankings}
    bundle = narratives.build_facts_bundle(league, 1, rankings, "")
    assert "ACTIVE STORYLINES" in bundle
    assert "Mike's arc" in bundle


def test_build_facts_bundle_omits_storylines_section_when_none_exist():
    league = {"weeks": {}}
    rankings = [{"name": "A", "rank": 1, "previous_rank": None, "rank_change": None, "record": "1-0", "power_score": 90.0, "key_factors": ["1-0 record"], "record_vs_power": "aligned"}]
    league["weeks"]["1"] = {"teams": [], "matchups": [], "rankings": rankings}
    bundle = narratives.build_facts_bundle(league, 1, rankings, "")
    assert "ACTIVE STORYLINES" not in bundle
