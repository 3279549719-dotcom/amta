# Migration inventory and backup plan

**Goal:** Preserve the current workbench code and non-secret runtime assets on GitHub, with a verifiable property list, while excluding user artwork and processing outputs. Investigate historical performance and Apple silicon portability without claiming an untested migration works.

**Approach:** Keep the current checkout and its five pre-existing code edits intact. Save this state on a dedicated snapshot branch. Store dependency declarations, configuration templates and inventories in Git; store model/runtime archives as release assets with SHA-256 manifests. Do not publish API secrets or machine-specific environment directories.

- [x] Inventory tracked source, local/external model directories, dependency versions, configuration names, fonts and external applications.
- [x] Package runtime assets, excluding caches and user inputs/outputs; compute per-file and archive hashes and validate archive contents.
- [x] Write configuration template and restoration instructions, explicitly recording Windows path and Apple MPS/Photoshop portability gaps.
- [x] Retrieve historical stage timings and investigate PSD export using timed probes if Photoshop is available; distinguish observations from hypotheses.
- [x] Review the snapshot for secrets and unwanted inputs/outputs and run the repository completion gate. Preserve the authorized existing work through the explicit archival exception recorded in `docs/migration/VALIDATION.md` (656 tests passed; existing type/memory checks remain red).
- [x] Push the snapshot branch, upload release assets, and verify the remote commit and asset checksums. All ten uploaded files (eight archives plus two manifests) match GitHub server SHA-256 and byte sizes; see `docs/migration/upload-verification.json`.

No model-quality upgrade or macOS port is part of this backup task. The migration snapshot must not be described as a ready-to-run macOS package.
