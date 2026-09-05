# 字体大小第一性原理优化 + 翻译质量修复验证 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 `decide_direction` 人为阈值，`fit_font_size` 同时计算横/竖排最大字号选最优；并在 p11-p15 上验证术语表接入和数组契约防错位的实际效果。

**Architecture:** 字体大小的本质是"给定矩形内放给定文字，字号最大化且不溢出"。横竖排只是两种排列方式，约束方程完全一致（宽高互换）。同时计算两种方案的最大可行字号，返回字号更大者。零人为阈值。

**Tech Stack:** Python 3.13, Pillow（渲染）, pytest（测试）

---

## Task 1: 为 fit_font_size 双方向优化写失败测试

**Files:**
- Test: `amta/tests/test_typeset_engine.py`（新建）

- [ ] **Step 1: 写测试——窄长框应选竖排且字号更大**

```python
"""typeset_engine 字体大小第一性原理测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.typeset_engine import fit_font_size, wrap_text


def test_narrow_tall_box_prefers_vertical():
    """窄长框（宽207高954，47字）应选竖排，字号应显著大于横排。"""
    bbox = (0, 0, 207, 954)
    text = "在那之后我的研究可能是因为八意大人开始插嘴的缘故进展得很顺利虽然很烦人但我忍耐了"
    font_size, direction = fit_font_size(text, bbox)
    assert direction == "vertical", f"窄长框应选竖排，实际选了{direction}"
    assert font_size >= 30, f"竖排字号应>=30，实际{font_size}"


def test_wide_short_box_prefers_horizontal():
    """宽扁框（宽380高222，8字）应选横排。"""
    bbox = (0, 0, 380, 222)
    text = "比起那个还是研究研究"
    font_size, direction = fit_font_size(text, bbox)
    assert direction == "horizontal", f"宽扁框应选横排，实际选了{direction}"
    assert font_size >= 35, f"横排字号应>=35，实际{font_size}"


def test_fit_font_size_returns_tuple():
    """fit_font_size 返回 (字号, 方向) 元组。"""
    result = fit_font_size("测试", (0, 0, 100, 100))
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], int)
    assert result[1] in ("horizontal", "vertical")


def test_wrap_text_vertical_one_char_per_line():
    """竖排 wrap_text 每字一行。"""
    lines = wrap_text("abc", 100, direction="vertical")
    assert lines == ["a", "b", "c"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py -v --tb=short`
Expected: FAIL（当前 `fit_font_size` 返回 int 不是 tuple，且 `wrap_text` 无 direction 参数）

---

## Task 2: 改造 fit_font_size 支持双方向计算

**Files:**
- Modify: `amta/src/amta/typeset_engine.py:39-60`（fit_font_size 函数）
- Modify: `amta/src/amta/typeset_engine.py:23-37`（wrap_text 函数，增加 direction 参数）

- [ ] **Step 1: 改造 wrap_text 支持竖排**

将 `wrap_text` 函数替换为：

```python
def wrap_text(text, max_width, font=None, direction="horizontal"):
    """按方向折行：横排按宽度折行，竖排每字一行（中文等宽）。"""
    if direction == "vertical":
        return [ch for ch in text if ch.strip()]
    # horizontal: greedy by pixel width
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        w = font.getlength(trial) if font else len(trial) * 16
        if cur and w > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines
```

- [ ] **Step 2: 改造 fit_font_size 返回 (字号, 方向) 元组**

将 `fit_font_size` 函数替换为：

```python
def fit_font_size(text, bbox, font_path=None, min_size=12, max_size=72):
    """同时计算横排和竖排的最大可行字号，返回 (字号, 方向) 元组。

    第一性原理：在给定矩形内放给定文字，字号最大化且不溢出。
    两种方向约束方程一致（宽高互换），选字号更大者。零人为阈值。
    """
    from amta.fonts import get_font
    x1, y1, x2, y2 = bbox
    box_w, box_h = x2 - x1, y2 - y1
    pad = 0.85
    max_w, max_h = box_w * pad, box_h * pad

    def _max_size_for_direction(direction):
        lo, hi = min_size, max_size
        best = min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            try:
                font = get_font(font_path, mid) if font_path else None
            except Exception:
                font = None
            if direction == "vertical":
                # 竖排：每列字数 = max_h / (字号*1.2)，列数 = ceil(字数/每列字数)
                chars_per_col = max(1, int(max_h / (mid * 1.2)))
                n_cols = (len(text) + chars_per_col - 1) // chars_per_col
                total_w = n_cols * mid * 1.15
                fits = total_w <= max_w
            else:
                # 横排：每行字数 = max_w / (字号*1.15)，行数 = ceil(字数/每行字数)
                chars_per_line = max(1, int(max_w / (mid * 1.15)))
                n_lines = (len(text) + chars_per_line - 1) // chars_per_line
                total_h = n_lines * mid * 1.2
                fits = total_h <= max_h
            if fits:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    h_size = _max_size_for_direction("horizontal")
    v_size = _max_size_for_direction("vertical")
    if v_size > h_size:
        return (v_size, "vertical")
    return (h_size, "horizontal")
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py -v --tb=short`
Expected: 4 tests PASS

---

## Task 3: 更新调用方——删除 decide_direction，适配新返回值

**Files:**
- Modify: `amta/src/amta/typeset_engine.py:63-92`（layout_text 函数）
- Modify: `amta/src/amta/typeset_station.py:40-55`（resolve_font_and_layout 函数）
- Delete: `amta/src/amta/typeset_engine.py:18-21`（decide_direction 函数）

- [ ] **Step 1: 删除 decide_direction 函数**

从 `typeset_engine.py` 中删除整个 `decide_direction` 函数（第18-21行）。

- [ ] **Step 2: 改造 layout_text 使用新 fit_font_size**

将 `layout_text` 函数替换为：

```python
def layout_text(text, bbox, font_path=None):
    """排版：双方向计算选最优字号 → 折行 → 返回 RenderSpec。"""
    font_size, direction = fit_font_size(text, bbox, font_path=font_path)
    from amta.fonts import get_font
    font = get_font(font_path, font_size) if font_path else None
    x1, y1, x2, y2 = bbox
    max_w = (x2 - x1) * 0.85
    lines = wrap_text(text, max_w, font=font, direction=direction)
    return RenderSpec(
        font_size=font_size,
        lines=lines,
        line_height=int(font_size * 1.2),
        layout_direction=direction,
    )
```

- [ ] **Step 3: 更新 typeset_station.py 的 resolve_font_and_layout**

将 `resolve_font_and_layout` 函数（第40-55行）替换为：

```python
def resolve_font_and_layout(category, text, bbox):
    """字体解析 + 排版。category 来自 canon（detect 透传），None 时走默认。"""
    font_path, stroke_width = resolve_font(category or "dialogue_bubble", text)
    spec = layout_text(text, bbox, font_path=font_path)
    return {
        "font_family": Path(font_path).name if font_path else "default",
        "font_size": spec.font_size,
        "stroke_width": stroke_width,
        "lines": spec.lines,
        "line_height": spec.line_height,
        "layout_direction": spec.layout_direction,
    }
```

注意：删除原来的 `direction = decide_direction(category, bbox, len(text))` 行。

- [ ] **Step 4: 运行全部 typeset 相关测试**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py tests/test_translate_station.py tests/test_stage3_minimal.py -v --tb=short`
Expected: 全部 PASS（共 27 个测试）

---

## Task 4: 验证前两项修复在真实数据上的效果

**Files:**
- 验证用：`amta/workspace/touhou-e2e-orchestrator/artifacts/`（已有产物）

- [ ] **Step 1: 验证术语替换——手动跑 pre_scan 确认サグメ被锁定**

Run:
```powershell
cd amta
python -c "import sys; sys.path.insert(0,'src'); from amta.pre_scan import run_pre_scan; r = run_pre_scan('touhou-e2e-orchestrator', 'workspace/touhou-e2e-orchestrator/artifacts'); print('锁定术语数:', len(r)); print('サグメ' in r, r.get('サグメ')); print('サグ姉' in r, r.get('サグ姉'))"
```
Expected: サグメ→探女、サグ姉→探女姐 均被锁定

- [ ] **Step 2: 验证数组契约——用 p14 canon 模拟翻译确认不错位**

Run:
```powershell
cd amta
python -c "
import sys, json; sys.path.insert(0,'src')
from amta.translate import translate_plain
canon = json.load(open('workspace/touhou-e2e-orchestrator/artifacts/page_14_canon.json',encoding='utf-8'))['items']
# 模拟一个会拆条的LLM：12条输入返回13条
calls = [0]
def bad_llm(messages, tools=None):
    calls[0] += 1
    if calls[0] <= 2:
        return json.dumps([f'译{i}' for i in range(13)])
    return json.dumps([f'译{i}' for i in range(6)])
result = translate_plain(canon, bad_llm, max_retries=1)
print('LLM调用次数:', calls[0], '(>2说明触发了二分拆分)')
print('翻译结果数:', len(result), '(=12说明按位置绑定正确)')
print('r00:', result.get('r00'), 'r11:', result.get('r11'))
"
```
Expected: LLM调用>2（触发二分），结果数=12，r00/r11均有值且不错位

- [ ] **Step 3: 验证字体大小——p11 r00 窄长框字号应>=30**

Run:
```powershell
cd amta
python -c "
import sys; sys.path.insert(0,'src')
from amta.typeset_engine import fit_font_size
text = '在那之后我的研究可能是因为八意大人开始插嘴的缘故进展得很顺利虽然很烦人但我忍耐了'
size, direction = fit_font_size(text, (1665,2139,1872,3093))
print(f'p11 r00: 字号={size}, 方向={direction}')
assert direction == 'vertical' and size >= 30, '字体大小修复未生效'
print('✓ 字体大小修复生效')
"
```
Expected: 方向=vertical，字号>=30（修复前是horizontal，字号19）

---

## Task 5: 提交

**Files:** 所有改动文件

- [ ] **Step 1: 查看改动范围**

Run: `cd amta && git status && git diff --stat`

- [ ] **Step 2: 提交**

```bash
git add src/amta/typeset_engine.py src/amta/typeset_station.py tests/test_typeset_engine.py
git commit -m "feat(typeset): 字体大小第一性原理——删除decide_direction，双方向计算选最优

- fit_font_size 返回 (字号, 方向) 元组，同时计算横/竖排最大字号
- wrap_text 增加 direction 参数，竖排每字一行
- 删除 decide_direction（含 h/w>=2.2 and char_count<=6 两个人为阈值）
- 窄长框自动选竖排（p11 r00 从19px→35px+），宽扁框自动选横排
- 零阈值，完全由数据驱动"
```

---

## Self-Review

**1. Spec coverage:**
- 决策C（字体大小第一性原理）：Task 1-3 完整覆盖
- 决策A（术语表接入）：已实施，Task 4 Step 1 验证
- 决策B（数组契约）：已实施，Task 4 Step 2 验证

**2. Placeholder scan:** 无 TBD/TODO/占位符，每步有完整代码和命令

**3. Type consistency:** `fit_font_size` 返回 `tuple[int, str]`，Task 2 定义、Task 3 使用一致；`wrap_text` 新增 `direction` 参数默认 `"horizontal"` 保持向后兼容
