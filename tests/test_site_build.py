import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import memory, site_build


def _week(n, theme, top="Alpha", manager="Real Person"):
    return {
        "teams": [{"name": "Alpha", "manager": manager, "record": f"{n}-0-0", "streak": f"W{n}",
                   "points_for": 100.0 * n, "points_against": 90.0 * n},
                  {"name": "Bravo", "manager": "Another Person", "record": f"0-{n}-0", "streak": f"L{n}",
                   "points_for": 80.0 * n, "points_against": 95.0 * n}],
        "matchups": [{"team_a": "Alpha", "team_b": "Bravo", "score_a": 100.0, "score_b": 80.0}],
        "rankings": [{"name": "Alpha", "manager": manager, "record": f"{n}-0-0", "rank": 1},
                     {"name": "Bravo", "manager": "Another Person", "record": f"0-{n}-0", "rank": 2}],
        "writeups": {"week_theme": theme, "recap": "Alpha won.", "awards": [],
                     "tiers": [{"tier_name": "Top", "tier_subtitle": "(sub)", "team_names": ["Alpha", "Bravo"]}],
                     "team_writeups": [{"name": "Alpha", "narrative": "Alpha line."},
                                       {"name": "Bravo", "narrative": "Bravo line."}]},
    }


def _league(tmp_path, lid="lg1", name="Test League", published=None, weeks=(1, 2)):
    memory.LEAGUES_DIR = tmp_path / "leagues"
    lg = {"id": lid, "name": name, "weeks": {str(w): _week(w, f"Theme {w}") for w in weeks},
          "league_notes": "secret notes", "managers": {"Alpha": "Real Person"}}
    if published:
        lg["site_published_week"] = published
    memory.save_league(lg)
    return lg


def _all_text(out: Path) -> str:
    return "\n".join(p.read_text() for p in out.rglob("*.html"))


def test_only_published_weeks_go_out(tmp_path):
    """The 9am run writes week 2; until it's reviewed and published, it must
    not reach the site, even when another league is being published."""
    lg = _league(tmp_path, published=1)
    out = tmp_path / "out"
    site_build.build_site(out, [lg])
    text = _all_text(out)
    assert "Theme 1" in text and "Theme 2" not in text
    assert not (out / lg["site_slug"] / "week-2").exists()


def test_an_unpublished_league_produces_nothing(tmp_path):
    lg = _league(tmp_path)
    out = tmp_path / "out"
    assert site_build.build_site(out, [lg]) == {}
    assert not lg.get("site_slug")


def test_preview_includes_the_week_about_to_be_published(tmp_path):
    lg = _league(tmp_path, published=1)
    out = tmp_path / "out"
    site_build.build_site(out, [lg], preview=True)
    assert "Theme 2" in _all_text(out)


def test_manager_names_and_notes_never_reach_the_site(tmp_path):
    lg = _league(tmp_path, published=2)
    out = tmp_path / "out"
    site_build.build_site(out, [lg])
    text = _all_text(out)
    assert "Real Person" not in text and "Another Person" not in text
    assert "secret notes" not in text


def test_leagues_do_not_link_to_each_other(tmp_path):
    """One site, but each group chat only gets its own league's link."""
    a = _league(tmp_path, "a", "League A", published=2)
    b = _league(tmp_path, "b", "League B", published=2)
    out = tmp_path / "out"
    site_build.build_site(out, [a, b])
    a_text = "\n".join(p.read_text() for p in (out / a["site_slug"]).rglob("*.html"))
    assert b["site_slug"] not in a_text and "League B" not in a_text
    root = (out / "index.html").read_text()
    assert a["site_slug"] not in root and b["site_slug"] not in root


def test_the_address_is_unlisted_and_stable(tmp_path):
    lg = _league(tmp_path, published=2)
    slug = site_build.ensure_site_slug(lg)
    assert slug.startswith("test-league-") and len(slug) > len("test-league-")
    lg["name"] = "Renamed"
    assert site_build.ensure_site_slug(lg) == slug


def test_search_engines_are_told_to_stay_out(tmp_path):
    lg = _league(tmp_path, published=2)
    out = tmp_path / "out"
    site_build.build_site(out, [lg])
    assert "Disallow: /" in (out / "robots.txt").read_text()
    assert "noindex" in (out / "_headers").read_text()
    assert 'content="noindex' in (out / lg["site_slug"] / "index.html").read_text()


def test_every_page_and_preview_image_is_written(tmp_path):
    lg = _league(tmp_path, published=2)
    out = tmp_path / "out"
    site_build.build_site(out, [lg])
    root = out / lg["site_slug"]
    for rel in ["", "week-1/", "week-2/", "season/", "teams/", "teams/alpha/", "teams/bravo/"]:
        assert (root / rel / "index.html").exists(), rel
    assert (root / "og" / "week-2.png").exists()
    assert 'og:image" content="' in (root / "index.html").read_text()


def test_mark_published_takes_the_latest_written_week(tmp_path):
    lg = _league(tmp_path, weeks=(1, 2, 3))
    assert site_build.mark_published(lg) == 3
    assert memory.load_league("lg1")["site_published_week"] == 3


def test_a_script_tag_inside_a_writeup_cannot_break_the_page(tmp_path):
    lg = _league(tmp_path, published=1)
    lg["weeks"]["1"]["writeups"]["team_writeups"][0]["narrative"] = "nice </script><b>x"
    out = tmp_path / "out"
    site_build.build_site(out, [lg])
    page = (out / lg["site_slug"] / "index.html").read_text()
    assert page.count("</script>") == 2  # the data block and the code block, nothing more
