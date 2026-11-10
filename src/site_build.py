"""Build the public site from the league files, and publish it.

One site, one unlisted address per league (``/my-league-3f9a1c/``), and no page
that links the leagues together: each group chat only ever sees its own link.

Only weeks you have published go out. Each league remembers the last week you
published (``site_published_week``), so a column the Tuesday-morning run wrote
but you haven't reviewed yet can't reach the site, even when you publish a
different league.

Manager names never leave this machine: the site shows team names only.
"""

import html
import json
import os
import re
import secrets
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from src import memory, narratives

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "site" / "template.html"
OUT_DIR = ROOT / "site_out"
PREVIEW_DIR = ROOT / "site_preview"
PREVIEW_PORT = 8765
DEFAULT_PROJECT = "power-rankings"


# --- addresses ----------------------------------------------------------------

def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "league"


def ensure_site_slug(league: dict) -> str:
    """The league's unlisted path, created once and then never changed, so a
    link people have bookmarked keeps working through a league rename. The
    random suffix is what keeps it unlisted: the name alone is guessable."""
    if not league.get("site_slug"):
        league["site_slug"] = f"{_slugify(league['name'])}-{secrets.token_hex(3)}"
    return league["site_slug"]


def site_url() -> str:
    """Public base URL, e.g. https://power-rankings.pages.dev (no trailing slash).

    Set SITE_URL in .env to the address Cloudflare printed on the first
    deploy; it can differ from the project name if that name was taken."""
    url = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if url:
        return url
    return f"https://{os.environ.get('CLOUDFLARE_PAGES_PROJECT', DEFAULT_PROJECT)}.pages.dev"


def league_url(league: dict) -> str | None:
    slug = league.get("site_slug")
    return f"{site_url()}/{slug}/" if slug else None


# --- data ---------------------------------------------------------------------

def published_weeks(league: dict, preview: bool = False) -> list[int]:
    """Weeks that go on the site. A preview shows every written week, so the
    one you're about to publish can be checked first."""
    upto = None if preview else league.get("site_published_week")
    if not preview and not upto:
        return []
    if preview:
        return sorted(int(k) for k, v in (league.get("weeks") or {}).items() if v.get("writeups"))
    return sorted(int(k) for k, v in (league.get("weeks") or {}).items()
                  if v.get("writeups") and int(k) <= int(upto))


def league_data(league: dict, preview: bool = False) -> dict | None:
    """Everything one league's pages need. Deliberately leaves out managers,
    league notes, storylines and anything else not already in the column."""
    weeks = published_weeks(league, preview)
    if not weeks:
        return None
    last = league["weeks"][str(weeks[-1])]
    current = [r["name"].strip() for r in last["rankings"]]
    canon = {}
    for name in current:
        for v in memory.name_variants(league, name):
            canon[v.strip()] = name

    def C(n):
        n = (n or "").strip()
        return canon.get(n, n)

    teams, used = [], {}
    for n in current:
        s = _slugify(n) if _slugify(n) != "league" else "team"
        used[s] = used.get(s, 0) + 1
        teams.append({"name": n, "slug": s if used[s] == 1 else f"{s}-{used[s]}"})

    out = []
    for wk in weeks:
        w = league["weeks"][str(wk)]
        wr = w["writeups"]
        by_team = {C(t["name"]): t for t in w.get("teams", [])}
        notes = {C(t["name"]): t.get("narrative", "") for t in wr.get("team_writeups", [])}
        rows = []
        for i, r in enumerate(w.get("rankings") or []):
            n = C(r["name"])
            t = by_team.get(n, {})
            rows.append({
                "team": n, "label": r["name"].strip(), "rank": r.get("rank") or i + 1,
                "change": r.get("rank_change"), "prev": r.get("previous_rank"),
                "record": narratives.tidy_record(r.get("record")),
                "streak": t.get("streak"), "pf": t.get("points_for"), "pa": t.get("points_against"),
                "writeup": notes.get(n, ""),
            })
        tiers = [{"name": t.get("tier_name"), "subtitle": _clean_subtitle(t.get("tier_subtitle")),
                  "teams": [C(x) for x in t.get("team_names", [])]} for t in wr.get("tiers", [])]
        games = [{"a": C(m["team_a"]), "b": C(m["team_b"]), "sa": m["score_a"], "sb": m["score_b"],
                  "pa": m.get("projected_a"), "pb": m.get("projected_b")}
                 for m in w.get("matchups", [])
                 if m.get("score_a") is not None and m.get("score_b") is not None]
        awards = [{"title": a.get("title"), "team": C(a.get("team")), "reason": a.get("reason")}
                  for a in wr.get("awards", [])]
        out.append({"week": wk, "theme": wr.get("week_theme", ""), "recap": wr.get("recap", ""),
                    "rows": rows, "tiers": tiers, "games": games, "awards": awards})
    return {"name": league["name"], "season": league.get("espn_season"), "teams": teams, "weeks": out}


def _clean_subtitle(s) -> str:
    s = (s or "").strip()
    while len(s) > 1 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s


# --- pages --------------------------------------------------------------------

def _head(title: str, description: str, image: str | None, url: str) -> str:
    e = lambda s: html.escape(s or "", quote=True)  # noqa: E731
    tags = [
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(description)}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{e(url)}">',
        '<meta property="og:type" content="website">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    if image:
        tags += [f'<meta property="og:image" content="{e(image)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">']
    return "\n".join(tags)


def _bare_theme(theme: str, week: int) -> str:
    """'Week 8: The Projections Filed A Police Report' -> the part after the
    prefix, so titles don't read 'Week 8: Week 8: ...'."""
    return re.sub(rf"^\s*week\s*{week}\s*[:\-–—]\s*", "", theme or "", flags=re.I).strip() or (theme or "")


def _short(text: str, n: int = 180) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _page(template: str, data: dict, base: str, route: dict, head: str, updated: str) -> str:
    blob = json.dumps({"league": data, "base": base, "route": route, "updated": updated},
                      ensure_ascii=False).replace("</", "<\\/")
    return (template.replace("__HEAD__", head)
                    .replace("__BASE__", base)
                    .replace("__LEAGUE_NAME__", html.escape(data["name"]))
                    .replace("__DATA__", blob))


def build_league(league: dict, out: Path, template: str, updated: str, preview: bool = False) -> int:
    """Write one league's pages under out/<site_slug>/. Returns pages written."""
    data = league_data(league, preview)
    if not data:
        return 0
    slug = ensure_site_slug(league)
    base = f"/{slug}/"
    root = out / slug
    abs_base = f"{site_url()}{base}"
    latest = data["weeks"][-1]
    n = 0

    def write(rel: str, route: dict, title: str, desc: str, image_week: int):
        nonlocal n
        img = f"{abs_base}og/week-{image_week}.png"
        head = _head(title, desc, img, abs_base + rel)
        path = root / rel / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_page(template, data, base, route, head, updated))
        n += 1

    for w in data["weeks"]:
        title = f"{data['name']} · Week {w['week']}: {_bare_theme(w['theme'], w['week'])}"
        write(f"week-{w['week']}/", {"kind": "week", "week": w["week"]}, title, _short(w["recap"]), w["week"])
        og_image(data, w, root / "og" / f"week-{w['week']}.png")
    write("", {"kind": "week", "week": latest["week"]},
          f"{data['name']} · Week {latest['week']}: {_bare_theme(latest['theme'], latest['week'])}",
          _short(latest["recap"]), latest["week"])
    write("season/", {"kind": "season"}, f"{data['name']} · Season", "Lucky or good, the rank race, records and the trophy case.", latest["week"])
    write("teams/", {"kind": "teams"}, f"{data['name']} · Teams", "Every team's page.", latest["week"])
    for t in data["teams"]:
        write(f"teams/{t['slug']}/", {"kind": "team", "slug": t["slug"]},
              f"{t['name']} · {data['name']}", f"Everything the column has said about {t['name']} this season.",
              latest["week"])
    return n


def build_site(out: Path = OUT_DIR, leagues: list[dict] | None = None, preview: bool = False) -> dict:
    """Rebuild the whole site from scratch. Returns {league_id: pages}.

    Leagues that gain a site_slug here are saved, so their address is fixed
    from the first build on."""
    template = TEMPLATE.read_text()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    updated = datetime.now().strftime("%b %-d, %Y")
    if leagues is None:
        leagues = [memory.load_league(e["id"]) for e in memory.list_leagues()]
    built = {}
    for lg in leagues:
        had_slug = bool(lg.get("site_slug"))
        pages = build_league(lg, out, template, updated, preview)
        if pages:
            built[lg["id"]] = pages
            if not had_slug:
                memory.save_league(lg)
    # The bare domain shows nothing and lists nothing.
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">'
        '<title>Nothing here</title><body style="font:16px system-ui;padding:40px">Nothing here.</body>')
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n")
    return built


# --- link preview image --------------------------------------------------------

_DISPLAY_FONTS = ["/System/Library/Fonts/Supplemental/Impact.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Black.ttf"]
_BODY_FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/System/Library/Fonts/Helvetica.ttc"]


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _plain(s: str) -> str:
    """Emoji render as empty boxes in these fonts; drop them from the image."""
    return "".join(ch for ch in (s or "") if ord(ch) < 0x2000 or 0x2010 <= ord(ch) <= 0x2027).strip()


def _wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def og_image(data: dict, week: dict, path: Path) -> None:
    """The card a group chat shows when the link is pasted."""
    from PIL import Image, ImageDraw
    W, H, pad = 1200, 630, 64
    img = Image.new("RGB", (W, H), "#121211")
    d = ImageDraw.Draw(img)
    d.text((pad, pad - 6), "THE POWER ", font=_font(_DISPLAY_FONTS, 40), fill="#f0efec")
    off = d.textlength("THE POWER ", font=_font(_DISPLAY_FONTS, 40))
    d.text((pad + off, pad - 6), "RANKINGS", font=_font(_DISPLAY_FONTS, 40), fill="#eb6834")
    d.text((pad, 130), f"{_plain(data['name']).upper()} · WEEK {week['week']}",
           font=_font(_BODY_FONTS, 30), fill="#c3c2b7")
    theme_font = _font(_DISPLAY_FONTS, 76)
    lines = _wrap(d, _plain(_bare_theme(week["theme"], week["week"])).upper(), theme_font, W - 2 * pad)[:3]
    y = 185
    for ln in lines:
        d.text((pad, y), ln, font=theme_font, fill="#f0efec")
        y += 86
    top = week["rows"][0] if week["rows"] else None
    if top:
        d.line((pad, H - 140, W - pad, H - 140), fill="#33332f", width=2)
        d.text((pad, H - 118), "#1", font=_font(_DISPLAY_FONTS, 64), fill="#eb6834")
        d.text((pad + 100, H - 112), _plain(top["label"]), font=_font(_BODY_FONTS, 40), fill="#f0efec")
        d.text((pad + 100, H - 62), top["record"], font=_font(_BODY_FONTS, 26), fill="#8f8d85")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


# --- publishing ----------------------------------------------------------------

def mark_published(league: dict) -> int | None:
    """Publish everything written so far for this league. Returns the week."""
    written = [int(k) for k, v in (league.get("weeks") or {}).items() if v.get("writeups")]
    if not written:
        return None
    league["site_published_week"] = max(written)
    ensure_site_slug(league)
    memory.save_league(league)
    return league["site_published_week"]


def missing_deploy_settings() -> list[str]:
    return [k for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID") if not os.environ.get(k)]


def deploy(out: Path = OUT_DIR) -> str:
    """Upload the built site to Cloudflare Pages. Returns wrangler's output.

    Direct upload: the built pages go straight to Cloudflare and never
    through git, so real team names stay off the public repo."""
    missing = missing_deploy_settings()
    if missing:
        raise RuntimeError("Missing in .env: " + ", ".join(missing))
    if not shutil.which("npx"):
        raise RuntimeError("npx not found -- install Node.js to publish.")
    project = os.environ.get("CLOUDFLARE_PAGES_PROJECT", DEFAULT_PROJECT)
    env = {**os.environ}
    # Creating a project that already exists fails harmlessly.
    subprocess.run(["npx", "--yes", "wrangler", "pages", "project", "create", project,
                    "--production-branch", "main"], env=env, capture_output=True, text=True, timeout=180)
    r = subprocess.run(["npx", "--yes", "wrangler", "pages", "deploy", str(out),
                        "--project-name", project, "--branch", "main", "--commit-dirty=true"],
                       env=env, capture_output=True, text=True, timeout=600)
    output = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(output.strip()[-800:] or "wrangler failed")
    return output


def publish(league: dict | None = None) -> str:
    """Mark `league` published (if given), rebuild every league's published
    weeks, and deploy. Returns wrangler's output."""
    if league is not None:
        mark_published(league)
    build_site()
    return deploy()


# --- local preview ------------------------------------------------------------

_server = None


def serve_preview(port: int = PREVIEW_PORT) -> str:
    """Build every league with all written weeks into site_preview/ and serve
    it on localhost. Returns the base URL. Safe to call repeatedly: the
    server starts once and later builds overwrite the files it serves."""
    global _server
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    build_site(PREVIEW_DIR, preview=True)
    if _server is None:
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        handler = functools.partial(Quiet, directory=str(PREVIEW_DIR))
        try:
            _server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            # Already being served (an earlier app session); the files are fresh.
            return f"http://127.0.0.1:{port}"
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"
