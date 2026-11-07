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
    status: str = "pending"  # pulled | generated | skipped | blocked | failed
    detail: str = ""
    reconciliation: tuple[int, int, int] | None = None
    profile: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("generated", "skipped")

    def line(self) -> str:
        icon = {
            "generated": "✅", "pulled": "◦", "skipped": "·",
            "blocked": "⚠️", "failed": "❌",
        }.get(self.status, "?")
        wk = f"W{self.week}" if self.week else "--"
        return f"{icon} {self.league_name[:24]:<26}{wk:<5}{self.status:<10}{self.detail}"


def target_week(league_client) -> int:
    """The most recently completed week.

    ESPN's current_week points at the upcoming week once a slate finishes, so
    the week worth writing about is the one before it.
    """
    return max(1, int(league_client.current_week) - 1)


def run_league(league_id: str, dry_run: bool = False, week: int | None = None) -> LeagueResult:
    league = memory.load_league(league_id)
    if league is None:
        return LeagueResult(league_id, league_id, status="failed", detail="league not found")

    result = LeagueResult(league_id, league.get("name", league_id))
    espn_id = league.get("espn_league_id")
    if not espn_id:
        result.status = "skipped"
        result.detail = "no ESPN league id configured"
        return result

    try:
        season = int(league.get("espn_season") or datetime.now().year)
        client = espn_sync.connect(int(espn_id), season)
        wk = int(week) if week else target_week(client)
        result.week = wk

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
    """Every league that has an ESPN id configured, each isolated from the others."""
    results = []
    for entry in memory.list_leagues():
        results.append(run_league(entry["id"], dry_run=dry_run, week=week))
    return results


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
