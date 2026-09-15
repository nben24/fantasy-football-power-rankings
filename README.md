# 🏈 Fantasy Football Power Rankings

A small, local-first app that turns a handful of ESPN fantasy football screenshots into a
funny, specific, factually-defensible weekly power rankings post — in about 5 minutes per league.

**Heads up on tone:** this is a trash-talk generator for a private fantasy football league group
chat. The writing style is deliberately crude, unhinged, and disrespectful by design (see
`src/prompts.py`) — that's the intended output, not a bug. Every claim is still grounded in real
stats/events (see the factual rules in that same file), just delivered with zero manners.

No auth, no cloud, no database server. Just Streamlit + JSON files on your machine.

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
2. **Upload screenshots** — standings, matchups, points, rosters. Upload whatever you have,
   there's no fixed set required.
3. Set the **Week** number (it defaults to "last week + 1").
4. Optionally type 1–3 sentences of **context** — trades, shit talk, injuries, whatever
   happened. This gets stored as narrative history for future callbacks.
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
| Roster strength | 15%* | Not scored in the MVP — see note below |
| Consistency | 10% | Inverse of week-to-week score variance |
| Schedule context | 10% | Average opponent win% faced |

\* Screenshots give player names, not points/projections, so there's no real number to compute
a roster-strength score from — and the app is built to never invent one. That weight is
automatically redistributed across the other components until a real data source (e.g. an
ESPN API integration) can supply it.

Every ranked team carries `key_factors` — short, number-backed strings — plus a
`record_vs_power` signal (`fraud_watch` / `underrated` / `aligned`) comparing its record-implied
rank to its actual power rank. That signal, and the full component breakdown, gets handed to the
writer so jokes are grounded in real data instead of vibes.

The writeups aren't a flat list — each week the writer invents its own tiers (e.g. "Fraud Watch,"
"The Mid-Card Bloodbath") based on how that week's power scores actually cluster, plus a headline
tying the week together. Tier count and names change week to week; there's no fixed template.

## How the writing works

The narrative pipeline is three LLM calls, run in sequence, not one call trying to do everything:

```
rankings (numbers)
      ↓
find_comedic_angles   -- "what's the actual joke for each team this week?"
      ↓                  also flags multi-week storylines worth remembering
generate_writeups      -- writes to the angle it was given, not to a stat by default
      ↓
critique_and_revise    -- rewrites anything generic, unearned, or all the same shape
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

Style rules (second person, direct commands, crude/absurd delivery, technique variety) are
options the writer reaches for when they make a specific joke land harder — not quotas it has to
hit. See `src/prompts.py` for the full philosophy.

### Feeding it your real style (`reference/`)

Copy `reference/comedy_examples.example.md` to `reference/comedy_examples.md`, paste in your own
past columns, then ask Claude to analyze them and update `src/prompts.py` accordingly. The working
copy is gitignored, so real manager names stay on your machine.

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
python -m pytest tests/ -v
```

## What this intentionally does NOT do (yet)

No ESPN API integration (screenshots only), no multi-user support, no cloud hosting, no
authentication. See the top-level product spec for the list of deliberately-deferred features
(ESPN sync, luck index, Monte Carlo playoff odds, auto-detected trades, Discord publishing).
The code is structured so those can be layered on later without a rewrite.
