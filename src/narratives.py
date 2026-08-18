"""The narrative pipeline: find the best comedic angle for each team, write to
it, then critique + rewrite. Three lightweight LLM calls, no agent framework:

    build_facts_bundle          (pure data, no LLM)
    find_comedic_angles         (LLM call #1 -- "what's the joke?")
    generate_writeups           (LLM call #2 -- "write it")
    critique_and_revise         (LLM call #3 -- "is it actually funny?")

The angle-finder also proposes storyline updates (new multi-week narratives,
or new events on existing ones), which get applied to league memory so future
weeks have targeted ammunition instead of a wall of past writeups.
"""

import json
import os
import re
import anthropic

from src import memory, prompts

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

SEASON_TRAJECTORY_WEEKS = 6  # how many past weeks of rank/record to summarize per team
STORYLINES_PER_TEAM = 3  # how many active storylines to surface per team as ammunition

ANGLE_FINDER_TOOL = {
    "name": "record_comedic_angles",
    "description": "For each team, select the single best comedic angle for this week's writeup, and flag any storyline updates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "team_angles": {
                "type": "array",
                "description": "One entry per team, in any order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "team": {"type": "string"},
                        "best_angle": {"type": "string", "description": "The specific comedic premise for this team, in a sentence."},
                        "comedy_type": {"type": "string", "description": "The closest fit from the taxonomy (or a close variant)."},
                        "supporting_facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The specific facts that make this angle true -- only things actually given to you.",
                        },
                        "why_this_is_the_best_angle": {"type": "string", "description": "One sentence on why this beats the alternatives."},
                        "backup_angles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Other angles considered but not chosen, for context.",
                        },
                    },
                    "required": ["team", "best_angle", "comedy_type", "supporting_facts"],
                },
            },
            "storyline_updates": {
                "type": "array",
                "description": (
                    "New storylines to start, or events to add to existing ones. Only include "
                    "when this week's facts/context genuinely suggest a multi-week narrative "
                    "worth tracking -- most teams most weeks won't produce one, and an empty "
                    "list is the normal/expected result."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "storyline_id": {
                            "type": ["string", "null"],
                            "description": "Set to an existing storyline's id (from ACTIVE STORYLINES below) to append to it, or null to start a new one.",
                        },
                        "title": {"type": "string"},
                        "teams": {"type": "array", "items": {"type": "string"}},
                        "event_description": {"type": "string", "description": "What happened this week, factually, in one sentence."},
                        "status": {"type": "string", "enum": ["ongoing", "resolved"]},
                    },
                    "required": ["title", "teams", "event_description", "status"],
                },
            },
        },
        "required": ["team_angles", "storyline_updates"],
    },
}

WRITEUP_TOOL = {
    "name": "record_power_rankings_writeup",
    "description": "Record the final power rankings writeups, tiers, awards, and league recap.",
    "input_schema": {
        "type": "object",
        "properties": {
            "week_theme": {
                "type": "string",
                "description": "A short headline tying the whole week together, e.g. 'The Great Regression -- Everyone's Mid Again'.",
            },
            "tiers": {
                "type": "array",
                "description": (
                    "Group all teams into tiers that fit THIS week's actual story -- invent fresh "
                    "tier names/count each time, don't reuse a fixed template. A dominant outlier "
                    "can be its own one-team tier. Tiers together must cover every team, ordered "
                    "best to worst, as CONTIGUOUS bands of the rank order."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "tier_name": {"type": "string"},
                        "tier_subtitle": {"type": "string", "description": "Optional short one-line flavor subtitle."},
                        "team_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Team names in this tier, in rank order, exactly matching names given below.",
                        },
                    },
                    "required": ["tier_name", "team_names"],
                },
            },
            "team_writeups": {
                "type": "array",
                "description": "One entry per team, matching every team in the tiers above.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Team name, must match exactly."},
                        "narrative": {
                            "type": "string",
                            "description": (
                                "The writeup, built around that team's selected comedic angle. Length "
                                "varies with the material -- a single sharp sentence is fine, so is 4 "
                                "sentences when there's a real bit. Don't make every writeup the same length."
                            ),
                        },
                    },
                    "required": ["name", "narrative"],
                },
            },
            "awards": {
                "type": "array",
                "description": "Only include awards genuinely supported by the data/context. Empty list is fine.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "e.g. 'Biggest Fraud', 'Luckiest Team'."},
                        "team": {"type": "string"},
                        "reason": {"type": "string", "description": "One sentence, fact-based."},
                    },
                    "required": ["title", "team", "reason"],
                },
            },
            "recap": {
                "type": "string",
                "description": "A short 'This Week in the League' columnist-style recap, 3-6 sentences.",
            },
        },
        "required": ["week_theme", "tiers", "team_writeups", "recap", "awards"],
    },
}


SINGLE_WRITEUP_TOOL = {
    "name": "record_single_writeup",
    "description": "Record a rewritten writeup for one team.",
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative": {"type": "string", "description": "The rewritten writeup for this one team."},
        },
        "required": ["narrative"],
    },
}


def build_facts_bundle(league: dict, week: int, rankings: list[dict], context_text: str) -> str:
    """Objective facts + targeted history (trajectory + relevant storylines).
    Deliberately does NOT dump full past-week writeup prose -- storylines are
    the structured replacement for that, see apply_storyline_updates()."""
    lines = [f"LEAGUE: {league.get('name')}", f"WEEK: {week}", ""]

    if league.get("league_notes"):
        lines.append("PERSISTENT LEAGUE NOTES (manager personalities, rivalries, running jokes -- narrative context, not stats):")
        lines.append(league["league_notes"])
        lines.append("")

    if context_text:
        lines.append("THIS WEEK'S USER-SUPPLIED CONTEXT (treat as fact -- came directly from the user):")
        lines.append(context_text)
        lines.append("")

    lines.append("THIS WEEK'S POWER RANKINGS (objective, computed from real data):")
    for r in rankings:
        move = ""
        if r["previous_rank"] is None:
            move = "(new to rankings)"
        elif r["rank_change"] == 0:
            move = "(unchanged from #%d)" % r["previous_rank"]
        else:
            direction = "up" if r["rank_change"] > 0 else "down"
            move = f"({direction} {abs(r['rank_change'])} from #{r['previous_rank']})"
        lines.append(
            f"#{r['rank']} {r['name']} -- {r.get('record')} -- power score {r['power_score']} {move}"
        )
        lines.append(f"   key facts: {'; '.join(r['key_factors'])}")
        lines.append(f"   record_vs_power signal: {r.get('record_vs_power', 'aligned')}")
    lines.append("")

    week_data = memory.get_week(league, week) or {}
    if week_data.get("matchups"):
        lines.append("THIS WEEK'S MATCHUP RESULTS:")
        for m in week_data["matchups"]:
            if m.get("score_a") is not None and m.get("score_b") is not None:
                winner = m["team_a"] if m["score_a"] > m["score_b"] else m["team_b"]
                lines.append(
                    f"  {m['team_a']} {m['score_a']} vs {m['team_b']} {m['score_b']} -- {winner} won"
                )
        lines.append("")

    if week_data.get("rosters"):
        lines.append("ROSTER NOTES (players actually visible in screenshots -- do not invent stats for them):")
        for r in week_data["rosters"]:
            if r.get("notable_players"):
                lines.append(f"  {r['team']}: {', '.join(r['notable_players'])}")
        lines.append("")

    if week_data.get("events"):
        lines.append("EVENTS LOGGED THIS WEEK:")
        for e in week_data["events"]:
            lines.append(f"  [{e.get('type', 'event')}] {e.get('details')}")
        lines.append("")

    trajectory_weeks = [w for w in memory.sorted_week_numbers(league) if w < week][-SEASON_TRAJECTORY_WEEKS:]
    if trajectory_weeks:
        lines.append("SEASON TRAJECTORY SO FAR (rank/record by week, for arc-of-the-season callbacks):")
        for r in rankings:
            points = []
            for w in trajectory_weeks:
                wd = league["weeks"][str(w)]
                match = next((x for x in wd.get("rankings", []) if x["name"] == r["name"]), None)
                if match:
                    points.append(f"W{w}: #{match['rank']} ({match.get('record')})")
            if points:
                lines.append(f"  {r['name']}: {' -> '.join(points)}")
        lines.append("")

    active_storylines = {r["name"]: memory.relevant_storylines_for_team(league, r["name"], week, STORYLINES_PER_TEAM) for r in rankings}
    if any(active_storylines.values()):
        lines.append("ACTIVE STORYLINES (structured multi-week narratives -- prefer these over raw stats when relevant):")
        seen_ids = set()
        for storylines in active_storylines.values():
            for s in storylines:
                if s["id"] in seen_ids:
                    continue
                seen_ids.add(s["id"])
                lines.append(f"  [{s['id']}] \"{s['title']}\" (teams: {', '.join(s['teams'])}, status: {s['status']})")
                for e in s["events"]:
                    lines.append(f"      W{e['week']}: {e['description']}")
        lines.append("")

    return "\n".join(lines)


def _call_forced_tool(system: str, user_content: str, tool: dict) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Model did not return structured output.")


def find_comedic_angles(league: dict, week: int, rankings: list[dict], context_text: str) -> dict:
    """LLM call #1: decide WHAT the joke is for each team, before writing it."""
    facts = build_facts_bundle(league, week, rankings, context_text)
    user_content = facts + "\n\nSelect the best comedic angle for every team listed above, and flag any storyline updates. Use the record_comedic_angles tool."
    return _call_forced_tool(prompts.ANGLE_FINDER_SYSTEM, user_content, ANGLE_FINDER_TOOL)


_FRAUD_LENS_KEYWORDS = ("fraud", "underrated", "sleeper", "inflated")


def cap_fraud_lens_angles(team_angles: list[dict], rankings: list[dict], max_count: int | None = None) -> list[dict]:
    """Deterministically cap how many teams can use the record_vs_power framing
    as their primary angle. Two real generations showed the model can't reliably
    self-count and enforce this during critique -- same failure shape as the
    tier-ordering bug, so it gets the same fix: force it in code instead of
    hoping the prompt is followed. Costs zero extra API calls; this runs on the
    already-returned angle data before generate_writeups is called."""
    if max_count is None:
        max_count = max(3, len(team_angles) // 3)

    def is_fraud_lens(comedy_type: str) -> bool:
        c = (comedy_type or "").lower()
        return any(k in c for k in _FRAUD_LENS_KEYWORDS)

    flagged_names = {a["team"] for a in team_angles if is_fraud_lens(a.get("comedy_type", ""))}
    if len(flagged_names) <= max_count:
        return team_angles

    # Keep the framing for whoever has the largest actual record-vs-power gap
    # (a real number rankings.py already computed) -- drop the rest.
    divergence = {r["name"]: abs(r.get("record_rank", r["rank"]) - r["rank"]) for r in rankings}
    ranked_flagged = sorted(flagged_names, key=lambda n: divergence.get(n, 0), reverse=True)
    reassign_names = set(ranked_flagged[max_count:])

    result = []
    for a in team_angles:
        if a["team"] in reassign_names:
            a = dict(a)
            backups = a.get("backup_angles") or []
            if backups:
                a["best_angle"] = backups[0]
            else:
                a["best_angle"] = (
                    a.get("best_angle", "")
                    + " -- NOTE: the record-vs-power/fraud framing is at capacity this week for "
                    "this team, do not use it. Pick a different angle (matchup result, "
                    "trajectory, storyline, blunt stat, name wordplay) from the facts bundle."
                )
            a["comedy_type"] = "reassigned (fraud-lens cap)"
        result.append(a)
    return result


_REPEATED_IMAGERY_STOPWORDS = {
    "about", "after", "again", "against", "already", "although", "always", "another", "anyone",
    "anymore", "anything", "around", "because", "before", "being", "better", "between", "beating",
    "bottom", "climbed", "could", "despite", "didnt", "doesnt", "during", "either", "enough",
    "every", "everyone", "finally", "further", "getting", "having", "hasnt", "havent", "himself",
    "hoping", "however", "instead", "itself", "just", "league", "literally", "little", "looking",
    "losing", "machine", "machines", "maybe", "might", "myself", "never", "nobody", "nothing",
    "number", "obviously", "official", "officially", "other", "others", "outright", "overall",
    "people", "perhaps", "playing", "playoffs", "points", "power", "quite", "rather", "really",
    "record", "running", "scored", "scoring", "season", "should", "showing", "simply", "since",
    "somehow", "someone", "something", "sometimes", "still", "straight", "surely", "that",
    "their", "theirs", "there", "therell", "theres", "these", "theyll", "theyre", "theyve",
    "think", "third", "this", "those", "though", "through", "throughout", "totally", "underneath",
    "unless", "until", "using", "wasnt", "weekly", "weeks", "were", "werent", "which", "while",
    "whole", "whose", "widely", "with", "within", "without", "would", "wouldnt", "youre",
    "youve", "youll",
}


def find_repeated_imagery(team_writeups: list[dict], min_word_len: int = 7) -> list[tuple]:
    """Free, deterministic heads-up: flags the same distinctive WORD showing up
    across more than one team's writeup in the same week (e.g. two different
    teams both getting called a "mugging"). This is a literal word-overlap
    check, not semantic understanding -- it won't catch two writeups using
    different words for the same underlying image (a "fake Rolex" vs a "fake
    mustache"), only literal repeats. It's a cheap signal to decide whether a
    regenerate is worth spending, not a comprehensive duplicate-joke detector.

    Words drawn from apostrophes are split at the apostrophe ("that's" ->
    "that", "s") rather than kept whole, so contractions fall through to the
    stopword list instead of needing every contracted form enumerated. Any
    word that's also part of a team's own name is excluded everywhere, since
    teams legitimately get named as each other's opponents across writeups
    (e.g. "beat The Inner Machine") -- that's expected, not a repeated image."""
    team_name_words = set()
    for w in team_writeups:
        team_name_words.update(re.findall(r"[a-zA-Z]+", w["name"].lower()))

    words_by_team = {}
    for w in team_writeups:
        tokens = re.findall(r"[a-zA-Z]+", w["narrative"].lower())
        distinctive = {
            t for t in tokens
            if len(t) >= min_word_len and t not in _REPEATED_IMAGERY_STOPWORDS and t not in team_name_words
        }
        words_by_team[w["name"]] = distinctive

    names = list(words_by_team.keys())
    warnings = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            shared = words_by_team[names[i]] & words_by_team[names[j]]
            if shared:
                warnings.append((names[i], names[j], sorted(shared)))
    return warnings


def apply_storyline_updates(league: dict, week: int, updates: list[dict]) -> None:
    """Mutates league in place. Does not save -- caller is expected to save
    the league (e.g. via memory.save_week) after calling this."""
    for u in updates or []:
        storyline_id = u.get("storyline_id")
        if storyline_id and memory.append_storyline_event(league, storyline_id, week, u["event_description"]):
            if u.get("status") == "resolved":
                memory.set_storyline_status(league, storyline_id, "resolved")
            continue
        memory.add_storyline(league, u["title"], u.get("teams", []), week, u["event_description"])


def _format_angles(angles: list[dict]) -> str:
    lines = ["SELECTED COMEDIC ANGLES (the premise to build each writeup around):"]
    for a in angles:
        lines.append(f"  {a['team']}: {a['best_angle']} [{a.get('comedy_type', '')}]")
        if a.get("supporting_facts"):
            lines.append(f"    supporting facts: {'; '.join(a['supporting_facts'])}")
    return "\n".join(lines)


def _normalize_tiers(writeups: dict, rankings: list[dict]) -> dict:
    """Force tiers into contiguous, correctly-ordered bands of the rank list.

    The model is instructed to keep tiers contiguous (rank 1-3, then 4-6, ...),
    but sometimes groups teams thematically across non-adjacent ranks instead
    (e.g. every 'fraud watch' team regardless of rank) -- which reads as an
    out-of-order power ranking. Rather than trust that instruction blindly, we
    rebuild the tier list here from the authoritative rank order, splitting a
    tier wherever its thematic label changes. This can never move a team out
    of its correct rank position."""
    rank_by_name = {r["name"]: r["rank"] for r in rankings}
    tiers = writeups.get("tiers") or []

    label_by_name = {}
    for tier in tiers:
        for name in tier.get("team_names", []):
            if name in rank_by_name:
                label_by_name[name] = (tier.get("tier_name") or "", tier.get("tier_subtitle"))

    ordered_names = [r["name"] for r in sorted(rankings, key=lambda r: r["rank"])]

    fixed_tiers = []
    current_label = object()  # sentinel, never equal to a real label
    for name in ordered_names:
        label = label_by_name.get(name, ("", None))
        if label != current_label:
            fixed_tiers.append({"tier_name": label[0], "tier_subtitle": label[1], "team_names": []})
            current_label = label
        fixed_tiers[-1]["team_names"].append(name)

    writeups["tiers"] = fixed_tiers
    return writeups


def generate_writeups(league: dict, week: int, rankings: list[dict], context_text: str, angles: list[dict]) -> dict:
    facts = build_facts_bundle(league, week, rankings, context_text)
    user_content = facts + "\n\n" + _format_angles(angles)
    system = (
        prompts.STYLE_PHILOSOPHY
        + "\n"
        + prompts.CRITICAL_RULES
        + "\n\nWrite one entry in team_writeups for every team listed below, built around its "
        "selected comedic angle. Group them into tiers you invent for this week, and give the "
        "week a theme. Use the record_power_rankings_writeup tool."
    )
    draft = _call_forced_tool(system, user_content, WRITEUP_TOOL)
    return _normalize_tiers(draft, rankings)


def critique_and_revise(league: dict, week: int, rankings: list[dict], context_text: str, draft: dict) -> dict:
    facts = build_facts_bundle(league, week, rankings, context_text)

    user_content = (
        facts
        + "\n\nDRAFT WRITEUP TO REVIEW:\n"
        + json.dumps(draft, indent=2)
        + "\n\nRewrite only the entries that fail the critique questions below. Keep entries that already "
        "pass as-is. Return the FULL writeup (theme, tiers, all teams) via the tool, revised or not."
    )
    system = (
        prompts.STYLE_PHILOSOPHY
        + "\n"
        + prompts.CRITICAL_RULES
        + "\n"
        + prompts.CRITIQUE_AXES
        + "\n\nYou are editing a draft, not writing from scratch. Use the record_power_rankings_writeup tool."
    )
    revised = _call_forced_tool(system, user_content, WRITEUP_TOOL)
    return _normalize_tiers(revised, rankings)


def regenerate_single_writeup(
    league: dict,
    week: int,
    rankings: list[dict],
    context_text: str,
    team_name: str,
    other_writeups: list[dict],
    angle: dict | None = None,
    feedback: str = "",
) -> str:
    """Rewrite just one team's writeup -- one API call, not a full regeneration.
    Keeps everything else on the page (tiers, other writeups, awards, recap)
    untouched. Returns the new narrative string."""
    facts = build_facts_bundle(league, week, rankings, context_text)

    other_lines = "\n".join(f"  {w['name']}: {w['narrative']}" for w in other_writeups if w["name"] != team_name)

    user_content = (
        facts
        + f"\n\nYou are rewriting ONLY the writeup for {team_name}. Everything else on the page is "
        "final and will not change -- for reference (avoid repeating the same technique these "
        "already use), here are the other teams' writeups:\n"
        + other_lines
    )
    if angle:
        user_content += f"\n\nThis team's previously selected angle: {angle.get('best_angle')} [{angle.get('comedy_type', '')}]"
    if feedback:
        user_content += (
            f"\n\nUSER FEEDBACK on the previous version -- address this directly, including "
            f"picking a different angle entirely if the feedback calls for it: {feedback}"
        )
    else:
        user_content += "\n\nNo specific feedback was given -- just make it funnier and sharper than the previous version."

    system = (
        prompts.STYLE_PHILOSOPHY
        + "\n"
        + prompts.CRITICAL_RULES
        + "\n"
        + prompts.CRITIQUE_AXES
        + f"\n\nWrite a single replacement writeup for {team_name} only. Apply the critique "
        "questions to your own output before finalizing -- there's no separate edit pass for "
        "this one. Use the record_single_writeup tool."
    )
    result = _call_forced_tool(system, user_content, SINGLE_WRITEUP_TOOL)
    return result["narrative"]
