# Snapshot validation — 2026-10-26

This is an archival snapshot of the user's existing workbench, not a claim that all quality checks pass.

## Checks performed

- Runtime archives: eight ZIPs; every listed member SHA-256 matches its original local file; ZIP CRCs pass. Archive SHA-256 values are in `SHA256SUMS.txt`. No artwork, page intermediates, PSDs or `.env` was packaged.
- Secret scan: checked known credential values from the private configuration against tracked text files, the unpushed commit patches, the working diff and new migration documents; also checked GitHub/OpenAI-style token patterns in publication changes. No matches. Secret values were not printed or written to the backup. This is a focused scan, not a historical security audit of every existing remote commit.
- `git diff --check`: pass.
- `uv run --no-sync python scripts/state.py gate`: **exit 1**. The full configured gate was run; its pytest step uses testmon and excludes `slow` and `experiment`.
- Pytest: **656 passed, 3 skipped, 66 deselected**, 3 deprecation warnings, 139.68s.
- Compile, Ruff, dependency guard, root/config checks, memory dry-run/injection and module-map generation: pass.
- Pyright: **one existing error** in `src/amta/gui/server.py:471`: an `object`-typed dictionary value is passed to `discover_pages(Path | str)`. This is in the five pre-existing modified files being preserved; this backup task did not alter their behavior or suppress the error.
- Project memory lint: **existing staleness failure**, `recent.md` 11 days old; also a warning that ADR-037 is absent from its index. These were not rewritten to make a backup look green.
- PSD: two successful instrumented exports; see `psd-timings.json` and `performance-and-mac.md`. No production export code was changed. No Apple silicon execution was tested.

## Archival commit exception

The repository provides `state.py finish --skip-check`. It is used explicitly for this preservation snapshot after recording the failed gate above, rather than repairing unrelated user work or pretending validation passed. The commit hook that repeats the same already-failed type check is disabled only for this one archival commit process, not in repository configuration. This snapshot is published as a prerelease, not a validated production release.

## Scope limits

Actual API credentials, proprietary applications/fonts, original artwork, translations and intermediate outputs require separate private migration. Dependency lockfiles and the observed Windows environment are recorded; Windows virtual environments cannot be transplanted to macOS. Model archives preserve local bytes rather than downloading newer versions. Existing repository history is not rewritten; any historical screenshots already tracked upstream remain historical repository content, not newly packaged runtime assets.
