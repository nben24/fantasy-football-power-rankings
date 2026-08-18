import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import data_extraction, data_validation, memory, narratives, rankings

st.set_page_config(page_title="Fantasy Power Rankings", page_icon="🏈", layout="wide")

DEBUG = os.environ.get("FPR_DEBUG", "").lower() in ("1", "true", "yes")


# ---------- helpers ----------

def rank_arrow(rank_change) -> str:
    if rank_change is None:
        return "🆕"
    if rank_change > 0:
        return f"↑{rank_change}"
    if rank_change < 0:
        return f"↓{abs(rank_change)}"
    return "—"


def _ordered_teams_with_tiers(week_data: dict) -> list[tuple]:
    """Returns [(tier_name_or_None, tier_subtitle_or_None, [ranking_dict, ...]), ...].
    Falls back to a single untiered group (flat rank order) if no tiers were generated
    (e.g. data saved before tiering was added)."""
    rankings_by_name = {r["name"]: r for r in week_data.get("rankings", [])}
    tiers = week_data.get("writeups", {}).get("tiers") or []

    if not tiers:
        return [(None, None, week_data.get("rankings", []))]

    groups = []
    seen = set()
    for tier in tiers:
        team_dicts = [rankings_by_name[n] for n in tier.get("team_names", []) if n in rankings_by_name]
        seen.update(t["name"] for t in team_dicts)
        groups.append((tier.get("tier_name"), tier.get("tier_subtitle"), team_dicts))

    leftover = [r for r in week_data.get("rankings", []) if r["name"] not in seen]
    if leftover:
        groups.append((None, None, leftover))
    return groups


DIVIDER = "⸻"


def format_rankings_imessage(league_name: str, week: int, week_data: dict) -> str:
    """Plain-text export, no markdown syntax -- iMessage (and most group chat
    apps) don't render #, **, or --- as formatting, they just show the raw
    characters. Emoji, caps, and blank-line spacing carry the visual hierarchy
    instead, the same way the reference-style columns this app is calibrated
    against are actually written."""
    theme = week_data.get("writeups", {}).get("week_theme")
    lines = [f"🏆 WEEK {week} POWER RANKINGS — {league_name}"]
    if theme:
        lines.append(f'"{theme}"')
    lines.append("")
    lines.append(DIVIDER)
    lines.append("")

    writeups = {w["name"]: w["narrative"] for w in week_data.get("writeups", {}).get("team_writeups", [])}
    for tier_name, tier_subtitle, teams in _ordered_teams_with_tiers(week_data):
        if tier_name:
            lines.append(tier_name.upper())
            if tier_subtitle:
                lines.append(f"({tier_subtitle})")
            lines.append("")
        for r in teams:
            prev = f"#{r['previous_rank']}" if r["previous_rank"] is not None else "unranked"
            lines.append(f"{r['rank']}. {r['name']} — {r.get('record') or 'record n/a'}")
            lines.append(f"Previous: {prev} {rank_arrow(r['rank_change'])}  |  Power Score: {r['power_score']}")
            lines.append("")
            if r["name"] in writeups:
                lines.append(writeups[r["name"]])
            lines.append("")
            lines.append(DIVIDER)
            lines.append("")

    awards = week_data.get("writeups", {}).get("awards", [])
    if awards:
        lines.append("🔥 WEEKLY AWARDS")
        lines.append("")
        for a in awards:
            lines.append(f"🏅 {a['title']} — {a['team']}")
            lines.append(a["reason"])
            lines.append("")
        lines.append(DIVIDER)
        lines.append("")

    recap = week_data.get("writeups", {}).get("recap")
    if recap:
        lines.append("📰 THIS WEEK IN THE LEAGUE")
        lines.append("")
        lines.append(recap)

    return "\n".join(lines)


def _regenerate_writeup_ui(league: dict, week: int, week_data: dict, team_name: str):
    key_base = f"regen_{league['id']}_{week}_{team_name}"
    with st.expander(f"🔄 Regenerate {team_name}'s writeup"):
        feedback = st.text_input(
            "What should change? (optional -- leave blank to just try again)",
            key=f"{key_base}_feedback",
        )
        if st.button("Regenerate this one", key=f"{key_base}_btn"):
            with st.spinner("Rewriting..."):
                try:
                    team_writeups = week_data["writeups"]["team_writeups"]
                    angle = next((a for a in week_data.get("angles", []) if a["team"] == team_name), None)
                    new_narrative = narratives.regenerate_single_writeup(
                        league,
                        week,
                        week_data["rankings"],
                        week_data.get("context", ""),
                        team_name,
                        team_writeups,
                        angle=angle,
                        feedback=feedback,
                    )
                    for w in team_writeups:
                        if w["name"] == team_name:
                            w["narrative"] = new_narrative
                            break
                    memory.save_week(league, week, week_data)
                    st.rerun()
                except Exception as e:
                    st.error(f"Couldn't regenerate that one: {e}")
                    if DEBUG:
                        st.exception(e)


def render_week(league: dict, week: int, week_data: dict):
    theme = week_data.get("writeups", {}).get("week_theme")
    if theme:
        st.markdown(f"#### _{theme}_")

    if week_data.get("context"):
        with st.expander("Weekly context supplied"):
            st.write(week_data["context"])

    writeups = {w["name"]: w["narrative"] for w in week_data.get("writeups", {}).get("team_writeups", [])}

    for tier_name, tier_subtitle, teams in _ordered_teams_with_tiers(week_data):
        if tier_name:
            st.markdown(f"## {tier_name}")
            if tier_subtitle:
                st.caption(tier_subtitle)
        for r in teams:
            prev = f"#{r['previous_rank']}" if r["previous_rank"] is not None else "unranked"
            st.markdown(f"### {r['rank']}. {r['name']} — {r.get('record') or 'record n/a'}")
            cols = st.columns([1, 1, 3])
            cols[0].metric("Previous", prev, delta=r["rank_change"] if r["rank_change"] else None)
            cols[1].metric("Power Score", r["power_score"])
            cols[2].caption(" · ".join(r["key_factors"]) + f"  (confidence: {r['confidence']})")
            if r["name"] in writeups:
                st.write(writeups[r["name"]])
            if week_data.get("writeups", {}).get("team_writeups"):
                _regenerate_writeup_ui(league, week, week_data, r["name"])
            st.divider()

    awards = week_data.get("writeups", {}).get("awards", [])
    if awards:
        st.markdown("## 🔥 Weekly Awards")
        for a in awards:
            st.markdown(f"**{a['title']}** — {a['team']}")
            st.caption(a["reason"])

    recap = week_data.get("writeups", {}).get("recap")
    if recap:
        st.markdown("## 📰 This Week in the League")
        st.write(recap)

    full_text = format_rankings_imessage(league["name"], week, week_data)
    st.markdown("### Export (formatted for iMessage / group chat)")
    st.code(full_text, language=None)
    st.download_button("⬇️ Download TXT", full_text, file_name=f"week_{week}_rankings.txt")


def reset_flow_state():
    for key in ("extracted", "warnings", "flow_stage"):
        st.session_state.pop(key, None)


# ---------- API key check ----------

if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
    st.title("🏈 Fantasy Power Rankings")
    st.error("AI credentials are not configured.")
    st.markdown(
        "Create a `.env` file in this project (copy `.env.example`) and set:\n\n"
        "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n\n"
        "Get a key at https://console.anthropic.com/settings/keys, then restart the app."
    )
    st.stop()


# ---------- sidebar: league management ----------

st.sidebar.title("🏈 Leagues")

leagues = memory.list_leagues()
league_options = {lg["name"]: lg["id"] for lg in leagues}

if leagues:
    selected_name = st.sidebar.selectbox("Select League", list(league_options.keys()))
    active_league_id = league_options[selected_name]
else:
    st.sidebar.info("No leagues yet — create one below.")
    active_league_id = None

if st.session_state.get("active_league_id") != active_league_id:
    st.session_state["active_league_id"] = active_league_id
    reset_flow_state()

with st.sidebar.expander("➕ Create League"):
    new_name = st.text_input("League name", key="new_league_name")
    new_desc = st.text_area("Description (optional)", key="new_league_desc")
    if st.button("Create", key="create_league_btn") and new_name.strip():
        new_id = memory.create_league(new_name.strip(), new_desc.strip())
        st.session_state["active_league_id"] = new_id
        reset_flow_state()
        st.rerun()

if active_league_id:
    league = memory.load_league(active_league_id)

    with st.sidebar.expander("✏️ Rename League"):
        renamed = st.text_input("New name", value=league["name"], key="rename_input")
        if st.button("Rename", key="rename_btn") and renamed.strip() and renamed.strip() != league["name"]:
            memory.rename_league(active_league_id, renamed.strip())
            st.rerun()

    with st.sidebar.expander("🗑️ Delete League"):
        st.caption("This permanently deletes all history for this league.")
        confirm = st.checkbox("I understand, delete it", key="delete_confirm")
        if st.button("Delete League", key="delete_btn", disabled=not confirm):
            memory.delete_league(active_league_id)
            st.session_state["active_league_id"] = None
            reset_flow_state()
            st.rerun()

    with st.sidebar.expander("📝 League Notes (managers, rivalries, running jokes)"):
        notes = st.text_area(
            "Persistent narrative context — used for flavor, not stated as fact unless true.",
            value=league.get("league_notes", ""),
            height=200,
            key="league_notes_input",
        )
        if st.button("Save Notes", key="save_notes_btn"):
            league["league_notes"] = notes
            memory.save_league(league)
            st.toast("League notes saved.")

    with st.sidebar.expander("📌 Log an Event"):
        st.caption("Trades, injuries, waiver moves, etc. — stored as objective history for future callbacks.")
        ev_week = st.number_input("Week", min_value=1, value=league.get("current_week", 1) or 1, key="event_week")
        ev_type = st.selectbox("Type", ["trade", "waiver", "injury", "decision", "other"], key="event_type")
        ev_details = st.text_input("Details", key="event_details")
        if st.button("Log Event", key="log_event_btn") and ev_details.strip():
            memory.add_event(league, int(ev_week), {"type": ev_type, "week": int(ev_week), "details": ev_details.strip()})
            memory.save_league(league)
            st.toast("Event logged.")


# ---------- main ----------

if not active_league_id:
    st.title("🏈 Fantasy Power Rankings")
    st.write("Create a league in the sidebar to get started.")
    st.stop()

league = memory.load_league(active_league_id)
st.title(f"🏈 {league['name']}")
if league.get("description"):
    st.caption(league["description"])

tab_week, tab_history = st.tabs(["This Week", "History"])

with tab_week:
    st.subheader("Upload This Week's Screenshots")
    st.caption("Standings, matchups, points, rosters — upload whatever you have. No fixed set required.")
    uploaded = st.file_uploader(
        "Screenshots",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{active_league_id}",
    )

    default_week = (league.get("current_week") or 0) + 1
    week_num = st.number_input("Week", min_value=1, value=default_week, step=1, key="week_input")

    context_text = st.text_area(
        "Anything important that happened this week? (optional)",
        placeholder="e.g. Mike traded Bijan last week and immediately lost. John has been talking shit all week.",
        key="context_input",
    )

    if st.button("🔍 Extract Data From Screenshots", type="primary", disabled=not uploaded):
        with st.spinner("Reading screenshots..."):
            try:
                extracted = data_extraction.extract_from_screenshots(uploaded, context_text)
                extracted = data_validation.normalize_extracted_data(league, extracted)
                memory.save_league(league)  # persist any new team-name aliases learned
                st.session_state["extracted"] = extracted
                st.session_state["warnings"] = data_validation.validate_extracted_data(extracted)
                st.session_state["flow_stage"] = "extracted"
            except Exception as e:
                st.error(f"Couldn't extract data from those screenshots: {e}")
                if DEBUG:
                    st.exception(e)

    if st.session_state.get("flow_stage") == "extracted":
        extracted = st.session_state["extracted"]
        warnings = st.session_state["warnings"]

        if extracted.get("week") and extracted["week"] != week_num:
            st.info(f"The screenshots suggest this might be Week {extracted['week']}. Adjust the Week field above if needed.")

        if warnings:
            with st.expander(f"⚠️ {len(warnings)} possible issue(s) found — review below", expanded=True):
                for w in warnings:
                    st.warning(w)

        st.markdown("#### Review & correct extracted data")
        st.caption("Edit any cell that looks wrong before generating rankings.")

        teams_df = pd.DataFrame(extracted.get("teams", [])).reindex(
            columns=["name", "manager", "record", "points_for", "points_against", "standing"]
        )
        edited_teams = st.data_editor(teams_df, num_rows="dynamic", key="teams_editor", use_container_width=True)

        matchups_df = pd.DataFrame(extracted.get("matchups", [])).reindex(
            columns=["team_a", "score_a", "team_b", "score_b"]
        )
        edited_matchups = st.data_editor(matchups_df, num_rows="dynamic", key="matchups_editor", use_container_width=True)

        if st.button("🔥 GENERATE POWER RANKINGS", type="primary"):
            with st.spinner("Crunching numbers and writing rankings..."):
                try:
                    teams_list = edited_teams.dropna(subset=["name"]).to_dict("records")
                    matchups_list = edited_matchups.dropna(subset=["team_a", "team_b"]).to_dict("records")
                    # clean NaN -> None for JSON-friendliness
                    for row in teams_list + matchups_list:
                        for k, v in list(row.items()):
                            if pd.isna(v):
                                row[k] = None

                    week_data = {
                        "teams": teams_list,
                        "matchups": matchups_list,
                        "rosters": extracted.get("rosters", []),
                        "context": context_text,
                        "events": (memory.get_week(league, int(week_num)) or {}).get("events", []),
                    }
                    memory.save_week(league, int(week_num), week_data)

                    ranked = rankings.compute_power_rankings(league, int(week_num))
                    week_data["rankings"] = ranked
                    memory.save_week(league, int(week_num), week_data)

                    angle_result = narratives.find_comedic_angles(league, int(week_num), ranked, context_text)
                    narratives.apply_storyline_updates(league, int(week_num), angle_result.get("storyline_updates", []))

                    # Deterministic, zero-extra-cost cap on the fraud/underrated framing --
                    # two real runs showed the model can't reliably self-enforce this via
                    # the critique prompt alone, so it's forced in code here instead.
                    capped_angles = narratives.cap_fraud_lens_angles(angle_result.get("team_angles", []), ranked)

                    draft = narratives.generate_writeups(league, int(week_num), ranked, context_text, capped_angles)
                    final = narratives.critique_and_revise(league, int(week_num), ranked, context_text, draft)
                    week_data["writeups"] = final
                    week_data["angles"] = capped_angles  # kept for later single-team regeneration
                    memory.save_week(league, int(week_num), week_data)  # also persists storyline updates (league-level)

                    repeated = narratives.find_repeated_imagery(final.get("team_writeups", []))
                    if repeated:
                        st.session_state["repeated_imagery_warning"] = repeated

                    st.session_state["flow_stage"] = "done"
                    st.session_state["done_week"] = int(week_num)
                    st.rerun()
                except Exception as e:
                    st.error(f"Something went wrong generating rankings: {e}")
                    if DEBUG:
                        st.exception(e)

    if st.session_state.get("flow_stage") == "done":
        w = st.session_state["done_week"]
        league = memory.load_league(active_league_id)  # reload fresh copy
        st.success(f"Week {w} power rankings generated.")
        repeated = st.session_state.pop("repeated_imagery_warning", None)
        if repeated:
            with st.expander(f"⚠️ {len(repeated)} possible repeated word(s) across writeups — worth a look", expanded=True):
                st.caption(
                    "This is a simple word-overlap check, not a full duplicate-joke detector -- "
                    "it can miss two writeups using different words for the same image. Use "
                    "🔄 Regenerate on one of them below if it's actually a repeat."
                )
                for team_a, team_b, words in repeated:
                    st.warning(f"**{team_a}** and **{team_b}** both use: {', '.join(words)}")
        render_week(league, w, memory.get_week(league, w))

with tab_history:
    weeks = memory.sorted_week_numbers(league)
    if not weeks:
        st.write("No history yet — generate this week's rankings first.")
    else:
        chosen_week = st.selectbox("Week", weeks[::-1], key="history_week_select")
        render_week(league, chosen_week, memory.get_week(league, chosen_week))
