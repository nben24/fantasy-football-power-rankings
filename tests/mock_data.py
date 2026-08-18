"""Small deterministic league fixtures used by the test suite. No screenshots,
no API calls -- just hand-built data covering the scenarios in the spec."""


def _record_str(w, l):
    return f"{w}-{l}"


def build_league_from_matchups(name: str, weekly_matchups: dict[int, list[tuple]]) -> dict:
    """weekly_matchups: {week_num: [(team_a, score_a, team_b, score_b), ...]}
    Builds a league dict with cumulative standings computed from the matchups,
    same shape memory.py / rankings.py expect."""
    league = {
        "id": "test_league",
        "name": name,
        "description": "",
        "managers": [],
        "league_notes": "",
        "team_aliases": {},
        "current_week": 0,
        "weeks": {},
    }

    cumulative = {}  # team -> {"w":0,"l":0,"pf":0.0,"pa":0.0}

    for week in sorted(weekly_matchups.keys()):
        matchups = []
        for team_a, score_a, team_b, score_b in weekly_matchups[week]:
            matchups.append({"team_a": team_a, "team_b": team_b, "score_a": score_a, "score_b": score_b})
            for team, own, opp in ((team_a, score_a, score_b), (team_b, score_b, score_a)):
                c = cumulative.setdefault(team, {"w": 0, "l": 0, "pf": 0.0, "pa": 0.0})
                c["pf"] += own
                c["pa"] += opp
                if own > opp:
                    c["w"] += 1
                elif own < opp:
                    c["l"] += 1

        teams = [
            {
                "name": t,
                "manager": None,
                "record": _record_str(c["w"], c["l"]),
                "points_for": round(c["pf"], 1),
                "points_against": round(c["pa"], 1),
                "standing": None,
            }
            for t, c in cumulative.items()
        ]

        league["weeks"][str(week)] = {
            "teams": teams,
            "matchups": matchups,
            "rosters": [],
            "context": "",
            "events": [],
        }
        league["current_week"] = week

    return league


# Scenario set: A = best record + best scoring. B = good record but weak scoring
# / soft schedule (beats only D, the league's weakest team). C = bad record but
# elite scoring, loses close games (an "unlucky" team the power rankings should
# recognize). D = bad team.
SCENARIO_MATCHUPS = {
    1: [("A", 160.0, "D", 90.0), ("B", 120.0, "C", 115.0)],
    2: [("A", 155.0, "C", 150.0), ("B", 110.0, "D", 95.0)],
    3: [("A", 150.0, "B", 140.0), ("C", 160.0, "D", 80.0)],
}
