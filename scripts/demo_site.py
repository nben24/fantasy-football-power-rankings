#!/usr/bin/env python
"""Build the website from a made-up league, for the README screenshots.

    python scripts/demo_site.py              # build into site_demo/ and print standings
    python scripts/demo_site.py --shots      # also screenshot it into docs/screenshots/

Everything here is fictional: team names, scores and writeups. Real leagues
never go into tracked files (see Privacy in CLAUDE.md), so the README shows
this instead.
"""

import argparse
import functools
import http.server
import random
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import site_build  # noqa: E402

OUT = ROOT / "site_demo"
SHOTS = ROOT / "docs" / "screenshots"
SLUG = "demo-league"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

TEAMS = [
    "Gridiron Goblins", "Fourth & Forever", "Waiver Wire Wizards", "Sunday Scaries",
    "Couch Coaches", "Hail Mary Poppins", "Bench Press", "Taco Tuesday FC",
    "The Bye Week Ballers", "Fumble Recovery",
]
# How good each team "really" is; the season is random around this.
STRENGTH = [128, 124, 121, 118, 116, 114, 112, 110, 106, 101]
WEEKS = 8


def schedule(n, weeks):
    """Round robin: the circle method, one rotation per week."""
    idx = list(range(n))
    out = []
    for _ in range(weeks):
        out.append([(idx[i], idx[n - 1 - i]) for i in range(n // 2)])
        idx = [idx[0]] + [idx[-1]] + idx[1:-1]
    return out


def simulate():
    rng = random.Random(7)
    games = []
    for wk, pairs in enumerate(schedule(len(TEAMS), WEEKS), start=1):
        week = []
        for a, b in pairs:
            sa = round(rng.gauss(STRENGTH[a], 19), 2)
            sb = round(rng.gauss(STRENGTH[b], 19), 2)
            pa = round(STRENGTH[a] + rng.uniform(-6, 6), 2)
            pb = round(STRENGTH[b] + rng.uniform(-6, 6), 2)
            week.append((TEAMS[a], TEAMS[b], sa, sb, pa, pb))
        games.append(week)
    return games


def standings_through(games, wk):
    st = {t: {"w": 0, "l": 0, "pf": 0.0, "pa": 0.0, "res": []} for t in TEAMS}
    for week in games[:wk]:
        for a, b, sa, sb, *_ in week:
            for me, them, s, o in ((a, b, sa, sb), (b, a, sb, sa)):
                st[me]["pf"] += s
                st[me]["pa"] += o
                won = s > o
                st[me]["w" if won else "l"] += 1
                st[me]["res"].append("W" if won else "L")
    for v in st.values():
        last = v["res"][-1]
        run = 0
        for r in reversed(v["res"]):
            if r != last:
                break
            run += 1
        v["streak"] = f"{last}{run}"
    order = sorted(TEAMS, key=lambda t: (-st[t]["w"], -st[t]["pf"]))
    return st, order


# Week 8 is the one the screenshots show, so it gets a real column. Every line
# is written against the simulated results printed by this script.
WEEK8 = {
    "theme": "Week 8: The Wizards Settle It",
    "recap": None,  # filled from results below
    "tiers": [
        ("The Front Office", "Actually earning it"),
        ("Respectable Chaos", "Good teams, bad habits"),
        ("Loitering", "Here for the snacks"),
        ("Draft Night Regrets", "There's always next year"),
    ],
    "tier_sizes": [3, 3, 2, 2],
}
WRITEUPS = {
    "Waiver Wire Wizards": "7-1, and the only loss was a week 5 dud against the Ballers. Beat the Goblins head-to-head, so the argument about who's best is closed until further notice.",
    "Gridiron Goblins": "Second-most points in the league and two straight losses. You're the guy who aces every practice test and then forgets his calculator.",
    "Fourth & Forever": "Started 1-3. Four straight wins since, and Sunday Scaries never had a chance. The comeback nobody asked for and everybody has to deal with now.",
    "Taco Tuesday FC": "5-3 with the seventh-most points in a ten-team league. Won by 1.10 this week and by 0.09 in week 5. That's not a team, that's a coin on a heater.",
    "Bench Press": "Lost by 1.10 to the luckiest team in the league. Of course it was them.",
    "Couch Coaches": "Started 4-1. Three straight losses since, the latest to a team projected for 97. The couch has taken over.",
    "Sunday Scaries": "16 under projection and run over by 32. Living up to the name.",
    "Hail Mary Poppins": "160 points, best in the league by more than 31, and still 2-6. Imagine doing this in a week that mattered.",
    "The Bye Week Ballers": "Ran into the one team that brought 160. Wrong place, wrong time, still 2-6.",
    "Fumble Recovery": "Snapped a four-game skid as a 23-point underdog. Fewest points in the league by more than 90, but this week the name was earned.",
}
# The team page screenshot shows one team's history, so that team gets real lines.
HISTORY = {"Fourth & Forever": {
    1: "Beat the Ballers by four in a game nobody will remember, including the people who played in it.",
    2: "Lost by 0.16. Somewhere there's a kicker who knows what he did.",
    3: "Projected for 120, scored 96, lost by 35. A full team effort, in the wrong direction.",
    4: "1-3 now. Waiver Wire Wizards scored 139 and the gap never felt that close.",
    5: "154.59, best score of the week, against Fumble Recovery. Finally, a pulse.",
    6: "Two straight. Beat Taco Tuesday by 38, which is not a coin flip, for once.",
    7: "Three straight wins and back to .500. The group chat has started to notice.",
}}
AWARDS = [
    {"title": "Weekly High Score", "team": "Hail Mary Poppins",
     "reason": "160.17, 45.83 over projection and the week's top score by 31.54."},
    {"title": "Luckiest Team", "team": "Taco Tuesday FC",
     "reason": "5-3 with the seventh-most points, thanks to wins by 1.10 and 0.09."},
    {"title": "Upset of the Week", "team": "Fumble Recovery",
     "reason": "Beat Couch Coaches 113.45-107.81 as a 23-point projected underdog."},
]
RECAP = ("Waiver Wire Wizards beat the Gridiron Goblins 128.33-121.61 and sit at 7-1, two games clear. "
         "Fourth & Forever made it four straight by beating Sunday Scaries by 31.98. Hail Mary Poppins "
         "dropped the week's top score, 160.17, on The Bye Week Ballers, and Fumble Recovery beat Couch "
         "Coaches as a 23-point underdog. Taco Tuesday FC won by 1.10, because of course they did.")
OLD_LINES = [
    "Showed up, scored points, went home. Nobody's writing a song about it.",
    "A week so normal the group chat didn't notice.",
    "Did enough. Barely. Moving on.",
    "The lineup was fine. The result was fine. Everything is fine.",
    "Somewhere a projection is very proud of you.",
    "Not the best week, not the worst. The fantasy equivalent of beige.",
]


def build_league():
    games = simulate()
    weeks = {}
    prev_order = None
    for wk in range(1, WEEKS + 1):
        st, order = standings_through(games, wk)
        rank = {t: i for i, t in enumerate(order, start=1)}
        prev = {t: i for i, t in enumerate(prev_order, start=1)} if prev_order else {}
        rankings = [{"name": t, "rank": rank[t], "previous_rank": prev.get(t),
                     "rank_change": (prev[t] - rank[t]) if prev else None,
                     "record": f"{st[t]['w']}-{st[t]['l']}-0"} for t in order]
        teams = [{"name": t, "record": f"{st[t]['w']}-{st[t]['l']}-0",
                  "points_for": round(st[t]["pf"], 2), "points_against": round(st[t]["pa"], 2),
                  "streak": st[t]["streak"]} for t in TEAMS]
        matchups = [{"team_a": a, "team_b": b, "score_a": sa, "score_b": sb,
                     "projected_a": pa, "projected_b": pb}
                    for a, b, sa, sb, pa, pb in games[wk - 1]]
        rng = random.Random(wk)
        if wk == WEEKS and WRITEUPS:
            writeups = column(order)
        else:
            writeups = {
                "week_theme": f"Week {wk}: " + rng.choice(
                    ["Nobody Panic", "The Middle Holds", "Points Were Scored", "Same Old League"]),
                "team_writeups": [{"name": t, "narrative": HISTORY.get(t, {}).get(wk) or rng.choice(OLD_LINES)}
                                  for t in order],
                "tiers": [{"tier_name": "The League", "team_names": order}],
                "awards": [],
                "recap": "Results are final. Week 8 is where this demo league gets its full column.",
            }
        weeks[str(wk)] = {"teams": teams, "matchups": matchups, "rankings": rankings,
                          "writeups": writeups}
        prev_order = order
    return {"id": "demo_league", "name": "The Demo League", "espn_season": 2026,
            "site_slug": SLUG, "site_published_week": WEEKS, "weeks": weeks}, games


def column(order):
    names, sizes = WEEK8["tiers"], WEEK8["tier_sizes"]
    tiers, i = [], 0
    for (name, sub), n in zip(names, sizes):
        tiers.append({"tier_name": name, "tier_subtitle": sub, "team_names": order[i:i + n]})
        i += n
    return {
        "week_theme": WEEK8["theme"],
        "team_writeups": [{"name": t, "narrative": WRITEUPS[t]} for t in order],
        "tiers": tiers,
        "awards": AWARDS,
        "recap": RECAP,
    }



def print_results(lg, games):
    for wk in range(1, WEEKS + 1):
        print(f"week {wk}:")
        for a, b, sa, sb, pa, pb in games[wk - 1]:
            print(f"   {a:22} {sa:7.2f} (proj {pa:6.2f})  vs  {b:22} {sb:7.2f} (proj {pb:6.2f})")
    st, order = standings_through(games, WEEKS)
    print("standings after week", WEEKS)
    for i, t in enumerate(order, 1):
        v = st[t]
        print(f"  {i:2} {t:22} {v['w']}-{v['l']}  PF {v['pf']:.1f}  {v['streak']}  {''.join(v['res'])}")


def screenshots():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:8799/{SLUG}/"
    SHOTS.mkdir(parents=True, exist_ok=True)
    shots = [("week.png", "", 1280, 2000), ("season.png", "season/", 1280, 1900),
             ("team.png", "teams/fourth-forever/", 1280, 1500)]
    for name, path, w, h in shots:
        subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={w},{h}", "--virtual-time-budget=4000",
                        f"--screenshot={SHOTS / name}", base + path],
                       check=True, capture_output=True)
        print("wrote", SHOTS / name)
    srv.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true")
    args = ap.parse_args()
    lg, games = build_league()
    if not WRITEUPS:
        print_results(lg, games)
        return
    site_build.build_site(OUT, [lg])
    print("built", OUT / SLUG)
    if args.shots:
        screenshots()


if __name__ == "__main__":
    main()
