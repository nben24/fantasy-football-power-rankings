#!/usr/bin/env python
"""Command-line entry point for the weekly unattended run.

    python scripts/weekly_run.py --dry-run     # pull and verify, spend nothing
    python scripts/weekly_run.py               # pull, verify and write up
    python scripts/weekly_run.py --week 9      # force a specific week

Exit codes are meaningful so a scheduler can tell quiet success from trouble:
    0  everything generated or deliberately skipped
    1  at least one league blocked or failed
    2  could not start (missing credentials)

Output goes to stdout and to logs/weekly_run.log.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src import weekly_run  # noqa: E402  (must follow load_dotenv)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull every configured league and write its column.")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull and reconcile only; makes no model calls and costs nothing")
    ap.add_argument("--week", type=int, default=None,
                    help="force a week instead of using the most recently completed one")
    ap.add_argument("--league", default=None, help="run a single league by id")
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    args = ap.parse_args()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_dir / "weekly_run.log"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("weekly_run.cli")

    if weekly_run.missing_credentials():
        log.error("ESPN_S2 / ESPN_SWID not set. Copy fresh cookies into .env.")
        return 2

    started = datetime.now()
    log.info("weekly run starting%s", " (dry run)" if args.dry_run else "")

    if args.league:
        results = [weekly_run.run_league(args.league, dry_run=args.dry_run, week=args.week)]
    else:
        results = weekly_run.run_all(dry_run=args.dry_run, week=args.week)

    summary = weekly_run.summarize(results)
    print()
    print(summary)
    log.info("finished in %.1fs", (datetime.now() - started).total_seconds())

    return 0 if all(r.ok or r.status == "pulled" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
