# ADR: Migrate to DSH-Native Manga Translator Agent

**Date:** 2026-09-29
**Branch:** `feat/dsh-native-agent-init`
**Status:** Accepted

## Context

The previous architecture wrapped DSH headless CLI in a Python outer loop
(`src/amta/agent_loop/runner.py`) that managed a state machine:
`queued → running → verifying → ready_for_review → accepted`. The outer loop
controlled budget, evidence fingerprints, and independent pytest verification.

The user's core critique was correct: **this was just a high-end headless SDK
wrapper**. The intelligence lived entirely inside DSH; the outer loop merely
automated "human says continue." It was not an autonomous agent — it was a
fixed pipeline that called an AI worker.

## Decision

Replace the custom outer runner with DSH's native agent loop primitives.
Follow **The Bitter Lesson**: give the model general tools and general rules,
let it decide workflow, stop conditions, and verification itself.

### What we kept

| Component | Source | Why |
|-----------|--------|-----|
| Main model | DeepSeek v4-flash | Cheap, fast, already configured |
| Vision backend | Qwen 3.5 omni-plus (DashScope) | Already configured via `describe-image` |
| Vision bridge | ModLens plugin (already installed) | Text model calls `modlens_read_image`, Qwen describes the image |
| Skills | `.dsh/skills/` (6 existing + 2 new) | Progressive disclosure: catalog auto-injected, body on-demand |
| Long-term memory | dsh-memory plugin | Auto-extracts and injects lessons across sessions |
| Code navigation | LSP (pyright-langserver) | goToDefinition / findReferences / hover without grep |
| Session search | session-query-sqlite (persistent) | Full-text search across past sessions |
| Persona | system-prompt.persona | One-line identity: manga translation engineer |

### What we removed

| Component | Replacement |
|-----------|-------------|
| `runner.py` state machine | DSH native `goal` + `goal-round-driver` + `tool-ralph` |
| Custom budget control | DSH native round limits and timeouts |
| Custom evidence fingerprinting | Agent runs pytest itself; visual-regression SKILL.md enforces proof |
| Independent supervisor verification | Deferred: SKILL.md completion criteria first; add PostToolUse hook only if model skips checks |

### What we explicitly did NOT add

- **MCP Server** — Shell tool running Python CLI is enough for now
- **External scheduler** — No cron use case; Windows Task Scheduler if needed later
- **LSP for other languages** — Python only (pyright)
- **Hooks / guards** — Trust the model first; add only after observing a real failure
- **Custom UI** — Use DSH's built-in web UI (localhost)

## New skills added

1. **`pipeline-triage`** — When a stage fails, classify the error, check
   lessons.md, isolate with a probe, verify the fix.
2. **`visual-regression`** — After rendering changes, generate the report,
   inspect specific pages with ModLens, compare before/after, and only declare
   "fixed" when pytest passes AND visual evidence confirms the symptom is gone.

## Configuration changes

### Headless profile (`~/.dsh/profiles/headless/`)

- `cordis.patch.yml`: persona, session-query-sqlite (persistent), LSP stdio (pyright)
- `package.json`: added `@deepseek-ai/dsh-lsp`, `dsh-lsp-stdio`, `dsh-tool-lsp`, `dsh-memory`

### Web profile (`~/.dsh/profiles/web/`)

- `cordis.patch.yml`: removed `modlens disabled: true` — vision now active

## Architecture diagram

```mermaid
graph TD
    U[User / CLI] --> AGENT[DSH Agent<br/>DeepSeek v4-flash]

    subgraph Native Tools
        PWSH[PowerShell tool]
        FS[File system]
        SEARCH[Grep / search]
        SKILL[Skill loader]
        LSP[LSP: pyright]
        RALPH[Ralph iteration]
        GOAL[Goal driver]
    end

    subgraph Plugins
        MEM[dsh-memory<br/>long-term lessons]
        ML[ModLens<br/>vision bridge]
        SESS[Session SQLite<br/>cross-session search]
    end

    subgraph Domain Skills
        TRIAGE[pipeline-triage]
        REGRESS[visual-regression]
        LESSONS[lessons.md<br/>56 human-curated]
    end

    subgraph Pipeline
        DETECT[detect] --> OCR[ocr]
        OCR --> TRANS[translate]
        TRANS --> INPAINT[inpaint]
        INPAINT --> TYPE[typeset]
    end

    AGENT --> PWSH
    AGENT --> FS
    AGENT --> SEARCH
    AGENT --> SKILL
    AGENT --> LSP
    AGENT --> RALPH
    AGENT --> GOAL
    AGENT --> MEM
    AGENT --> ML
    AGENT --> SESS

    SKILL --> TRIAGE
    SKILL --> REGRESS
    SKILL --> LESSONS

    PWSH -.runs.-> DETECT
    ML -.describes.-> TYPE
```

## Open questions / deferred

- If the model repeatedly skips verification, add a `PostToolUse` hook on pytest.
- If code navigation becomes a bottleneck beyond LSP, consider TS/JS LSP later.
- If visual inspection needs are more complex, evaluate a vision subagent (fork with Qwen).

## Runtime upgrade: 0.1.0-rc.7 → 0.2.0-rc.2 (2026-09-30)

- **Runtime**: exact tag `0.2.0-rc.2` (commit `639ed015`), checked out at
  `E:\deepseek harness\deepseek-harness-v0.2.0-rc.2\`; launcher `F:\npm-global\dsh.cmd`
  now points at its built `apps\cli\lib\bin.js`. The old checkout
  `E:\deepseek harness\deepseek-harness\` @ `99f6f02f` (0.1.0-rc.7) is kept untouched as
  the rollback boundary.
- **Profile pins (headless + web)**: `@liustack/modlens` pinned `3.26.5`; the three LSP
  packages (`dsh-lsp`, `dsh-lsp-stdio`, `dsh-tool-lsp`) pinned to exact `0.2.0-rc.2`
  `file:` tgz vendored under `~/.dsh/vendor-lsp/` (NOT Temp). Web-only plugins bumped to
  the tested set: agent-teams `0.1.22`, dsh-context `0.60.0`, dshmarket `1.66.6`,
  dsh-pocket `2.10.6`.
- **dsh-memory removed**: it was never verified as active; it is no longer declared in
  either profile's `package.json` or bundle list. Long-term memory is currently the
  human-curated `docs/lessons.md` only.
- **Credentials**: `~/.dsh/.credentials.yaml` was rewritten to the v1 `refs:` schema,
  UTF-8 **without BOM**. The old flat file carried a BOM (`EF BB BF`) that the 0.2.0
  local-credentials migrator turned into a garbage key (`MISSING_CREDENTIAL`). If a future
  restore re-introduces the BOM, re-run the v1 rewrite.
- **Verified in isolation before promotion**: goal create → write/read tools → get_goal →
  `update_goal complete` with zero approval; AMTA cwd reads `AGENTS.md` and runs
  `uv run python scripts/peek.py`; a v3-era session resumes onto turn 3 with no migration
  error; production `dsh --version` = `0.2.0-rc.2` and a headless smoke task returns OK.
- **Known limitation**: one-shot `--profile headless` answers the human turn and exits
  before the `goal-round-driver`'s async follow-up can start the next round (Windows
  microtask race with the needsCheckpoint flush). Multi-round unattended closure is a
  long-lived-process feature; run it inside the web profile (localhost server), not the
  one-shot CLI.
- **Known incompatibility**: `@omdsh-dev/dsh-genui` (pinned from GitHub latest, now
  0.8.7) declares peer deps on `^0.1.0-rc.8` and is skipped by the 0.2.0 loader. The web
  UI still boots; generative-UI cards are off until a genui release targets 0.2.0.
- **Rollback**: restore `F:\npm-global\dsh.cmd` from
  `%LOCALAPPDATA%\AMTA\dsh-upgrade-backups\20260930-002406\dsh.cmd` (points back to the
  old checkout); restore `~/.dsh` from that backup dir if the profile/certs need to go too.
