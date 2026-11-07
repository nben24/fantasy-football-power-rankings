"""Pull a week straight from ESPN instead of reading screenshots.

Emits exactly the dict shape `data_extraction.extract_from_screenshots`
returns, so the rest of the pipeline is unchanged -- plus a `lineups` key the
screenshot path can never populate, which is where the player-level material
comes from.

Auth is two browser cookies (espn_s2, SWID) and a league id. espn_s2 is a full
account session token, so it lives in .env and is never logged. This is an
unofficial API: it has changed before and will again, which is why the
screenshot path stays supported rather than being deleted.
"""

import os

from espn_api.football import League

BENCH_SLOTS = {"BE"}
RESERVE_SLOTS = {"IR"}
NON_STARTING_SLOTS = BENCH_SLOTS | RESERVE_SLOTS

# Statuses meaning the player could not meaningfully play.


def slot_eligibility(slot: str) -> set[str]:
    """Positions a lineup slot accepts.

    Flex slots are slash-delimited ("RB/WR/TE" takes a running back, receiver
    or tight end). D/ST contains a slash but is a single position, not a flex,
    so it is special-cased -- splitting it would produce {"D", "ST"} and match
    nothing.
    """
    if slot == "D/ST":
        return {"D/ST"}
    return {part for part in slot.split("/") if part}


def connect(league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None) -> League:
    """A League client. Credentials fall back to the environment."""
    espn_s2 = espn_s2 or os.environ.get("ESPN_S2")
    swid = swid or os.environ.get("ESPN_SWID")
    if not espn_s2 or not swid:
        raise ValueError(
            "ESPN_S2 and ESPN_SWID must be set (in .env) to read a private league."
        )
    return League(league_id=int(league_id), year=int(year), espn_s2=espn_s2, swid=swid)


def _manager_name(team) -> str | None:
    owners = getattr(team, "owners", None) or []
    if not owners:
        return None
    first = owners[0]
    if isinstance(first, dict):
        name = " ".join(x for x in (first.get("firstName"), first.get("lastName")) if x)
        return name or first.get("displayName")
    return str(first)


def _streak_from_outcomes(outcomes: list[str]) -> str | None:
    """Trailing run of identical results, as 'W3' / 'L2'."""
    played = [o for o in outcomes if o in ("W", "L", "T")]
    if not played:
        return None
    last = played[-1]
    if last == "T":
        return None
    run = 0
    for o in reversed(played):
        if o != last:
            break
        run += 1
    return f"{last}{run}"


def team_state_through(team, week: int) -> dict:
    """Record, points and streak as they stood after `week`.

    `league.teams` carries LIVE standings -- pulling week 1 in week 9 would
    otherwise report a 3-5 record beside week 1 scores. ESPN exposes per-week
    arrays (scores, outcomes, margin of victory), so the state at any past week
    is reconstructable: points against follows from own points minus margin,
    since margin is own minus opponent.
    """
    scores = list(getattr(team, "scores", []) or [])[:week]
    outcomes = list(getattr(team, "outcomes", []) or [])[:week]
    movs = list(getattr(team, "mov", []) or [])[:week]

    # 'U' marks a week not yet decided; it is not a result.
    played = [o for o in outcomes if o in ("W", "L", "T")]
    wins = played.count("W")
    losses = played.count("L")
    ties = played.count("T")

    points_for = sum(scores)
    points_against = points_for - sum(movs)

    return {
        "record": f"{wins}-{losses}-{ties}",
        "points_for": round(points_for, 2),
        "points_against": round(points_against, 2),
        "streak": _streak_from_outcomes(outcomes),
        "games": len(played),
    }


def _played(p):
    """True if the player has an actual stat line for the week, False if he
    has none, None if unknown. ESPN writes a line for anyone who appeared --
    a tight end with one target and zero points still has one."""
    breakdown = getattr(p, "breakdown", None)
    if breakdown is None:
        return None
    return bool(breakdown)


def _player_row(p) -> dict:
    return {
        "name": p.name,
        "position": p.position,
        "slot": p.slot_position,
        "started": p.slot_position not in NON_STARTING_SLOTS,
        "points": round(p.points, 2) if p.points is not None else None,
        "projected": round(p.projected_points, 2) if p.projected_points is not None else None,
        # Whether the player recorded a stat line this week, i.e. was in the
        # game. Injury status is deliberately not recorded: ESPN only reports
        # it as of today, so a Tuesday pull showed a QB hurt mid-game as
        # "started on IR". This is the game-time fact that status was standing in for.
        "played": _played(p),
        "on_bye": bool(getattr(p, "on_bye_week", False)),
    }


def fetch_week(league_id: int, year: int, week: int, espn_s2=None, swid=None) -> dict:
    """One week of league data in the pipeline's extraction shape.

    `uncertain_notes` is always empty: there is no OCR here to be unsure about.
    """
    league = connect(league_id, year, espn_s2, swid)
    return build_week(league, week)


def build_week(league: League, week: int) -> dict:
    # Is this the latest completed week? Only then do live-only figures --
    # playoff odds, transaction counts, seeding -- describe the week asked for.
    latest = max(
        (len([o for o in (getattr(t, "outcomes", []) or []) if o in ("W", "L", "T")])
         for t in league.teams),
        default=0,
    )
    is_current = week >= latest

    standings_order = {}
    try:
        standings_order = {
            t.team_name: i for i, t in enumerate(league.standings_weekly(week), start=1)
        }
    except Exception:  # noqa: BLE001 - ordering is a nicety, not worth failing a pull
        standings_order = {}

    teams = []
    for t in league.teams:
        state = team_state_through(t, week)
        teams.append(
            {
                "name": t.team_name,
                "manager": _manager_name(t),
                "record": state["record"],
                "points_for": state["points_for"],
                "points_against": state["points_against"],
                "standing": standings_order.get(t.team_name) or (t.standing if is_current else None),
                "streak": state["streak"],
                # A playoff projection is a live simulation; ESPN keeps no history
                # of what it said in week 3, so claiming one for a past week would
                # be inventing it.
                "playoff_pct": (
                    round(t.playoff_pct, 2)
                    if is_current and t.playoff_pct is not None
                    else None
                ),
                "division": getattr(t, "division_name", None) or None,
                # Season-long manager behaviour. Also live-only counters.
                "acquisitions": getattr(t, "acquisitions", 0) if is_current else None,
                "drops": getattr(t, "drops", 0) if is_current else None,
                "trades": getattr(t, "trades", 0) if is_current else None,
                "moves_to_ir": getattr(t, "move_to_ir", 0) if is_current else None,
            }
        )

    matchups, lineups = [], []
    for box in league.box_scores(week):
        # A team can be absent in a playoff bye; skip rather than invent a matchup.
        if not box.home_team or not box.away_team:
            continue
        matchups.append(
            {
                "team_a": box.home_team.team_name,
                "team_b": box.away_team.team_name,
                "score_a": round(box.home_score, 2),
                "score_b": round(box.away_score, 2),
                "projected_a": round(box.home_projected, 2) if box.home_projected is not None else None,
                "projected_b": round(box.away_projected, 2) if box.away_projected is not None else None,
            }
        )
        for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
            lineups.append(
                {"team": team.team_name, "players": [_player_row(p) for p in lineup]}
            )

    return {
        "week": week,
        "teams": teams,
        "matchups": matchups,
        "lineups": lineups,
        "rosters": [],
        "uncertain_notes": [],
        "source": "espn_api",
    }


def league_team_names(league_id: int, year: int, espn_s2=None, swid=None) -> list[str]:
    """Current team names, for reconciling ESPN's spelling against stored history.

    Screenshot OCR and ESPN disagree on punctuation and case more often than on
    data -- a curly apostrophe, a trailing space, a dropped emoji.
    """
    return [t.team_name for t in connect(league_id, year, espn_s2, swid).teams]
