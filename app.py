import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import data_extraction, data_validation, espn_sync, memory, narratives, rankings

st.set_page_config(page_title="Fantasy Power Rankings", page_icon="🏈", layout="wide")

DEBUG = os.environ.get("FPR_DEBUG", "").lower() in ("1", "true", "yes")


# ---------- helpers ----------

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


def _clean_subtitle(subtitle) -> str:
    """The writer sometimes wraps its own subtitle in parentheses; both the export
    and the UI add their own, producing ((doubled parens))."""
    s = (subtitle or "").strip()
    while len(s) > 1 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s

_RANK_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _rank_emoji(rank: int) -> str:
    if 1 <= rank <= 10:
        return _RANK_EMOJI[rank - 1]
    return "".join(_RANK_EMOJI[int(d) - 1] if d != "0" else "🔟" for d in str(rank))


def _header_meta(r: dict, week_data: dict) -> str:
    """Record • streak • PF/PA -- every stat the prose is forbidden from restating
    lives here instead, the way the reference columns do it."""
    team = next((t for t in week_data.get("teams", []) if t["name"] == r["name"]), {})
    parts = [narratives.tidy_record(r.get("record"))]
    if team.get("streak"):
        parts.append(team["streak"])
    pf, pa = team.get("points_for"), team.get("points_against")
    if pf is not None and pa is not None:
        parts.append(f"{pf:.0f} PF / {pa:.0f} PA")
    return " • ".join(parts)


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
            if _clean_subtitle(tier_subtitle):
                lines.append(f"({_clean_subtitle(tier_subtitle)})")
            lines.append("")
        # Dividers separate tiers only. A rule between every team triples the
        # scroll length in a group chat for no added structure.
        for r in teams:
            lines.append(f"{_rank_emoji(r['rank'])} {r['name']} ({_header_meta(r, week_data)})")
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


def _regenerate_writeup_ui(league: dict, week: int, week_data: dict, team_name: str, context: str):
    key_base = f"regen_{context}_{league['id']}_{week}_{team_name}"
    with st.expander(f"🔄 Regenerate {team_name}'s writeup", key=f"{key_base}_expander"):
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


def render_week(league: dict, week: int, week_data: dict, context: str):
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
            if _clean_subtitle(tier_subtitle):
                st.caption(_clean_subtitle(tier_subtitle))
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
                _regenerate_writeup_ui(league, week, week_data, r["name"], context)
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
    st.download_button(
        "⬇️ Download TXT",
        full_text,
        file_name=f"week_{week}_rankings.txt",
        key=f"download_{context}_{league['id']}_{week}",
    )


def regenerate_week_writeups(league: dict, week: int) -> dict:
    """Re-run the narrative pipeline over a week's already-extracted data.

    Skips the vision call entirely -- the scores, context and matchups are
    already stored. Rolls back that week's storyline events first, since
    storyline updates append and would otherwise be logged twice.
    """
    week_data = memory.get_week(league, week)
    if not week_data:
        raise ValueError(f"No stored data for week {week}")

    memory.remove_storyline_events_for_week(league, week)
    context_text = week_data.get("context", "")

    ranked = rankings.compute_power_rankings(league, week)
    week_data["rankings"] = ranked

    angle_result = narratives.find_comedic_angles(league, week, ranked, context_text)
    narratives.apply_storyline_updates(league, week, angle_result.get("storyline_updates", []))
    capped = narratives.cap_fraud_lens_angles(angle_result.get("team_angles", []), ranked)

    draft = narratives.generate_writeups(league, week, ranked, context_text, capped)
    final = narratives.critique_and_revise(league, week, ranked, context_text, draft)

    week_data["writeups"] = final
    week_data["angles"] = capped
    memory.save_week(league, week, week_data)
    return final


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
#
# Every league-specific widget is keyed with the league id. Unkeyed (or
# globally keyed) widgets keep their first value when the league changes, so
# switching leagues showed one league's ESPN id and notes -- and pressing Save
# would have written them into whichever league was now selected.

def _lk(name: str) -> str:
    return f"{name}_{active_league_id}"


def _select_league(league_id):
    """Switch leagues from a button. The selectbox already exists by then and
    Streamlit forbids writing its key, so the choice is applied next run."""
    st.session_state["_pending_league"] = league_id
    reset_flow_state()


st.sidebar.title("🏈 Leagues")

leagues = memory.list_leagues()
league_names = {lg["id"]: lg["name"] for lg in leagues}

if "_pending_league" in st.session_state:
    pending = st.session_state.pop("_pending_league")
    st.session_state.pop("league_select", None)
    if pending:
        st.session_state["league_select"] = pending
    else:
        st.query_params.pop("league", None)

if leagues:
    # The choice survives a browser refresh through the URL (?league=...).
    # Without a key or a remembered value the selectbox fell back to the
    # first league alphabetically on every new session.
    if st.session_state.get("league_select") not in league_names:
        from_url = st.query_params.get("league")
        st.session_state["league_select"] = from_url if from_url in league_names else leagues[0]["id"]
    active_league_id = st.sidebar.selectbox(
        "League", list(league_names), format_func=league_names.get, key="league_select",
    )
    st.query_params["league"] = active_league_id
else:
    st.sidebar.info("No leagues yet — create one below.")
    active_league_id = None

if st.session_state.get("active_league_id") != active_league_id:
    st.session_state["active_league_id"] = active_league_id
    reset_flow_state()

with st.sidebar.popover("➕ New league", width="stretch"):
    with st.form("create_league_form", clear_on_submit=True, border=False):
        new_name = st.text_input("League name")
        new_desc = st.text_area("Description (optional)")
        if st.form_submit_button("Create", type="primary") and new_name.strip():
            _select_league(memory.create_league(new_name.strip(), new_desc.strip()))
            st.rerun()

if active_league_id:
    league = memory.load_league(active_league_id)
    st.sidebar.divider()
    st.sidebar.caption(f"**{league['name']}** settings")

    with st.sidebar.expander("📝 League notes"):
        st.caption("Managers, rivalries, running jokes. Used for flavor, never stated as fact unless true.")
        with st.form(_lk("notes_form"), border=False):
            notes = st.text_area("Notes", value=league.get("league_notes", ""), height=200,
                                 label_visibility="collapsed")
            if st.form_submit_button("Save notes"):
                league["league_notes"] = notes
                memory.save_league(league)
                st.toast("League notes saved.")
                st.rerun()

    with st.sidebar.expander("📌 Log an event"):
        st.caption("Trades, injuries, waiver moves — kept as history for future callbacks.")
        with st.form(_lk("event_form"), clear_on_submit=True, border=False):
            ev_week = st.number_input("Week", min_value=1, value=league.get("current_week", 1) or 1)
            ev_type = st.selectbox("Type", ["trade", "waiver", "injury", "decision", "other"])
            ev_details = st.text_input("Details")
            if st.form_submit_button("Log event") and ev_details.strip():
                memory.add_event(league, int(ev_week), {"type": ev_type, "week": int(ev_week),
                                                        "details": ev_details.strip()})
                memory.save_league(league)
                st.toast("Event logged.")
                st.rerun()

    with st.sidebar.expander("🔁 A team renamed itself"):
        st.caption(
            "A renamed team matches nothing, so it reads as brand new — no previous rank, its "
            "history stranded under the old label. Link the two names here."
        )
        known = sorted({t["name"] for w in league.get("weeks", {}).values() for t in w.get("teams", [])})
        former_map = league.get("former_names") or {}
        if former_map:
            st.caption("Already linked: " + "; ".join(f"{', '.join(v)} → {k}" for k, v in former_map.items()))
        with st.form(_lk("team_rename_form"), border=False):
            old_nm = st.selectbox("Previous name", [""] + known)
            new_nm = st.selectbox("Current name", [""] + known)
            if st.form_submit_button("Link names"):
                if not (old_nm and new_nm):
                    st.warning("Pick both names.")
                elif old_nm == new_nm:
                    st.warning("Those are the same name.")
                else:
                    memory.record_rename(league, old_nm, new_nm)
                    st.toast(f"Linked. Regenerate a week to pick up {new_nm}'s full history.")
                    st.rerun()

    with st.sidebar.expander("✏️ Rename or delete league"):
        with st.form(_lk("rename_form"), border=False):
            renamed = st.text_input("League name", value=league["name"])
            if st.form_submit_button("Rename") and renamed.strip() and renamed.strip() != league["name"]:
                memory.rename_league(active_league_id, renamed.strip())
                st.toast("Renamed.")
                st.rerun()
        st.divider()
        st.caption("Deleting removes every week of history for this league.")
        confirm = st.checkbox("I understand, delete it", key=_lk("delete_confirm"))
        if st.button("🗑️ Delete league", key=_lk("delete_btn"), disabled=not confirm):
            memory.delete_league(active_league_id)
            _select_league(None)
            st.rerun()


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
    # One week field drives everything below: the ESPN pull, the screenshot
    # path, and the week the result is saved under. Two separate fields let a
    # week-2 pull be filed as week 9. It follows the league: when a week is
    # written (or deleted) it moves to the next unwritten one on its own.
    written = [int(k) for k, v in (league.get("weeks") or {}).items() if v.get("writeups")]
    next_week = (max(written) if written else 0) + 1
    week_key = f"week_input_{active_league_id}"
    seen_key = f"_next_week_seen_{active_league_id}"
    if st.session_state.get(seen_key) != next_week:
        st.session_state[seen_key] = next_week
        st.session_state[week_key] = next_week
    week_num = st.number_input("Week", min_value=1, step=1, key=week_key)

    espn_creds = bool(os.environ.get("ESPN_S2") and os.environ.get("ESPN_SWID"))

    def _espn_settings_form(connected: bool):
        with st.form(f"espn_form_{active_league_id}", border=False):
            c1, c2 = st.columns([3, 1])
            espn_id = c1.text_input(
                "ESPN league ID", value=str(league.get("espn_league_id") or ""),
                help="The number after leagueId= in the league's ESPN URL.",
            )
            espn_year = c2.number_input(
                "Season", min_value=2019, max_value=2100,
                value=int(league.get("espn_season") or datetime.now().year),
            )
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("Save" if connected else "Connect", type="primary")
            disconnect = connected and b2.form_submit_button("Disconnect")
        if save:
            cleaned = espn_id.strip()
            if cleaned and not cleaned.isdigit():
                st.error("The league ID is just the number from the URL.")
            else:
                league["espn_league_id"] = cleaned or None
                league["espn_season"] = int(espn_year)
                memory.save_league(league)
                st.toast("ESPN settings saved.")
                st.rerun()
        if disconnect:
            league["espn_league_id"] = None
            memory.save_league(league)
            st.toast("Disconnected from ESPN.")
            st.rerun()
        st.caption(
            "✅ ESPN cookies found in .env (shared by every league)" if espn_creds
            else "⚠️ ESPN_S2 / ESPN_SWID aren't set in .env, so pulling will fail"
        )

    if not league.get("espn_league_id"):
        with st.expander("🔗 Connect this league to ESPN to skip screenshots"):
            st.caption("Pulls scores, standings, projections and full lineups straight from ESPN.")
            _espn_settings_form(connected=False)
    else:
        st.subheader("Pull This Week From ESPN")
        st.caption(
            f"ESPN league {league['espn_league_id']}, {league.get('espn_season') or datetime.now().year} "
            "season. Pulls scores, standings, projections and full lineups, including who was benched."
        )
        pull_week = int(week_num)
        if st.button(f"⬇️ Pull week {pull_week} from ESPN", type="primary", key="espn_pull_btn"):
            with st.spinner("Fetching from ESPN..."):
                try:
                    extracted = espn_sync.fetch_week(
                        int(league["espn_league_id"]),
                        int(league.get("espn_season") or datetime.now().year),
                        int(pull_week),
                    )
                    extracted = data_validation.normalize_extracted_data(league, extracted)
                    memory.save_league(league)
                    st.session_state["extracted"] = extracted
                    st.session_state["warnings"] = data_validation.validate_extracted_data(extracted)
                    st.session_state["reconciliation"] = data_validation.reconcile_week(
                        league, int(pull_week), extracted
                    )
                    st.session_state["flow_stage"] = "extracted"
                    n_lineups = len(extracted.get("lineups") or [])
                    st.success(f"Pulled week {pull_week}: {len(extracted['teams'])} teams, "
                               f"{len(extracted['matchups'])} matchups, {n_lineups} lineups.")
                except Exception as e:
                    st.error(f"Couldn't pull from ESPN: {e}")
                    st.caption(
                        "If this says access denied, the espn_s2 cookie has probably expired — "
                        "copy a fresh one from your browser into .env. Screenshots still work below."
                    )
                    if DEBUG:
                        st.exception(e)
        with st.expander("⚙️ ESPN settings"):
            _espn_settings_form(connected=True)
        st.divider()

    st.subheader("Or Upload Screenshots")
    st.caption("Standings and scoreboard. Still works if the ESPN pull fails or cookies expire.")
    uploaded = st.file_uploader(
        "Screenshots",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{active_league_id}",
    )

    context_text = st.text_area(
        "Anything important that happened this week? (optional)",
        placeholder="e.g. Mike traded Bijan last week and immediately lost. John has been talking shit all week.",
        key=f"context_input_{active_league_id}",
    )

    if st.button("🔍 Extract Data From Screenshots", type="primary", disabled=not uploaded):
        with st.spinner("Reading screenshots..."):
            try:
                extracted = data_extraction.extract_from_screenshots(uploaded, context_text)
                extracted = data_validation.normalize_extracted_data(league, extracted)
                memory.save_league(league)  # persist any new team-name aliases learned
                st.session_state["extracted"] = extracted
                st.session_state["warnings"] = data_validation.validate_extracted_data(extracted)
                st.session_state["reconciliation"] = data_validation.reconcile_week(
                    league, int(week_num), extracted
                )
                st.session_state["flow_stage"] = "extracted"
            except Exception as e:
                st.error(f"Couldn't extract data from those screenshots: {e}")
                if DEBUG:
                    st.exception(e)

    if st.session_state.get("flow_stage") == "extracted":
        extracted = st.session_state["extracted"]
        warnings = st.session_state["warnings"]

        if extracted.get("source") != "espn_api" and extracted.get("week") and extracted["week"] != week_num:
            st.info(f"The screenshots suggest this might be Week {extracted['week']}. Adjust the Week field above if needed.")

        if warnings:
            with st.expander(f"⚠️ {len(warnings)} possible issue(s) found — review below", expanded=True):
                for w in warnings:
                    st.warning(w)

        recon = st.session_state.get("reconciliation") or []
        ok, failed, skipped = data_validation.reconciliation_summary(recon)
        if failed:
            st.error(f"🔴 {failed} number(s) don't add up — fix these before generating:")
            for r in recon:
                if r["status"] == "fail":
                    st.warning(f"**{r['team']}** — {r['check']}: {r['detail']}")
        elif ok:
            st.success(f"🟢 All {ok} cross-checks passed — scores, records and streaks agree with last week.")
        elif skipped:
            st.info("First stored week for this league — nothing to cross-check against yet.")

        with st.expander("Review & correct extracted data", expanded=bool(failed)):
            st.caption("Edit any cell that looks wrong before generating rankings.")

            teams_df = pd.DataFrame(extracted.get("teams", [])).reindex(
                columns=["name", "manager", "record", "streak", "points_for", "points_against",
                         "playoff_pct", "division", "standing"]
            )
            edited_teams = st.data_editor(teams_df, num_rows="dynamic", key=f"teams_editor_{active_league_id}", use_container_width=True)

            matchups_df = pd.DataFrame(extracted.get("matchups", [])).reindex(
                columns=["team_a", "score_a", "projected_a", "team_b", "score_b", "projected_b"]
            )
            edited_matchups = st.data_editor(matchups_df, num_rows="dynamic", key=f"matchups_editor_{active_league_id}", use_container_width=True)

        # Pulled data knows its own week for certain. If the field was changed
        # after pulling, saving would file one week's results under another.
        pulled_week = extracted.get("week") if extracted.get("source") == "espn_api" else None
        week_mismatch = pulled_week is not None and int(pulled_week) != int(week_num)
        if week_mismatch:
            st.error(
                f"This data was pulled for week {pulled_week}, but the Week field says "
                f"{int(week_num)}. Set it back to {pulled_week}, or pull week {int(week_num)}."
            )

        if st.button("🔥 GENERATE POWER RANKINGS", type="primary", disabled=week_mismatch):
            with st.spinner("Crunching numbers and writing rankings..."):
                try:
                    narratives.reset_usage()
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
                        # Carried through from the pull. The editable tables only
                        # cover teams and matchups, so without this the lineup
                        # data -- the whole point of the API path -- is dropped
                        # between extraction and generation.
                        "lineups": extracted.get("lineups", []),
                        "source": extracted.get("source", "screenshots"),
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
                    st.session_state["column_profile"] = narratives.profile_writeups(
                        final.get("team_writeups", [])
                    )
                    st.session_state["token_usage"] = narratives.cache_summary()

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

        profile = st.session_state.get("column_profile") or {}
        if profile.get("n"):
            st.caption(
                f"Column profile: {profile['n']} writeups · mean {profile['mean_words']} words "
                f"(reference corpus ≈29) · shortest {profile['shortest']} · longest {profile['longest']}"
            )
            usage = st.session_state.get("token_usage") or {}
            if usage.get("calls"):
                cached = usage["cache_read"]
                billed = usage["input"] + usage["cache_write"]
                st.caption(
                    f"Tokens: {billed:,} input · {cached:,} read from cache · "
                    f"{usage['output']:,} output across {usage['calls']} calls"
                    + ("" if cached else "  ⚠️ no cache hits — prompts may have changed")
                )

            if profile.get("violations"):
                with st.expander(f"⚠️ {len(profile['violations'])} style rule violation(s)"):
                    for v in profile["violations"]:
                        st.warning(v)

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
        render_week(league, w, memory.get_week(league, w), context="upload")

with tab_history:
    weeks = memory.sorted_week_numbers(league)
    if not weeks:
        st.write("No history yet — generate this week's rankings first.")
    else:
        chosen_week = st.selectbox("Week", weeks[::-1], key=f"history_week_select_{active_league_id}")

        with st.expander("⚙️ Redo or delete this week"):
            st.caption(
                "Rewriting reuses the stored scores and context — no screenshots to re-upload and "
                "no vision call, so it costs three API calls instead of four. Other weeks are left "
                "alone either way."
            )
            awards_feedback = st.text_input(
                "What should change about the awards/recap? (optional)",
                key=f"history_awards_feedback_{active_league_id}",
            )
            if st.button("🏅 Redo just the awards + recap (1 call)", key="history_awards_btn"):
                with st.spinner("Rewriting awards and recap..."):
                    try:
                        wd = memory.get_week(league, int(chosen_week))
                        result = narratives.regenerate_awards_and_recap(
                            league,
                            int(chosen_week),
                            wd["rankings"],
                            wd.get("context", ""),
                            wd["writeups"]["team_writeups"],
                            feedback=awards_feedback,
                        )
                        wd["writeups"]["week_theme"] = result["week_theme"]
                        wd["writeups"]["awards"] = result["awards"]
                        wd["writeups"]["recap"] = result["recap"]
                        memory.save_week(league, int(chosen_week), wd)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Couldn't rewrite the awards: {e}")
                        if DEBUG:
                            st.exception(e)

            st.divider()
            col_a, col_b = st.columns(2)

            if col_a.button(f"🔄 Rewrite week {chosen_week}", key="history_regen_btn"):
                with st.spinner("Rewriting the whole week..."):
                    try:
                        final = regenerate_week_writeups(league, int(chosen_week))
                        st.session_state["column_profile"] = narratives.profile_writeups(
                            final.get("team_writeups", [])
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Couldn't rewrite that week: {e}")
                        if DEBUG:
                            st.exception(e)

            confirm = col_b.checkbox("I'm sure", key=f"history_delete_confirm_{active_league_id}")
            if col_b.button(f"🗑️ Delete week {chosen_week}", key="history_delete_btn", disabled=not confirm):
                memory.delete_week(league, int(chosen_week))
                st.success(f"Week {chosen_week} deleted. Other weeks untouched.")
                st.rerun()

        profile = st.session_state.get("column_profile") or {}
        if profile.get("n"):
            st.caption(
                f"Column profile: {profile['n']} writeups · mean {profile['mean_words']} words "
                f"(reference corpus ≈29) · shortest {profile['shortest']} · longest {profile['longest']}"
            )

        render_week(league, chosen_week, memory.get_week(league, chosen_week), context="history")
