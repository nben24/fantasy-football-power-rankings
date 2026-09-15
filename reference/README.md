# reference/

Calibration material — your own past power-rankings columns, used to tune the app's voice to
sound like *you* rather than like a generic AI roast.

## Files

| file | tracked by git? | what it's for |
|---|---|---|
| `comedy_examples.example.md` | yes | Template. Copy it, don't edit it. |
| `comedy_examples.md` | **no — gitignored** | Your real columns. Contains real names, stays local. |

```bash
cp reference/comedy_examples.example.md reference/comedy_examples.md
# paste your columns in, then ask Claude to recalibrate src/prompts.py
```

## This is not read at runtime

The running app never opens these files. Calibration is a **one-time pass**: you paste columns in,
then ask Claude to analyze them and update `src/prompts.py`. Two reasons it works this way —
sending them on every generation would cost tokens for no benefit once the lessons are baked into
the prompt, and it would tempt the model into reusing old punchlines verbatim instead of writing
new ones.

## What actually makes this useful

From calibrating against ~250 real writeups, the things that mattered most:

- **Quantity beats polish.** 10+ columns across several weeks tells you far more than 2 great ones.
- **Spread across the season.** Early-season columns are short (one-liners, nothing has happened
  yet); late-season ones are longer because arcs have accumulated. Without early weeks you'll
  calibrate to a length that's wrong for most of the year.
- **Consecutive weeks from one league** reveal how callbacks and running jokes evolve — the single
  hardest thing to infer from isolated columns.
- **Columns where a real event drove the writing** (a trade, a bad benching) show how much prose
  you give an actual occurrence versus a routine week.

One honest caveat: if your best lines came from manual re-prompting and revision rather than
one-shot generation, say so during calibration. Otherwise the prompt gets tuned toward an output
quality that isn't reachable without you in the loop every week.
