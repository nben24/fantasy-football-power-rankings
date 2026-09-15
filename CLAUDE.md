# CLAUDE.md

Guidance for Claude Code working in this repo. The README covers *how to use* the app; this
covers *how to work on it* and — more importantly — the decisions that look arbitrary but aren't.

## Commands

```bash
source .venv/bin/activate
streamlit run app.py                      # the app, at localhost:8501
pip install -r requirements-dev.txt       # pytest isn't in the runtime requirements
python -m pytest tests/ -q                # fast, no API calls, no cost
```

**Restart Streamlit after editing anything under `src/`.** A browser refresh re-executes
`app.py` but does not reliably re-import already-loaded submodules, which surfaces as
`AttributeError: module 'src.x' has no attribute 'y'` for a function that plainly exists.

## What this app is optimizing for

The user runs **four leagues** and needs a paste-ready column in **2–5 minutes each**. That
constraint drives most design decisions:

- **Zero user context is the normal case**, not the degraded one. Most weeks nobody types
  anything into the context box, and the output still has to be good.
- **Regeneration should be rare.** If the user is re-rolling several writeups per league, the
  feature has failed on its own terms, regardless of how good the final text is.
- **A wrong fact is the worst possible output.** A savage, specific, confidently-wrong writeup
  goes straight into a group chat. Accuracy beats humor every time.

## The central design decision

Early versions handed the writer season aggregates (PPG, win%, strength of schedule) and asked it
to find a story. It manufactured statistical ones — 75-word writeups citing power scores and
decimal PPG about teams that had a completely routine week.

`src/occurrences.py` now detects things that actually *happened* and hands those over instead.
**A team with nothing notable gets an explicit empty marker, and that silence is load-bearing** —
it's what produces a one-line dismissal rather than a paragraph manufactured out of rate stats.

Length is therefore a function of material, not a style dial. Verified on real generations: teams
with zero occurrences land at 15–20 words, teams with four or five at 35–45.

## Rules that will look arbitrary later

Each of these was learned from a real failure. Please don't quietly revert them.

1. **Fix the payload, not the prompt.** The model follows the *shape of the data it is handed*
   far more reliably than instructions about that data. Four lines saying "you don't have to cite
   stats" never once beat twelve teams' worth of numbers labelled "key facts." When output drifts,
   change what goes into `build_facts_bundle`, not the wording of `prompts.py`.

2. **Permissions, never quotas.** Telling the model to use a technique produces it every single
   week, which is exactly how a voice becomes a tic. The fix for an under-used device is to
   *remove the prohibition* on it, not add a mandate. Corollary: never write frequency targets
   ("use X in ~20% of writeups") into the prompt.

3. **No quotable example lines in `prompts.py`.** An earlier version included illustrative lines
   about the Hague and forfeiting an ESPN login; the model reproduced both near-verbatim in
   shipped output. Describe technique abstractly instead.

4. **The power score is a sorting mechanism, not content.** It orders the column and nothing else.
   The writer is forbidden from naming it, citing it, or narrating rank positions. Real columns
   don't discuss their own internal metric.

5. **Stats live in the export header, not the prose.** Record, streak and PF/PA are printed above
   each writeup, so restating them in the text is pure duplication.

6. **Never claim a season high/low without full-season history.** The app usually starts
   mid-season, so a maximum across three stored weeks is not a season high — asserting one is a
   fabricated fact, and this shipped once before it was caught. `occurrences.py` requires six
   weeks of history plus a real margin over the previous mark, and phrases partial history as
   "in N weeks."

7. **Tier names stay stable, subtitles rotate.** A recurring "Fraud Watch" reads as a league
   institution; four brand-new tier names every week reads as effort. Verified to persist across
   consecutive real weeks.

8. **Enforce in code what the prompt can't hold.** Precedent: `_normalize_tiers`,
   `cap_fraud_lens_angles`, `profile_writeups`. Prefer a deterministic guard over another
   paragraph of instructions — but only after observing the failure, not preemptively.

## Accuracy: reconciliation

`data_validation.reconcile_week` proves extracted numbers against the previous week rather than
asking the user to proofread a table: season PF must rise by exactly this week's score, PA by the
opponent's, records advance on the correct side, streaks follow from the result.

These are **week-over-week deltas, not season sums**, specifically so they work when a league
starts uploading mid-season and the app has never seen weeks 1–8. Week 1 of a season has nothing
to compare against and correctly reports all-skip.

## Voice calibration

`reference/my_columns.md` (gitignored) holds the user's real past columns. Empirical targets
measured from ~250 of them:

| metric | target |
|---|---|
| mean words | ~29 |
| coefficient of variation | ~0.32 |
| mentions of power score / schedule strength | 0 |
| numbers per writeup | ~1, whole not decimal |

`narratives.profile_writeups` measures every generation against this and surfaces it in the UI.
If a week drifts toward 60+ word averages, that's the signal to investigate — and per rule 1, look
at the facts bundle first.

Note the corpus is **post-iteration output**: the sharpest player-level lines came from manual
re-prompting, not one-shot generation. Treat it as the source for *voice and structure*, never as
a target for event specificity the app cannot reach without user input.

## Privacy

This repo is **public**. `data/` (real manager names) and `reference/my_columns.md` are
gitignored and must stay that way. Before committing, check `git status` after any broad `git add`
and never add example output containing real league or manager names to tracked files.
