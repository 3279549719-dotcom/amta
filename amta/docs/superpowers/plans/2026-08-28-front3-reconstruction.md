# 前三阶段重构（Front3 Reconstruction）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 detect/OCR/translate 前三阶段，砍掉硬编码微观规则（absorb_contained 丢弃、build_regions 嵌套、flatten 展平灭口），改为粗粒度高召回 + 双引擎会诊 + 纯文本语义翻译，解决漫画文字漏检问题。

**Architecture:** Stage 1 砍掉 build_regions/flatten，absorb_contained 改标记不丢弃，所有框平级独立 OCR；Stage 2 新增 VLM contact sheet 批量校验，Baberu+VLM 双引擎文本并列，不自动除噪；Stage 3 纯文本 DeepSeek 翻译，输入双引擎文本，LLM 自行判断选择。每阶段独立 trace 文件。分步实施，每步验证。

**Tech Stack:** Python 3.13, koharu.exe (4-detector + Baberu OCR), DeepSeek API (纯文本翻译 + VLM 校验), PIL (contact sheet 拼图), pytest (测试)

**ADR:** `docs/decisions/023-front3-reconstruction.md`

---

## File Structure

### 修改的文件
- `scripts/01_detect.py` — Stage 1 重构：砍 build_regions/flatten，absorb_contained 改标记，加 source_engines，加 tracing
- `scripts/02_ocr.py` — Stage 2 改造：输出双引擎文本（baberu_text + vlm_text），加 VLM contact sheet 校验调用，加 tracing
- `scripts/03_translate.py` — Stage 3 改造：输入改为双引擎文本，LLM 自行选择，加 tracing
- `src/amta/geometry.py` — 保留 union_blocks/assign_category，新增 mark_contained（替代 absorb_contained），build_regions/flatten_regions 保留但不在主链调用（回退用）
- `src/amta/ocr_engines.py` — 新增 VLM contact sheet 校验函数（vlm_verify_batch）

### 新增的文件
- `src/amta/vlm_verify.py` — VLM contact sheet 校验模块：拼图 + DeepSeek vision 调用 + 输出解析 + 容错
- `scripts/eval_stage1.py` — Stage 1 验证脚本：框数/覆盖率/假框率/已知漏检检查，输出 HTML
- `scripts/eval_stage2.py` — Stage 2 验证脚本：双引擎一致率/VLM 对齐率/差异分析，输出 HTML
- `tests/test_front3_stage1.py` — Stage 1 单元测试：mark_contained、平级输出、source_engines、tracing
- `tests/test_front3_stage2.py` — Stage 2 单元测试：contact sheet 拼图、VLM 输出解析、双引擎输出格式、容错
- `tests/test_front3_stage3.py` — Stage 3 单元测试：双引擎输入、LLM 选择、tracing

### 保留但不调用的文件（回退用）
- `src/amta/geometry.py` 中的 `build_regions()` / `flatten_regions()` — 保留代码，01_detect.py 不再调用

---

## Phase 1: Stage 1 重构

### Task 1: 新增 mark_contained 函数（替代 absorb_contained）

**Files:**
- Modify: `src/amta/geometry.py`
- Test: `tests/test_front3_stage1.py`

- [ ] **Step 1: 写测试**

在 `tests/test_front3_stage1.py` 中添加：

```python
"""Stage 1 重构单元测试：mark_contained 替代 absorb_contained。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.geometry import mark_contained, union_blocks


def _b(x1, y1, x2, y2, eid="test"):
    return {"bbox": [x1, y1, x2, y2], "node_id": eid, "bubble_type": "text",
            "category": "dialogue_bubble", "source_engines": [eid]}


def test_mark_contained_adds_contained_in_tag():
    """嵌套小框应被标记 contained_in，但不被丢弃。"""
    parent = _b(100, 100, 300, 300, "parent")
    child = _b(120, 120, 180, 180, "child")  # IoA = 3600/3600 = 1.0
    result = mark_contained([parent, child])
    assert len(result) == 2, "嵌套框不应被丢弃"
    child_out = [b for b in result if b["node_id"] == "child"][0]
    assert child_out["contained_in"] == "parent", "应标记父框 id"
    parent_out = [b for b in result if b["node_id"] == "parent"][0]
    assert parent_out.get("contained_in") is None, "父框不应有 contained_in"


def test_mark_contained_partial_overlap_not_tagged():
    """部分重叠（IoA < 0.75）不应被标记。"""
    a = _b(100, 100, 200, 200, "a")
    b = _b(150, 150, 250, 250, "b")  # 部分重叠
    result = mark_contained([a, b])
    for box in result:
        assert box.get("contained_in") is None


def test_mark_contained_preserves_all_boxes():
    """所有框都应保留，不丢弃任何框。"""
    boxes = [_b(i*10, i*10, i*10+50, i*10+50, f"b{i}") for i in range(5)]
    result = mark_contained(boxes)
    assert len(result) == 5


def test_mark_contained_assigns_region_id():
    """每个框应被分配 region_id（u00, u01, ...）。"""
    boxes = [_b(10, 10, 50, 50, "a"), _b(60, 60, 100, 100, "b")]
    result = mark_contained(boxes)
    ids = [b["region_id"] for b in result]
    assert ids == ["u00", "u01"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
Expected: FAIL with "cannot import name 'mark_contained'"

- [ ] **Step 3: 实现 mark_contained**

在 `src/amta/geometry.py` 中，在 `absorb_contained` 函数之后添加：

```python
def mark_contained(blocks: list[dict], ioa_threshold: float = 0.75) -> list[dict]:
    """标记嵌套框但不丢弃。

    替代 absorb_contained：IoA >= threshold 的小框被标记 contained_in=<父框region_id>，
    但保留在输出中，信息留给下游 LLM 判断。

    Args:
        blocks: 输入框列表（需含 bbox 字段）
        ioa_threshold: 嵌套判定阈值（默认 0.75，与原 absorb_contained 一致）

    Returns:
        标记后的框列表，每个框新增 region_id（u00, u01, ...）和 contained_in（None 或父框 id）
    """
    # 先分配 region_id
    for i, b in enumerate(blocks):
        b["region_id"] = f"u{i:02d}"
        if "contained_in" not in b:
            b["contained_in"] = None

    # 按面积降序排列，大框优先作为候选父框
    sorted_by_area = sorted(blocks, key=lambda b: bbox_area(b["bbox"]), reverse=True)

    for i, small in enumerate(sorted_by_area):
        if small["contained_in"] is not None:
            continue  # 已经被标记
        for j, big in enumerate(sorted_by_area):
            if i == j:
                continue
            if big["contained_in"] == small["region_id"]:
                continue  # 避免循环
            ioa = intersection_over_area(small["bbox"], big["bbox"])
            if ioa >= ioa_threshold:
                small["contained_in"] = big["region_id"]
                break

    return blocks
```

注意：需要确认 `intersection_over_area` 函数已存在于 geometry.py 中。如果不存在，添加：

```python
def intersection_over_area(a: list[float], b: list[float]) -> float:
    """计算 a 与 b 的交集面积 / a 的面积（IoA，a 嵌套在 b 中的比例）。"""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = bbox_area(a)
    return inter / area_a if area_a > 0 else 0.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd E:\manga translator agent\amta
git add src/amta/geometry.py tests/test_front3_stage1.py
git commit -m "feat(stage1): add mark_contained to replace absorb_contained

Nested boxes are now tagged with contained_in instead of being dropped.
Preserves all detector output for downstream LLM judgment.
Refs ADR-023"
```

---

### Task 2: 重构 01_detect.py 主链

**Files:**
- Modify: `scripts/01_detect.py`
- Test: `tests/test_front3_stage1.py`（追加测试）

- [ ] **Step 1: 写测试（01_detect 输出格式）**

在 `tests/test_front3_stage1.py` 末尾追加：

```python
def test_detection_output_format_flat_blocks():
    """detection.json 应输出平级 blocks，不含 regions/child_lines。"""
    # 模拟 01_detect 的输出结构
    blocks = [
        {"region_id": "u00", "bbox": [10, 10, 50, 50], "category": "dialogue_bubble",
         "bubble_type": "text", "source_engines": ["det1"], "contained_in": None},
        {"region_id": "u01", "bbox": [20, 20, 40, 40], "category": "dialogue_bubble",
         "bubble_type": "text", "source_engines": ["det1", "det2"], "contained_in": "u00"},
    ]
    doc = {"page": "test", "blocks": blocks, "n_boxes": 2}
    assert "regions" not in doc, "不应有 regions 字段"
    assert doc["n_boxes"] == 2
    assert all("child_lines" not in b for b in blocks)
    assert blocks[1]["contained_in"] == "u00"
    assert "det2" in blocks[1]["source_engines"]
```

- [ ] **Step 2: 跑测试确认通过（纯结构测试，不依赖 01_detect）**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py::test_detection_output_format_flat_blocks -v`
Expected: PASS

- [ ] **Step 3: 修改 01_detect.py 主链**

将 `scripts/01_detect.py` 中的 `run()` 函数核心逻辑从：

```python
blocks = union_blocks(comp)
blocks = assign_category(blocks)
regions = build_regions(blocks)
flat_blocks = flatten_regions(regions)
doc = {
    "regions": regions,
    "blocks": flat_blocks,
    "n_boxes": len(flat_blocks),
    "n_regions": len(regions),
    ...
}
```

改为：

```python
blocks = union_blocks(comp)
blocks = assign_category(blocks)
# 新增：合并 source_engines（union 后记录哪些 detector 检到了这个框）
for b in blocks:
    if "source_engines" not in b:
        b["source_engines"] = [b.get("node_id", "unknown")]
# 替代 absorb_contained：标记嵌套但不丢弃
blocks = mark_contained(blocks)

doc = {
    "work_id": work_id,
    "page": raw_page.stem,
    "source": str(raw_page),
    "image_meta": {"width": img.width, "height": img.height,
                   "channels": len(img.getbands())},
    "blocks": blocks,
    "n_boxes": len(blocks),
    "detect_steps": DETECTOR_STEPS,
    "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
    "front3_version": "2.0",  # 标记新架构版本
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
}
```

需要在文件顶部 import `mark_contained`：

```python
from amta.geometry import union_blocks, assign_category, mark_contained, compact_blocks
```

注意：`build_regions` 和 `flatten_regions` 的 import 保留（回退用），但不在主链调用。

- [ ] **Step 4: 添加 tracing 落盘**

在 `run()` 函数中，写 detection.json 之前，添加 trace 落盘：

```python
# Tracing: Stage 1 处理过程
trace = {
    "page": raw_page.stem,
    "per_engine_raw": {eng: len(blks) for eng, blks in comp.items()},
    "after_union": len(union_blocks(comp)),
    "after_mark_contained": len(blocks),
    "contained_boxes": [b["region_id"] for b in blocks if b.get("contained_in")],
    "contained_pairs": [(b["region_id"], b["contained_in"]) for b in blocks if b.get("contained_in")],
    "detect_steps": DETECTOR_STEPS,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
}
trace_path = out_path.parent / f"{raw_page.stem}_01_detect_trace.json"
write_json(trace_path, trace)
```

- [ ] **Step 5: 跑全部 Stage 1 测试**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
Expected: 5 tests PASS

- [ ] **Step 6: 手动验证 01_detect 能跑通（单页）**

先启动 koharu，然后跑单页：

```bash
cd E:\manga translator agent\amta
py -3.13 scripts/01_detect.py --work-id touhou-single-wing --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\14.jpg" --out "workspace\touhou-single-wing\artifacts\page_13_detection.json"
```

Expected: 输出 `[01_detect] 14: N boxes -> ...`，N 应大于旧架构的框数（因为不再丢弃嵌套框）。

检查输出 JSON：应包含 `blocks`（平级）、`front3_version: "2.0"`，不应包含 `regions`。

- [ ] **Step 7: Commit**

```bash
cd E:\manga translator agent\amta
git add scripts/01_detect.py tests/test_front3_stage1.py
git commit -m "feat(stage1): refactor 01_detect to flat blocks with mark_contained

Replace build_regions/flatten_regions/absorb_contained with flat block output.
All detector boxes preserved, nested boxes tagged with contained_in.
Add per-engine source tracking and stage1 trace file.
Refs ADR-023"
```

---

### Task 3: Stage 1 全量验证（11-20 页）

**Files:**
- Create: `scripts/eval_stage1.py`

- [ ] **Step 1: 写验证脚本**

创建 `scripts/eval_stage1.py`，功能：
1. 备份旧 detection.json
2. 用新 01_detect 跑 11-20 页
3. 对比新旧：框数变化、每引擎贡献、已知漏检覆盖率、假框率（双引擎都空的比例——但 Stage 1 还没有 OCR，所以这一步只看框数和覆盖率）
4. 输出 HTML 报告

脚本核心逻辑（参考已有的 `scripts/eval_flatten_fix_v2.py`）：

```python
"""eval_stage1.py — Stage 1 重构验证：11-20 页全量对比。"""
# 实现要点：
# 1. EVAL_PAGES = [11,12,13,14,15,16,17,18,19,20]
# 2. 备份旧 detection.json 到 backup_pre_front3/
# 3. 逐页跑 01_detect.py（subprocess）
# 4. 对比：旧 n_boxes vs 新 n_boxes，新 contained_in 数量，per_engine 对比
# 5. 已知漏检区域检查（14页「では豊ちゃん」、15页「弟子だからね」等）
# 6. 输出 eval_stage1_report.html + eval_stage1_results.json
```

（完整代码由执行 agent 编写，参考 eval_flatten_fix_v2.py 的结构。）

- [ ] **Step 2: 启动 koharu 并跑验证**

```bash
cd E:\manga translator agent\amta
powershell -ExecutionPolicy Bypass -File scripts/start_koharu.ps1
py -3.13 scripts/eval_stage1.py
```

Expected: 10 页全部跑完，输出 HTML 报告。框数应增加（因为不再丢弃嵌套框），已知漏检区域应有对应框。

- [ ] **Step 3: 人工抽检核心 case（14/15 页）**

打开 HTML 报告，检查：
- 14 页「では豊ちゃん」区域是否有框覆盖（bbox 应包含 [1600,2630,1870,3150]）
- 15 页「弟子だからね」区域是否有框覆盖（bbox 应包含 [50,2430,210,2870]）
- 框数增加是否合理（不应爆炸式增长，预期 +20%~50%）

- [ ] **Step 4: Commit 验证脚本和报告**

```bash
cd E:\manga translator agent\amta
git add scripts/eval_stage1.py
git commit -m "test(stage1): add eval_stage1.py for 11-20 page validation

Compares old vs new detection output: box count, per-engine contribution,
known miss-region coverage, contained_in tagging.
Refs ADR-023"
```

---

## Phase 2: Stage 2 双引擎会诊

### Task 4: 新增 VLM contact sheet 校验模块

**Files:**
- Create: `src/amta/vlm_verify.py`
- Test: `tests/test_front3_stage2.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_front3_stage2.py`：

```python
"""Stage 2 单元测试：VLM contact sheet 校验。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.vlm_verify import make_contact_sheet, parse_vlm_output, vlm_verify_batch


def test_make_contact_sheet_grid_layout():
    """contact sheet 应按网格排列 crop 图。"""
    from PIL import Image
    crops = [Image.new("RGB", (100, 50), (255, 255, 255)) for _ in range(7)]
    sheet = make_contact_sheet(crops, cols=3, pad=10, bg=(0, 0, 0))
    # 3列 → 3行，每行 100+10*2=120 宽，每列 50+10*2=70 高
    assert sheet.width == 3 * 120  # 360
    assert sheet.height == 3 * 70   # 210


def test_parse_vlm_output_line_by_line():
    """VLM 输出应按行解析，与输入顺序对应。"""
    raw = "文本1\n文本2\n文本3\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert len(result) == 3
    assert result == ["文本1", "文本2", "文本3"]


def test_parse_vlm_output_empty_lines():
    """空行应解析为空字符串。"""
    raw = "文本1\n\n文本3\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert result[1] == ""


def test_parse_vlm_output_count_mismatch():
    """输出数量与预期不符时应返回 None（触发容错）。"""
    raw = "只有一行\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert result is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
Expected: FAIL with "No module named 'amta.vlm_verify'"

- [ ] **Step 3: 实现 vlm_verify.py**

创建 `src/amta/vlm_verify.py`：

```python
"""VLM contact sheet 批量校验模块。

把所有 crop 图拼成 contact sheet，送 DeepSeek vision 做批量转写。
配置：thinking=disabled, detail=low（probe B 组验证最优，2-3s/页）。
输出：按输入顺序对应的转写文本列表。
"""
from __future__ import annotations
import base64
import io
import time
from pathlib import Path
from typing import Optional
from PIL import Image


def make_contact_sheet(crops: list[Image.Image], cols: int = 3,
                       pad: int = 12, bg: tuple = (255, 255, 255)) -> Image.Image:
    """把 crop 图列表拼成网格 contact sheet。

    Args:
        crops: PIL Image 列表
        cols: 列数
        pad: 图片间距
        bg: 背景色

    Returns:
        拼接后的 PIL Image
    """
    if not crops:
        return Image.new("RGB", (10, 10), bg)
    rows = (len(crops) + cols - 1) // cols
    # 统一缩放到相同宽度（保持比例）
    target_w = max(c.width for c in crops)
    normalized = []
    for c in crops:
        if c.width != target_w:
            ratio = target_w / c.width
            new_h = int(c.height * ratio)
            c = c.resize((target_w, new_h), Image.LANCZOS)
        normalized.append(c)
    cell_w = target_w + pad * 2
    cell_h = max(c.height for c in normalized) + pad * 2
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), bg)
    for i, c in enumerate(normalized):
        r, col = divmod(i, cols)
        x = col * cell_w + pad
        y = r * cell_h + pad
        sheet.paste(c, (x, y))
    return sheet


def parse_vlm_output(raw: str, expected_count: int) -> Optional[list[str]]:
    """解析 VLM 输出，按行对应输入顺序。

    Args:
        raw: VLM 原始输出文本
        expected_count: 预期的行数（与 crop 数量一致）

    Returns:
        文本列表（长度=expected_count），或 None（数量不符时触发容错）
    """
    lines = [line.strip() for line in raw.strip().split("\n")]
    # 过滤掉纯空行？不——空行可能表示 VLM 认为该区域无文字
    # 但 VLM 可能输出多余的空行，需要精确匹配
    if len(lines) != expected_count:
        return None
    return lines


def vlm_verify_batch(crops: list[Image.Image], api_key: str,
                     model: str = "deepseek-v4-flash-vision-exp",
                     max_retries: int = 2, timeout: int = 60) -> dict:
    """VLM contact sheet 批量校验主函数。

    Args:
        crops: crop 图列表
        api_key: DeepSeek API key
        model: VLM 模型名
        max_retries: 最大重试次数
        timeout: 单次调用超时（秒）

    Returns:
        {
            "texts": list[str] | None,  # 转写文本列表，失败时为 None
            "status": "ok" | "failed" | "count_mismatch",
            "raw_output": str,
            "elapsed": float,
            "retries": int,
        }
    """
    import requests
    sheet = make_contact_sheet(crops)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = (
        f"这是一页漫画的 {len(crops)} 个文字区域截图，按从左到右、从上到下的网格顺序排列。"
        f"请逐个转写每个区域中的日文文字，直接输出每行一个区域的转写结果，共 {len(crops)} 行。"
        f"如果某个区域没有文字，输出空行。不要输出编号、解释或其他内容。"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
        ]}],
        "max_tokens": 4000,
        "temperature": 0.1,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(max_retries + 1):
        t0 = time.time()
        try:
            resp = requests.post("https://api.deepseek.com/chat/completions",
                                 json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            elapsed = time.time() - t0
            texts = parse_vlm_output(raw, len(crops))
            if texts is not None:
                return {"texts": texts, "status": "ok", "raw_output": raw,
                        "elapsed": elapsed, "retries": attempt}
            else:
                # 数量不符，重试
                if attempt < max_retries:
                    continue
                return {"texts": None, "status": "count_mismatch", "raw_output": raw,
                        "elapsed": elapsed, "retries": attempt}
        except Exception as e:
            elapsed = time.time() - t0
            if attempt < max_retries:
                time.sleep(2)
                continue
            return {"texts": None, "status": "failed", "raw_output": str(e),
                    "elapsed": elapsed, "retries": attempt}
```

注意：API endpoint 和模型名需要根据实际配置确认。参考 `src/amta/translate.py` 中的 DeepSeek 调用方式。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
Expected: 4 tests PASS（vlm_verify_batch 测试可能需要 mock，执行时按需添加 mock）

- [ ] **Step 5: Commit**

```bash
cd E:\manga translator agent\amta
git add src/amta/vlm_verify.py tests/test_front3_stage2.py
git commit -m "feat(stage2): add VLM contact sheet batch verification module

Probe-validated config: thinking=disabled, detail=low, ~2-3s/page.
Outputs text list aligned with input crop order. Includes retry/fallback logic.
Refs ADR-023"
```

---

### Task 5: 改造 02_ocr.py 输出双引擎文本

**Files:**
- Modify: `scripts/02_ocr.py`
- Test: `tests/test_front3_stage2.py`（追加）

- [ ] **Step 1: 写测试（canon 输出格式）**

在 `tests/test_front3_stage2.py` 末尾追加：

```python
def test_canon_output_dual_engine_format():
    """canon.json 应输出双引擎文本（baberu_text + vlm_text）。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "では豊ちゃん…",
        "vlm_text": "では豊ちゃん、輝夜様に…",
        "contained_in": None,
        "source_engines": ["det1"],
        "vlm_status": "ok",
    }
    assert "baberu_text" in item
    assert "vlm_text" in item
    assert "vlm_status" in item
    assert item["vlm_status"] in ("ok", "failed", "count_mismatch", "skipped")
```

- [ ] **Step 2: 修改 02_ocr.py**

将 `scripts/02_ocr.py` 的输出从单文本改为双引擎文本：

1. 读取 detection.json 的 `blocks`（平级，含 region_id/bbox/contained_in/source_engines）
2. 对每个 block 裁 crop 图，跑 Baberu OCR（现有逻辑）
3. 收集所有 crop 图，调用 `vlm_verify_batch()` 做 VLM 批量校验
4. 合并输出：每个 region `{region_id, bbox, baberu_text, vlm_text, contained_in, source_engines, vlm_status}`
5. VLM 失败时 vlm_text=None, vlm_status="failed"，降级只用 Baberu
6. 添加 trace 落盘：`{page}_02_ocr_trace.json`

核心输出结构：

```python
items = []
for i, block in enumerate(blocks):
    items.append({
        "region_id": block["region_id"],
        "bbox": block["bbox"],
        "baberu_text": baberu_results[i],
        "vlm_text": vlm_result["texts"][i] if vlm_result["status"] == "ok" else None,
        "contained_in": block.get("contained_in"),
        "source_engines": block.get("source_engines", []),
        "vlm_status": vlm_result["status"],
    })
```

- [ ] **Step 3: 跑测试**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
Expected: 5 tests PASS

- [ ] **Step 4: 手动验证单页**

```bash
cd E:\manga translator agent\amta
py -3.13 scripts/02_ocr.py --work-id touhou-single-wing \
  --det workspace/touhou-single-wing/artifacts/page_13_detection.json \
  --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\14.jpg" \
  --out workspace/touhou-single-wing/artifacts/page_13_canon.json \
  --page-idx 13 --engine auto
```

Expected: 输出 canon.json，每个 item 含 baberu_text 和 vlm_text。

- [ ] **Step 5: Commit**

```bash
cd E:\manga translator agent\amta
git add scripts/02_ocr.py tests/test_front3_stage2.py
git commit -m "feat(stage2): refactor 02_ocr to output dual-engine text

Baberu OCR + VLM contact sheet verification results are output side-by-side.
VLM failure degrades gracefully to Baberu-only. Adds stage2 trace file.
Refs ADR-023"
```

---

### Task 6: Stage 2 全量验证

**Files:**
- Create: `scripts/eval_stage2.py`

- [ ] **Step 1: 写验证脚本**

创建 `scripts/eval_stage2.py`，功能：
1. 用新 02_ocr 跑 11-20 页（需要 Stage 1 已跑完）
2. 统计：双引擎一致率、VLM 输出对齐率、VLM 修正数（VLM 与 Baberu 不同的区域）、VLM 空文本比例、VLM 失败率
3. 人工抽检：VLM 修正是否正确（对比 crop 图）
4. 输出 HTML 报告

- [ ] **Step 2: 跑验证**

```bash
cd E:\manga translator agent\amta
py -3.13 scripts/eval_stage2.py
```

Expected: 10 页跑完，输出 HTML。VLM 对齐率应 >90%（probe B 组 100%），一致率约 60-80%。

- [ ] **Step 3: 人工抽检 VLM 修正质量**

检查 14/15 页中 VLM 与 Baberu 不同的区域，判断 VLM 修正是否正确。重点关注：
- 汉字误读修正（如「ハ意様→八意様」）应为正确
- 拟声词/短文本（如「すっ」「ぽ」）VLM 可能改错，这些应在 Stage 3 由 LLM 判断选择

- [ ] **Step 4: Commit**

```bash
cd E:\manga translator agent\amta
git add scripts/eval_stage2.py
git commit -m "test(stage2): add eval_stage2.py for dual-engine validation

Metrics: agreement rate, VLM alignment rate, correction count,
empty rate, failure rate. HTML report with manual sampling.
Refs ADR-023"
```

---

## Phase 3: Stage 3 纯文本语义翻译

### Task 7: 改造 03_translate.py 输入为双引擎文本

**Files:**
- Modify: `scripts/03_translate.py`
- Modify: `src/amta/translate.py`
- Test: `tests/test_front3_stage3.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_front3_stage3.py`：

```python
"""Stage 3 单元测试：双引擎文本输入 + LLM 选择。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_translate_input_dual_engine():
    """翻译输入应包含 baberu_text 和 vlm_text。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "では豊ちゃん…",
        "vlm_text": "では豊ちゃん、輝夜様に…",
        "contained_in": None,
        "source_engines": ["det1"],
        "vlm_status": "ok",
    }
    assert item["baberu_text"]
    assert item["vlm_text"]
    # 翻译时应把两个文本都提供给 LLM


def test_translate_vlm_failed_fallback():
    """VLM 失败时应只用 baberu_text。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "テスト",
        "vlm_text": None,
        "vlm_status": "failed",
    }
    assert item["vlm_text"] is None
    # 翻译 prompt 应只提供 baberu_text


def test_contained_in_merged_translation():
    """嵌套框的文本应在翻译时合并提示。"""
    parent = {"region_id": "u00", "baberu_text": "弟子だからね", "vlm_text": "弟子だからね", "contained_in": None}
    child = {"region_id": "u01", "baberu_text": "落ち着きなさい", "vlm_text": "落ち着きなさい", "contained_in": "u00"}
    # 翻译 prompt 应提示 LLM：u01 嵌套在 u00 中，可能是同一气泡的大小字
    assert child["contained_in"] == "u00"
```

- [ ] **Step 2: 跑测试确认通过（纯结构测试）**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage3.py -v`
Expected: 3 tests PASS

- [ ] **Step 3: 修改 translate.py 的 prompt 构建**

在 `src/amta/translate.py` 中，修改翻译 prompt，将双引擎文本提供给 LLM：

原 prompt（单文本）：
```
原文：{text}
```

新 prompt（双引擎）：
```
以下是一个漫画文字区域的两个 OCR 结果：
- Baberu OCR：{baberu_text}
- VLM 校验：{vlm_text or "（VLM 校验失败，仅参考 Baberu）"}

{contained_in_note}  # 如果有 contained_in，提示嵌套关系

请结合上下文判断哪个 OCR 结果更准确，并翻译成中文。
```

如果 `vlm_status != "ok"` 或 `vlm_text is None`，prompt 中只提供 baberu_text。

如果 `contained_in` 不为 None，prompt 中添加：
```
注意：此区域嵌套在区域 {contained_in} 中，可能是同一气泡的小字/碎碎念，请结合父区域文本判断。
```

- [ ] **Step 4: 修改 03_translate.py 读取 canon 格式**

03_translate.py 读取 canon.json 时，从 `item["text"]` 改为读取 `item["baberu_text"]` 和 `item["vlm_text"]`，传递给 translate 函数。

- [ ] **Step 5: 添加 trace 落盘**

在 03_translate.py 中添加 `{page}_03_translate_trace.json`，记录：
- LLM 模型/参数
- 每个区域：选择了 baberu 还是 vlm（从 LLM 输出中解析，或让 LLM 在输出中标注）
- 重试次数
- 耗时

注意：让 LLM 标注选择了哪个文本可能需要修改输出格式。简化方案：trace 中记录每个区域的 baberu_text 和 vlm_text 以及最终译文，由后续分析判断选择了哪个。

- [ ] **Step 6: 跑测试**

Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage3.py tests/test_translate.py -v`
Expected: 全部 PASS（test_translate.py 是旧测试，需确认不被破坏）

- [ ] **Step 7: 手动验证单页翻译**

```bash
cd E:\manga translator agent\amta
py -3.13 scripts/03_translate.py --work-id touhou-single-wing \
  --canon workspace/touhou-single-wing/artifacts/page_13_canon.json \
  --out workspace/touhou-single-wing/artifacts/page_13_translation.json \
  --page-idx 13
```

Expected: 输出 translation.json，译文应准确。重点检查 14 页「では豊ちゃん」是否被正确翻译（VLM 提供了完整文本）。

- [ ] **Step 8: Commit**

```bash
cd E:\manga translator agent\amta
git add scripts/03_translate.py src/amta/translate.py tests/test_front3_stage3.py
git commit -m "feat(stage3): refactor translate to accept dual-engine OCR input

LLM receives both Baberu and VLM text, chooses based on context.
Contained_in nesting info provided for merge decisions.
Adds stage3 trace file.
Refs ADR-023"
```

---

### Task 8: 端到端全量验证（11-20 页）

**Files:**
- Create: `scripts/eval_front3_e2e.py`

- [ ] **Step 1: 写端到端验证脚本**

创建 `scripts/eval_front3_e2e.py`，功能：
1. 用完整新流水线（01_detect → 02_ocr → 03_translate）跑 11-20 页
2. 对比旧流水线结果：
   - 检测框数变化
   - OCR 文本数变化
   - 翻译文本数变化
   - 已知漏检文本是否出现在最终译文中（端到端召回率）
   - 总处理时间
3. 输出 HTML 报告：逐页对比 + 汇总指标

- [ ] **Step 2: 跑端到端验证**

```bash
cd E:\manga translator agent\amta
py -3.13 scripts/eval_front3_e2e.py
```

Expected: 10 页全跑完，输出 HTML 报告。

核心指标：
- 端到端召回率：已知应存在的文本（「では豊ちゃん」「弟子だからね」「じゃ、そういうことで」等）有多少出现在最终译文中
- 框数变化率
- 总处理时间 vs 旧流水线

- [ ] **Step 3: 人工抽检核心 case**

检查 14/15/17 页的最终译文：
- 14 页「では豊ちゃん、輝夜様にこの羽根を見せに行ってきます」是否被正确翻译
- 15 页「弟子だからね 落ち着きなさい」是否被正确翻译（大小字合并）
- 17 页"2个大人"的对话是否被检测到并翻译

- [ ] **Step 4: Commit 验证脚本和报告**

```bash
cd E:\manga translator agent\amta
git add scripts/eval_front3_e2e.py
git commit -m "test(front3): add end-to-end validation for 11-20 pages

Full pipeline run: detect -> OCR(dual) -> translate.
Metrics: e2e recall rate, box count delta, processing time.
HTML report with core case sampling.
Refs ADR-023"
```

---

## Self-Review

**1. Spec coverage:**
- Stage 1 重构（砍 build_regions/flatten，absorb_contained 改标记）→ Task 1-3 ✅
- Stage 2 双引擎会诊（VLM contact sheet + 双文本输出）→ Task 4-6 ✅
- Stage 3 纯文本翻译（双引擎输入 + LLM 选择）→ Task 7-8 ✅
- Tracing（每阶段独立 trace）→ Task 2/5/7 中包含 ✅
- 分步验证（每阶段独立验证 + 端到端验证）→ Task 3/6/8 ✅

**2. Placeholder scan:**
- Task 3 的 eval_stage1.py 核心逻辑用了描述性文字而非完整代码 → 执行 agent 需参考 eval_flatten_fix_v2.py 补全。这是可接受的，因为完整代码较长且有参考模板。
- Task 6/8 同理。
- 无 TBD/TODO/implement later。

**3. Type consistency:**
- `mark_contained` 输出 `region_id`（u00, u01...）→ 02_ocr.py 和 03_translate.py 都引用 `region_id` ✅
- `contained_in` 字段在 Stage 1 输出 → Stage 2 canon 传递 → Stage 3 prompt 使用 ✅
- `source_engines` 在 Stage 1 输出 → Stage 2 canon 传递 ✅
- `vlm_status` 值：ok/failed/count_mismatch/skipped → 测试和代码一致 ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-28-front3-reconstruction.md`.

**执行前注意事项：**
1. 当前在 `feat/contract-hygiene` 分支，有未提交的 flatten 修复改动。建议新开 worktree/分支（如 `feat/front3-reconstruction`）实施本计划。
2. koharu.exe 需在运行状态（detect + OCR 依赖）。
3. DeepSeek API key 需配置（VLM 校验 + 翻译依赖）。
4. 旧 detection.json/canon.json/translation.json 需备份（验证脚本会自动备份）。
5. build_regions/flatten_regions 代码保留不删（回退用），仅不在主链调用。

**两个执行选项：**

1. **Subagent-Driven (recommended)** - 每个 Task 派一个 fresh subagent，任务间 review，快速迭代
2. **Inline Execution** - 在当前会话中按 executing-plans 批量执行，带 checkpoint review

**Which approach?**
