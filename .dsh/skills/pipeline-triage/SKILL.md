---
name: pipeline-triage
description: Diagnose pipeline runs that fail, process zero pages, or produce suspicious OCR/translation/rendered output even when the exit code is 0. Use when a stage errors or the user reports a bad result.
---

# Pipeline Triage

The pipeline is `detect → ocr → translate → inpaint → typeset`. Diagnose from the
run summary, quality flags, and affected artifacts; `failed: 0` alone is not proof
that pages were processed or that their contents are correct.

## 1. Find where it broke

First check `pages`, `failed`, and the quality flags. Locate the affected page's
artifacts with `scripts/artifact.py query --work-id <work>`. Compare the earliest
incorrect artifact with its input before choosing a stage to rerun. If there is
a traceback, find the first frame in project code.

```powershell
uv run python scripts/run_pipeline.py --work-id <work> --src-dir <dir> `
  --start-page <page> --end-page <page> --stages detect,ocr
```

This example investigates OCR. For a later stage, extend `--stages` through that
stage, including every upstream dependency. The artifact cache skips unchanged
stages; never pass only a downstream stage to this CLI.

## 2. Classify the failure

| Signal | Likely cause | First thing to check |
|--------|-------------|---------------------|
| FileNotFoundError / path issues | Workspace layout | `workspace/<work-id>/` structure |
| Model API error (429, 500, auth) | External service | `.env` keys, network, quota |
| Empty OCR / missed bubbles | Detection model | Page image resolution, detector config |
| Garbled translation | LLM prompt or context | Source text quality, prompt template |
| Black boxes in inpaint | CTM mask too small | `ctd-mask` coverage, inpaint model |
| Overflow / overlap in typeset | Text measurement | Bubble dimensions, font size |
| Zero pages, `failed: 0` | Input selection | `--src-dir`, page range, filename mapping |
| Quality flags with `failed: 0` | Content error | The flagged region and preceding stage artifact |

## 3. Check known issues before reinventing

Read `docs/lessons.md` — it accumulates past failures and their root causes.
Search for keywords from the error message. If a past lesson matches, follow it
instead of re-deriving the fix.

## 4. Isolate with a probe

When the cause is unclear, use an existing focused test or one-page probe to
inspect the earliest incorrect intermediate artifact. Add a probe only if the
existing artifacts cannot answer the question. Keep `run_pipeline.py` as the
production entry point.

## 5. Verify the fix

After changing code:
1. Run the relevant regression test and project checks.
2. Recheck the original page and region; confirm a page was processed, the
   expected artifact exists, and the reported symptom is gone.
3. If the output is visual, compare the affected region before and after with
   visual-regression.
