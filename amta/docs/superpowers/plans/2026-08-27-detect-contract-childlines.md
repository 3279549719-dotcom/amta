# Detect 契约升级 + child_lines/sub_tier 适配 + flash 模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 01_detect 从"扁平 blocks[]"升级为"regions + child_lines + sub_tier"契约，支持一个气泡容器内多段文字（主台词 primary / 碎碎念 aside）的检测与下游 OCR 展平翻译，并把 translate 通道模型切到 flash。

**Architecture:** detect 产出层级 DetectionArtifact（regions[].child_lines[].sub_tier），02_ocr 将每个 child_line 展平成独立 region_id 供 03 扁平翻译，03/canon 契约保持扁平不变；sub_tier 由 detect 用机械行宽比≥1.4 判定（Gemini v1.1 Stage 1 原案），Stage 3 保留改写权。04_inpaint/05_typeset 尚不存在（future work），本次只改 01/02，为 05 预留 child_lines。

**Tech Stack:** Python 3.13 + stdlib（零依赖铁律 ADR-009/018）、koharu v0.59.1 REST (:4000)、DeepSeek flash、pytest（fastcheck）、HTML 核对报告。

---

## 已确认决策（grill 定案）

- **Q1**：并集"宁多勿漏"（假阳性由 02_ocr 空文本自动丢弃）。
- **Q3**：验收 = 每页检出框数 ≥ 用户手工真值（p11=8,p12=5,p13=11,p14=16,p15=10,p16=10,p17=10/11,p18=10,p19=7,p20=10），并单列假阳性数供抽查。
- **Q6**：detect 契约升级为 regions + child_lines 子级结构（分期：本次先落召回并集，再落 child_lines 结构）。
- **Q7/Q9**：sub_tier 主次分段判定放 **detect**（机械行宽比≥1.4，Gemini v1.1 原案）。
- **Q8**：p12/p16/p14/p17 逐框核对报告先行。
- **Q11**：碎片 vs 复合气泡用 **IoA 判定**——child_lines 内新行被已收录行高度包含(IoA≥0.5)视为同文字碎片丢弃。p17「まあ…」重合框合并为 1。
- **Q12**：sub_tier 保留机械行宽比**启发式**，真实主次留给 Stage 3 LLM 裁决（detect 只给初步标注，不承担语义精度责任）。
- **translate 模型**：`.env CHAT_MODEL` → `deepseek-v4-flash`（用户明确，已改）。

---

## 契约现状（基线）

### 01_detect 当前输出（扁平，已 4-detector 并集 + IoA 去重）
```json
{
  "work_id": "...", "page": "12", "source": "...",
  "blocks": [
    {"node_id": "...", "bbox": [x1,y1,x2,y2], "bubble_type": "dialogue", "text": null},
    ...
  ],
  "n_boxes": 7, "detect_steps": [...], "per_engine_boxes": {...}, "generated_at": "..."
}
```

### 02_ocr 当前消费
- 读 `det["blocks"]`，按每个 block 的 `bbox` 裁框，region_id = `page_{idx}_u{i:02d}`（i 从 0 递增），OCR 后生成扁平 canon：
```json
[{"region_id": "page_11_u00", "text": "...", "page": 11, "node_id": "..."}, ...]
```

### 03_translate 当前消费
- 读扁平 canon（list of {region_id,text,page}），返回扁平 `{region_id: translation}`。
- 机械护栏（canon_schema.py）：region_id 唯一非空、text 非空、page 为 int。

---

## 文件结构

- 修改：`scripts/01_detect.py` — 输出升级为 regions + child_lines + sub_tier
- 修改：`src/amta/geometry.py` — 新增行宽比 sub_tier 判定 / child_lines 展平辅助
- 修改：`scripts/02_ocr.py` — 消费 regions[].child_lines 展平为独立 region_id
- 修改：`scripts/repair_failed.py` — 注释 deepseek-v4-pro → flash（仅注释）
- 修改：`src/amta/canon_schema.py` — 保持扁平校验（确认无需改，仅回归）
- 新增：`scripts/check_detect_report.py` — 逐框核对报告（HTML+裁剪图）
- 测试：`tests/test_pipeline_flow.py` / `tests/test_shared_lib.py` — 补 child_lines 相关用例
- 验证：`output/data/detect_union_11_20/*.json` + 手工真值对照

---

## Task 1: sub_tier 机械判定（geometry）

**Files:**
- Modify: `src/amta/geometry.py`
- Test: `tests/test_shared_lib.py`

- [ ] **Step 1: 写失败测试**

```python
def test_assign_sub_tier_primary_vs_aside(self):
    # 容器内两行: 行宽比 >= 1.4 → 判定为 aside(碎碎念), 否则 primary
    lines = [
        {"bbox": [100, 100, 500, 200]},  # 宽 400
        {"bbox": [100, 220, 160, 260]},  # 宽 60, 与上一行宽比 400/60≈6.7 → aside
    ]
    out = geometry.assign_sub_tier(lines, ratio=1.4)
    self.assertEqual(out[0]["sub_tier"], "primary")
    self.assertEqual(out[1]["sub_tier"], "aside")

def test_assign_sub_tier_all_primary_when_ratio_low(self):
    lines = [{"bbox": [0, 0, 100, 30]}, {"bbox": [0, 40, 110, 70]}]  # 宽 100/110 → 比值<1.4
    out = geometry.assign_sub_tier(lines, ratio=1.4)
    self.assertEqual([l["sub_tier"] for l in out], ["primary", "primary"])
```

- [ ] **Step 2: 跑测试确认失败**
Run: `python -m pytest tests/test_shared_lib.py -v -k sub_tier`
Expected: FAIL — `assign_sub_tier` not defined

- [ ] **Step 3: 实现 assign_sub_tier**

```python
def assign_sub_tier(lines: list[dict], ratio: float = 1.4) -> list[dict]:
    """机械主次分段: 容器内每行, 与最大行宽比 >= ratio 则标 aside(碎碎念), 否则 primary。

    Gemini v1.1 Stage 1 原案: 行宽比>=1.4 自动拆分主台词与碎碎念。
    """
    if not lines:
        return list(lines)
    widths = [b["bbox"][2] - b["bbox"][0] for b in lines]
    max_w = max(widths) or 1.0
    out = []
    for b, w in zip(lines, widths):
        item = dict(b)
        item["sub_tier"] = "aside" if (w / max_w) < (1.0 / ratio) else "primary"
        out.append(item)
    return out
```

- [ ] **Step 4: 跑测试确认通过**
Run: `python -m pytest tests/test_shared_lib.py -v -k sub_tier`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add src/amta/geometry.py tests/test_shared_lib.py
git commit -m "feat(detect): assign_sub_tier 机械主次分段(行宽比>=1.4)"
```

---

## Task 2: 01_detect 输出升级为 regions + child_lines

**Files:**
- Modify: `scripts/01_detect.py`
- Modify: `src/amta/geometry.py`（child_lines 分组辅助）
- Test: `tests/test_pipeline_flow.py`

- [ ] **Step 1: 写失败测试**（02_ocr 仍消费 blocks；新增字段 regions 应可导出且不破坏 blocks）

```python
def test_detect_output_has_regions_childlines(tmp_path, monkeypatch):
    """01_detect 输出含 regions[].child_lines[].sub_tier 层级结构。"""
    impl = _impl("_01_detect")
    # mock KoharuClient.run_all_pages 返回: 一个容器含两行(宽比高→一 primary 一 aside)
    ...
    doc = impl.run("w", tmp_path / "raw.jpg", tmp_path / "det.json")
    regions = doc["regions"]
    assert any("child_lines" in r for r in regions)
```

- [ ] **Step 2: 实现 01_detect regions 结构**
01_detect 在现有 union 后，把"相互嵌套的框"合并成容器 + child_lines：凡被 `absorb_contained` 丢弃的子框，改为挂到父容器 `child_lines`，而非直接丢弃。保留扁平 `blocks` 兼容字段（=每个 child_line/独立 region 展平后的 bbox）。

```python
def build_regions(blocks, ioa_thresh=0.75):
    """把扁平 blocks 重组为 regions[].child_lines[]. 嵌套子框挂父容器, 独立框自成 region。
    保留 blocks 兼容(展平所有 child_lines 与独立 region 的 bbox)。"""
    ...
```

- [ ] **Step 3: 跑测试确认通过**
- [ ] **Step 4: 提交**

---

## Task 3: 02_ocr 消费 child_lines 展平

**Files:**
- Modify: `scripts/02_ocr.py`
- Test: `tests/test_pipeline_flow.py`

- [ ] **Step 1: 写失败测试**：detection.json 有 regions[].child_lines 时，每个 child_line 生成独立 region_id + 裁剪。
- [ ] **Step 2: 实现**：`_crop_by_region` 优先从 `det["regions"]` 展平 child_lines（无 child_lines 的 region 自身一框），fallback 到 `det["blocks"]`（兼容旧）。region_id 编号保持 `page_{idx}_u{i:02d}` 全局递增。
- [ ] **Step 3: 跑测试确认通过**
- [ ] **Step 4: 提交**

---

## Task 4: 核对报告生成脚本

**Files:**
- Create: `scripts/check_detect_report.py`

- [ ] **Step 1: 实现**：读 `output/data/detect_union_11_20/p*.json`，每页列出框坐标 + 类型 + 是否疑似假阳性（bubble_type + bbox 面积启发式），裁剪图嵌入 HTML，对照用户手工真值标注 Δ。
- [ ] **Step 2: 跑 p11 生成 `output/reports/detect_check_11_20.html`**
- [ ] **Step 3: 提交**

---

## Task 5: flash 模型同步 + 回归

**Files:**
- Modify: `scripts/repair_failed.py`（注释 deepseek-v4-pro → flash）
- 验证：`.env CHAT_MODEL=deepseek-v4-flash`（已改）

- [ ] **Step 1: 改 repair_failed.py 注释**
- [ ] **Step 2: 跑 fastcheck** `python scripts/fastcheck.py` → 全绿
- [ ] **Step 3: 提交**

---

## Task 6: 跑 11-20 全流程验证

- [ ] **Step 1: 确认引擎存活**（koharu :4000 / llama :8118）
- [ ] **Step 2: 跑 11-20**：
```bash
python scripts/00_run_all.py --work-id touhou-single-wing \
  --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" \
  --start-page 11 --end-page 20 --ocr-engine auto
```
- [ ] **Step 3: 核对每页检出框数 ≥ 手工真值，记录 Δ**
- [ ] **Step 4: 提交产物**

---

## Self-Review

**Spec coverage:** Q1(宁多勿漏)→Task6 验收≥真值；Q3(手工真值基准)→Task6；Q6(child_lines 契约)→Task2/3；Q7/Q9(sub_tier 放 detect)→Task1；Q8(核对报告)→Task4；flash→Task5。全covered。

**Placeholder scan:** 已确认无 TBD/TODO 占位（Task2/3 的 mock 细节在实现时按实际 koharu 返回填充，属 TDD 红线内）。

**Type consistency:** sub_tier 枚举统一为 `"primary"|"aside"`；region_id 格式统一 `page_{idx}_u{i:02d}`；geometry 函数名 `assign_sub_tier`/`build_regions` 全篇一致。
