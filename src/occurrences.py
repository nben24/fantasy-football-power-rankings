"""Deterministic detection of things that actually HAPPENED this week.

The angle-finder used to receive only aggregates (PPG, win%, schedule
strength), so it manufactured statistical premises -- every storyline it
produced was an observation about averages rather than an event. This module
supplies the missing layer: concrete occurrences, computed from data already
on hand, at zero API cost.

Design note: a team with nothing notable gets an EMPTY list, and that silence
is meaningful. It's the signal for the writer to be brief and dismissive
instead of inflating a non-event into a paragraph.
"""

from src import memory, rankings

BLOWOUT_MARGIN = 40.0
NAILBITER_MARGIN = 3.0
PROJECTION_GAP = 25.0
NOTABLE_STREAK = 3
NOTABLE_RANK_MOVE = 3
PLAYOFF_LONGSHOT = 10.0
PLAYOFF_NEAR_LOCK = 95.0

# A "new high/low" is only an event if there's enough history for it to mean
# something. With N weeks on record roughly 2/N of the league sets an extreme
# every week by chance alone -- at N=3 that's two thirds of the teams, which is
# noise dressed up as a story. It also has to clear the old mark by a real
# margin rather than tying it by a rounding error.
MIN_WEEKS_FOR_EXTREME = 6
EXTREME_MARGIN = 3.0


def _fmt(n):
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _this_week_games(week_data):
    """{team: {'own','opp','opponent','won','margin','proj','opp_proj'}}"""
    out = {}
    for m in week_data.get("matchups", []):
        sa, sb = m.get("score_a"), m.get("score_b")
        if sa is None or sb is None:
            continue
        a, b = m["team_a"], m["team_b"]
        pa, pb = m.get("projected_a"), m.get("projected_b")
        out[a] = {"own": sa, "opp": sb, "opponent": b, "won": sa > sb,
                  "margin": sa - sb, "proj": pa, "opp_proj": pb}
        out[b] = {"own": sb, "opp": sa, "opponent": a, "won": sb > sa,
                  "margin": sb - sa, "proj": pb, "opp_proj": pa}
    return out


def detect(league: dict, week: int, ranked: list[dict]) -> dict:
    """Returns {'teams': {name: [occurrence, ...]}, 'league': [occurrence, ...]}.

    Each occurrence is {'kind': str, 'text': str, 'weight': int} where text is
    a plain factual sentence safe to quote and weight orders significance.
    """
    week_data = memory.get_week(league, week) or {}
    games = _this_week_games(week_data)
    by_name = {r["name"]: r for r in ranked}
    teams: dict[str, list[dict]] = {r["name"]: [] for r in ranked}

    def add(name, kind, text, weight):
        if name in teams:
            teams[name].append({"kind": kind, "text": text, "weight": weight})

    scores = {n: g["own"] for n, g in games.items()}
    league_notes = []

    if scores:
        hi_name = max(scores, key=scores.get)
        lo_name = min(scores, key=scores.get)
        league_notes.append({"kind": "week_high", "weight": 5,
                             "text": f"highest score of the week: {hi_name} with {_fmt(scores[hi_name])}"})
        league_notes.append({"kind": "week_low", "weight": 5,
                             "text": f"lowest score of the week: {lo_name} with {_fmt(scores[lo_name])}"})
        add(hi_name, "week_high", f"scored {_fmt(scores[hi_name])} -- the highest score in the league this week", 8)
        add(lo_name, "week_low", f"scored {_fmt(scores[lo_name])} -- the lowest score in the league this week", 8)

    for name, g in games.items():
        if name not in teams:
            continue
        margin = abs(g["margin"])

        if margin >= BLOWOUT_MARGIN:
            verb = "beat" if g["won"] else "lost to"
            add(name, "blowout", f"{verb} {g['opponent']} by {_fmt(margin)} ({_fmt(g['own'])}-{_fmt(g['opp'])})", 9)
        elif margin <= NAILBITER_MARGIN:
            verb = "won" if g["won"] else "lost"
            add(name, "nailbiter", f"{verb} by {_fmt(margin)} against {g['opponent']} "
                                   f"({_fmt(g['own'])}-{_fmt(g['opp'])})", 9)

        # Scored well and still lost / scored badly and still won. The top-3 and
        # bottom-3 variants only mean anything in a real-sized league -- in a small
        # one they'd flag most of the field.
        others = [s for t, s in scores.items() if t not in (name, g["opponent"])]
        if not g["won"] and others and g["own"] > max(others):
            add(name, "high_score_loss",
                "outscored every other team in the league this week and still lost, "
                f"because {g['opponent']} put up {_fmt(g['opp'])}", 10)
        elif len(scores) >= 6 and not g["won"] and g["own"] > sorted(scores.values(), reverse=True)[2]:
            add(name, "good_score_loss", f"scored {_fmt(g['own'])}, a top-3 score this week, and still lost", 7)
        if len(scores) >= 6 and g["won"] and g["own"] <= sorted(scores.values())[2]:
            add(name, "bad_score_win", f"won despite scoring only {_fmt(g['own'])}, one of the week's worst", 6)

        # Projection gaps -- ESPN's own number, so this is factual, not invented.
        if g["proj"] is not None:
            gap = g["own"] - g["proj"]
            if gap <= -PROJECTION_GAP:
                add(name, "under_projection",
                    f"projected {_fmt(g['proj'])} but scored {_fmt(g['own'])} -- {_fmt(abs(gap))} under", 8)
            elif gap >= PROJECTION_GAP:
                add(name, "over_projection",
                    f"projected {_fmt(g['proj'])} but scored {_fmt(g['own'])} -- {_fmt(gap)} over", 7)
            if g["opp_proj"] is not None and not g["won"] and g["proj"] > g["opp_proj"]:
                add(name, "lost_as_favorite",
                    f"was projected to outscore {g['opponent']} "
                    f"({_fmt(g['proj'])} to {_fmt(g['opp_proj'])}) and lost anyway", 8)

        history = rankings._team_game_history(league, name, week)
        prior = [h["score"] for h in history if h["week"] != week]
        if len(prior) + 1 >= MIN_WEEKS_FOR_EXTREME:
            # Only a true season extreme if tracking started at week 1 -- otherwise
            # the earlier weeks were never uploaded and claiming "season-high" is a
            # fabricated fact. The partial-history wording is phrased as a normal
            # sports claim ("in nine weeks"), not as a database disclaimer.
            full_season = min(memory.sorted_week_numbers(league) or [week]) <= 1
            span = "of the season" if full_season else f"in {len(prior) + 1} weeks"
            if g["own"] >= max(prior) + EXTREME_MARGIN:
                add(name, "high_water", f"{_fmt(g['own'])} -- their best score {span}", 7)
            elif g["own"] <= min(prior) - EXTREME_MARGIN:
                add(name, "low_water", f"{_fmt(g['own'])} -- their worst score {span}", 7)

    for r in ranked:
        name = r["name"]
        t = next((x for x in week_data.get("teams", []) if x["name"] == name), {})

        streak = _streak_tuple(t.get("streak"))
        if streak:
            direction, length = streak
            if length >= NOTABLE_STREAK:
                word = "win" if direction == "W" else "losing"
                add(name, "streak", f"on a {length}-game {word} streak ({direction}{length})", 8)
        prev_streak = _prev_streak(league, week, name)
        if prev_streak and streak and prev_streak[0] != streak[0] and prev_streak[1] >= NOTABLE_STREAK:
            word = "winning" if prev_streak[0] == "W" else "losing"
            add(name, "streak_snapped", f"{prev_streak[1]}-game {word} streak ended this week", 9)

        if r.get("previous_rank") is not None and r.get("rank_change"):
            move = r["rank_change"]
            if abs(move) >= NOTABLE_RANK_MOVE:
                direction = "climbed" if move > 0 else "fell"
                add(name, "rank_move", f"{direction} {abs(move)} spots in the rankings this week", 7)

        pct = t.get("playoff_pct")
        if pct is not None:
            if pct <= PLAYOFF_LONGSHOT:
                add(name, "playoff_longshot", f"playoff odds down to {_fmt(pct)}%", 6)
            elif pct >= PLAYOFF_NEAR_LOCK:
                add(name, "playoff_lock", f"playoff odds at {_fmt(pct)}%", 5)
            prev_pct = _prev_playoff_pct(league, week, name)
            if prev_pct is not None and abs(pct - prev_pct) >= 20:
                direction = "rose" if pct > prev_pct else "fell"
                add(name, "playoff_swing",
                    f"playoff odds {direction} from {_fmt(prev_pct)}% to {_fmt(pct)}%", 8)

    for name in teams:
        teams[name].sort(key=lambda o: -o["weight"])

    return {"teams": teams, "league": league_notes}


def _streak_tuple(streak):
    import re
    if not streak:
        return None
    m = re.match(r"\s*([WL])\s*(\d+)\s*$", str(streak), re.I)
    return (m.group(1).upper(), int(m.group(2))) if m else None


def _prev_streak(league, week, name):
    prev = memory.get_previous_week_number(league, week)
    if prev is None:
        return None
    pd = memory.get_week(league, prev) or {}
    t = next((x for x in pd.get("teams", []) if x["name"] == name), None)
    return _streak_tuple((t or {}).get("streak"))


def _prev_playoff_pct(league, week, name):
    prev = memory.get_previous_week_number(league, week)
    if prev is None:
        return None
    pd = memory.get_week(league, prev) or {}
    t = next((x for x in pd.get("teams", []) if x["name"] == name), None)
    return (t or {}).get("playoff_pct")


def format_for_prompt(detected: dict, team_name: str) -> str:
    """The occurrence lines for one team, or an explicit empty marker."""
    items = detected.get("teams", {}).get(team_name, [])
    if not items:
        return "NOTHING NOTABLE HAPPENED TO THIS TEAM THIS WEEK"
    return "; ".join(o["text"] for o in items)
