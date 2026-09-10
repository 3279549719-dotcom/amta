# 竖排排版修复（避头尾 + 标点旋转）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复竖排文本中标点单独占列、省略号等横向标点竖排显示难看的问题。

**Architecture:** 在 `typeset_engine.py` 的 `wrap_vertical()` 中增加避头尾逻辑（与横排 `wrap_text()` 对称），在 `typeset_render.py` 竖排渲染循环中检测横向标点并旋转90度后绘制。

**Tech Stack:** Python 3.12, PIL/Pillow, pytest

**Worktree:** `E:\manga translator agent\amta-wt-fix-typesetting` (branch: `fix/vertical-typesetting-punctuation`)

---

## 文件结构

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/amta/typeset_engine.py:64-66` | `wrap_vertical()` 增加避头尾逻辑 |
| 修改 | `src/amta/typeset_render.py:41-55` | 竖排渲染时横向标点旋转90度 |
| 修改测试 | `tests/test_typeset_engine.py` | 新增竖排避头尾测试 |
| 修改测试 | `tests/test_typeset_render.py` | 新增标点旋转渲染测试 |

---

### Task 1: 竖排避头尾逻辑

**Files:**
- Modify: `src/amta/typeset_engine.py:64-66`
- Test: `tests/test_typeset_engine.py`

- [ ] **Step 1: 写失败测试 — 标点不落列首**

在 `tests/test_typeset_engine.py` 末尾添加：

```python
def test_wrap_vertical_avoid_punctuation_at_col_start():
    """竖排避头尾：标点不能出现在列首，应挤到上一列末尾。"""
    from amta.typeset_engine import wrap_vertical
    # 文本长度 = 每列字数的倍数 + 1个标点 → 标点会单独成列
    text = "一二三四五六七八九十，"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    # 标点不应该单独占一列，应该挤到第一列
    assert len(lines) == 1
    assert lines[0] == "一二三四五六七八九十，"


def test_wrap_vertical_avoid_multiple_punctuation():
    """多个连续标点都不落列首。"""
    from amta.typeset_engine import wrap_vertical
    text = "一二三四五六七八九十……"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    # 省略号（2个字符）都应该挤到第一列
    assert len(lines) == 1
    assert lines[0] == "一二三四五六七八九十……"


def test_wrap_vertical_no_punctuation_normal_split():
    """没有标点时正常分割。"""
    from amta.typeset_engine import wrap_vertical
    text = "一二三四五六七八九十一二三四五六七八九十"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 2
    assert lines[0] == "一二三四五六七八九十"
    assert lines[1] == "一二三四五六七八九十"


def test_wrap_vertical_punctuation_in_middle_unchanged():
    """标点在列中间时不影响分割。"""
    from amta.typeset_engine import wrap_vertical
    text = "一二三四五，六七八九十一二三四五六七八九十"
    chars_per_col = 10
    lines = wrap_vertical(text, chars_per_col)
    assert len(lines) == 3
    assert lines[0] == "一二三四五，六七八九"
    assert lines[1] == "十一二三四五六七八九"
    assert lines[2] == "十"
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run pytest tests/test_typeset_engine.py::test_wrap_vertical_avoid_punctuation_at_col_start tests/test_typeset_engine.py::test_wrap_vertical_avoid_multiple_punctuation -v
```
Expected: FAIL（`wrap_vertical` 目前是纯切片，标点会单独成列）

- [ ] **Step 3: 实现竖排避头尾逻辑**

替换 `src/amta/typeset_engine.py` 第64-66行的 `wrap_vertical()`：

```python
def wrap_vertical(text: str, chars_per_col: int) -> list[str]:
    """竖排按列分割，返回列列表（每列是一个字符串）。

    避头尾规则：列首不能是禁则标点（，。！？、）》】……—），
    若分割点后第一个字符是标点，则将该标点挤到上一列末尾。
    与横排 wrap_text() 的 NO_START_PUNCT 逻辑对称。
    """
    if chars_per_col <= 0:
        return [text] if text else []

    lines: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chars_per_col, n)
        # 检查下一列的第一个字符是否是禁则标点
        if end < n and text[end] in NO_START_PUNCT:
            # 把标点挤到当前列（容忍轻微超出）
            # 找到连续的标点，全部挤过来
            punct_end = end
            while punct_end < n and text[punct_end] in NO_START_PUNCT:
                punct_end += 1
            end = punct_end
        lines.append(text[i:end])
        i = end
    return lines
```

注意：需要确保 `NO_START_PUNCT` 常量中包含省略号和破折号。当前定义在第13行：
```python
NO_START_PUNCT = "，。！？、）》】"
```
需要扩展为：
```python
NO_START_PUNCT = "，。！？、）》】……—"
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run pytest tests/test_typeset_engine.py -v
```
Expected: 全部 PASS（包括新增的4个测试和原有的14个测试）

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
git add src/amta/typeset_engine.py tests/test_typeset_engine.py
git commit -m "feat: 竖排wrap_vertical增加避头尾逻辑，标点不再单独占列"
```

---

### Task 2: 竖排横向标点旋转渲染

**Files:**
- Modify: `src/amta/typeset_render.py:41-55`
- Test: `tests/test_typeset_render.py`

- [ ] **Step 1: 写失败测试 — 竖排省略号被旋转**

在 `tests/test_typeset_render.py` 末尾添加：

```python
from PIL import Image


def test_render_vertical_ellipsis_rotated():
    """竖排渲染时，省略号等横向标点应旋转90度绘制。"""
    from amta.typeset_render import render_item
    img = Image.new("RGB", (400, 800), "white")
    bbox = [100, 100, 300, 700]  # 窄长框 → 竖排
    text = "测试省略号……"
    result = render_item(img, text, "msyh.ttc", bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 验证图片不是全白（有内容被绘制）
    # 更严格的验证：检查渲染区域有非白色像素
    bbox_region = img.crop((100, 100, 300, 700))
    pixels = list(bbox_region.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 100  # 有足够多的文字像素


def test_render_vertical_dash_rotated():
    """竖排渲染时，破折号应旋转90度绘制。"""
    from amta.typeset_render import render_item
    img = Image.new("RGB", (400, 800), "white")
    bbox = [100, 100, 300, 700]
    text = "破折号测试——"
    result = render_item(img, text, "msyh.ttc", bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    bbox_region = img.crop((100, 100, 300, 700))
    pixels = list(bbox_region.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 100
```

- [ ] **Step 2: 运行测试确认当前状态（应该能通过，但没有旋转）**

Run:
```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run pytest tests/test_typeset_render.py::test_render_vertical_ellipsis_rotated -v
```
Expected: PASS（当前代码能渲染，但省略号是横向的，测试只验证了有内容绘制）

注意：这个测试是"烟雾测试"，验证渲染不崩溃。真正的旋转效果需要人工看图验证。我们会在Task 3做端到端视觉验证。

- [ ] **Step 3: 实现竖排标点旋转**

修改 `src/amta/typeset_render.py` 第41-55行的竖排渲染循环。

首先在文件顶部添加导入：
```python
import io
```

然后替换竖排渲染部分（第41-55行）：

```python
    if direction == "vertical":
        # 竖排多列：从右到左排列，每列从上到下
        n_cols = len(lines)
        col_width = font_size * CHAR_WIDTH_RATIO
        total_w = n_cols * col_width
        # 最右列的 x 坐标（列中心）
        x_start = cx + total_w / 2 - col_width / 2
        # 需要旋转的横向标点（在竖排中应垂直显示）
        ROTATE_CHARS = set("……—–")
        for col_idx, col_text in enumerate(lines):
            x = x_start - col_idx * col_width
            col_h = len(col_text) * lh
            y = cy - col_h // 2
            for ch in col_text:
                if ch in ROTATE_CHARS:
                    # 横向标点旋转90度后绘制
                    # 先创建一个透明小图画字符，再旋转，再粘贴到主图
                    char_img = Image.new("RGBA", (font_size * 2, font_size * 2),
                                          (0, 0, 0, 0))
                    char_draw = ImageDraw.Draw(char_img)
                    char_draw.text((font_size // 2, font_size // 2), ch,
                                   font=font, fill=color,
                                   stroke_width=int(stroke), stroke_fill="white")
                    rotated = char_img.rotate(90, expand=True)
                    # 计算粘贴位置（居中对齐）
                    paste_x = int(x - rotated.width / 2)
                    paste_y = int(y - rotated.height / 2 + lh / 2)
                    img.paste(rotated, (paste_x, paste_y), rotated)
                else:
                    draw.text((x, y), ch, font=font, fill=color,
                              stroke_width=int(stroke), stroke_fill="white")
                y += lh
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run pytest tests/test_typeset_render.py -v
```
Expected: 全部 PASS（包括新增的2个测试和原有的7个测试）

- [ ] **Step 5: Commit**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
git add src/amta/typeset_render.py tests/test_typeset_render.py
git commit -m "feat: 竖排渲染时横向标点（省略号/破折号）旋转90度垂直显示"
```

---

### Task 3: 端到端验证

**Files:**
- 验证用：`workspace/touhou-e2e-orchestrator/artifacts/page_11~15_*.json`
- 输出：对比图

- [ ] **Step 1: 重跑 p11-p15 排版**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run --project . python ../amta/rerun_typeset_11_15.py
```
注意：如果脚本路径不对，直接用Python调用排版模块：
```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run python -c "
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from amta.typeset_render import render_item
from amta.artifacts import load_canon, load_translation, artifact_paths
from PIL import Image
import json

art_dir = Path('workspace/touhou-e2e-orchestrator/artifacts')
for page_num in range(11, 16):
    page = f'page_{page_num}'
    canon = load_canon(art_dir / f'{page}_canon.json')
    trans = load_translation(art_dir / f'{page}_translation.json')
    clean_img = Image.open(art_dir / 'clean' / f'{page}_clean.png')
    for item in canon['items']:
        rid = item['region_id']
        text = trans['translations'].get(rid, '')
        if text:
            render_item(clean_img, text, 'msyh.ttc', item['bbox'],
                       stroke=0, preferred_direction=None)
    out_path = art_dir / 'final' / f'{page}_final_vertical_fix.png'
    clean_img.save(out_path)
    print(f'Saved {out_path}')
"
```

- [ ] **Step 2: 生成对比图（修复前 vs 修复后）**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run python -c "
from PIL import Image
from pathlib import Path

art_dir = Path('workspace/touhou-e2e-orchestrator/artifacts')
out_dir = Path('output/vertical_fix_comparison')
out_dir.mkdir(parents=True, exist_ok=True)

for page_num in range(11, 16):
    page = f'page_{page_num}'
    before = Image.open(art_dir / 'final' / f'{page}_final.png')
    after = Image.open(art_dir / 'final' / f'{page}_final_vertical_fix.png')
    # 左右拼接
    w = before.width + after.width + 20
    h = max(before.height, after.height)
    comp = Image.new('RGB', (w, h), 'white')
    comp.paste(before, (0, 0))
    comp.paste(after, (before.width + 20, 0))
    out_path = out_dir / f'{page}_comparison.jpg'
    comp.save(out_path, quality=90)
    print(f'Saved {out_path}')
"
```

- [ ] **Step 3: 人工检查清单**

打开 `output/vertical_fix_comparison/` 下的对比图，逐项验证：

- [ ] p11 r03 "连我自己都觉得这想法真是异想天开……" — 省略号不再单独占列
- [ ] p11 r01 "月之民非常相似也许……" — 省略号与文字同列，且垂直显示
- [ ] p11 r02 "可是……" — 省略号垂直显示
- [ ] p13 r00 "此而已……" — 省略号不再单独占列
- [ ] p13 r02 "冷、冷静点……" — 顿号和省略号都不落列首
- [ ] 所有竖排文本中的省略号都是垂直的六个点，不是横向的
- [ ] 横排文本（如p11 r04）不受影响，标点正常显示
- [ ] 没有文字溢出气泡框
- [ ] 字号与修复前一致（没有因为避头尾导致字号变小）

- [ ] **Step 4: 运行全量测试回归**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
uv run pytest tests/ -q --ignore=tests/test_detect_rtdetr.py
```
Expected: 375+ passed（原有375 + 新增6 = 381），0 failed（除了onnxruntime相关的3个已有失败）

- [ ] **Step 5: 最终Commit + 交接文档**

```powershell
cd E:\manga translator agent\amta-wt-fix-typesetting
git add -A
git commit -m "test: 端到端验证通过，竖排避头尾+标点旋转修复完成"
```

创建交接文档 `docs/debug/vertical-typesetting-fix-handoff-2026-09-05.md`，包含：
- 改动摘要（2个核心文件）
- 测试结果（新增6个测试，全量381 passed）
- 对比图路径
- 验证清单结果
- 遗留问题（如有）

---

## 自检清单

- [x] **Spec覆盖**: 标点单独占列 → Task 1 避头尾；省略号竖排难看 → Task 2 旋转；验证 → Task 3
- [x] **无占位符**: 所有步骤都有具体代码和命令
- [x] **类型一致**: `wrap_vertical(text, chars_per_col) -> list[str]` 签名保持不变
- [x] **向后兼容**: 横排逻辑完全不动，只改竖排
