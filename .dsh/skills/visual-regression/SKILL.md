---
name: visual-regression
description: Compare before/after rendered pages to detect visual regressions. Use after changing inpaint, typeset, or translation rendering — before claiming a fix "looks better".
---

# Visual Regression

When you change rendering code (inpaint mask, typeset layout, bubble text
placement), you must prove the output actually improved. "I think it looks
better" is not evidence.

## 1. Generate the review report

```powershell
uv run python scripts/gen_report.py --work-id <work> --src-dir <dir> --pages 1-10
```

This produces a side-by-side report (source vs rendered) in the workspace.
Open it to see every page at a glance.

## 2. Look at the specific pages you changed

Use `modlens_read_image` to inspect individual rendered pages. Ask specific
questions, not "is this good?":

- Are any bubbles still showing original Japanese text?
- Is any translation text overflowing its bubble?
- Are there black boxes or artifact remnants from inpaint?
- Is text vertically centered within its bubble?
- Are column-end commas (vertical layout) eliminated?

## 3. Compare before/after

If you have a previous render to compare (git stash, backup directory, or
a previous work-id), use `modlens_read_image` on both versions of the same
page and describe the difference. A regression is a page that got worse —
new overflow, new missed bubbles, new inpaint artifacts.

## 4. Decision gate

You may only claim "fixed" when ALL of these are true:

- [ ] `uv run python -m pytest -q` exits 0
- [ ] The probe on the affected page produces the expected intermediate output
- [ ] `modlens_read_image` on the rendered page confirms the specific symptom
  you set out to fix is gone
- [ ] No NEW symptoms appeared on pages adjacent to your change

If any box is unchecked, you are not done. Go back and fix it.
