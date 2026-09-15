"""Sanity-check and normalize data extracted from screenshots before it's
trusted for ranking. Never silently trust the vision model.

Two layers:
  validate_extracted_data  -- shape checks (duplicates, missing scores, ties)
  reconcile_week           -- arithmetic proof that this week's numbers agree
                              with last week's stored numbers

Reconciliation works on week-over-week DELTAS rather than full-season sums,
because a league's stored history usually starts mid-season (the user's first
upload might be week 9) while the standings PF/PA columns cover the whole year.
A delta only needs the immediately preceding week to be checkable.
"""

import re

from src import memory

RECON_TOLERANCE = 0.05  # scores carry 2 decimals; allow for a rounding wobble


def _parse_record(record):
    """'7-2-0' -> (7, 2, 0). Returns None if unparseable."""
    if not record:
        return None
    nums = [int(p) for p in re.split(r"[-–]", record.strip()) if p.strip().isdigit()]
    if not nums:
        return None
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _parse_streak(streak):
    """'W5' -> ('W', 5). Returns None if unparseable."""
    if not streak:
        return None
    m = re.match(r"\s*([WL])\s*(\d+)\s*$", str(streak), re.I)
    return (m.group(1).upper(), int(m.group(2))) if m else None


def _week_scores(matchups):
    """{team_name: (own_score, opponent_score, won)} for one week's matchups."""
    out = {}
    for m in matchups:
        a, b = m.get("team_a"), m.get("team_b")
        sa, sb = m.get("score_a"), m.get("score_b")
        if sa is None or sb is None:
            continue
        out[a] = (sa, sb, sa > sb)
        out[b] = (sb, sa, sb > sa)
    return out


def normalize_extracted_data(league: dict, extracted: dict) -> dict:
    """Map every team name in the extraction onto the league's canonical
    team names, so 'Team A' and 'team a ' don't become two teams."""
    for team in extracted.get("teams", []):
        team["name"] = memory.normalize_team_name(league, team["name"])
        if team.get("streak"):
            team["streak"] = str(team["streak"]).strip().upper().replace(" ", "")

    for m in extracted.get("matchups", []):
        m["team_a"] = memory.normalize_team_name(league, m["team_a"])
        m["team_b"] = memory.normalize_team_name(league, m["team_b"])

    for r in extracted.get("rosters", []) or []:
        r["team"] = memory.normalize_team_name(league, r["team"])

    return extracted


def validate_extracted_data(extracted: dict) -> list[str]:
    """Return a list of human-readable warnings. Does not mutate data or
    block generation -- the user reviews/edits before confirming."""
    warnings: list[str] = []

    teams = extracted.get("teams", [])
    matchups = extracted.get("matchups", [])

    team_names = [t["name"] for t in teams]
    seen = set()
    for name in team_names:
        if name in seen:
            warnings.append(f"'{name}' appears more than once in standings -- possible duplicate/OCR mismatch.")
        seen.add(name)

    known_names = set(team_names)
    for m in matchups:
        for side in ("team_a", "team_b"):
            if m[side] not in known_names and known_names:
                warnings.append(
                    f"Matchup references '{m[side]}', which doesn't match any team in the standings screenshot."
                )
        score_a, score_b = m.get("score_a"), m.get("score_b")
        if score_a is not None and score_b is not None and score_a == score_b:
            warnings.append(f"'{m['team_a']}' vs '{m['team_b']}' is an exact tie ({score_a}) -- double-check this score.")

    for m in matchups:
        if m.get("score_a") is None or m.get("score_b") is None:
            warnings.append(f"Missing a score for '{m['team_a']}' vs '{m['team_b']}'.")

    for note in extracted.get("uncertain_notes", []) or []:
        warnings.append(f"Model flagged as uncertain: {note}")

    if not teams:
        warnings.append("No teams were extracted -- try a clearer standings screenshot.")
    if not matchups:
        warnings.append("No matchups were extracted -- rankings will rely on standings only.")

    for m in matchups:
        for side, proj_key, score_key in (("team_a", "projected_a", "score_a"), ("team_b", "projected_b", "score_b")):
            proj, score = m.get(proj_key), m.get(score_key)
            # The projection sits visually below the score; a swap is the likely OCR error.
            if proj is not None and score is not None and proj > score * 3:
                warnings.append(
                    f"'{m[side]}' projected {proj} vs actual {score} -- implausible gap, "
                    "check the score and projection weren't swapped."
                )

    return warnings


def reconcile_week(league: dict, week: int, extracted: dict) -> list[dict]:
    """Prove this week's extracted numbers against last week's stored numbers.

    Returns one result dict per check: {team, check, status, detail} where
    status is 'ok', 'fail', or 'skip' (not enough data to verify). A 'fail' is
    a real arithmetic contradiction -- it means a number was misread, not that
    something merely looks unusual.
    """
    results: list[dict] = []
    prev_week = memory.get_previous_week_number(league, week)
    prev_data = memory.get_week(league, prev_week) if prev_week is not None else None
    prev_teams = {t["name"]: t for t in (prev_data or {}).get("teams", [])}

    scores = _week_scores(extracted.get("matchups", []))

    for team in extracted.get("teams", []):
        name = team["name"]
        got = scores.get(name)

        if got is None:
            results.append({"team": name, "check": "matchup", "status": "skip",
                            "detail": "no matchup score found for this team"})
            continue
        own, opp, won = got
        prev = prev_teams.get(name)

        if not prev:
            results.append({"team": name, "check": "week-over-week", "status": "skip",
                            "detail": f"no stored week {prev_week} data to compare against"
                                      if prev_week else "first stored week -- nothing to compare yet"})
            continue

        # PF delta must equal this week's score.
        if team.get("points_for") is not None and prev.get("points_for") is not None:
            delta = team["points_for"] - prev["points_for"]
            if abs(delta - own) > RECON_TOLERANCE:
                results.append({"team": name, "check": "PF", "status": "fail",
                                "detail": f"season PF rose {delta:.2f} but this week's score reads {own:.2f}"})
            else:
                results.append({"team": name, "check": "PF", "status": "ok",
                                "detail": f"PF +{delta:.2f} matches score {own:.2f}"})

        # PA delta must equal the opponent's score.
        if team.get("points_against") is not None and prev.get("points_against") is not None:
            delta = team["points_against"] - prev["points_against"]
            if abs(delta - opp) > RECON_TOLERANCE:
                results.append({"team": name, "check": "PA", "status": "fail",
                                "detail": f"season PA rose {delta:.2f} but opponent scored {opp:.2f}"})
            else:
                results.append({"team": name, "check": "PA", "status": "ok",
                                "detail": f"PA +{delta:.2f} matches opponent {opp:.2f}"})

        # Record must advance by exactly one game, on the correct side.
        rec_now, rec_prev = _parse_record(team.get("record")), _parse_record(prev.get("record"))
        if rec_now and rec_prev:
            dw, dl = rec_now[0] - rec_prev[0], rec_now[1] - rec_prev[1]
            expected = (1, 0) if won else (0, 1)
            if (dw, dl) != expected:
                verb = "won" if won else "lost"
                results.append({"team": name, "check": "record", "status": "fail",
                                "detail": f"{verb} this week but record moved {rec_prev[0]}-{rec_prev[1]} "
                                          f"-> {rec_now[0]}-{rec_now[1]}"})
            else:
                results.append({"team": name, "check": "record", "status": "ok",
                                "detail": f"{rec_prev[0]}-{rec_prev[1]} -> {rec_now[0]}-{rec_now[1]}"})

        # Streak must continue or reset consistently with this week's result.
        s_now, s_prev = _parse_streak(team.get("streak")), _parse_streak(prev.get("streak"))
        if s_now and s_prev:
            want_dir = "W" if won else "L"
            want_len = s_prev[1] + 1 if s_prev[0] == want_dir else 1
            if s_now != (want_dir, want_len):
                results.append({"team": name, "check": "streak", "status": "fail",
                                "detail": f"was {s_prev[0]}{s_prev[1]} and {'won' if won else 'lost'}, "
                                          f"so expected {want_dir}{want_len} but reads {s_now[0]}{s_now[1]}"})
            else:
                results.append({"team": name, "check": "streak", "status": "ok",
                                "detail": f"{s_prev[0]}{s_prev[1]} -> {s_now[0]}{s_now[1]}"})

    return results


def reconciliation_summary(results: list[dict]) -> tuple[int, int, int]:
    """(passed, failed, skipped) counts for a one-line status banner."""
    ok = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    skip = sum(1 for r in results if r["status"] == "skip")
    return ok, fail, skip
