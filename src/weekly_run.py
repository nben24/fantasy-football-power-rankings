"""Unattended weekly generation: pull every configured league and write its column.

Intended for a Tuesday-morning cron/launchd job, so that four finished columns
are waiting rather than four screenshot sessions. Everything here is
deliberately conservative, because nobody is watching when it runs:

- A week that already has writeups is never regenerated. Re-running the job is
  safe and costs nothing.
- If reconciliation fails, the week is saved but NOT written up. Publishing
  numbers that do not add up is the worst outcome this project has; a column
  that is merely late is recoverable.
- Each league is independent. A dead cookie or an ESPN hiccup on one league
  does not stop the other three.

Generation costs three API calls per league. Use dry_run to pull and verify
without spending anything.
"""

import logging
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime

from src import data_validation, espn_sync, memory, narratives, rankings

log = logging.getLogger("weekly_run")


@dataclass
class LeagueResult:
    league_id: str
    league_name: str
    week: int | None = None
    status: str = "pending"  # pulled | generated | skipped | waiting | blocked | failed
    detail: str = ""
    reconciliation: tuple[int, int, int] | None = None
    profile: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # "waiting" is normal at 9am if ESPN hasn't finalised the week yet;
        # the next scheduled attempt picks it up.
        return self.status in ("generated", "skipped", "waiting")

    def line(self) -> str:
        icon = {
            "generated": "✅", "pulled": "◦", "skipped": "·", "waiting": "…",
            "blocked": "⚠️", "failed": "❌",
        }.get(self.status, "?")
        wk = f"W{self.week}" if self.week else "--"
        return f"{icon} {self.league_name[:24]:<26}{wk:<5}{self.status:<10}{self.detail}"


def target_week(league_client, league: dict | None = None) -> int:
    """The week to write: the league's next unwritten one.

    This used to be "ESPN's current_week minus one", which depends on when
    ESPN rolls the week over. Run before the rollover, it pointed at last
    week, found it already written, and quietly did nothing. A league with no
    written weeks yet falls back to that rule.
    """
    written = [int(k) for k, v in ((league or {}).get("weeks") or {}).items() if v.get("writeups")]
    if written:
        return max(written) + 1
    return max(1, int(league_client.current_week) - 1)


def week_is_final(league_client, week: int) -> bool:
    """True once every matchup in `week` has a result.

    ESPN keeps a team's outcome for a week as "U" (undecided) until it is
    final. A week before current_week is final regardless, which also covers
    playoff weeks where eliminated teams never get an outcome.
    """
    if week < int(league_client.current_week):
        return True
    teams = getattr(league_client, "teams", None) or []
    if not teams:
        return False
    for t in teams:
        outcomes = getattr(t, "outcomes", None) or []
        if len(outcomes) < week or outcomes[week - 1] not in ("W", "L", "T"):
            return False
    return True


def run_league(league_id: str, dry_run: bool = False, week: int | None = None,
               scheduled: bool = False) -> LeagueResult:
    league = memory.load_league(league_id)
    if league is None:
        return LeagueResult(league_id, league_id, status="failed", detail="league not found")

    result = LeagueResult(league_id, league.get("name", league_id))
    espn_id = league.get("espn_league_id")
    if not espn_id:
        result.status = "skipped"
        result.detail = "no ESPN league id configured"
        return result
    if scheduled and league.get("auto_weekly") is False:
        result.status = "skipped"
        result.detail = "automatic Tuesday runs are off for this league"
        return result

    try:
        season = int(league.get("espn_season") or datetime.now().year)
        client = espn_sync.connect(int(espn_id), season)
        wk = int(week) if week else target_week(client, league)
        result.week = wk
        if not week and not week_is_final(client, wk):
            result.status = "waiting"
            result.detail = f"week {wk} isn't final on ESPN yet"
            return result

        existing = memory.get_week(league, wk) or {}
        if existing.get("writeups"):
            result.status = "skipped"
            result.detail = "already generated"
            return result

        pulled = espn_sync.build_week(client, wk)
        pulled = data_validation.normalize_extracted_data(league, pulled)

        recon = data_validation.reconcile_week(league, wk, pulled)
        ok, failed, skipped = data_validation.reconciliation_summary(recon)
        result.reconciliation = (ok, failed, skipped)

        week_data = {
            "teams": pulled["teams"],
            "matchups": pulled["matchups"],
            "lineups": pulled["lineups"],
            "context": existing.get("context", ""),
            "events": existing.get("events", []),
            "source": "espn_api",
        }
        memory.save_week(league, wk, week_data)

        if failed:
            bad = "; ".join(f"{r['team']} {r['check']}" for r in recon if r["status"] == "fail")
            result.status = "blocked"
            result.detail = f"{failed} reconciliation failure(s), not written up: {bad[:120]}"
            return result

        if dry_run:
            result.status = "pulled"
            result.detail = f"{ok} checks passed; generation skipped (dry run)"
            return result

        ranked = rankings.compute_power_rankings(league, wk)
        week_data["rankings"] = ranked
        memory.save_week(league, wk, week_data)

        context_text = week_data.get("context", "")
        angles = narratives.find_comedic_angles(league, wk, ranked, context_text)
        narratives.apply_storyline_updates(league, wk, angles.get("storyline_updates", []))
        capped = narratives.cap_fraud_lens_angles(angles.get("team_angles", []), ranked)
        draft = narratives.generate_writeups(league, wk, ranked, context_text, capped)
        final = narratives.critique_and_revise(league, wk, ranked, context_text, draft)

        week_data["writeups"] = final
        week_data["angles"] = capped
        memory.save_week(league, wk, week_data)

        result.profile = narratives.profile_writeups(final.get("team_writeups", []))
        result.status = "generated"
        viol = len(result.profile.get("violations") or [])
        result.detail = (
            f"{result.profile.get('n')} writeups, mean {result.profile.get('mean_words')}w"
            + (f", {viol} style flag(s)" if viol else "")
        )
        return result

    except Exception as exc:  # noqa: BLE001 - one league must not stop the rest
        result.status = "failed"
        result.detail = f"{type(exc).__name__}: {exc}"[:200]
        log.debug("league %s failed\n%s", league_id, traceback.format_exc())
        return result


def run_all(dry_run: bool = False, week: int | None = None) -> list[LeagueResult]:
    """Every league with an ESPN id and automatic runs on, each isolated from the others."""
    results = []
    for entry in memory.list_leagues():
        results.append(run_league(entry["id"], dry_run=dry_run, week=week, scheduled=True))
    return results


def notification_text(results: list[LeagueResult]) -> str | None:
    """One line for a desktop notification, or None if there's nothing new."""
    done = [r for r in results if r.status == "generated"]
    bad = [r for r in results if r.status in ("blocked", "failed")]
    if not done and not bad:
        return None
    parts = []
    if done:
        parts.append("Ready: " + ", ".join(f"{r.league_name} W{r.week}" for r in done))
    if bad:
        parts.append("Needs a look: " + ", ".join(r.league_name for r in bad))
    return ". ".join(parts)


def summarize(results: list[LeagueResult]) -> str:
    lines = [r.line() for r in results]
    generated = sum(1 for r in results if r.status == "generated")
    problems = [r for r in results if r.status in ("blocked", "failed")]
    lines.append("")
    lines.append(f"{generated} generated, {len(problems)} needing attention, {len(results)} total")
    if problems:
        lines.append("Needs a look: " + ", ".join(r.league_name for r in problems))
    return "\n".join(lines)


def missing_credentials() -> bool:
    return not (os.environ.get("ESPN_S2") and os.environ.get("ESPN_SWID"))
