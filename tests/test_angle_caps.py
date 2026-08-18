import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narratives


def _angle(team, comedy_type, backups=None):
    return {"team": team, "best_angle": f"{team}'s angle", "comedy_type": comedy_type, "supporting_facts": [], "backup_angles": backups or []}


def _ranking(name, rank, record_rank):
    return {"name": name, "rank": rank, "record_rank": record_rank}


def test_cap_fraud_lens_angles_noop_when_under_cap():
    angles = [_angle("A", "fraud / inflated record"), _angle("B", "trade regret")]
    rankings = [_ranking("A", 1, 3), _ranking("B", 2, 2)]
    result = narratives.cap_fraud_lens_angles(angles, rankings, max_count=3)
    assert result == angles


def test_cap_fraud_lens_angles_reassigns_excess_to_backup():
    # 5 teams flagged fraud/underrated, cap of 2 -- 3 should get reassigned.
    angles = [
        _angle("A", "fraud / inflated record", backups=["A backup"]),
        _angle("B", "underrated contender", backups=["B backup"]),
        _angle("C", "fraud / inflated record", backups=["C backup"]),
        _angle("D", "underrated contender", backups=["D backup"]),
        _angle("E", "fraud / inflated record", backups=["E backup"]),
    ]
    # Divergence magnitude (|record_rank - rank|): A=5, B=4, C=3, D=2, E=1 -- keep A, B.
    rankings = [
        _ranking("A", 1, 6),
        _ranking("B", 2, 6),
        _ranking("C", 3, 6),
        _ranking("D", 4, 6),
        _ranking("E", 5, 6),
    ]
    result = narratives.cap_fraud_lens_angles(angles, rankings, max_count=2)
    by_team = {a["team"]: a for a in result}

    assert by_team["A"]["comedy_type"] == "fraud / inflated record"
    assert by_team["B"]["comedy_type"] == "underrated contender"
    assert by_team["C"]["best_angle"] == "C backup"
    assert by_team["D"]["best_angle"] == "D backup"
    assert by_team["E"]["best_angle"] == "E backup"
    assert by_team["C"]["comedy_type"] == "reassigned (fraud-lens cap)"


def test_cap_fraud_lens_angles_falls_back_to_note_without_backups():
    angles = [
        _angle("A", "fraud / inflated record"),
        _angle("B", "fraud / inflated record"),
        _angle("C", "fraud / inflated record"),
    ]
    rankings = [_ranking("A", 1, 3), _ranking("B", 2, 4), _ranking("C", 3, 1)]
    result = narratives.cap_fraud_lens_angles(angles, rankings, max_count=1)
    reassigned = [a for a in result if a["comedy_type"] == "reassigned (fraud-lens cap)"]
    assert len(reassigned) == 2
    for a in reassigned:
        assert "do not use it" in a["best_angle"]


def test_cap_fraud_lens_angles_default_cap_is_roughly_a_third():
    angles = [_angle(f"T{i}", "fraud / inflated record") for i in range(12)]
    rankings = [_ranking(f"T{i}", i + 1, 12 - i) for i in range(12)]
    result = narratives.cap_fraud_lens_angles(angles, rankings)  # no explicit max_count
    kept = [a for a in result if a["comedy_type"] == "fraud / inflated record"]
    assert len(kept) == max(3, 12 // 3)


def test_find_repeated_imagery_flags_shared_distinctive_word():
    writeups = [
        {"name": "A", "narrative": "That's not a bad beat, that's a mugging with a scoreboard attached."},
        {"name": "B", "narrative": "This wasn't a win, it was a mugging in broad daylight."},
        {"name": "C", "narrative": "A clean, unremarkable victory with nothing notable about it."},
    ]
    warnings = narratives.find_repeated_imagery(writeups)
    assert len(warnings) == 1
    team_a, team_b, words = warnings[0]
    assert {team_a, team_b} == {"A", "B"}
    assert "mugging" in words


def test_find_repeated_imagery_no_false_positive_on_common_words():
    writeups = [
        {"name": "A", "narrative": "This team scored well this week and still somehow lost the game."},
        {"name": "B", "narrative": "Another team scored well this week and finally won a game."},
    ]
    warnings = narratives.find_repeated_imagery(writeups)
    assert warnings == []
