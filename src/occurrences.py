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
MAX_OCCURRENCES_PER_TEAM = 3
BIG_BENCH_GAP = 20.0  # below this, a bench gap only counts if it cost the game
MAX_BENCH_LINES_PER_WEEK = 3  # the user's ceiling for the whole column
REVERSAL_SWING = 10.0  # the player's own score must move this much between the two calls


BENCH_GAP = 10.0  # points a benched player beat a startable one by, to be worth saying


def _fmt(n):
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _eligible_slots(position: str, starters: list[dict]) -> list[dict]:
    """Starters this player could have replaced.

    Slot labels are slash-delimited for flex ("RB/WR/TE"), so a benched tight
    end is eligible for the TE slot *and* the flex. D/ST contains a slash but
    is one position, not a flex.
    """
    out = []
    for s in starters:
        slot = s.get("slot") or ""
        allowed = {slot} if slot == "D/ST" else {p for p in slot.split("/") if p}
        if position in allowed:
            out.append(s)
    return out


def _decision_cost(player: dict, players: list[dict]) -> float | None:
    """How many points a start/sit call on `player` cost, or None if it cost
    nothing that could have been fixed with an eligible swap.

    Started: the best eligible bench player minus his score.
    Benched: his score minus the worst eligible starter he could have replaced.
    """
    starters = [p for p in players if p.get("started")]
    bench = [p for p in players if not p.get("started") and (p.get("slot") or "") != "IR"
             and not p.get("on_bye") and p.get("points") is not None]
    pts = player.get("points")
    if pts is None:
        return None
    if player.get("started"):
        rivals = [b["points"] for b in bench if player in _eligible_slots(b.get("position") or "", starters)]
        return (max(rivals) - pts) if rivals else None
    if (player.get("slot") or "") == "IR" or player.get("on_bye"):
        return None
    rivals = [o["points"] for o in _eligible_slots(player.get("position") or "", starters)
              if o.get("points") is not None]
    return (pts - min(rivals)) if rivals else None


# What an empty stat line means. "Didn't play" was itself a guess: a receiver
# hurt on the opening drive also has no stat line, and the writer turned "didn't
# play" into "inactive" for one who got hurt in the game. Say only what the data
# knows, and say out loud that the reason isn't known so nothing fills the gap.
NO_STAT_LINE = ("scored 0 with no stats recorded -- the data can't say whether he "
                "got hurt early, was inactive or just never touched the ball")


def lineup_reversal(current: list[dict], earlier: list[tuple[int, list[dict]]]) -> dict | None:
    """The same player called wrong in opposite directions: benched the week
    he went off, started the week he didn't (or the reverse). Both calls must
    have cost at least BENCH_GAP and his own score must have swung by
    REVERSAL_SWING, so it is a pattern, not noise.

    `earlier` is [(week, players), ...]; the most recent qualifying week wins.
    """
    best = None
    for p in current:
        cost_now = _decision_cost(p, current)
        if cost_now is None or cost_now < BENCH_GAP:
            continue
        for wk, players in sorted(earlier, key=lambda x: -x[0]):
            then = next((q for q in players if q.get("name") == p.get("name")), None)
            if not then or bool(then.get("started")) == bool(p.get("started")):
                continue
            cost_then = _decision_cost(then, players)
            if cost_then is None or cost_then < BENCH_GAP:
                continue
            # The joke is "benched him when he went off, started him when he
            # didn't". Without a real swing in his own score (10.5 then 15.1)
            # it is just two ordinary bench gaps that share a name.
            if abs((p.get("points") or 0) - (then.get("points") or 0)) < REVERSAL_SWING:
                continue
            total = cost_now + cost_then
            # Weeks in between where he got the same call as now. Leaving them
            # out let the writer say "finally trusted Coker" about a player
            # who had also started the week before.
            between = []
            for w2, pl2 in sorted(earlier, key=lambda x: x[0]):
                if w2 <= wk:
                    continue
                q = next((q for q in pl2 if q.get("name") == p.get("name")), None)
                if q and bool(q.get("started")) == bool(p.get("started")) and q.get("points") is not None:
                    between.append((w2, q["points"]))
            if best is None or total > best[0]:
                best = (total, p, then, wk, between)
            break
    if not best:
        return None
    _, now, then, wk, between = best
    if now.get("started"):
        text = (f"started {now['name']} this week for {_fmt(now['points'])} after benching him in "
                f"week {wk}, when he scored {_fmt(then['points'])} -- wrong about him both times")
        verb = "started"
    else:
        text = (f"benched {now['name']} this week while he scored {_fmt(now['points'])} after "
                f"starting him in week {wk} for {_fmt(then['points'])} -- wrong about him both times")
        verb = "benched"
    if between:
        text += f" (also {verb} him in " + ", ".join(
            f"week {w2}, {_fmt(pts)}" for w2, pts in between) + ")"
    return {"kind": "lineup_reversal", "weight": 10, "player": now["name"], "text": text}


def lineup_occurrences(players: list[dict]) -> list[dict]:
    """Occurrences visible only in a full lineup: the ones the manager caused.

    This is the material that previously had to be typed into the context box
    every week -- who was benched, who was started hurt, who was on a bye.
    """
    found = []
    starters = [p for p in players if p.get("started")]
    # Only BE can be swapped in; IR is not a choice the manager had.
    bench = [p for p in players if not p.get("started") and (p.get("slot") or "") != "IR"]

    best = None
    for b in bench:
        if b.get("points") is None or b.get("on_bye"):
            continue
        options = _eligible_slots(b.get("position") or "", starters)
        options = [o for o in options if o.get("points") is not None]
        if not options:
            continue
        worst = min(options, key=lambda o: o["points"])
        gap = b["points"] - worst["points"]
        if gap >= BENCH_GAP and (best is None or gap > best[0]):
            best = (gap, worst, b)
    no_show_named = None
    if best:
        gap, worst, b = best
        # When the starter never took the field, say so in the same fact
        # rather than spending a second of the team's three slots on it.
        if worst.get("played") is False:
            no_show_named = worst["name"]
            started = f"started {worst['name']}, who {NO_STAT_LINE},"
        else:
            started = f"started {worst['name']} ({_fmt(worst['points'])})"
        found.append({
            "kind": "bench_disaster",
            "weight": 10,
            "gap": gap,
            "players": (worst["name"], b["name"]),
            "no_show": no_show_named,
            "text": (
                f"{started} over {b['name']} "
                f"({_fmt(b['points'])}) on the bench -- {_fmt(gap)} points left there"
            ),
        })

    # A started player with no stat line at all didn't take the field. That is
    # a game-time fact. ESPN's injury status is not: it is reported as of today,
    # so a Tuesday pull listed a QB who was hurt during the game as "on IR", and
    # Lamar Jackson as on IR in a week he scored 30. Why a player sat isn't
    # knowable from this data, so the text doesn't guess at it.
    for s in starters:
        if s.get("played") is False and not s.get("on_bye") and s["name"] != no_show_named:
            found.append({
                "kind": "started_did_not_play",
                "weight": 9,
                "text": f"started {s['name']}, who {NO_STAT_LINE}",
            })
            break

    for s in starters:
        if s.get("on_bye"):
            found.append({
                "kind": "started_on_bye",
                "weight": 9,
                "text": f"started {s['name']}, who was on a bye week",
            })
            break

    return found


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

    def add(name, kind, text, weight, **extra):
        if name in teams:
            teams[name].append({"kind": kind, "text": text, "weight": weight, **extra})

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
            # Say who was favored. Given only "projected 117, lost", the writer
            # called an underdog "projected to cruise" -- a big-sounding number
            # read as favoritism the matchup never had.
            odds = ""
            if g["opp_proj"] is not None and g["proj"] != g["opp_proj"]:
                side = "favored" if g["proj"] > g["opp_proj"] else "the underdog"
                odds = (f"; was {side} against {g['opponent']} going in "
                        f"({_fmt(g['proj'])} to {_fmt(g['opp_proj'])})")
            if gap <= -PROJECTION_GAP:
                add(name, "under_projection",
                    f"projected {_fmt(g['proj'])} but scored {_fmt(g['own'])} -- {_fmt(abs(gap))} under{odds}", 8)
            elif gap >= PROJECTION_GAP:
                add(name, "over_projection",
                    f"projected {_fmt(g['proj'])} but scored {_fmt(g['own'])} -- {_fmt(gap)} over{odds}", 7)
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

    # Lineup-level occurrences, when the week came from the API. The screenshot
    # path has no player data, so this simply contributes nothing there.
    for entry in week_data.get("lineups") or []:
        name = entry.get("team")
        if name not in teams:
            continue
        players = entry.get("players") or []
        for occ in lineup_occurrences(players):
            add(name, occ["kind"], occ["text"], occ["weight"],
                **{k: v for k, v in occ.items() if k not in ("kind", "text", "weight")})
        rev = lineup_reversal(players, _earlier_lineups(league, week, name))
        if rev:
            # The reversal is the better telling of a bench gap on the same
            # player this week, so it replaces that one rather than doubling up.
            replaced = [o for o in teams[name]
                        if o["kind"] == "bench_disaster" and rev["player"] in o.get("players", ())]
            teams[name] = [o for o in teams[name] if o not in replaced]
            add(name, rev["kind"], rev["text"], rev["weight"], player=rev["player"])
            # A no-show folded into the replaced fact is still its own fact.
            for o in replaced:
                if o.get("no_show"):
                    add(name, "started_did_not_play",
                        f"started {o['no_show']}, who {NO_STAT_LINE}", 9)

    # League-wide extremes, computed rather than left to the writer. Shown only
    # each team's own facts, it called a 32.8-point projection miss "the worst
    # of the week" when another team missed by 44.9, and a 21.04 bench gap "the
    # biggest" when another was 21.8. A superlative is only safe if it is
    # stated here, so these are named in the league section and on the
    # leader's own fact. A tie at the top gets no superlative at all.
    def crown(values: dict, kind: str, label: str, describe):
        if not values:
            return
        ordered = sorted(values.items(), key=lambda kv: -kv[1])
        if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
            return
        leader, _ = ordered[0]
        league_notes.append({"kind": kind, "weight": 5,
                             "text": f"{label}: {leader}, {describe(leader)}"})
        for o in teams.get(leader, []):
            if o["kind"] == kind:
                o["text"] += f" -- the {label} in the league this week"

    misses, beats = {}, {}
    for name, g in games.items():
        if name in teams and g["proj"] is not None:
            gap = g["own"] - g["proj"]
            if gap <= -PROJECTION_GAP:
                misses[name] = -gap
            elif gap >= PROJECTION_GAP:
                beats[name] = gap
    crown(misses, "under_projection", "biggest miss of projection",
          lambda n: f"{_fmt(misses[n])} under")
    crown(beats, "over_projection", "biggest beat of projection",
          lambda n: f"{_fmt(beats[n])} over")
    bench_gaps = {n: o["gap"] for n, occ in teams.items() for o in occ
                  if o["kind"] == "bench_disaster" and "gap" in o}
    crown(bench_gaps, "bench_disaster", "biggest bench gap",
          lambda n: f"{_fmt(bench_gaps[n])} points left on the bench")

    # A 10-point bench gap is ordinary in a 12-team league -- most rosters
    # leave that much most weeks -- so reporting every one put a bench line in
    # 8 of 12 writeups by week 3 (the user's own columns: 2% of paragraphs).
    # Keep the ones that are a story: the gap would have flipped a loss, it is
    # big in absolute terms, or it is the league's biggest. Each kept fact
    # also says whether it changed the result, so the writer doesn't have to
    # work that out.
    for name in teams:
        g = games.get(name)
        kept = []
        for o in teams[name]:
            if o["kind"] == "bench_disaster" and "gap" in o:
                lost = g is not None and not g["won"]
                flipped = lost and o["gap"] > abs(g["margin"])
                leader = "the biggest bench gap" in o["text"]
                if not (flipped or o["gap"] >= BIG_BENCH_GAP or leader):
                    continue
                if lost:
                    o["text"] += (" -- enough to have won the game" if flipped
                                  else " -- would still have lost")
                    if flipped:
                        o["weight"] = 11
            kept.append(o)
        teams[name] = kept

    # The column gets at most MAX_BENCH_LINES_PER_WEEK lineup-decision lines in
    # total. Priority: a call that cost the game, then the same player called
    # wrong both ways, then the size of the gap.
    bench_kinds = ("bench_disaster", "lineup_reversal")
    ranked_bench = sorted(
        ((name, o) for name, occ in teams.items() for o in occ if o["kind"] in bench_kinds),
        key=lambda no: (
            "enough to have won" not in no[1]["text"],
            no[1]["kind"] != "lineup_reversal",
            -no[1].get("gap", 0),
        ),
    )
    dropped = {id(o) for _, o in ranked_bench[MAX_BENCH_LINES_PER_WEEK:]}
    for name in teams:
        teams[name] = [o for o in teams[name] if id(o) not in dropped]
    # If the league's biggest gap lost its slot, don't advertise it either --
    # the league note alone would put a fourth bench line in the column.
    if not any("the biggest bench gap" in o["text"] for occ in teams.values() for o in occ):
        league_notes[:] = [n for n in league_notes if n["kind"] != "bench_disaster"]

    # Keep only the strongest few. Thresholds were set in week 4 with four games
    # of history; by week 6 streaks, rank movement and high/low water marks have
    # all unlocked, so a team can accumulate five "notable" items and earn a
    # paragraph it hasn't done anything to deserve. Everything beyond the top
    # three is padding.
    for name in teams:
        teams[name].sort(key=lambda o: -o["weight"])
        del teams[name][MAX_OCCURRENCES_PER_TEAM:]

    return {"teams": teams, "league": league_notes}


def _earlier_lineups(league: dict, week: int, name: str) -> list[tuple[int, list[dict]]]:
    """This team's stored lineups from earlier weeks, matched across renames
    and stray whitespace in how ESPN spelled the name at the time."""
    variants = {v.strip() for v in memory.name_variants(league, name)}
    out = []
    for k, wd in (league.get("weeks") or {}).items():
        if int(k) >= week:
            continue
        for entry in wd.get("lineups") or []:
            if (entry.get("team") or "").strip() in variants:
                out.append((int(k), entry.get("players") or []))
    return out


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
    names = memory.name_variants(league, name)
    t = next((x for x in pd.get("teams", []) if x["name"] in names), None)
    return _streak_tuple((t or {}).get("streak"))


def _prev_playoff_pct(league, week, name):
    prev = memory.get_previous_week_number(league, week)
    if prev is None:
        return None
    pd = memory.get_week(league, prev) or {}
    names = memory.name_variants(league, name)
    t = next((x for x in pd.get("teams", []) if x["name"] in names), None)
    return (t or {}).get("playoff_pct")


def format_for_prompt(detected: dict, team_name: str) -> str:
    """The occurrence lines for one team, or an explicit empty marker."""
    items = detected.get("teams", {}).get(team_name, [])
    if not items:
        return "NOTHING NOTABLE HAPPENED TO THIS TEAM THIS WEEK"
    return "; ".join(o["text"] for o in items)
