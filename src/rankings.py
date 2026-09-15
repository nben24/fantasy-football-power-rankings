"""Transparent power-ranking engine.

Baseline formula (weights redistributed when a component is unavailable):
  season performance  25%   win/loss record
  points scored       20%   points-per-game
  recent form         20%   last up-to-3 weeks, win rate + margin
  roster strength     15%   NOT scored -- screenshots expose team-level
                             projections, not per-player points, so there is no
                             honest number to compute this from. Its weight is
                             redistributed across the rest.
  consistency         10%   inverse of stdev of weekly scores
  schedule context     10%   average opponent win% faced

The resulting power score orders the column and nothing else -- it is never
shown to readers and the writer is forbidden from naming it. Each team also
carries `key_factors`, which the narrative layer treats as thin background
rather than primary material; see src/occurrences.py for what the writer
actually builds on.
"""

import re
import statistics

from src import memory

BASE_WEIGHTS = {
    "season": 0.25,
    "points": 0.20,
    "recent_form": 0.20,
    "roster": 0.15,
    "consistency": 0.10,
    "schedule": 0.10,
}

RECENT_FORM_WINDOW = 3


def parse_record(record: str | None) -> tuple[int, int, int]:
    if not record:
        return (0, 0, 0)
    parts = re.split(r"[-–]", record.strip())
    nums = []
    for p in parts:
        p = p.strip()
        nums.append(int(p)) if p.isdigit() else None
    nums = [n for n in nums if n is not None]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _min_max_normalize(raw: dict[str, float]) -> dict[str, float]:
    if not raw:
        return {}
    values = list(raw.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {k: 50.0 for k in raw}
    return {k: (v - lo) / (hi - lo) * 100 for k, v in raw.items()}


def _team_game_history(league: dict, team_name: str, up_to_week: int) -> list[dict]:
    """All completed matchups for this team across weeks <= up_to_week, in order."""
    history = []
    for w in sorted(int(k) for k in league.get("weeks", {}).keys()):
        if w > up_to_week:
            continue
        week_data = league["weeks"][str(w)]
        for m in week_data.get("matchups", []):
            if team_name not in (m.get("team_a"), m.get("team_b")):
                continue
            is_a = m["team_a"] == team_name
            own = m.get("score_a") if is_a else m.get("score_b")
            opp_score = m.get("score_b") if is_a else m.get("score_a")
            opponent = m.get("team_b") if is_a else m.get("team_a")
            if own is None or opp_score is None:
                continue
            history.append(
                {"week": w, "score": own, "opponent": opponent, "win": own > opp_score, "margin": own - opp_score}
            )
    return history


def compute_power_rankings(league: dict, week: int) -> list[dict]:
    week_data = memory.get_week(league, week)
    if not week_data:
        raise ValueError(f"No data stored for week {week}")

    teams = week_data.get("teams", [])
    if not teams:
        raise ValueError("No teams to rank")

    team_names = [t["name"] for t in teams]
    records = {t["name"]: parse_record(t.get("record")) for t in teams}
    win_pct_now = {
        name: (w / (w + l + t) if (w + l + t) > 0 else 0.0) for name, (w, l, t) in records.items()
    }

    histories = {name: _team_game_history(league, name, week) for name in team_names}

    # -- season performance --
    season_raw = {name: win_pct_now[name] for name in team_names}

    # -- points scored (PPG) --
    points_raw = {}
    for t in teams:
        w, l, tie = records[t["name"]]
        games = w + l + tie or len(histories[t["name"]]) or 1
        pf = t.get("points_for")
        points_raw[t["name"]] = (pf / games) if pf is not None else 0.0

    # -- recent form: win rate + avg margin over last N games --
    recent_win_raw, recent_margin_raw = {}, {}
    for name in team_names:
        recent = histories[name][-RECENT_FORM_WINDOW:]
        if recent:
            recent_win_raw[name] = sum(1 for g in recent if g["win"]) / len(recent)
            recent_margin_raw[name] = statistics.mean(g["margin"] for g in recent)
        else:
            recent_win_raw[name] = 0.0
            recent_margin_raw[name] = 0.0

    # -- consistency: inverse stdev of scores so far (neutral if <2 games) --
    consistency_raw = {}
    for name in team_names:
        scores = [g["score"] for g in histories[name]]
        consistency_raw[name] = -statistics.pstdev(scores) if len(scores) >= 2 else None

    # -- schedule context: avg opponent win% (using opponents' current records) --
    schedule_raw = {}
    for name in team_names:
        opp_pcts = [win_pct_now[g["opponent"]] for g in histories[name] if g["opponent"] in win_pct_now]
        schedule_raw[name] = statistics.mean(opp_pcts) if opp_pcts else None

    season_n = _min_max_normalize(season_raw)
    points_n = _min_max_normalize(points_raw)
    recent_win_n = _min_max_normalize(recent_win_raw)
    recent_margin_n = _min_max_normalize(recent_margin_raw)
    recent_form_n = {name: recent_win_n[name] * 0.6 + recent_margin_n[name] * 0.4 for name in team_names}

    have_consistency = any(v is not None for v in consistency_raw.values())
    consistency_n = _min_max_normalize({k: v for k, v in consistency_raw.items() if v is not None}) if have_consistency else {}

    have_schedule = any(v is not None for v in schedule_raw.values())
    schedule_n = _min_max_normalize({k: v for k, v in schedule_raw.items() if v is not None}) if have_schedule else {}

    # Roster strength is never scored -- redistribute its weight.
    active_components = ["season", "points", "recent_form"]
    if have_consistency:
        active_components.append("consistency")
    if have_schedule:
        active_components.append("schedule")
    weight_sum = sum(BASE_WEIGHTS[c] for c in active_components)
    weights = {c: BASE_WEIGHTS[c] / weight_sum for c in active_components}

    prev_week = memory.get_previous_week_number(league, week)
    prev_rankings = {}
    if prev_week is not None:
        prev_week_data = memory.get_week(league, prev_week)
        for r in (prev_week_data or {}).get("rankings", []):
            prev_rankings[r["name"]] = r["rank"]

    stored_weeks = sorted(int(k) for k in league.get("weeks", {}).keys() if int(k) <= week)
    weeks_of_history = len(stored_weeks)
    tracking_from_week_one = bool(stored_weeks) and min(stored_weeks) <= 1

    results = []
    for t in teams:
        name = t["name"]
        components = {
            "season": season_n.get(name, 50.0),
            "points": points_n.get(name, 50.0),
            "recent_form": recent_form_n.get(name, 50.0),
        }
        if have_consistency:
            components["consistency"] = consistency_n.get(name, 50.0)
        if have_schedule:
            components["schedule"] = schedule_n.get(name, 50.0)

        power_score = sum(components[c] * weights[c] for c in active_components)

        w, l, tie = records[name]
        key_factors = [f"{w}-{l}" + (f"-{tie}" if tie else "") + " record"]
        if t.get("points_for") is not None:
            key_factors.append(f"{points_raw[name]:.1f} PPG")
        recent = histories[name][-RECENT_FORM_WINDOW:]
        if recent:
            rw = sum(1 for g in recent if g["win"])
            key_factors.append(f"{rw}-{len(recent) - rw} in last {len(recent)}")
        else:
            key_factors.append("no matchup history yet")
        if have_schedule and schedule_raw.get(name) is not None:
            key_factors.append(f"opponents avg {schedule_raw[name] * 100:.0f}% win rate")
        if have_consistency and consistency_raw.get(name) is not None:
            scores = [g["score"] for g in histories[name]]
            # "this season" is only true when week 1 was actually uploaded; otherwise
            # this range covers just the weeks the app has seen.
            span = "this season" if tracking_from_week_one else f"over {len(scores)} tracked weeks"
            key_factors.append(f"scored {min(scores):.1f}-{max(scores):.1f} {span}")

        confidence = "low" if weeks_of_history <= 1 else ("medium" if weeks_of_history == 2 else "high")

        results.append(
            {
                "name": name,
                "manager": t.get("manager"),
                "record": t.get("record"),
                "power_score": round(power_score, 1),
                "components": {k: round(v, 1) for k, v in components.items()},
                "key_factors": key_factors,
                "confidence": confidence,
                "previous_rank": prev_rankings.get(name),
            }
        )

    results.sort(key=lambda r: r["power_score"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
        r["rank_change"] = (r["previous_rank"] - i) if r["previous_rank"] is not None else None

    # Record-vs-power divergence: is this team's record flattering or underselling it?
    # Tie-break record rank by points_for so teams with identical records still separate.
    record_order = sorted(team_names, key=lambda n: (win_pct_now[n], points_raw[n]), reverse=True)
    record_rank = {name: i for i, name in enumerate(record_order, start=1)}

    for r in results:
        r_rank = record_rank[r["name"]]
        diff = r_rank - r["rank"]  # positive: power ranks them better than their record does
        r["record_rank"] = r_rank
        if diff >= 2:
            r["record_vs_power"] = "underrated"
            r["key_factors"].append(f"record ranks #{r_rank} but power score only ranks #{r['rank']} -- quietly better than the record shows")
        elif diff <= -2:
            r["record_vs_power"] = "fraud_watch"
            r["key_factors"].append(f"record ranks #{r_rank} but power score ranks #{r['rank']} -- record is flattering this team")
        else:
            r["record_vs_power"] = "aligned"

    return results
