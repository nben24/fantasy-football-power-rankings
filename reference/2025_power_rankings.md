# 2025 Power Rankings — Reference Material

Paste your actual power rankings columns from last season into this file (or split them across
multiple `.md` files in this directory, one per week — either works).

**This file is not read by the running app.** It's a workspace for a one-time calibration pass:
once you've pasted in real content, ask Claude to analyze it and update `src/prompts.py` with
whatever it learns. That's a deliberate choice, not an oversight — the app pulling this file into
every single generation would (a) cost extra tokens on every run for no clear benefit once the
lessons are already baked into the prompt, and (b) risk the model leaning on old wording instead
of writing fresh material. See `comedy_examples.md` for the analysis format.

## How to use this

1. Paste in as many weeks as you have — more examples make for a better calibration pass.
2. Tell Claude something like: "analyze reference/2025_power_rankings.md and update the prompts
   to match this style better."
3. Claude should extract patterns (structure, joke construction, tone, length, callback usage) —
   not copy sentences. The critical rule from `src/prompts.py` stands: never reuse old
   punchlines or wording verbatim, only the underlying technique.
