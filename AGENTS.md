# Repository Guidelines

## Project Structure & Module Organization

AMTA is a session-directed manga translation pipeline. Runtime code lives in `src/amta/`: `stations/` handles detection and OCR, `translation/` handles LLM translation, `inpaint/` and `typeset/` produce pages, and `orchestrator/` coordinates stages. Keep entry points thin in `scripts/`; experiments belong in `scripts/probes/`, and retired scripts in `scripts/archive/`. Tests live in `tests/`, decisions in `docs/decisions/`, reusable lessons in `docs/lessons.md`, and runtime data in ignored `workspace/<work-id>/` directories. Local model weights under `models/` must not be committed.

## Architecture & Primary Workflows

The production flow is `detect -> ocr -> translate -> inpaint -> typeset`. All stages are local except `translate`, which uses the configured LLM API. Use the supported entry points instead of assembling stage scripts manually:

- `uv run python scripts/peek.py` — inspect the live stage registry and dependencies.
- `uv run python scripts/run_pipeline.py --work-id demo --src-dir D:\pages --start-page 1 --end-page 10 --stages detect,ocr,translate,inpaint,typeset` — run or resume a work.
  - Add `--vlm-pages 60,63,67` to route those pages through the VLM paratext engine (OCR does visual transcription + typography observation; typeset uses the formal `src/amta/typeset/vlm_render.py` greedy-wrap renderer). Pages not listed stay on the normal hayai + MITS render path. Routing is decided inside typeset from the canon's `ocr_engine == "vlm-paratext"`.
- `uv run python scripts/artifact.py query --work-id demo` — locate generated artifacts.
- `uv run python scripts/gen_report.py --work-id demo --src-dir D:\pages --pages 1-10` — generate the visual review report.

## Build, Test, and Development Commands

Use `uv run python` for every Python command; the system Python lacks project dependencies.

- `npm run check` — fast compile, lint, type, root, and environment checks.
- `uv run python -m pytest -q` — run the deterministic test suite.
- `npm run finish -- "summary"` — run the full project checks and repository finish workflow.

## Coding Style & Testing

Target Python 3.12, four-space indentation, type hints, and small public interfaces. Ruff and Pyright enforce style and typing. Use `snake_case` for modules/functions, `PascalCase` for classes, and `test_<behavior>` for tests. Add regression tests for every bug fix, especially artifact contracts, stage dependencies, and rendering behavior. Keep fixtures small; never commit full manga pages.

## Commits & Pull Requests

Follow the existing Conventional Commit style: `feat(scope):`, `fix(scope):`, `refactor(scope):`, `docs(scope):`, or `chore(scope):`. Keep commits focused. Pull requests should include purpose, affected stages, verification results, and before/after report screenshots for OCR, inpaint, or typesetting changes. Link the relevant ADR or issue when changing architecture.

## Configuration & Safety

Keep API keys in `.env`; never commit credentials, model weights, source scans, or generated workspaces. Read `CLAUDE.md` for operational guardrails before changing pipeline architecture or release workflows.
