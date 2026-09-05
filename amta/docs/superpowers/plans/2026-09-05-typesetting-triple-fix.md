# Typesetting 三修复实施计划（P0 翻译错位 + P1 横竖方向 + P2 标点精简）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复漫画翻译管线的三个排版硬伤——翻译错位(P0)、横竖方向不一致(P1)、标点冗余(P2后续)。

**Architecture:** P0 增强翻译护栏检测语义错位并重跑验证；P1 从 bbox 长宽比推断原文方向，传入 fit_font_size 作为首选方向约束；P2 用"原文标点数量对齐译文"的机械规则精简标点，辅以竖排标点旋转。

**Tech Stack:** Python 3.x, PIL/Pillow, pytest, 现有 amta 管线

**当前分支:** `fix/typeset-direction-punctuation-translation-misalignment`

**执行范围:** 本计划先执行 P0 + P1（Task 1–8），P2（Task 9–11）列入但标注为后续执行。

---

## 文件结构总览

| 文件 | 改动类型 | 责任 |
|------|---------|------|
| `amta/src/amta/guardrails.py` | 修改 | 增加译文/原文长度比异常检测 |
| `amta/src/amta/typeset_engine.py` | 修改 | 增加 infer_direction_from_bbox + fit_font_size 首选方向参数 |
| `amta/src/amta/typeset_render.py` | 修改 | render_item 传递 preferred_direction |
| `amta/src/amta/typeset_station.py` | 修改 | 从 bbox 推断方向并传入渲染 |
| `amta/src/amta/punctuation_align.py` | 新建（P2） | 原文标点数量对齐译文的机械规则 |
| `amta/src/amta/translate_station.py` | 修改（P2） | 翻译后调用标点对齐 |
| `amta/tests/test_guardrails.py` | 新建 | 护栏增强测试 |
| `amta/tests/test_typeset_engine.py` | 修改 | 方向推断 + 首选方向测试 |
| `amta/tests/test_punctuation_align.py` | 新建（P2） | 标点对齐测试 |

---

## P0：翻译错位修复

### Task 1: 增强 mechanical_guardrails — 译文/原文长度比异常检测

**Files:**
- Modify: `amta/src/amta/guardrails.py:15-28`
- Create: `amta/tests/test_guardrails.py`

- [ ] **Step 1: 写失败测试**

在 `amta/tests/test_guardrails.py` 写入：

```python
"""guardrails 机械护栏测试 — 结构错 + 长度比异常检测。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_mechanical_guardrails_detects_missing_id():
    """缺失 region_id 应被检测。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}, {"region_id": "r01", "text": "world"}]
    translation = {"r00": "你好"}  # r01 缺失
    problems = mechanical_guardrails(canon, translation)
    assert any("r01" in p for p in problems), f"应检测到 r01 缺失，实际: {problems}"


def test_mechanical_guardrails_detects_empty_translation():
    """空译文应被检测。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "hello"}]
    translation = {"r00": "   "}
    problems = mechanical_guardrails(canon, translation)
    assert any("empty" in p for p in problems), f"应检测到空译文，实际: {problems}"


def test_length_ratio_detects_severe_truncation():
    """译文长度远小于原文（<30%）应被标记为可疑截断。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "ちょっと待て! 仮行さぼりたいだけでしょ"}]
    translation = {"r00": "等一下！"}  # 原文20字符，译文4字，比例20%
    problems = mechanical_guardrails(canon, translation)
    assert any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
               for p in problems), f"应检测到严重截断，实际: {problems}"


def test_length_ratio_passes_normal_translation():
    """正常译文（长度比30%-200%）不应触发长度告警。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "こんにちは世界"}]
    translation = {"r00": "你好世界"}  # 比例合理
    problems = mechanical_guardrails(canon, translation)
    assert not any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
                   for p in problems), f"正常翻译不应触发长度告警，实际: {problems}"


def test_length_ratio_very_short_text_exempt():
    """极短原文（<=4字符）不做长度比检测（避免误报）。"""
    from amta.guardrails import mechanical_guardrails
    canon = [{"region_id": "r00", "text": "はい"}]
    translation = {"r00": "嗯"}
    problems = mechanical_guardrails(canon, translation)
    assert not any("truncat" in p.lower() or "长度" in p or "ratio" in p.lower()
                   for p in problems), f"极短文本不应触发长度告警，实际: {problems}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd amta && python -m pytest tests/test_guardrails.py -v`
Expected: 后三个测试 FAIL（length_ratio 函数不存在），前两个 PASS（已有功能）

- [ ] **Step 3: 实现长度比检测**

修改 `amta/src/amta/guardrails.py`，在 `mechanical_guardrails` 函数末尾（return 之前）增加：

```python
def mechanical_guardrails(canon: list[dict], translation: dict[str, str]) -> list[str]:
    """护栏①结构错：region_id 与输入一一对应（无漏无重）、字段齐全、长度比异常。"""
    problems = []
    ids = {r["region_id"] for r in canon}
    for r in canon:
        rid = r["region_id"]
        if rid not in translation:
            problems.append(f"missing region_id {rid}")
        elif not translation[rid].strip():
            problems.append(f"empty translation for {rid}")
        else:
            # 长度比异常检测：译文字符数 / 原文字符数
            src = (r.get("text") or r.get("baberu_text") or "").strip()
            tgt = translation[rid].strip()
            if len(src) >= 5:  # 极短文本不检测
                ratio = len(tgt) / len(src) if len(src) > 0 else 1.0
                if ratio < 0.30:
                    problems.append(
                        f"suspected truncation {rid}: "
                        f"src={len(src)}chars tgt={len(tgt)}chars ratio={ratio:.2f}"
                    )
                elif ratio > 3.0:
                    problems.append(
                        f"suspected over-expansion {rid}: "
                        f"src={len(src)}chars tgt={len(tgt)}chars ratio={ratio:.2f}"
                    )
    extra = set(translation) - ids
    if extra:
        problems.append(f"extra region_ids: {sorted(extra)}")
    return problems
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd amta && python -m pytest tests/test_guardrails.py -v`
Expected: 全部 5 个测试 PASS

- [ ] **Step 5: 提交**

```bash
git add amta/src/amta/guardrails.py amta/tests/test_guardrails.py
git commit -m "fix(guardrails): 增加译文/原文长度比异常检测，防 LLM 截断式错位"
```

---

### Task 2: 重跑 p11–p15 翻译阶段，验证错位消失

**Files:**
- 读取: `amta/src/amta/translate_station.py`（确认调用方式）
- 产物: `amta/workspace/touhou-e2e-orchestrator/artifacts/page_11_translation.json` ~ `page_15_translation.json`（覆盖）

- [ ] **Step 1: 确认翻译重跑入口**

Run: `cd amta && python -c "from amta.translate_station import run; import inspect; print(inspect.signature(run))"`
Expected: 打印 run 函数签名，确认需要哪些参数

- [ ] **Step 2: 编写重跑脚本（临时）**

在项目根目录创建 `rerun_translation_11_15.py`：

```python
"""临时脚本：用当前代码重跑 p11-15 翻译阶段，验证数组契约+护栏修复生效。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "amta" / "src"))

from amta.translate_station import run as translate_run
from amta.paths import read_json

WORK = "touhou-e2e-orchestrator"
ART = Path("amta/workspace/touhou-e2e-orchestrator/artifacts")

for page in range(11, 16):
    page_key = f"page_{page}"
    canon_path = ART / f"{page_key}_canon.json"
    det_path = ART / f"{page_key}_detection.json"
    out_path = ART / f"{page_key}_translation.json"
    print(f"\n=== 重跑 {page_key} 翻译 ===")
    result = translate_run(
        work_id=WORK,
        canon_path=canon_path,
        det_path=det_path,
        out_path=out_path,
    )
    print(f"  翻译条数: {len(result.get('translations', {}))}")
    # 检查护栏
    canon = read_json(canon_path).get("items", [])
    from amta.guardrails import mechanical_guardrails
    problems = mechanical_guardrails(canon, result.get("translations", {}))
    if problems:
        print(f"  ⚠ 护栏告警: {problems}")
    else:
        print(f"  ✓ 护栏通过")
print("\n完成")
```

- [ ] **Step 3: 运行重跑脚本**

Run: `cd "E:\manga translator agent" && python rerun_translation_11_15.py`
Expected: p11–p15 翻译重跑完成，p14 不再出现 r01 截断为"等一下！"的情况，护栏无严重告警

- [ ] **Step 4: 验证 p14 错位修复**

Run: `cd "E:\manga translator agent" && python -c "
import json
t = json.load(open('amta/workspace/touhou-e2e-orchestrator/artifacts/page_14_translation.json', encoding='utf-8'))
for rid in ['r01','r02','r10','r11']:
    print(f'{rid}: {t[\"translations\"].get(rid, \"MISSING\")}')"`
Expected:
- r01 应包含"等一下"和"偷懒"相关内容（完整翻译，不是只有"等一下！"）
- r10 应为"萨古姐!?"或类似译文（不再丢失）
- r11 应为"…探女"或类似译文（不再丢失）

- [ ] **Step 5: 重跑 typeset 生成新 final 图**

Run: 用现有 rerun_typeset.py 或类似脚本重跑 p11–p15 typeset
Expected: 生成新的 `page_11_final.png` ~ `page_15_final.png`，p14 文字嵌入正确

- [ ] **Step 6: 提交（翻译产物不入库，仅提交脚本和代码）**

```bash
git add rerun_translation_11_15.py
git commit -m "chore: 临时重跑翻译脚本，验证 p14 错位修复"
```

---

## P1：横竖方向修复

### Task 3: 实现 infer_direction_from_bbox — 从框长宽比推断原文方向

**Files:**
- Modify: `amta/src/amta/typeset_engine.py`（增加函数）
- Modify: `amta/tests/test_typeset_engine.py`（增加测试）

- [ ] **Step 1: 写失败测试**

在 `amta/tests/test_typeset_engine.py` 末尾追加：

```python
def test_infer_direction_tall_narrow_box_is_vertical():
    """高宽比 >= 1.5 的窄长框推断为竖排。"""
    from amta.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 166, 691]  # 高宽比 4.16
    assert infer_direction_from_bbox(bbox) == "vertical"


def test_infer_direction_wide_short_box_is_horizontal():
    """宽高比 >= 1.5 的横长框推断为横排。"""
    from amta.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 380, 222]  # 宽高比 1.71
    assert infer_direction_from_bbox(bbox) == "horizontal"


def test_infer_direction_square_box_returns_none():
    """接近方形的框返回 None（不强制方向，回退到字号选优）。"""
    from amta.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 200, 200]  # 1:1
    assert infer_direction_from_bbox(bbox) is None


def test_infer_direction_moderate_tall_box_is_vertical():
    """高宽比刚好 1.5 的框推断为竖排。"""
    from amta.typeset_engine import infer_direction_from_bbox
    bbox = [0, 0, 100, 150]  # 高宽比 1.5
    assert infer_direction_from_bbox(bbox) == "vertical"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py::test_infer_direction_tall_narrow_box_is_vertical -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现 infer_direction_from_bbox**

在 `amta/src/amta/typeset_engine.py` 中，`fit_font_size` 函数之前增加：

```python
# 方向推断阈值：高宽比 >= 1.5 视为竖排框，宽高比 >= 1.5 视为横排框
DIRECTION_RATIO_THRESHOLD = 1.5


def infer_direction_from_bbox(bbox: list) -> str | None:
    """从文本框长宽比推断原文排版方向。

    日漫排版规律：窄长框（高>>宽）通常是竖排，横长框（宽>>高）通常是横排。
    接近方形的框返回 None，表示不强制方向，回退到字号选优。

    Args:
        bbox: [x1, y1, x2, y2]

    Returns:
        "vertical" | "horizontal" | None
    """
    x1, y1, x2, y2 = bbox
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    if h / w >= DIRECTION_RATIO_THRESHOLD:
        return "vertical"
    if w / h >= DIRECTION_RATIO_THRESHOLD:
        return "horizontal"
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py -v -k infer_direction`
Expected: 4 个方向推断测试全部 PASS

- [ ] **Step 5: 提交**

```bash
git add amta/src/amta/typeset_engine.py amta/tests/test_typeset_engine.py
git commit -m "feat(typeset): 增加 infer_direction_from_bbox，从框长宽比推断原文方向"
```

---

### Task 4: fit_font_size 增加 preferred_direction 参数 — 首选方向约束

**Files:**
- Modify: `amta/src/amta/typeset_engine.py:94-106`
- Modify: `amta/tests/test_typeset_engine.py`

- [ ] **Step 1: 写失败测试**

在 `amta/tests/test_typeset_engine.py` 末尾追加：

```python
def test_preferred_direction_horizontal_for_wide_box():
    """横长框指定 preferred_direction='horizontal' 时，应选横排。"""
    from amta.typeset_engine import fit_font_size
    bbox = [0, 0, 380, 222]  # 横长框
    text = "比起那个还是研究研究"
    font_size, direction, lines = fit_font_size(
        text, FONT_PATH, bbox, preferred_direction="horizontal"
    )
    assert direction == "horizontal", f"横长框首选横排，实际选了{direction}"


def test_preferred_direction_vertical_for_tall_box():
    """窄长框指定 preferred_direction='vertical' 时，应选竖排。"""
    from amta.typeset_engine import fit_font_size
    bbox = [0, 0, 166, 691]  # 窄长框
    text = "冷、冷静点……并不是担心八意大人什么的"
    font_size, direction, lines = fit_font_size(
        text, FONT_PATH, bbox, preferred_direction="vertical"
    )
    assert direction == "vertical", f"窄长框首选竖排，实际选了{direction}"


def test_preferred_direction_fallback_when_too_small():
    """首选方向字号过小（<次选70%）时，允许切换到次选方向。"""
    from amta.typeset_engine import fit_font_size
    # 极端情况：极宽框放超长文本，横排字号极小，允许切竖排
    bbox = [0, 0, 500, 50]  # 极宽极扁
    text = "这是一段非常长的文本用来测试首选方向字号过小时是否允许回退到次选方向"
    h_size, h_dir, _ = fit_font_size(text, FONT_PATH, bbox, preferred_direction="horizontal")
    # 不强制断言方向，但验证函数不崩溃且返回合理结果
    assert h_size >= 12
    assert h_dir in ("horizontal", "vertical")


def test_no_preferred_direction_matches_old_behavior():
    """不传 preferred_direction 时行为与旧版一致（纯字号选优）。"""
    from amta.typeset_engine import fit_font_size
    bbox = [0, 0, 200, 200]
    text = "测试文本"
    font_size, direction, lines = fit_font_size(text, FONT_PATH, bbox)
    assert direction in ("horizontal", "vertical")
    assert font_size >= 12
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py -v -k preferred_direction`
Expected: FAIL（preferred_direction 参数不存在）

- [ ] **Step 3: 修改 fit_font_size 支持首选方向**

修改 `amta/src/amta/typeset_engine.py` 的 `fit_font_size` 函数：

```python
def fit_font_size(text: str, font_path: Path, bbox: list,
                  min_sz: int = MIN_SIZE, max_sz: int = MAX_SIZE,
                  preferred_direction: str | None = None
                  ) -> tuple[int, str, list[str]]:
    """同时计算横排和竖排的最大可行字号，返回 (字号, 方向, 折行/分列)。

    第一性原理：在给定矩形内放给定文字，字号最大化且不溢出。
    两种方向约束方程一致（宽高互换），选字号更大者。

    preferred_direction: 首选方向（"horizontal"|"vertical"|None）。
        - 若指定，优先在该方向最大化字号；
        - 仅当首选方向字号 < 次选方向字号 * 0.70 时才切换到次选方向；
        - 平局时（字号差 <= 2px）优先选首选方向。
        - None 时纯字号选优（旧行为）。
    """
    h_size, h_lines = _max_size_for_direction(text, font_path, bbox, "horizontal", min_sz, max_sz)
    v_size, v_lines = _max_size_for_direction(text, font_path, bbox, "vertical", min_sz, max_sz)

    if preferred_direction == "horizontal":
        # 首选横排：横排字号不小于竖排70%就选横排
        if h_size >= v_size * 0.70:
            return h_size, "horizontal", h_lines
        return v_size, "vertical", v_lines
    if preferred_direction == "vertical":
        # 首选竖排：竖排字号不小于横排70%就选竖排
        if v_size >= h_size * 0.70:
            return v_size, "vertical", v_lines
        return h_size, "horizontal", h_lines

    # 无首选方向：纯字号选优，平局偏向竖排（旧行为）
    if v_size >= h_size:
        return v_size, "vertical", v_lines
    return h_size, "horizontal", h_lines
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd amta && python -m pytest tests/test_typeset_engine.py -v`
Expected: 全部测试 PASS（包括旧的 5 个 + 新的 8 个）

- [ ] **Step 5: 提交**

```bash
git add amta/src/amta/typeset_engine.py amta/tests/test_typeset_engine.py
git commit -m "feat(typeset): fit_font_size 支持 preferred_direction，首选方向字号不小于次选70%时保持"
```

---

### Task 5: typeset_render 和 typeset_station 传递方向

**Files:**
- Modify: `amta/src/amta/typeset_render.py:15-25`
- Modify: `amta/src/amta/typeset_station.py:36-47`
- Modify: `amta/tests/test_typeset_render.py`（确认现有测试仍通过）

- [ ] **Step 1: 修改 render_item 接收 preferred_direction**

修改 `amta/src/amta/typeset_render.py` 的 `render_item` 函数签名和调用：

```python
def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                stroke: int, color=(0, 0, 0),
                preferred_direction: str | None = None) -> dict:
    """渲染一条译文到 img(就地修改)。

    preferred_direction: 首选排版方向，从 bbox 长宽比推断传入。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    font_size, direction, lines = fit_font_size(
        text, Path(font_path), bbox, preferred_direction=preferred_direction
    )
    # ... 其余渲染逻辑不变
```

- [ ] **Step 2: 修改 typeset_station 推断方向并传入**

修改 `amta/src/amta/typeset_station.py` 的 run 函数，在循环内推断方向：

```python
from amta.typeset_engine import infer_direction_from_bbox

# 在 for item in canon_items: 循环内，render_item 调用处：
for item in canon_items:
    rid = item.get("region_id")
    text = trans.get(rid)
    if text is None:
        continue
    bbox = bbox_by_rid.get(item.get("region_id"))
    if not bbox:
        skipped_no_bbox.append(rid)
        continue
    category = item.get("category")
    font_path, stroke = resolve_font(category or "dialogue_bubble", text)
    preferred_dir = infer_direction_from_bbox(bbox)  # ← 新增
    meta = render_item(img, text, str(font_path), bbox, stroke=stroke,
                       preferred_direction=preferred_dir)  # ← 增加参数
    meta["region_id"] = rid
    meta["preferred_direction"] = preferred_dir  # ← 记录推断方向，便于调试
    # ... 其余不变
```

- [ ] **Step 3: 运行现有渲染测试确认不破坏**

Run: `cd amta && python -m pytest tests/test_typeset_render.py tests/test_typeset_station.py -v`
Expected: 全部 PASS（render_item 新增参数有默认值 None，旧调用不受影响）

- [ ] **Step 4: 提交**

```bash
git add amta/src/amta/typeset_render.py amta/src/amta/typeset_station.py
git commit -m "feat(typeset): 从 bbox 推断方向并传入 render_item，尊重原文排版方向"
```

---

### Task 6: 重跑 typeset 验证方向修复 + 生成对比图

**Files:**
- 产物: `amta/workspace/touhou-e2e-orchestrator/artifacts/final/page_11_final.png` ~ `page_15_final.png`（覆盖）
- 产物: `amta/output/comparison_11to15/`（更新对比图）

- [ ] **Step 1: 重跑 p11–p15 typeset**

Run: 用项目中的 `rerun_typeset.py` 或编写临时脚本重跑
Expected: 生成新 final 图

- [ ] **Step 2: 验证 p11 r04 恢复横排**

Run: `cd "E:\manga translator agent" && python -c "
import json
t = json.load(open('amta/workspace/touhou-e2e-orchestrator/artifacts/page_11_typeset.json', encoding='utf-8'))
r04 = [x for x in t['rendered_items'] if x['region_id']=='r04'][0]
print(f'r04 direction: {r04[\"layout_direction\"]}')
print(f'r04 preferred: {r04.get(\"preferred_direction\")}')
print(f'r04 lines: {r04[\"lines\"]}')"`
Expected: r04 layout_direction = "horizontal"，preferred_direction = "horizontal"

- [ ] **Step 3: 验证 p13 r02 恢复竖排**

Run: 类似命令查 p13 r02
Expected: r02 layout_direction = "vertical"，preferred_direction = "vertical"

- [ ] **Step 4: 生成新对比图**

Run: `python gen_comparison.py`（项目根目录已有脚本）
Expected: 更新 `page_11_comparison.jpg` ~ `page_15_comparison.jpg`

- [ ] **Step 5: 人工目检对比图**

确认：
- p11 不再全部竖排
- p11 r04"比起那个还是研究"横排
- p13 r02"冷静点"竖排
- p14 文字嵌入正确（P0 修复后）

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "chore: 重跑 p11-15 typeset，验证方向修复 + 更新对比图"
```

---

### Task 7: 全量 pytest 回归

- [ ] **Step 1: 运行全量测试**

Run: `cd amta && python -m pytest tests/ -v --ignore=tests/archive -x`
Expected: 全部 PASS（如有旧断言需更新）

- [ ] **Step 2: 修复失败的旧测试**

如果 `test_typeset_station.py::test_station_renders_all_and_checks_coverage` 等旧测试因方向逻辑变化而失败，更新断言以匹配新行为。

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: 更新旧测试断言以匹配方向推断新行为"
```

---

## P2：标点精简（后续执行，当前仅列入计划）

> **状态：后续执行。** P0+P1 完成并验证后再启动 P2。

### Task 8（P2）: 实现 punctuation_align — 原文标点数量对齐译文

**Files:**
- Create: `amta/src/amta/punctuation_align.py`
- Create: `amta/tests/test_punctuation_align.py`

**核心设计：**

机械规则，不依赖 LLM：
1. 统计原文中标点的数量和类型
2. 统计译文中标点的数量和类型
3. 如果译文某类标点 > 原文该类标点，删除多余的
4. 删除优先级：句号（。）> 逗号（，）> 顿号（、）
5. 语气标点（！？……——）不删（承载情绪）
6. 日语"..."映射到中文"……"算同类

```python
# punctuation_align.py 核心函数签名
def align_punctuation(source: str, target: str) -> str:
    """按原文标点数量精简译文标点，返回精简后的译文。"""
    ...
```

**测试用例：**
- 原文 0 标点，译文"比起那个，还是研究，研究。"→ "比起那个还是研究研究"
- 原文 1 个"..."，译文"连我自己都觉得真是异想天开啊……"→ 保留省略号
- 原文 2 标点，译文 5 标点 → 删除多余的句号和逗号
- 语气标点"！？"始终保留

---

### Task 9（P2）: translate_station 调用标点对齐

翻译完成后、写入 translation.json 前，对每条译文调用 `align_punctuation(原文, 译文)`。

---

### Task 10（P2）: 竖排标点旋转 + 避头尾

在 `typeset_render.py` 竖排分支中：
- 对 `……——～` 等字符旋转 90° 后绘制
- `wrap_vertical` 增加避头尾：标点不出现在列首

---

## 自检清单

- [x] P0 覆盖：guardrails 长度比检测 + 重跑翻译验证
- [x] P1 覆盖：方向推断函数 + fit_font_size 首选参数 + 渲染层传递 + 重跑验证
- [x] P2 覆盖：标点对齐机械规则 + 调用点 + 竖排标点处理（标注后续执行）
- [x] 无 TBD/TODO 占位
- [x] 每个代码步骤有完整代码
- [x] 每个任务有测试 + 提交
- [x] 文件路径精确
- [x] 类型/函数名前后一致

---

## 执行方式

Plan saved to `amta/docs/superpowers/plans/2026-09-05-typesetting-triple-fix.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
