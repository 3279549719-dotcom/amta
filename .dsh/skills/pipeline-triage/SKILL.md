---
name: pipeline-triage
description: Diagnose pipeline failures when detect/ocr/translate/inpaint/typeset errors out. Use when a stage throws, produces garbage, or the user says "pipeline broke"/"fix this error".
---

# Pipeline Triage

The pipeline is `detect → ocr → translate → inpaint → typeset`. When a stage fails,
triage in this order — don't guess, read the actual error.

## 1. Find where it broke

Run the pipeline resume command from the last successful stage. Read the traceback
top to bottom — the root cause is usually in the first line that names your code,
not the last frame.

```powershell
uv run python scripts/run_pipeline.py --work-id <work> --src-dir <dir> `
  --start-page <page> --end-page <page> --stages <failed-stage>
```

## 2. Classify the failure

| Signal | Likely cause | First thing to check |
|--------|-------------|---------------------|
| FileNotFoundError / path issues | Workspace layout | `workspace/<work-id>/` structure |
| Model API error (429, 500, auth) | External service | `.env` keys, network, quota |
| Empty OCR / missed bubbles | Detection model | Page image resolution, detector config |
| Garbled translation | LLM prompt or context | Source text quality, prompt template |
| Black boxes in inpaint | CTM mask too small | `ctd-mask` coverage, inpaint model |
| Overflow / overlap in typeset | Text measurement | Bubble dimensions, font size |

## 3. Check known issues before reinventing

Read `docs/lessons.md` — it accumulates past failures and their root causes.
Search for keywords from the error message. If a past lesson matches, follow it
instead of re-deriving the fix.

## 4. Isolate with a probe

Don't re-run the whole pipeline to test a fix. Write or use a one-page probe
under `scripts/probes/`:

```powershell
uv run python scripts/probes/<your_probe>.py --page <n>
```

The probe should run just the broken stage on one page and print the intermediate
artifact (raw OCR, translation JSON, mask overlay).

## 5. Verify the fix

After changing code:
1. Run `uv run python -m pytest -q` — all tests must pass
2. Re-run the probe on the same page — failure must be gone
3. Run `uv run python scripts/artifact.py query --work-id <work>` — confirm
   the expected output file exists and is non-empty
4. If the fix touches rendering, run visual-regression before declaring done
