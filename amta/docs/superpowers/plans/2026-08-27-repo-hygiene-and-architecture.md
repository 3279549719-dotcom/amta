# AMTA 仓库卫生 + 架构可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全盘清理 `E:\manga translator agent` 的目录混乱（顶层散落 / research-docs 双份 / reference 混杂源码 / workspace 595 个 ws-* 垃圾），机器化 audit 文档卫生检查，并用 c4 skill 生成 AMTA 第一份 Mermaid 架构图。

**Architecture:** 单一事实源原则（调研产物只留 research/，docs/ 只留指针；reference/ 只留设计文档；workspace/ 空壳定期清理）+ audit 加 3 条机器检查 + c4 skill 产出架构文档。所有清理走 anti-entropy 治理（delete-first 内部退役，持久状态确认）。

**Tech Stack:** PowerShell（文件操作）/ Python（audit 检查）/ c4-codebase-architecture skill（架构图，已装）/ repomix（目录树，已装）。

---

## File Structure

**新建/修改（都在 amta git 仓库内）：**
- `scripts/audit.py` — 加 3 条卫生检查（Modify）
- `tests/test_audit.py` — 卫生检查测试（Create）
- `.dsh/skills/c4-codebase-architecture/SKILL.md` — c4 钉版（已拷入，待提交）
- `docs/architecture/README.md` — C4 架构文档（Create，含 Mermaid）
- `docs/superpowers/plans/2026-08-27-front3-stages-v2.md` — v2 计划归位（Move）
- `docs/progress.md` / `CLAUDE.md` — 收尾更新（Modify）

**纯文件操作（仓库外，不 git 跟踪）：**
- `research/` — 上游素材归档到 `research/koharu-upstream/` 子目录
- `reference/` — 第三方源码 clone 移除/归档
- `workspace/` — 595 个 ws-* 空壳删除
- 顶层散落文件归位

---

## Task 1: workspace/ 595 个 ws-* 空壳清理

**Files:** 无代码，纯清理（workspace/ 已 gitignore）

- [ ] **Step 1: 安全检查——确认 ws-* 都是空壳**

```powershell
cd E:\manga translator agent\amta\workspace
# 统计：只有 state/ 骨架、无 artifacts/ 的目录数
$empties = Get-ChildItem -Directory -Filter "ws-*" | Where-Object { -not (Test-Path "$($_.FullName)\artifacts") }
$empties.Count
```

Expected: 595（或接近，>500 即确认是批量空壳）

- [ ] **Step 2: 保留含产物的 ws-*，删除纯空壳**

```powershell
$empties | Remove-Item -Recurse -Force
# 复核
(Get-ChildItem -Directory -Filter "ws-*").Count
```

Expected: 剩余 ≤ 个位数（有 artifacts 的真实工作区）

> 说明：ws-* 是 `workstate.work_dir()` 每次调用建的 state 骨架，无 artifact 即无价值（derived-state，可重建，delete-first 合规）。

## Task 2: 顶层散落文件归位

**Files:** `E:\manga translator agent\` 顶层

- [ ] **Step 1: v2 计划归位到 docs/superpowers/plans/**

```powershell
Move-Item "E:\manga translator agent\2026-08-27-front3-stages-v2.md" `
  "E:\manga translator agent\amta\docs\superpowers\plans\2026-08-27-front3-stages-v2.md"
```

- [ ] **Step 2: 散落参考文件归档到 reference/**

```powershell
New-Item -ItemType Directory -Path "E:\manga translator agent\reference\misc" -Force
Move-Item "E:\manga translator agent\text-detector fixing.html" "E:\manga translator agent\reference\misc\"
Move-Item "E:\manga translator agent\ChatGPT Image 2026年8月24日 22_53_51.png" "E:\manga translator agent\reference\misc\"
```

- [ ] **Step 3: .env 保持原位**（多 worktree 共享设计，`ROOT.parent/.env` 是 ocr_engines 的读取路径，**不动**）

## Task 3: research/ 与 docs/ 去重（单一事实源）

**Files:** `research/` `amta/docs/`

- [ ] **Step 1: 上游素材归档到子目录**（research/ 根只留自有调研报告）

```powershell
New-Item -ItemType Directory -Path "E:\manga translator agent\research\koharu-upstream" -Force
Get-ChildItem "E:\manga translator agent\research" -File | Where-Object {
  $_.Name -like "docs__*" -or $_.Name -like "v0612__*" -or $_.Name -like "koharu-*" -or
  $_.Name -like "crates__*" -or $_.Name -like "packages__*" -or $_.Name -like "doc-*" -or
  $_.Name -like "preview-*" -or $_.Name -like "chatgpt-*" -or $_.Name -like "*.rs" -or
  $_.Name -like "*.txt" -or $_.Name -like "*.html" -or $_.Name -eq "Cargo.toml"
} | Move-Item -Destination "E:\manga translator agent\research\koharu-upstream\"
```

Expected: research/ 根只留 01-06 详报 + AGENTS.md

- [ ] **Step 2: docs/ 删除与 research/ 完全重复的 01/04，留指针**

```powershell
Remove-Item "E:\manga translator agent\amta\docs\01-调研报告与集成编排方案.md"
Remove-Item "E:\manga translator agent\amta\docs\04-SFX拟声词OCR调研-详报.md"
```

然后在 `docs/README.md` 或 CLAUDE.md 渐进式加载表把引用改指向 `research/`（见 Task 4）。

> ⚠️ 检查引用：CLAUDE.md 渐进式加载表引用了 `docs/01`（架构决策背景）——必须同步改指 research/01。

- [ ] **Step 3: docs/02/03 重命名为 research 新规名并移动**（内容相同，仅文件名不同）

```powershell
Move-Item "E:\manga translator agent\amta\docs\02-本地轮子详报.md" "E:\manga translator agent\research\02-本地轮子-manga-localization-详报.md" -Force
Move-Item "E:\manga translator agent\amta\docs\03-koharu上游详报.md" "E:\manga translator agent\research\03-koharu-上游深度调研-详报.md" -Force
```

> ⚠️ 但先确认 research/02/03 内容与 docs/02/03 相同（之前核对：02/03 docs 独有、research 有近似名——先 diff 再移，避免覆盖新版本）。

## Task 4: CLAUDE.md 引用修正 + research/README 索引

**Files:**
- Modify: `CLAUDE.md`（渐进式加载表）
- Create: `research/README.md`

- [ ] **Step 1: CLAUDE.md 渐进式加载表改指 research/**

把：
```
| 架构决策背景 | `docs/01-调研报告与集成编排方案.md` |
| 可复用轮子资产 | `docs/02-本地轮子详报.md` |
| 上游能力/迁移权衡 | `docs/03-koharu上游详报.md` |
```
改为：
```
| 调研报告（唯一事实源） | `research/README.md`（01-06 详报索引） |
| 架构决策背景 | `research/01-调研报告与集成编排方案.md` |
| 可复用轮子资产 | `research/02-本地轮子-manga-localization-详报.md` |
| 上游能力/迁移权衡 | `research/03-koharu-上游深度调研-详报.md` |
```

- [ ] **Step 2: 建 research/README.md 索引**

列出 01-06 详报 + koharu-upstream 素材子目录说明 + AGENTS.md 约定。

## Task 5: reference/ 整理（只留设计文档）

**Files:** `reference/`

- [ ] **Step 1: 第三方源码 clone 归档到 reference/_vendor/（或删除）**

```powershell
New-Item -ItemType Directory -Path "E:\manga translator agent\reference\_vendor" -Force
@("pdm","pytest","pre-commit","python-package-template") | ForEach-Object {
  Move-Item "E:\manga translator agent\reference\$_" "E:\manga translator agent\reference\_vendor\$_" -Force
}
```

> 说明：这些是调研时拉的第三方源码（pdm/pytest 文档、pre-commit 源码），非项目资产。`_vendor/` 加 README 说明来源与用途，避免误当项目代码。

- [ ] **Step 2: 设计文档目录更名（`suggestion from other model` → 规范名）**

```powershell
Rename-Item "E:\manga translator agent\reference\suggestion from other model" "design-docs"
```

- [ ] **Step 3: other artifacts 保留**（5 张 en 样本图，测试素材）

## Task 6: audit 加 3 条机器卫生检查（TDD）

**Files:**
- Modify: `scripts/audit.py`
- Create: `tests/test_audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audit.py
import pytest
from pathlib import Path


class TestWorkspaceHygiene:
    def test_ws_empty_dirs_detected(self, tmp_path):
        from scripts.audit import check_workspace_empties
        ws = tmp_path / "workspace"; (ws / "ws-abc").mkdir(parents=True)
        (ws / "ws-xyz").mkdir(parents=True)
        (ws / "ws-real" / "artifacts").mkdir(parents=True)
        n, paths = check_workspace_empties(ws)
        assert n == 2
        assert all("ws-abc" in p or "ws-xyz" in p for p in paths)


class TestDupDetection:
    def test_duplicate_files_detected(self, tmp_path):
        from scripts.audit import find_duplicate_files
        a = tmp_path / "a.md"; b = tmp_path / "b.md"
        a.write_text("same", encoding="utf-8"); b.write_text("same", encoding="utf-8")
        (tmp_path / "c.md").write_text("diff", encoding="utf-8")
        dups = find_duplicate_files(tmp_path)
        assert len(dups) == 1  # 一对
        assert {p.name for p in dups[0]} == {"a.md", "b.md"}


class TestTopLevelClutter:
    def test_unexpected_top_files_detected(self, tmp_path):
        from scripts.audit import check_top_level_clutter
        (tmp_path / "amta").mkdir()
        (tmp_path / "research").mkdir()
        (tmp_path / "reference").mkdir()
        (tmp_path / "stray.md").write_text("x", encoding="utf-8")
        (tmp_path / "stray.png").write_bytes(b"x")
        bad = check_top_level_clutter(tmp_path)
        assert len(bad) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — `scripts.audit` 无这些函数

- [ ] **Step 3: 实现 3 个检查函数（追加到 scripts/audit.py）**

```python
def check_workspace_empties(ws_root: Path) -> tuple[int, list[str]]:
    """workspace/ 下无 artifacts 的 ws-* 空壳目录。"""
    if not ws_root.exists():
        return 0, []
    empties = [str(p) for p in ws_root.glob("ws-*")
               if p.is_dir() and not (p / "artifacts").exists()]
    return len(empties), empties


def find_duplicate_files(root: Path, exts=(".md",)) -> list[list[Path]]:
    """按 (文件名, 大小, 内容) 找重复文件（跨 research/docs）。"""
    from collections import defaultdict
    groups: dict[tuple, list[Path]] = defaultdict(list)
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in exts and ".git" not in p.parts and ".venv" not in p.parts:
            try:
                key = (p.name, p.stat().st_size, p.read_text(encoding="utf-8", errors="ignore")[:500])
            except OSError:
                continue
            groups[key].append(p)
    return [ps for ps in groups.values() if len(ps) > 1]


def check_top_level_clutter(root: Path, allowed=("amta", "research", "reference", ".firecrawl",
                                                ".remember", ".agent-teams", ".env")) -> list[str]:
    """顶层不应有的散落文件（允许目录+白名单）。"""
    if not root.exists():
        return []
    stray = [str(p) for p in root.iterdir()
             if p.is_file() and p.name not in allowed and not p.name.startswith(".env")]
    return stray
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audit.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: audit.py main() 接入新检查 + fastcheck**

```python
# main() 里追加：
ws = ROOT / "workspace"
n_ws, ws_paths = check_workspace_empties(ws)
if n_ws:
    print(f"[audit] workspace 空壳 ws-*: {n_ws}（建议清理）")
    for p in ws_paths[:5]:
        print(f"  {p}")
dups = find_duplicate_files(ROOT)
if dups:
    print(f"[audit] 重复文件: {len(dups)} 组")
    for g in dups[:5]:
        print(f"  {' / '.join(str(x) for x in g)}")
stray = check_top_level_clutter(ROOT.parent)
if stray:
    print(f"[audit] 顶层散落: {len(stray)}")
    for s in stray[:5]:
        print(f"  {s}")
```

Run: `python scripts/fastcheck.py`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add scripts/audit.py tests/test_audit.py
git commit -m "feat(audit): 文档卫生检查 - workspace空壳/重复文件/顶层散落"
```

## Task 7: c4 架构文档（Mermaid）

**Files:**
- Create: `docs/architecture/README.md`（C4 三视图 + Mermaid）
- Create: `docs/architecture/system-context.mmd`（可选）

- [ ] **Step 1: 采集架构证据**（用 c4 skill 方法：入口点/模块/外部依赖）

已从 CLAUDE.md + src/ 已知：
- 容器：DSH 会话（导演）、amta Python 执行器、koharu v0.59.1 headless(:4000)（引擎）、llama-server(:8118)（本地 OCR）、DeepSeek API（翻译/VLM）、DashScope（可选 OCR）
- 组件：`src/amta/*.py`（koharu_client/pipeline/runner/ocr_engines/translate/workstate/tickets/inpaint_strategy/typeset_*）
- 工位脚本：`scripts/00_run_all` → 01_detect → 02_ocr → 03_translate → 04_inpaint → 05_typeset

- [ ] **Step 2: 写 C4 文档（三视图：Context / Container / Component）**

文档含：
1. Scope 声明（本仓 = AMTA 编排层，非 koharu 本体）
2. System Context：用户/导演 ↔ AMTA ↔ koharu/DeepSeek/llama-server/DashScope
3. Container：DSH 会话、Python 执行器、引擎、API、OCR
4. Component（amta 容器内部）：工位链 + 共享库 + 状态
5. Mermaid flowchart + 观察/推断分离 + 待澄清问题

- [ ] **Step 3: 提交**

```bash
git add docs/architecture/README.md
git commit -m "docs(architecture): AMTA C4 架构文档（Context/Container/Component + Mermaid）"
```

## Task 8: v2 计划引用修正 + 收尾

**Files:**
- Modify: `docs/progress.md`
- Modify: `CLAUDE.md`（如需要）

- [ ] **Step 1: progress.md 记录仓库卫生 + 架构文档条目**

- [ ] **Step 2: 全量 fastcheck + 提交**

```bash
python scripts/fastcheck.py
git add docs/progress.md CLAUDE.md .dsh/skills/c4-codebase-architecture/SKILL.md
git commit -m "chore(hygiene): 仓库卫生清理 + c4 skill 钉版 + 调研单一事实源"
```

---

## Self-Review

**1. Spec coverage:**
- 595 ws-* 清理 → Task 1 ✅
- 顶层散落归位 → Task 2 ✅
- research/docs 去重 → Task 3 ✅
- reference 混杂源码 → Task 5 ✅
- audit 机器化卫生检查 → Task 6 ✅
- c4 Mermaid 架构图 → Task 7 ✅
- 引用修正（CLAUDE.md 渐进式加载表指 research/）→ Task 4 ✅

**2. Placeholder scan:** 无 TBD/TODO；每个 Step 有具体命令/代码。

**3. Type consistency:** `check_workspace_empties`/`find_duplicate_files`/`check_top_level_clutter` 三函数签名在 Task 6 测试与实现一致；CLAUDE.md 引用路径与 Task 3/4 移动后的实际路径一致。

**⚠️ 执行前确认项：**
- Task 3 Step 3：docs/02/03 与 research/02/03 内容 diff（避免覆盖新版本）
- `.env` 顶层保留是设计（多 worktree 共享），不清理
- reference/ 第三方源码先归档 `_vendor/` 而非删除（防后悔，可后续再删）
