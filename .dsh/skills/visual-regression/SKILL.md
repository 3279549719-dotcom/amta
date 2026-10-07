---
name: visual-regression
description: Compare source and before/after page regions when OCR, translation, inpaint, or typeset changes could affect the final image. Use before claiming a visual or text-quality fix succeeded.
---

# Visual Regression

For a visual or text-quality fix, identify the affected page and region first.
Compare the source, the relevant intermediate text/artifact, and the rendered
result. A whole-page impression cannot verify a small bubble.

## 1. Generate the review report

```powershell
uv run python scripts/gen_report.py --work-id <work> --src-dir <dir> --pages <page>
```

This produces a side-by-side report (source vs rendered) in the workspace.
Open the affected page and region.

## 2. Look at the specific pages you changed

Inspect the exact affected crop in the report or image viewer. Ask specific
questions, not "is this good?":

- Are any bubbles still showing original Japanese text?
- Is any translation text overflowing its bubble?
- Are there black boxes or artifact remnants from inpaint?
- Is text vertically centered within its bubble?
- Are column-end commas (vertical layout) eliminated?

## 3. Compare before/after

If you have a previous render to compare (backup directory or previous work-id),
inspect the same region in both versions and describe the difference. Look for
new overflow, missed bubbles, or inpaint artifacts.

## 4. Decision gate

You may only claim "fixed" when ALL of these are true:

- [ ] Relevant regression tests and project checks pass
- [ ] The affected page's intermediate artifact has the expected content
- [ ] The source, intermediate artifact, and before/after crop support the
  specific claim; a single image-tool judgment is not sufficient
- [ ] No new symptom appeared in the inspected before/after regions

If any box is unchecked, you are not done. Go back and fix it.
