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
cd fantasy_football_powr_rankings_august_2026
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
5. Click **🔍 Extract Data From Screenshots**. Claude reads the images and fills in a table.
6. **Review the extracted table** — fix anything wrong (OCR mistakes, missing scores). Any
   flagged issues show up as warnings above the table.
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

`reference/2025_power_rankings.md` and `reference/comedy_examples.md` are a workspace for
calibrating the voice against your actual past columns — paste in real examples, then ask Claude
to analyze them and update `src/prompts.py` accordingly. These files aren't read by the running
app; the calibration is a one-time pass that bakes distilled lessons into the prompt, not a
runtime lookup, and old wording should never get reused verbatim.

## Project layout

```
app.py                  Streamlit UI — the whole weekly workflow
src/
  memory.py              JSON persistence: leagues, weeks, events, storylines, team-name normalization
  data_extraction.py     Screenshot -> structured data (Claude vision, forced tool call)
  data_validation.py     Duplicate/missing-data checks, name normalization
  rankings.py            The power-ranking formula
  narratives.py          Angle-finding -> writeup generation -> editorial critique pipeline
  prompts.py             Shared tone/style/critical-rules text, comedy taxonomy
data/leagues/*.json      One file per league — your entire league history lives here
reference/               Workspace for calibrating style against your real past rankings
tests/                   Mock-data tests for the ranking math, validation, and storyline logic
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
