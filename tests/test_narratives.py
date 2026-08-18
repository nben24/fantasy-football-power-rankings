import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narratives

# Reproduces the real bug: a "Fraud Watch" tier scattered ranks 4, 8, and 10
# together while a "Quietly Better" tier (ranks 5-7) was placed before it,
# making the final list read #1,#2,#3,#5,#6,#7,#4,#8,#10,#9,#11,#12.
RANKINGS = [{"name": f"Team{i}", "rank": i} for i in range(1, 13)]

BROKEN_WRITEUPS = {
    "week_theme": "test",
    "team_writeups": [{"name": f"Team{i}", "narrative": "x"} for i in range(1, 13)],
    "awards": [],
    "recap": "",
    "tiers": [
        {"tier_name": "The Real Ones", "team_names": ["Team1", "Team2", "Team3"]},
        {"tier_name": "Quietly Better", "team_names": ["Team5", "Team6", "Team7"]},
        {"tier_name": "Fraud Watch Convention", "team_names": ["Team4", "Team8", "Team10"]},
        {"tier_name": "Honest Disasters", "team_names": ["Team9", "Team11"]},
        {"tier_name": "Somebody Check On Them", "team_names": ["Team12"]},
    ],
}


def test_normalize_tiers_forces_strict_rank_order():
    fixed = narratives._normalize_tiers(BROKEN_WRITEUPS, RANKINGS)
    flattened = [name for tier in fixed["tiers"] for name in tier["team_names"]]
    assert flattened == [f"Team{i}" for i in range(1, 13)]


def test_normalize_tiers_every_tier_is_contiguous_by_rank():
    fixed = narratives._normalize_tiers(BROKEN_WRITEUPS, RANKINGS)
    rank_by_name = {r["name"]: r["rank"] for r in RANKINGS}
    for tier in fixed["tiers"]:
        ranks = [rank_by_name[n] for n in tier["team_names"]]
        assert ranks == list(range(ranks[0], ranks[0] + len(ranks)))


def test_normalize_tiers_is_a_noop_on_already_contiguous_input():
    clean = {
        "tiers": [
            {"tier_name": "Top", "team_names": ["Team1", "Team2"]},
            {"tier_name": "Bottom", "team_names": ["Team3"]},
        ]
    }
    rankings = [{"name": "Team1", "rank": 1}, {"name": "Team2", "rank": 2}, {"name": "Team3", "rank": 3}]
    fixed = narratives._normalize_tiers(clean, rankings)
    assert [t["team_names"] for t in fixed["tiers"]] == [["Team1", "Team2"], ["Team3"]]
