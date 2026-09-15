# 🏈 Fantasy Football Power Rankings

A small, local-first app that turns a handful of ESPN fantasy football screenshots into a
funny, specific, factually-defensible weekly power rankings post — in about 5 minutes per league.

**On tone:** the generated output is deliberately crude. This writes trash talk for a private
league group chat and the prompt is tuned for exactly that — it's the intended behavior, not a
defect. Every claim is still grounded in real data; the factual rules in `src/prompts.py` are
strict about it. If you need something publishable, this isn't the tool.

No auth, no cloud, no database server — Streamlit plus JSON files on your machine. Requires
Python 3.10+ and an Anthropic API key.

## Setup (one-time)

```bash
cd fantasy-football-power-rankings
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
# (get a key at https://console.anthropic.com/settings/keys)
```

## Running it every week

```bash
source .venv/bin/activate
streamlit run app.py
```

This opens the app at `http://localhost:8501`.

Weekly workflow, per league:

1. **Select the league** in the sidebar (or create it, the first time).
2. **Upload screenshots** — the scoreboard (matchups, scores, projections) and the standings
   table. Standings columns often span two screenshots on a phone; upload both and they get
   merged. More screenshots is generally better, and none are strictly required.
3. Set the **Week** number (it defaults to "last week + 1").
4. Optionally type 1–3 sentences of **context** — trades, trash talk, injuries, a bad benching.
   This is the highest-value input you can give it, because these are the events the screenshots
   can't show. It's also stored as narrative history for future callbacks.
5. Click **🔍 Extract Data From Screenshots**. Claude reads the images and pulls out team names,
   records, streaks, PF/PA, playoff odds, divisions, scores and ESPN's projected scores.
6. **Check the reconciliation banner.** Green means every number was verified against last week
   (see below) and you can move straight on. Red names the specific cell that doesn't add up.
   The full editable table is still there, collapsed, if you want it.
7. Click **🔥 GENERATE POWER RANKINGS**. This computes the power scores, finds the best
   comedic angle for each team, writes the commentary around those angles, then runs a
   second editorial pass to cut generic filler and tighten jokes (four API calls total: one
   to read the screenshots, three for the narrative pipeline below).
8. Read it. If one team's writeup missed, expand **🔄 Regenerate** under that team, optionally
   type what should change, and it rewrites just that one line (one API call, not a full redo —
   everything else on the page stays exactly as-is).
9. Copy it (there's a code block with a built-in copy button, formatted as plain text for
   iMessage/group chats — no markdown symbols) or hit **Download TXT**, paste into your group chat.

Repeat for each of your leagues — the app remembers each league's full history independently.

Use the **History** tab to pull up any previous week's rankings, and the sidebar's
**League Notes** / **Log an Event** panels to keep persistent context (rivalries, running
jokes, trades) that future weeks' commentary can draw on.

## How it avoids getting facts wrong

A savage, specific writeup built on a misread score is the worst possible output, so extracted
numbers get **proven rather than eyeballed**. The two screenshot types overlap, and that
redundancy allows arithmetic verification:

- season PF must rise by exactly this week's score, and PA by the opponent's
- the record must advance by one game, on the correct side
- the streak must follow from this week's result (was `W4`, won → must read `W5`)

These are week-over-week deltas, so they work even when you start uploading mid-season and the
app has never seen weeks 1–8. Everything reconciling gets you one green line; anything that
doesn't names the exact team and field. Week 1 of a season has nothing to compare against, so
that one upload is worth a manual look.

## What the writeups are built from

`src/occurrences.py` detects things that actually *happened* — blowouts, nail-biters, streaks,
scoring the most points in the league and still losing, big misses against ESPN's projection,
rank swings, playoff-odds collapses — and hands those to the writer instead of season averages.

A team that did nothing gets an explicit *nothing notable* marker, and that silence is the point:
it's what produces a one-line dismissal instead of a paragraph manufactured out of rate stats.
Length follows material, which is why a real column comes out uneven the way a human-written one
is.

## How the ranking works

Power score is a transparent, weighted blend, not just standings:

| Component | Weight | What it measures |
|---|---|---|
| Season performance | 25% | Win/loss record |
| Points scored | 20% | Points-per-game |
| Recent form | 20% | Last up to 3 weeks (win rate + margin) |
| Roster strength | 15%* | Not scored — see note below |
| Consistency | 10% | Inverse of week-to-week score variance |
| Schedule context | 10% | Average opponent win% faced |

\* Screenshots expose team-level projections, not per-player points, so there's no honest way to
compute a roster-strength score — and the app is built to never invent one. That weight is
redistributed across the other components until a real data source (e.g. an ESPN API integration)
can supply it.

Components that can't be computed yet (consistency needs two weeks, schedule context needs
played games) drop out the same way, so week 1 still produces a valid ranking from a narrower
blend, flagged at `confidence: low`.

**The power score is a sorting mechanism, not content.** It orders the column and nothing else —
the writer is explicitly forbidden from naming it, citing it, or narrating rank positions. Real
power-rankings columns don't talk about their own internal metric, and neither does this one.

The writeups are grouped into tiers with a deliberately stable skeleton — roughly *good /
frauds / mid / embarrassments* — where the tier names stay recognizable week to week and the
subtitle carries that week's joke. A league recognizes "Fraud Watch" as a recurring institution;
inventing four brand-new tier names every week reads as effort rather than voice.

## How the writing works

The narrative pipeline is three LLM calls, run in sequence, not one call trying to do everything:

```
rankings + occurrences   -- what happened, detected deterministically (no LLM)
      ↓
find_comedic_angles      -- "what's the actual joke for each team this week?"
      ↓                     also flags multi-week storylines worth remembering
generate_writeups        -- writes to the angle it was given, at a length set by the material
      ↓
critique_and_revise      -- rewrites anything generic, over-long, or all the same shape
      ↓
final power rankings
```

The angle-finder picks from a taxonomy of comedic premises (trade regret, fraud/inflated record,
collapse, comeback, historical callback, statistical absurdity, etc.) instead of defaulting to
"cite the PPG." It also detects when something happening this week is worth tracking across
future weeks (a trade whose consequences are still unfolding, a prediction that keeps aging
badly) and saves it as a **storyline** — a structured, persistent multi-week narrative stored on
the league (see `memory.get_storylines()`). Future weeks' angle-finding gets handed only the
storylines relevant to each team, instead of every past week's full writeup text.

The prompt is written as **conditions rather than style dials**, which is the main thing keeping
output from reading as formulaic. Length is a function of how much happened; a team with nothing
notable gets a one-line dismissal and a hard 60-word ceiling applies to everything. Techniques
like team-name wordplay are permitted rather than mandated — a rule that says "use X often"
reliably produces X every single week, which is how a voice becomes a tic.

Each generation is measured against the reference corpus and the result is shown in the UI: word
count mean, spread, and any rule violations. Drift is visible the week it happens rather than
months later. See `src/prompts.py` for the full philosophy.

### Feeding it your real style (`reference/`)

Copy `reference/TEMPLATE.md` to `reference/my_columns.md`, paste in your own past columns, then
ask Claude to analyze them and update `src/prompts.py` accordingly. The working copy is
gitignored, so real manager names stay on your machine.

This is a one-time calibration pass, not a runtime lookup — the app never reads the file while
generating, and old wording should never be reused verbatim. See `reference/README.md` for what
makes good calibration material.

## Project layout

```
app.py                  Streamlit UI — the whole weekly workflow
src/
  memory.py              JSON persistence: leagues, weeks, events, storylines, team-name normalization
  data_extraction.py     Screenshot -> structured data (Claude vision, forced tool call)
  data_validation.py     Name normalization, shape checks, and week-over-week reconciliation
  occurrences.py         Deterministic detection of what actually happened this week
  rankings.py            The power-ranking formula
  narratives.py          Angle-finding -> writeup generation -> editorial critique pipeline
  prompts.py             Shared tone/style/critical-rules text, comedy taxonomy
data/leagues/*.json      One file per league — your entire league history lives here (gitignored)
reference/               Your past columns, for a one-time voice calibration pass (see its README)
tests/                   Mock-data tests for ranking math, validation, occurrences, storylines
```

## Running the tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

The suite runs entirely on hand-built fixtures — no screenshots, no API calls, no cost. It covers
the ranking maths, name normalization, storyline logic, occurrence detection, and the
reconciliation checks.

## Scope

Deliberately not included: ESPN API integration (screenshots only), multi-user support, cloud
hosting, authentication. Known candidates for later: ESPN sync, a luck index, Monte Carlo playoff
odds, auto-detected trades, Discord publishing.

The clearest current limitation is that screenshots show team-level data, so player-level material
— a bad benching, an injury, a lopsided trade — can only reach the column through the weekly
context box. That's usually where the sharpest lines come from, so it's worth the fifteen seconds
of typing.
