#!/usr/bin/env python
"""Build and publish the rankings site.

    python scripts/publish_site.py --preview          # build everything, serve at localhost:8765
    python scripts/publish_site.py --league my_league   # publish that league's latest week, deploy
    python scripts/publish_site.py                    # rebuild and redeploy what's already published

The app's Publish button does the same thing; this is for the terminal.
"""

import argparse
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src import memory, site_build  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview", action="store_true", help="build with every written week and serve locally")
    ap.add_argument("--league", help="mark this league's latest written week as published first")
    args = ap.parse_args()

    if args.preview:
        url = site_build.serve_preview()
        for e in memory.list_leagues():
            lg = memory.load_league(e["id"])
            if lg.get("site_slug"):
                print(f"{lg['name']:<28} {url}/{lg['site_slug']}/")
        webbrowser.open(url + "/")
        print("\nServing the preview. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    league = None
    if args.league:
        league = memory.load_league(args.league)
        if league is None:
            print(f"No league with id {args.league!r}.")
            return 1
    try:
        site_build.publish(league)
    except Exception as e:  # noqa: BLE001
        print(f"Publish failed: {e}")
        return 1
    for e in memory.list_leagues():
        lg = memory.load_league(e["id"])
        if lg.get("site_published_week"):
            print(f"{lg['name']:<28} week {lg['site_published_week']:<3} {site_build.league_url(lg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
