"""Sanity-check and normalize data extracted from screenshots before it's
trusted for ranking. Never silently trust the vision model."""

from src import memory


def normalize_extracted_data(league: dict, extracted: dict) -> dict:
    """Map every team name in the extraction onto the league's canonical
    team names, so 'Team A' and 'team a ' don't become two teams."""
    for team in extracted.get("teams", []):
        team["name"] = memory.normalize_team_name(league, team["name"])

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

    return warnings
