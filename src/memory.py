"""Persistent JSON storage for leagues. One file per league under data/leagues/."""

import json
import re
import uuid
import difflib
from pathlib import Path
from datetime import datetime, timezone

LEAGUES_DIR = Path(__file__).resolve().parent.parent / "data" / "leagues"

FUZZY_MATCH_THRESHOLD = 0.82


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "league"


def _path_for(league_id: str) -> Path:
    return LEAGUES_DIR / f"{league_id}.json"


def list_leagues() -> list[dict]:
    LEAGUES_DIR.mkdir(parents=True, exist_ok=True)
    leagues = []
    for f in sorted(LEAGUES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            leagues.append({"id": data["id"], "name": data.get("name", data["id"])})
        except (json.JSONDecodeError, KeyError):
            continue
    return leagues


def create_league(name: str, description: str = "") -> str:
    LEAGUES_DIR.mkdir(parents=True, exist_ok=True)
    base_id = _slugify(name)
    league_id = base_id
    suffix = 2
    while _path_for(league_id).exists():
        league_id = f"{base_id}_{suffix}"
        suffix += 1

    league = {
        "id": league_id,
        "name": name,
        "description": description,
        "managers": [],
        "league_notes": "",
        "team_aliases": {},
        "current_week": 0,
        "weeks": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_league(league)
    return league_id


def load_league(league_id: str) -> dict | None:
    path = _path_for(league_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_league(league: dict) -> None:
    LEAGUES_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(league["id"])
    path.write_text(json.dumps(league, indent=2, sort_keys=False))


def rename_league(league_id: str, new_name: str) -> None:
    league = load_league(league_id)
    if league is None:
        raise ValueError(f"League {league_id} not found")
    league["name"] = new_name
    save_league(league)


def delete_league(league_id: str) -> None:
    path = _path_for(league_id)
    if path.exists():
        path.unlink()


def sorted_week_numbers(league: dict) -> list[int]:
    return sorted(int(w) for w in league.get("weeks", {}).keys())


def get_week(league: dict, week: int) -> dict | None:
    return league.get("weeks", {}).get(str(week))


def get_previous_week_number(league: dict, week: int) -> int | None:
    prior = [w for w in sorted_week_numbers(league) if w < week]
    return prior[-1] if prior else None


def save_week(league: dict, week: int, week_data: dict) -> None:
    league.setdefault("weeks", {})[str(week)] = week_data
    if week > league.get("current_week", 0):
        league["current_week"] = week
    save_league(league)


def normalize_team_name(league: dict, raw_name: str) -> str:
    """Map a possibly-OCR-noisy team name to a canonical name already known
    to this league, recording the alias for next time. Unknown names are
    returned as-is (and become canonical on first save)."""
    raw_name = raw_name.strip()
    aliases = league.setdefault("team_aliases", {})

    if raw_name in aliases:
        return aliases[raw_name]

    known_canonical = set(aliases.values())
    # also treat prior canonical names already used verbatim as known
    for w in league.get("weeks", {}).values():
        for t in w.get("teams", []):
            known_canonical.add(t["name"])

    if raw_name in known_canonical:
        aliases[raw_name] = raw_name
        return raw_name

    if known_canonical:
        match = difflib.get_close_matches(
            raw_name, list(known_canonical), n=1, cutoff=FUZZY_MATCH_THRESHOLD
        )
        if match:
            aliases[raw_name] = match[0]
            return match[0]

        # ESPN truncates long team names with a literal "..." in some screenshot
        # crops but not others (e.g. "EL SUCIO DE LOS..." vs "EL SUCIO DE LOS
        # SUCIOS"). That structural difference drops the fuzzy-match ratio below
        # the normal threshold even though it's obviously the same team, so this
        # is checked explicitly rather than by loosening the fuzzy cutoff (which
        # would risk merging genuinely different teams). Canonicalize to
        # whichever form is already established in history, not the new one, so
        # every already-saved week's stored data keeps matching by exact string.
        for candidate in known_canonical:
            if _is_ellipsis_truncation(raw_name, candidate):
                aliases[raw_name] = candidate
                return candidate

    # New team we haven't seen before.
    aliases[raw_name] = raw_name
    return raw_name


def _is_ellipsis_truncation(a: str, b: str, min_len: int = 8) -> bool:
    """True if the shorter of a/b literally ends in ESPN's '...' truncation
    marker and is a prefix of the other -- not a generic fuzzy/prefix match."""
    for truncated, full in ((a, b), (b, a)):
        truncated = truncated.strip()
        if not truncated.endswith("..."):
            continue
        prefix = truncated.rstrip(".").rstrip().lower()
        if len(prefix) >= min_len and full.strip().lower().startswith(prefix):
            return True
    return False


def add_event(league: dict, week: int, event: dict) -> None:
    week_data = league.setdefault("weeks", {}).setdefault(str(week), {})
    week_data.setdefault("events", []).append(event)


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# --- Storylines: persistent multi-week narratives (trade regret arcs, running
# collapses, feuds) that the comedic-angle finder can surface as ammunition,
# instead of dumping every past week's full writeup text into every prompt. ---

def get_storylines(league: dict) -> list[dict]:
    return league.setdefault("storylines", [])


def add_storyline(league: dict, title: str, teams: list[str], week: int, description: str) -> dict:
    storyline = {
        "id": new_id(),
        "title": title,
        "teams": teams,
        "status": "ongoing",
        "events": [{"week": week, "description": description}],
    }
    get_storylines(league).append(storyline)
    return storyline


def append_storyline_event(league: dict, storyline_id: str, week: int, description: str) -> bool:
    for s in get_storylines(league):
        if s["id"] == storyline_id:
            s["events"].append({"week": week, "description": description})
            return True
    return False


def set_storyline_status(league: dict, storyline_id: str, status: str) -> bool:
    for s in get_storylines(league):
        if s["id"] == storyline_id:
            s["status"] = status
            return True
    return False


def relevant_storylines_for_team(league: dict, team_name: str, up_to_week: int, limit: int = 3) -> list[dict]:
    """Storylines involving this team with at least one event by up_to_week,
    most recently active first. This is the targeted ammunition handed to the
    angle-finder/writer instead of a full history dump."""
    def last_relevant_week(s: dict) -> int:
        weeks = [e["week"] for e in s.get("events", []) if e["week"] <= up_to_week]
        return max(weeks) if weeks else -1

    candidates = [
        s for s in get_storylines(league)
        if team_name in s.get("teams", []) and last_relevant_week(s) >= 0
    ]
    candidates.sort(key=last_relevant_week, reverse=True)
    return candidates[:limit]
