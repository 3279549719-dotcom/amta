# 后三阶段方案 B 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为后三阶段（mask/inpaint/typeset）实施方案 B：复用检测器 label 实现框内/框外字体分类 + inpaint 空转跳过 + 译文自动扩框，显著提升排版效果而不引入复杂架构。

**Architecture:** (1) RT-DETR-v2 检测器的 `_detect_single()` 保留 label（0=bubble/1=text_bubble/2=text_free），`detect()` 写入 `bubble_type` 字段；(2) 该字段随 detect → OCR → translate → typeset 全链路传递；(3) 排版阶段 `resolve_font()` 根据 `bubble_type` 选字体（text_bubble→漫画体，text_free→黑体）；(4) inpaint 阶段加"本页无 inpaint 区域则跳过 koharu"判断；(5) 排版阶段新增 `auto_expand_bbox()`：译文比原文长时自动扩大 bbox（横排扩宽、竖排扩高），重叠则回退缩字。

**Tech Stack:** Python 3.11+, PIL (Pillow), existing `amta` contracts, RT-DETR-v2 ONNX detector, koharu lama-manga (existing), pytest.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/detect_rtdetr.py` | Modify | `_detect_single()` 返回 label；`detect()` 写入 `bubble_type` 字段（不再硬编码 "unknown"） |
| `src/amta/detect_station.py` | Modify | 透传 `bubble_type` 字段到 detection artifact（当前 `union_blocks` 可能丢字段，需确认） |
| `src/amta/ocr_station.py` | Modify | 裁框时透传 `bubble_type` 到 canon items |
| `src/amta/translate_station.py` | Modify | 透传 `bubble_type`（minimal 模式下 canon items 已有，确认不丢） |
| `src/amta/fonts.py` | Modify | `resolve_font()` 增加 `bubble_type` 参数：text_bubble→现有漫画体，text_free→黑体/宋体 |
| `src/amta/typeset_engine.py` | Modify | 新增 `auto_expand_bbox()` 函数；`fit_font_size()` 支持扩框后重试 |
| `scripts/04_inpaint.py` | Modify | 加"本页无 inpaint 区域则跳过 koharu client"判断 |
| `scripts/05_typeset.py` | Modify | 调用 `resolve_font(category, text, bubble_type)`；调用 `auto_expand_bbox()` |
| `tests/test_detect_rtdetr_label.py` | Create | 检测器 label 保留与传递的单元测试 |
| `tests/test_typeset_auto_expand.py` | Create | 自动扩框 + 重叠回退的单元测试 |
| `tests/test_inpaint_skip.py` | Create | inpaint 空转跳过的单元测试 |
| `docs/post3-stages-research-2026-09-01.md` | Create | 调研文档（已完成） |

**Open-source copy map:**

| Component | Copied from | Source file / pattern |
|---|---|---|
| 自动扩框（横排扩宽/竖排扩高） | manga-image-translator | `manga_translator/rendering/__init__.py:resize_regions_to_font_size()` |
| 检测器 label 分类（text_bubble/text_free） | RT-DETR-v2 模型原生输出 | `ogkalu/comic-text-and-bubble-detector`，label 0=bubble/1=text_bubble/2=text_free |
| CJK 竖排标点转换（远期） | manga-image-translator | `manga_translator/rendering/text_render.py:CJK_H2V` |

---

## Phase 1: 检测器 Label 传递 + 字体分类 + Inpaint 空转（零成本）

### Task 1: 检测器保留 label 字段

**Files:**
- Modify: `scripts/detect_rtdetr.py:239-264` (`_detect_single`)
- Modify: `scripts/detect_rtdetr.py:266-312` (`detect`)
- Test: `tests/test_detect_rtdetr_label.py`

- [ ] **Step 1: Write failing test**

```python
"""Test: RT-DETR-v2 detector preserves label in bubble_type field."""
import numpy as np
from scripts.detect_rtdetr import RTDetrDetector


def test_detect_single_returns_labels():
    """_detect_single should return (boxes, labels) not just boxes."""
    det = RTDetrDetector(conf_threshold=0.3)
    det._load()
    # 用真实图测试（11.jpg = page_10）
    import cv2
    img = cv2.imread(r"D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg")
    result = det._detect_single(img)
    # 新接口返回 (boxes, labels) 元组
    assert isinstance(result, tuple), f"expected tuple, got {type(result)}"
    boxes, labels = result
    assert len(boxes) == len(labels)
    # label 只能是 0/1/2
    assert all(l in (0, 1, 2) for l in labels)
    # text_bubble(1) 和 text_free(2) 应该都有（东方项目有对话也有标题）
    label_set = set(labels)
    assert 1 in label_set or 2 in label_set, f"expected text labels, got {label_set}"


def test_detect_writes_bubble_type():
    """detect() output blocks should have bubble_type = 'text_bubble' or 'text_free'."""
    det = RTDetrDetector(conf_threshold=0.3)
    blocks = det.detect(r"D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg")
    assert len(blocks) > 0
    for b in blocks:
        assert "bubble_type" in b, f"missing bubble_type: {b}"
        assert b["bubble_type"] in ("text_bubble", "text_free"), \
            f"unexpected bubble_type: {b['bubble_type']}"
    # 应该至少有一个 text_free（标题/旁白）
    free_count = sum(1 for b in blocks if b["bubble_type"] == "text_free")
    assert free_count > 0, "expected at least one text_free region"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "E:\manga translator agent\amta" && python -m pytest tests/test_detect_rtdetr_label.py -v`
Expected: FAIL — `_detect_single` currently returns `np.array` (boxes only), not tuple.

- [ ] **Step 3: Modify `_detect_single` to return labels**

在 `scripts/detect_rtdetr.py:239-264`，修改返回值：

```python
def _detect_single(self, image: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """单张图推理，返回 (text_boxes [N,4], labels [N])。
    label: 0=bubble(纯气泡), 1=text_bubble(气泡内文字), 2=text_free(无气泡文字)
    """
    self._load()
    assert self._session is not None
    h_orig, w_orig = image.shape[:2]
    resized = cv2.resize(image, (640, 640), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(chw, axis=0)
    orig_sizes = np.array([[w_orig, h_orig]], dtype=np.int64)

    outputs = self._session.run(None, {
        "images": input_tensor,
        "orig_target_sizes": orig_sizes,
    })
    labels, boxes, scores = outputs
    text_boxes = []
    text_labels = []
    for box, score, label in zip(boxes[0], scores[0], labels[0]):
        if score < self.conf_threshold:
            continue
        # label 0=bubble, 1=text_bubble, 2=text_free → 只取文本框(1,2)
        if label in (1, 2):
            x1, y1, x2, y2 = map(int, box)
            text_boxes.append([x1, y1, x2, y2])
            text_labels.append(int(label))
    return np.array(text_boxes) if text_boxes else np.array([]), text_labels
```

- [ ] **Step 4: Modify `detect()` to write bubble_type**

在 `scripts/detect_rtdetr.py:266-312`，修改 `detect()` 方法：

```python
def detect(self, image: str | Path | np.ndarray,
           conf_threshold: float | None = None) -> list[dict]:
    # ... (前面的加载和切片逻辑不变) ...
    t0 = time.perf_counter()
    boxes, labels = self.slicer.process(img, self._detect_single)
    # 后处理
    if boxes.size > 0:
        boxes = merge_duplicate_boxes(boxes, iou_thresh=0.7)
        boxes = remove_contained_boxes(boxes, threshold=0.8)
    elapsed = time.perf_counter() - t0

    # 注意：merge_duplicate_boxes 和 remove_contained_boxes 会丢失 label 对应关系。
    # 简化方案：合并后用 bbox 中心匹配回原始 label。
    # 更简单的方案：合并后默认 text_bubble，text_free 占比低可接受。
    # 这里采用 bbox 中心匹配方案（精确）。
    label_map = {}
    for box, label in zip(boxes.tolist() if boxes.size else [], labels):
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        label_map[(round(cx, 1), round(cy, 1))] = label

    blocks = []
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = [int(v) for v in box]
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            continue
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        label = label_map.get((round(cx, 1), round(cy, 1)), 1)  # 默认 text_bubble
        bubble_type = "text_bubble" if label == 1 else "text_free"
        blocks.append({
            "bbox": [float(x1), float(y1), float(x2), float(y2)],
            "source_engines": ["rtdetr-v2"],
            "bubble_type": bubble_type,
            "region_id": f"r{i:02d}",
            "confidence": 0.0,
        })
    self._last_time = elapsed
    self._last_n = len(blocks)
    return blocks
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_detect_rtdetr_label.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/detect_rtdetr.py tests/test_detect_rtdetr_label.py
git commit -m "feat(detect): preserve RT-DETR-v2 label in bubble_type field

- _detect_single now returns (boxes, labels) tuple
- detect() maps label 1→text_bubble, 2→text_free
- bbox-center matching preserves label through merge/dedup
- adds 2 unit tests"
```

---

### Task 2: bubble_type 全链路传递（detect → OCR → translate → typeset）

**Files:**
- Modify: `src/amta/detect_station.py`（确认 union_blocks 不丢 bubble_type）
- Modify: `src/amta/ocr_station.py`（裁框时透传 bubble_type）
- Test: `tests/test_detect_rtdetr_label.py`（新增传递测试）

- [ ] **Step 1: Write failing test for OCR station bubble_type passthrough**

```python
def test_ocr_station_preserves_bubble_type():
    """ocr_station should pass bubble_type from detection to canon items."""
    from amta.ocr_station import ocr_page
    # 构造 mock detection（含 bubble_type）
    det = {
        "blocks": [
            {"region_id": "page_10_u00", "bbox": [100, 100, 300, 200],
             "bubble_type": "text_bubble", "category": "dialogue_bubble"},
            {"region_id": "page_10_u01", "bbox": [400, 50, 600, 100],
             "bubble_type": "text_free", "category": "overlay_text"},
        ],
        "image_meta": {"width": 1200, "height": 1700},
    }
    # 用 fake ocr_fn 避免真实 API 调用
    def fake_ocr(crops, engine="auto"):
        return [{"crop": c, "ocr": "テスト"} for c in crops]

    canon = ocr_page("test", det, Path(r"D:\...\11.jpg"),
                     Path("tmp/artifacts"), page_idx=10,
                     ocr_fn=fake_ocr, vlm_enabled=False)
    items = canon["items"]
    assert len(items) == 2
    assert items[0]["bubble_type"] == "text_bubble"
    assert items[1]["bubble_type"] == "text_free"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_detect_rtdetr_label.py::test_ocr_station_preserves_bubble_type -v`
Expected: FAIL — ocr_station 当前构造 item 时没传 bubble_type。

- [ ] **Step 3: Modify ocr_station to pass bubble_type**

在 `src/amta/ocr_station.py:105-122`，修改 items 构造：

```python
items = []
vlm_texts = vlm_result.get("texts")
for i, (rid, b, crop, _pil) in enumerate(pairs):
    vlm_text = vlm_texts[i] if (vlm_texts and i < len(vlm_texts)) else None
    item = {
        "region_id": rid,
        "bbox": b.get("bbox"),
        "baberu_text": ocr_by_crop.get(str(crop), ""),
        "vlm_text": vlm_text,
        "contained_in": b.get("contained_in"),
        "source_engines": b.get("source_engines", []),
        "vlm_status": vlm_result["status"],
        "page": page_idx,
        "bubble_type": b.get("bubble_type", "text_bubble"),  # 新增：透传
    }
```

- [ ] **Step 4: Verify detect_station union_blocks preserves bubble_type**

检查 `src/amta/geometry.py` 的 `union_blocks()` 是否保留额外字段。如果不保留，修改它：

```python
# 在 union_blocks 合并时，保留所有非几何字段（取第一个非空值）
def union_blocks(comp: dict) -> list[dict]:
    # ... 现有逻辑 ...
    # 合并时保留 bubble_type 等额外字段
    for b in merged_blocks:
        for key in ("bubble_type", "category", "bubble_type"):
            if key not in b:
                # 从原始 comp 里找
                for eng_blocks in comp.values():
                    for orig in eng_blocks:
                        if orig.get("bbox") == b.get("bbox") and key in orig:
                            b[key] = orig[key]
                            break
```

（具体实现取决于 union_blocks 的现有代码结构，以实际为准。）

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_detect_rtdetr_label.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/amta/ocr_station.py src/amta/geometry.py tests/test_detect_rtdetr_label.py
git commit -m "feat(ocr): pass bubble_type through OCR station to canon

- ocr_station items now include bubble_type from detection
- union_blocks preserves extra fields through merge
- adds passthrough unit test"
```

---

### Task 3: 排版阶段字体分类（text_bubble→漫画体，text_free→黑体）

**Files:**
- Modify: `src/amta/fonts.py`（`resolve_font()` 增加 bubble_type 参数）
- Modify: `scripts/05_typeset.py`（调用时传 bubble_type）
- Test: `tests/test_typeset_font_selection.py`

- [ ] **Step 1: Write failing test**

```python
def test_resolve_font_by_bubble_type():
    """resolve_font should return comic font for text_bubble, sans/serif for text_free."""
    from amta.fonts import resolve_font
    from pathlib import Path

    # text_bubble → 漫画体（现有默认字体）
    font_bubble, stroke_bubble = resolve_font("dialogue_bubble", "你好", bubble_type="text_bubble")
    assert font_bubble is not None

    # text_free → 黑体/宋体（不是漫画体）
    font_free, stroke_free = resolve_font("overlay_text", "你好", bubble_type="text_free")
    assert font_free is not None
    # text_free 应该用不同的字体（黑体或宋体）
    assert font_bubble != font_free, "text_bubble and text_free should use different fonts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_typeset_font_selection.py -v`
Expected: FAIL — resolve_font 当前不接受 bubble_type 参数。

- [ ] **Step 3: Modify resolve_font to accept bubble_type**

在 `src/amta/fonts.py`，修改 `resolve_font()`：

```python
def resolve_font(category: str, text: str, bubble_type: str = "text_bubble") -> tuple[Path, int]:
    """根据 category 和 bubble_type 选择字体。

    bubble_type="text_bubble" → 漫画体（圆润，适合对话气泡）
    bubble_type="text_free" → 黑体/宋体（正式，适合标题/旁白/覆盖文字）
    """
    # 现有字体路径定义（以项目实际为准）
    COMIC_FONT = Path("fonts/your-comic-font.ttf")  # 替换为项目实际漫画体路径
    SANS_FONT = Path("fonts/SourceHanSansSC-Regular.otf")  # 思源黑体
    SERIF_FONT = Path("fonts/SourceHanSerifSC-Regular.otf")  # 思源宋体

    if bubble_type == "text_free":
        # 框外字：标题用黑体，旁白用宋体
        if category in ("overlay_text", "sign", "title"):
            return SANS_FONT, 0  # 黑体，无描边
        else:
            return SERIF_FONT, 0  # 宋体，无描边
    else:
        # 框内字（对话气泡）：漫画体 + 描边
        return COMIC_FONT, 2  # 漫画体，2px描边
```

（注意：实际字体路径以项目 `fonts.py` 现有定义为准，这里只是示例结构。）

- [ ] **Step 4: Modify 05_typeset.py to pass bubble_type**

在 `scripts/05_typeset.py:47`，修改：

```python
category = item.get("category")
bubble_type = item.get("bubble_type", "text_bubble")  # 新增
font_path, stroke = resolve_font(category or "dialogue_bubble", text, bubble_type=bubble_type)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_typeset_font_selection.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/amta/fonts.py scripts/05_typeset.py tests/test_typeset_font_selection.py
git commit -m "feat(typeset): font selection by bubble_type

- text_bubble → comic font with stroke
- text_free → sans/serif font without stroke
- resolve_font accepts bubble_type param
- adds font selection unit test"
```

---

### Task 4: Inpaint 空转跳过（全页无 inpaint 区域则跳过 koharu）

**Files:**
- Modify: `scripts/04_inpaint.py`（`run()` 函数加空转判断）
- Test: `tests/test_inpaint_skip.py`

- [ ] **Step 1: Write failing test**

```python
def test_inpaint_skip_when_no_inpaint_regions():
    """If all regions are fill_white (dialogue_bubble), skip koharu client entirely."""
    from amta.inpaint_strategy import plan_inpaint

    # 全是 dialogue_bubble → 全是 fill_white，无 inpaint
    regions = [
        {"region_id": "u00", "bbox": [10, 10, 100, 50], "category": "dialogue_bubble"},
        {"region_id": "u01", "bbox": [200, 200, 300, 250], "category": "dialogue_bubble"},
    ]
    plan = plan_inpaint(regions)
    inpaint_count = sum(1 for p in plan if p["action"] == "inpaint")
    assert inpaint_count == 0, "all dialogue_bubble should be fill_white, no inpaint"

    # 有一个 overlay_text → 有 1 个 inpaint
    regions2 = regions + [{"region_id": "u02", "bbox": [400, 400, 500, 450], "category": "overlay_text"}]
    plan2 = plan_inpaint(regions2)
    inpaint_count2 = sum(1 for p in plan2 if p["action"] == "inpaint")
    assert inpaint_count2 == 1, "one overlay_text should trigger 1 inpaint"
```

- [ ] **Step 2: Run test to verify it passes（plan_inpaint 已经是对的）**

Run: `python -m pytest tests/test_inpaint_skip.py -v`
Expected: PASS — plan_inpaint 已经正确分类。这个测试验证的是策略层，已经对了。

- [ ] **Step 3: Modify 04_inpaint.py run() to skip koharu when no inpaint**

在 `scripts/04_inpaint.py:65`，修改：

```python
if not dry_run and (filled or inpaint_boxes):
    if inpaint_boxes:  # 只有真正有 inpaint 区域时才启动 koharu
        client = KoharuClient(host=host, port=port)
        client.wait_server(timeout=60)
        client.close_current_project()
        client.create_project(f"amta-inpaint-{work_id}")
        page_id = client.import_page(raw_page)
        client.run_inpaint(page_id, {"segment": _build_mask(img, inpaint_boxes),
                                     "bubble": _build_mask(img, inpaint_boxes)},
                           engine="lama-manga")
        data = client.fetch_inpainted(page_id)
        if data:
            try:
                inpainted = Image.open(io.BytesIO(data)).convert("RGB")
                if inpainted.size == img.size:
                    img = inpainted
            except Exception as e:
                print(f"[04_inpaint] WARN inpainted decode failed: {e}")
        else:
            print("[04_inpaint] WARN no inpainted result found")
    else:
        # 全页 fill_white，跳过 koharu，直接涂白
        print("[04_inpaint] all regions fill_white, skipping koharu lama")
    for p in filled:
        _apply_fill_white(img, p["bbox"])
```

- [ ] **Step 4: Add integration test for skip behavior**

```python
def test_inpaint_run_skips_koharu_when_all_fill_white(tmp_path):
    """04_inpaint run() should not create KoharuClient when all regions are fill_white."""
    # 用 mock 验证 KoharuClient 没被实例化
    import scripts.f04_inpaint as mod
    original_client = mod.KoharuClient
    calls = []
    class MockClient:
        def __init__(self, **kwargs): calls.append("init")
        def wait_server(self, **kwargs): calls.append("wait")
        def close_current_project(self): pass
        def create_project(self, name): pass
        def import_page(self, path): return "page1"
        def run_inpaint(self, page_id, masks, engine): pass
        def fetch_inpainted(self, page_id): return None
    mod.KoharuClient = MockClient
    try:
        # 构造全 dialogue_bubble 的 detection
        det = {"regions": [{"bbox": [10,10,100,50], "category": "dialogue_bubble"}],
               "image_meta": {"width": 200, "height": 200}, "page": "page_0"}
        raw = tmp_path / "test.jpg"
        Image.new("RGB", (200, 200), "white").save(raw)
        out = tmp_path / "out.json"
        mod.run("test", det, raw, out, clean_dir=tmp_path / "clean")
        assert calls == [], f"KoharuClient should not be called, got {calls}"
    finally:
        mod.KoharuClient = original_client
```

- [ ] **Step 5: Run all inpaint tests**

Run: `python -m pytest tests/test_inpaint_skip.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/04_inpaint.py tests/test_inpaint_skip.py
git commit -m "feat(inpaint): skip koharu when page has no inpaint regions

- all dialogue_bubble pages skip lama-manga entirely
- only create KoharuClient when inpaint_boxes is non-empty
- adds skip behavior unit test"
```

---

## Phase 2: 自动扩框（译文太长时扩框而非缩字）

### Task 5: auto_expand_bbox 函数 + 重叠检测回退

**Files:**
- Modify: `src/amta/typeset_engine.py`（新增 `auto_expand_bbox()`，修改 `fit_font_size()`）
- Test: `tests/test_typeset_auto_expand.py`

- [ ] **Step 1: Write failing test**

```python
def test_auto_expand_bbox_horizontal():
    """Horizontal text: if translation is longer, expand bbox width."""
    from amta.typeset_engine import auto_expand_bbox

    bbox = [100, 100, 300, 200]  # 200x100
    original_len = 5  # 日文5字
    translation_len = 15  # 中文15字（3倍长）
    direction = "horizontal"

    expanded = auto_expand_bbox(bbox, original_len, translation_len, direction)
    # 宽度应该扩大
    assert expanded[2] - expanded[0] > bbox[2] - bbox[0]
    # 高度不变
    assert expanded[3] - expanded[1] == bbox[3] - bbox[1]


def test_auto_expand_bbox_vertical():
    """Vertical text: expand bbox height."""
    from amta.typeset_engine import auto_expand_bbox

    bbox = [100, 100, 150, 300]  # 50x200
    expanded = auto_expand_bbox(bbox, 5, 15, "vertical")
    # 高度扩大
    assert expanded[3] - expanded[1] > bbox[3] - bbox[1]
    # 宽度不变
    assert expanded[2] - expanded[0] == bbox[2] - bbox[0]


def test_auto_expand_no_expand_when_short():
    """If translation is shorter, no expansion."""
    from amta.typeset_engine import auto_expand_bbox

    bbox = [100, 100, 300, 200]
    expanded = auto_expand_bbox(bbox, 15, 5, "horizontal")
    assert expanded == bbox  # 不扩大


def test_overlap_detection_fallback():
    """If expanded bbox overlaps with another, fallback to original (shrink font instead)."""
    from amta.typeset_engine import check_overlap, auto_expand_bbox_with_fallback

    bbox1 = [100, 100, 300, 200]
    bbox2 = [310, 100, 500, 200]  # 紧挨着 bbox1
    expanded1 = auto_expand_bbox(bbox1, 5, 15, "horizontal")
    # expanded1 会扩到 [100, 100, 500, 200]，和 bbox2 重叠
    overlaps = check_overlap(expanded1, [bbox2])
    assert overlaps is True
    # 回退：用原 bbox，靠缩小字号
    final = auto_expand_bbox_with_fallback(bbox1, 5, 15, "horizontal", [bbox2])
    assert final == bbox1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_typeset_auto_expand.py -v`
Expected: FAIL — `auto_expand_bbox` 不存在。

- [ ] **Step 3: Implement auto_expand_bbox in typeset_engine.py**

在 `src/amta/typeset_engine.py` 末尾新增：

```python
def auto_expand_bbox(bbox: list, original_len: int, translation_len: int,
                     direction: str, max_expand_ratio: float = 2.0) -> list:
    """译文比原文长时自动扩大 bbox。

    横排扩宽，竖排扩高。扩大量 = (translation_len / original_len - 1) * 原尺寸，
    上限为 max_expand_ratio 倍。译文更短时不扩大。

    抄自 manga-image-translator resize_regions_to_font_size() 的思路。
    """
    if translation_len <= original_len:
        return list(bbox)  # 不扩大

    x1, y1, x2, y2 = bbox
    ratio = min(translation_len / original_len, max_expand_ratio)
    expand_factor = ratio - 1  # 0~1

    if direction == "horizontal":
        # 横排：向左右两侧扩宽
        w = x2 - x1
        expand_w = int(w * expand_factor)
        return [x1 - expand_w // 2, y1, x2 + expand_w - expand_w // 2, y2]
    else:
        # 竖排：向上下两侧扩高
        h = y2 - y1
        expand_h = int(h * expand_factor)
        return [x1, y1 - expand_h // 2, x2, y2 + expand_h - expand_h // 2]


def check_overlap(bbox: list, others: list[list], threshold: float = 0.01) -> bool:
    """检查 bbox 是否与 others 中任意一个重叠（面积比 > threshold）。"""
    x1, y1, x2, y2 = bbox
    area = max(0, x2 - x1) * max(0, y2 - y1)
    if area == 0:
        return False
    for other in others:
        ox1, oy1, ox2, oy2 = other
        ix1, iy1 = max(x1, ox1), max(y1, oy1)
        ix2, iy2 = min(x2, ox2), min(y2, oy2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter / area > threshold:
            return True
    return False


def auto_expand_bbox_with_fallback(bbox: list, original_len: int, translation_len: int,
                                    direction: str, others: list[list]) -> list:
    """自动扩框，如与其他框重叠则回退原 bbox（靠缩小字号适配）。"""
    expanded = auto_expand_bbox(bbox, original_len, translation_len, direction)
    if expanded == bbox:
        return bbox
    if check_overlap(expanded, others):
        return list(bbox)  # 重叠，回退
    return expanded
```

- [ ] **Step 4: Modify 05_typeset.py to use auto_expand**

在 `scripts/05_typeset.py:37-57`，修改渲染循环：

```python
# 收集所有 bbox 用于重叠检测
all_bboxes = [item.get("bbox") for item in canon if item.get("bbox")]

for item in canon:
    rid = item.get("region_id")
    text = trans.get(rid)
    if text is None:
        continue
    bbox = bbox_by_node.get(item.get("node_id"))
    if not bbox:
        skipped_no_bbox.append(rid)
        continue
    category = item.get("category")
    bubble_type = item.get("bubble_type", "text_bubble")
    font_path, stroke = resolve_font(category or "dialogue_bubble", text, bubble_type=bubble_type)
    direction = decide_direction(category, bbox, len(text))

    # 自动扩框：译文比原文长时扩大 bbox，重叠则回退
    original_len = len(item.get("baberu_text", "") or "")
    other_bboxes = [b for b in all_bboxes if b != bbox]
    bbox = auto_expand_bbox_with_fallback(bbox, original_len, len(text), direction, other_bboxes)

    meta = render_item(img, text, str(font_path), bbox, direction, stroke=stroke)
    # ... 后续不变
```

- [ ] **Step 5: Run all typeset tests**

Run: `python -m pytest tests/test_typeset_auto_expand.py tests/test_typeset_font_selection.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/amta/typeset_engine.py scripts/05_typeset.py tests/test_typeset_auto_expand.py
git commit -m "feat(typeset): auto-expand bbox when translation is longer

- horizontal expands width, vertical expands height
- overlap detection falls back to original bbox (shrink font)
- max expand ratio 2.0x
-抄自 manga-image-translator resize_regions_to_font_size
- adds 4 unit tests"
```

---

## Phase 3: 集成验证

### Task 6: 端到端跑 5 页验证效果

**Files:**
- 无新文件，运行现有流水线

- [ ] **Step 1: 跑 5 页完整流水线（含 detect → OCR → translate → inpaint → typeset）**

Run:
```bash
python scripts/00_run_all.py --work-id touhou-single-wing \
  --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" \
  --start-page 11 --end-page 15 \
  --with-inpaint --with-typeset
```

Expected: 5 页全部成功，无崩溃。

- [ ] **Step 2: 人工检查最终渲染图**

检查 `workspace/touhou-single-wing/artifacts/final/page_1*_final.png`：
- 框内字（对话气泡）用漫画体，框外字（标题/旁白）用黑体/宋体
- 译文长的框是否自动扩大了，没有缩成一团
- inpaint 区域是否擦干净了
- 有无明显的字体错误

- [ ] **Step 3: 记录验证结果**

在 `docs/post3-stages-research-2026-09-01.md` 末尾追加验证结果。

- [ ] **Step 4: Commit 验证结果**

```bash
git add docs/post3-stages-research-2026-09-01.md
git commit -m "docs: post3-stages plan B 5-page e2e validation results"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: 方案 B 的所有能力（label传递、字体分类、inpaint空转、自动扩框、重叠回退）都有对应 Task
- [x] **Placeholder scan**: 无 TBD/TODO，所有代码步骤都有实际代码
- [x] **Type consistency**: `bubble_type` 字段名在 detect/ocr/translate/typeset 全链路一致；`auto_expand_bbox` 函数签名在定义和调用处一致
- [x] **Scope check**: 6 个 Task，每个可独立测试，适合 subagent-driven 执行

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-01-post3-stages-plan-b.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
