# 竖排列尾冗余逗号修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复竖排漫画中逗号/句号被断行算法推到列最底端的冗余标点问题，使分列后的排版视觉舒适，同时保留语义必要的句中停顿标点。

**Architecture:** 在 `vertical_punct.py` 新增列尾标点掩码纯函数，在竖排渲染前对分列结果做后处理：当某列最后一个字符是逗号族标点（，、；：）且该列不是最后一列时，将该标点移到下一列开头或隐去（由渲染层决定）。不修改翻译文本，不修改横排逻辑，不全局删标点。

**Tech Stack:** Python 3.12, PIL, pytest, 现有 AMTA typeset 管线

**问题样本:** `workspace/touhou-getten-shinchi/成品汇总/04.png` 第4页，两个气泡：
- 左中气泡（r03）：末列"哦 ，"——逗号悬在列底
- 右中气泡（r01）：末列"！画家，"——逗号在列底

**根因:** `src/amta/typeset/typeset_engine.py:160` 的 `break_lines()` 对 `strong_break = set("，。！？、；：")` 后的断列给予 `cost -= 50` 奖励，导致算法主动偏好把逗号放在列尾。但竖排分列的视觉分隔本身已实现断句功能，列尾逗号冗余。

---

### Task 1: 复现问题并确认根因

**Files:**
- Read: `src/amta/typeset/typeset_engine.py:92-177` (break_lines)
- Read: `src/amta/typeset/vertical_punct.py`
- Read: `workspace/touhou-getten-shinchi/artifacts/translation/page_4.json`
- Read: `workspace/touhou-getten-shinchi/artifacts/typeset/page_4.json`

- [ ] **Step 1: 写一个最小复现脚本**

创建 `scripts/probes/probe_column_end_comma.py`：

```python
"""复现竖排列尾冗余逗号问题。"""
from pathlib import Path
import json
from amta.typeset.typeset_engine import break_lines

# r03: 而且漫画家是一种职业，在幻想乡靠它谋生很难哦
text = "而且漫画家是一种职业，在幻想乡靠它谋生很难哦"
lines = break_lines(text, max_chars=8)
print("分列结果:")
for i, col in enumerate(lines):
    print(f"  列{i}: {col!r} (末字符: {col[-1]!r})")

# 检查是否有列以逗号族结尾且不是最后一列
comma_family = set("，、；：")
bad_cols = [i for i, col in enumerate(lines)
            if i < len(lines) - 1 and col and col[-1] in comma_family]
print(f"\n列尾冗余逗号的列: {bad_cols}")
assert bad_cols, "预期至少有一列以逗号结尾且不是末列"
print("复现成功：断行算法把逗号推到了列底")
```

- [ ] **Step 2: 运行复现脚本确认问题**

Run: `uv run python scripts/probes/probe_column_end_comma.py`
Expected: 输出显示某列以"，"结尾且不是最后一列，打印"复现成功"

- [ ] **Step 3: 检查 typeset/page_4.json 确认成品图中的实际分列**

Run: `uv run python -c "import json; d=json.load(open('workspace/touhou-getten-shinchi/artifacts/typeset/page_4.json')); [print(b.get('text','')[:60], '|', b.get('lines',b.get('columns','?'))) for b in d.get('bubbles', d.get('blocks', [])) if 'r0' in str(b.get('id',''))]"`
Expected: 看到 r01 和 r03 的分列结果中存在列尾逗号

- [ ] **Step 4: 提交复现脚本**

```bash
git add scripts/probes/probe_column_end_comma.py
git commit -m "test: reproduce column-end comma issue in vertical typeset"
```

---

### Task 2: 实现列尾标点掩码纯函数

**Files:**
- Modify: `src/amta/typeset/vertical_punct.py`
- Test: `tests/typeset/test_vertical_punct.py`（如不存在则创建）

- [ ] **Step 1: 写失败测试**

在 `tests/typeset/test_vertical_punct.py` 中添加：

```python
"""列尾冗余逗号掩码测试。"""
from amta.typeset.vertical_punct import column_end_pause_mask


def test_mask_marks_comma_at_non_final_column_end():
    """非末列以逗号结尾时，该位置应被标记为可移除。"""
    columns = ["而且漫画家是一种职业，", "在幻想乡靠它谋生很难哦"]
    mask = column_end_pause_mask(columns)
    assert mask == [True, False]  # 第0列末尾逗号可移除


def test_mask_preserves_comma_in_final_column():
    """末列的逗号不标记（末列没有下一列来承接断句）。"""
    columns = ["在幻想乡靠它谋生", "很难哦，"]
    mask = column_end_pause_mask(columns)
    assert mask == [False, False]


def test_mask_preserves_period_at_column_end():
    """句号。！？是强终止符，即使在列尾也保留（语义终止比视觉冗余更重要）。"""
    columns = ["第一句。", "第二句"]
    mask = column_end_pause_mask(columns)
    assert mask == [False, False]


def test_mask_handles_empty_columns():
    """空列不崩溃。"""
    columns = ["abc，", ""]
    mask = column_end_pause_mask(columns)
    assert mask == [True, False]


def test_mask_only_comma_family():
    """只有逗号族（，、；：）被标记，其他标点不标记。"""
    columns = ["文字…", "后续"]
    mask = column_end_pause_mask(columns)
    assert mask == [False, False]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/typeset/test_vertical_punct.py -v`
Expected: ImportError 或 AttributeError（column_end_pause_mask 尚未定义）

- [ ] **Step 3: 在 vertical_punct.py 实现函数**

在 `vertical_punct.py` 末尾添加：

```python
# 列尾可移除的逗号族标点：这些是"停顿"而非"终止"，竖排分列的视觉分隔
# 已经承担了断句功能，列底再放一个逗号会显得冗余。
# 句号。！？不在这里——它们是强终止符，语义终止比视觉冗余更重要。
COLUMN_END_PAUSE_CHARS: set[str] = set("，、；：")


def column_end_pause_mask(columns: list[str]) -> list[bool]:
    """返回每列末尾的逗号族标点是否可移除的掩码。

    规则：
    - 某列非空、最后一个字符是逗号族（，、；：）、且该列不是最后一列 → True
    - 其他情况 → False

    这是纯函数，不修改输入。调用方（渲染层）根据掩码决定是移除该标点
    还是将其移到下一列开头。
    """
    mask = []
    last_idx = len(columns) - 1
    for i, col in enumerate(columns):
        if i < last_idx and col and col[-1] in COLUMN_END_PAUSE_CHARS:
            mask.append(True)
        else:
            mask.append(False)
    return mask


def apply_column_end_pause_mask(columns: list[str]) -> list[str]:
    """应用掩码：移除被标记列末尾的逗号族标点，返回新列表。"""
    mask = column_end_pause_mask(columns)
    result = []
    for col, remove in zip(columns, mask):
        result.append(col[:-1] if remove else col)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/typeset/test_vertical_punct.py -v`
Expected: 5 个测试全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/typeset/vertical_punct.py tests/typeset/test_vertical_punct.py
git commit -m "feat(typeset): add column_end_pause_mask for vertical comma cleanup"
```

---

### Task 3: 集成到竖排渲染流程

**Files:**
- Modify: `src/amta/typeset/typeset_render.py`（竖排渲染入口）
- Modify: `src/amta/typeset/vlm_render.py`（VLM 竖排渲染入口，如有）
- Test: `tests/typeset/test_typeset_render.py` 或现有测试

- [ ] **Step 1: 定位竖排渲染中调用 break_lines/wrap_vertical 的位置**

Run: `uv run python -c "import inspect; from amta.typeset import typeset_render; print([n for n in dir(typeset_render) if 'render' in n.lower() or 'vertical' in n.lower()])"`
Expected: 找到竖排渲染函数名

- [ ] **Step 2: 在竖排渲染中对分列结果应用掩码**

在 `typeset_render.py` 的竖排渲染函数中，找到调用 `wrap_vertical` 或 `break_lines` 得到 `columns` 后、实际绘制文字前的位置，插入：

```python
from amta.typeset.vertical_punct import apply_column_end_pause_mask

# 竖排分列后，移除非末列列尾的冗余逗号族标点
if direction == "vertical":
    columns = apply_column_end_pause_mask(columns)
```

注意：只在竖排路径应用，横排路径不改动。

- [ ] **Step 3: 对 vlm_render.py 做同样集成（如适用）**

检查 `vlm_render.py` 是否有独立的竖排断列逻辑。如果有，同样应用 `apply_column_end_pause_mask`。如果它复用 typeset_render 的函数，则跳过此步。

- [ ] **Step 4: 写集成测试验证渲染输出不含列尾逗号**

```python
def test_vertical_render_removes_column_end_comma():
    """竖排渲染后，非末列不应以逗号族标点结尾。"""
    from amta.typeset.typeset_engine import break_lines
    from amta.typeset.vertical_punct import apply_column_end_pause_mask
    text = "而且漫画家是一种职业，在幻想乡靠它谋生很难哦"
    columns = break_lines(text, max_chars=8)
    cleaned = apply_column_end_pause_mask(columns)
    comma_family = set("，、；：")
    for i, col in enumerate(cleaned[:-1]):
        assert not (col and col[-1] in comma_family), f"列{i}仍有列尾逗号: {col!r}"
```

- [ ] **Step 5: 运行全部 typeset 测试确认无回归**

Run: `uv run pytest tests/typeset/ -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/amta/typeset/typeset_render.py src/amta/typeset/vlm_render.py tests/typeset/
git commit -m "feat(typeset): apply column-end comma cleanup in vertical render path"
```

---

### Task 4: 重新生成第4页并制作 before/after 对比图

**Files:**
- Output: `workspace/column-end-comma-fix/page_4_before.png`
- Output: `workspace/column-end-comma-fix/page_4_after.png`
- Output: `workspace/column-end-comma-fix/page_4_diff.png`（标注差异位置）

- [ ] **Step 1: 备份当前第4页成品图作为 before**

Run:
```powershell
New-Item -ItemType Directory -Force workspace/column-end-comma-fix
Copy-Item "workspace/touhou-getten-shinchi/artifacts/final/page_4_final.png" "workspace/column-end-comma-fix/page_4_before.png"
```

- [ ] **Step 2: 用修改后的代码重新渲染第4页**

使用项目支持的入口点重跑第4页的 typeset 阶段。优先使用 `scripts/run_pipeline.py`：

```powershell
uv run python scripts/run_pipeline.py --work-id touhou-getten-shinchi --src-dir <源图目录> --start-page 4 --end-page 4 --stages typeset
```

如果 `--src-dir` 不确定，先运行 `uv run python scripts/artifact.py query --work-id touhou-getten-shinchi` 查找源图目录。

Expected: 生成新的 `artifacts/final/page_4_final.png`

- [ ] **Step 3: 复制新图作为 after**

```powershell
Copy-Item "workspace/touhou-getten-shinchi/artifacts/final/page_4_final.png" "workspace/column-end-comma-fix/page_4_after.png"
```

- [ ] **Step 4: 制作标注对比图**

创建 `scripts/probes/make_comparison.py`，在 before 和 after 图上用红框标注两个问题气泡的位置，并排拼接：

```python
"""制作 before/after 对比图，红框标注问题气泡。"""
from PIL import Image, ImageDraw

before = Image.open("workspace/column-end-comma-fix/page_4_before.png")
after = Image.open("workspace/column-end-comma-fix/page_4_after.png")
# 并排拼接
w, h = before.size
comparison = Image.new("RGB", (w * 2 + 20, h), "white")
comparison.paste(before, (0, 0))
comparison.paste(after, (w + 20, 0))
draw = ImageDraw.Draw(comparison)
# 在 before 图标注两个问题气泡位置（需要根据实际坐标调整）
# 左中气泡和右中气泡的大致 bbox 从 detection/page_4.json 读取
import json
det = json.load(open("workspace/touhou-getten-shinchi/artifacts/detection/page_4.json"))
# 标注 r01 和 r03 对应的框
for block in det.get("blocks", det.get("bubbles", [])):
    if str(block.get("id", "")) in ("r01", "r03"):
        x1, y1, x2, y2 = block["bbox"]
        draw.rectangle([x1, y1, x2, y2], outline="red", width=4)
        # after 图上同样标注（偏移 w+20）
        draw.rectangle([x1 + w + 20, y1, x2 + w + 20, y2], outline="red", width=4)
comparison.save("workspace/column-end-comma-fix/page_4_comparison.png")
print("对比图已保存")
```

Run: `uv run python scripts/probes/make_comparison.py`
Expected: 生成 `page_4_comparison.png`，左侧 before 有红框标注列底逗号，右侧 after 同位置无逗号

- [ ] **Step 5: 提交对比图和脚本**

```bash
git add scripts/probes/make_comparison.py workspace/column-end-comma-fix/
git commit -m "test: add before/after comparison for column-end comma fix"
```

---

### Task 5: 验证其他页面并写总结报告

**Files:**
- Output: `workspace/column-end-comma-fix/REPORT.md`

- [ ] **Step 1: 扫描全 work 找出所有有列尾逗号的页面**

创建 `scripts/probes/scan_column_end_comma.py`，遍历 `workspace/touhou-getten-shinchi/artifacts/typeset/` 下所有 page_*.json，检查每个竖排气泡的分列结果：

```python
"""扫描所有页面，统计列尾冗余逗号情况。"""
import json
from pathlib import Path

comma_family = set("，、；：")
typeset_dir = Path("workspace/touhou-getten-shinchi/artifacts/typeset")
issues = []
for f in sorted(typeset_dir.glob("page_*.json")):
    data = json.load(open(f))
    for block in data.get("bubbles", data.get("blocks", [])):
        if block.get("direction") != "vertical":
            continue
        columns = block.get("lines", block.get("columns", []))
        for i, col in enumerate(columns[:-1]):
            if col and col[-1] in comma_family:
                issues.append((f.stem, block.get("id"), i, col))
print(f"共发现 {len(issues)} 处列尾冗余逗号:")
for page, bid, col_idx, col in issues[:20]:
    print(f"  {page} {bid} 列{col_idx}: ...{col[-3:]!r}")
```

Run: `uv run python scripts/probes/scan_column_end_comma.py`
Expected: 输出问题列表，至少包含 page_4 的 r01 和 r03

- [ ] **Step 2: 对问题最严重的 3 个页面重新渲染并验证**

从扫描结果中选取除第4页外问题最多的 2-3 个页面，重跑 typeset 阶段，确认修复后列尾逗号消失。记录页面编号和改善情况。

- [ ] **Step 3: 写总结报告**

创建 `workspace/column-end-comma-fix/REPORT.md`：

```markdown
# 竖排列尾冗余逗号修复报告

## 问题
竖排漫画中，断行算法的 strong_break 奖励（cost -= 50）主动把逗号推到列底，
但分列的视觉分隔已实现断句，列底逗号冗余且视觉突兀。

## 根因
`src/amta/typeset/typeset_engine.py:160` — break_lines() 对 strong_break
后的断列给予成本奖励。

## 修复方案
在 `vertical_punct.py` 新增 `column_end_pause_mask()` 和
`apply_column_end_pause_mask()`，竖排渲染前对非末列的列尾逗号族标点
（，、；：）做移除。句号。！？保留（强终止符语义更重要）。

## 验证结果
- page_4: r01 和 r03 的列尾逗号已消除 [before/after 对比图]
- 其他页面: [列出验证的页面和结果]
- 测试: typeset 测试全部通过，无回归

## 边界
- 不修改翻译文本
- 不影响横排
- 不全局删标点，只处理非末列的列尾逗号族
- 句号/感叹号/问号保留
```

- [ ] **Step 4: 运行完整测试套件做最终回归**

Run: `uv run pytest tests/ -q`
Expected: 全部 PASS（或仅有与本改动无关的已知失败）

- [ ] **Step 5: 提交报告和扫描脚本**

```bash
git add scripts/probes/scan_column_end_comma.py workspace/column-end-comma-fix/REPORT.md
git commit -m "docs: add report for column-end comma fix"
```

---

## 验收标准（Definition of Done）

1. ✅ `column_end_pause_mask()` 纯函数存在且有 5 个单元测试覆盖
2. ✅ 竖排渲染路径集成了 `apply_column_end_pause_mask()`，横排不受影响
3. ✅ 第4页 before/after 对比图存在，两个问题气泡的列尾逗号在 after 中消失
4. ✅ 至少另外 2 个页面验证改善
5. ✅ `pytest tests/typeset/` 全部通过
6. ✅ `pytest tests/` 无新增回归
7. ✅ REPORT.md 记录了根因、方案、验证结果、边界
8. ✅ 没有手改最终译文或成品图
9. ✅ 没有合并、推送、发布——停在 ready_for_review 状态

## 不做的事（Out of Scope）

- 不修改翻译 prompt 或翻译后端
- 不修改横排排版逻辑
- 不处理句号/感叹号/问号的列尾问题（强终止符保留）
- 不处理 VLM OCR 路径的独立渲染逻辑（如复用 typeset_render 则自动受益）
- 不合并到 main，不推送远程
