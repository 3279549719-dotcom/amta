# AMTA 前3 Stage v2 补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 detect/ocr/translate 前3 stage：修复 11-20 复审发现的 5 类机械 bug，新增 02.5 audit（VLM 存在性审核）+ 02.6 repair（差异修复）工位，升级翻译 prompt 与术语库机制。

**Architecture:** 01_detect（bubble_type 优先级合并 + 容器/child 都出框）→ 02_ocr（墨量拒框 + 碎片过滤 + 容器文本去重 + 单字面积 sub_tier）→ 02.5_audit（整页图+canon 清单 → VLM 存在性判断 → 差异报告）→ 02.6_repair（幻觉删/误读重OCR/漏检方位框 → canon_repaired.json）→ 03_translate（category prompt 指导 + suggestions 守卫 + lookup 前缀匹配 + 术语门槛≥3页）。03.5 语义评审本次不升级，保持逐 region。

**Tech Stack:** Python 3.13 + stdlib（零依赖铁律 ADR-009/018）、koharu v0.59.1 REST (:4000)、baberu-OCR ONNX（默认 OCR，auto 模式 baberu 优先空/超长回退 local）、DeepSeek flash（翻译）+ deepseek-v4-flash-vision-exp（audit VLM）、pytest（fastcheck）、Pillow。

**Spec:** `1_整改方案与新流水线.md` + `7_ADR/019-contract-triage.md` + 2026-08-27 架构讨论决策（本文件头部"决策清单"章节）。

## 决策清单（本次实现的依据，不可偏离）

| ID | 决策 |
|----|------|
| A4 | bubble_type 合并用引擎优先级：comic-text-bubble-detector > comic-text-detector > anime-text > pp-doclayout-v3 |
| A3 | 所有检测框独立 OCR；sub_tier 用单字面积判定（bbox面积÷文字数，大=primary 小=aside）；容器大框 OCR 后与 child 拼接比对，重复则丢弃 |
| C10 | 碎片框过滤：小框面积 < 同页最大框 15% 且与大框 IoA≥0.3 → 丢弃不单独 OCR |
| C9 | 墨量拒框：裁框后黑色像素占比 <1% → 跳过 OCR |
| 02.5 | audit 输入=整页图+canon 清单（1次VLM调用）；VLM 只做存在性判断，不报坐标不报正确文本；输出严格 JSON 差异报告 |
| 02.6 | repair：hallucination 高置信度删/低置信度工单；misread 原 bbox 重跑 baberu；missed 九宫格方位框→OCR→工单；输出 canon_repaired.json 重新连续编号 u00 起 |
| A1 | suggestions 守卫：译文 >12 字 OR 含句末标点（。！？…）→ 不产生 suggestion |
| A2 | lookup_term 未命中时前缀匹配（前2字符）+ 搜 characters aliases，返回相关词条供模型自判 |
| C9译 | user prompt 标注 [category] + system 提示 4 类翻译策略 |
| 术语 | ≥3 页一致 → confirmed；2 页一致 → inferred（不进 glossary 强制校验） |

## Global Constraints

- Python 3.13 全局解释器（fastcheck/pre-commit 必须用，AutoClaw 的 python 无 pytest）
- 零新增依赖（requests/pillow 不变；baberu ONNX 已有）
- 并发 workers=1（CPU-only i5-1135G7）
- OCR 默认 engine=auto（baberu fast path，空/超长回退 local For-Manga）
- region_id 格式 `page_{idx}_u{MM}`，0 基页码
- 日文残留检测只用假名 `[\u3040-\u30ff]`（L21，汉字中日共用不可用）
- 测试一律 pytest 风格，fastcheck 用 pytest 收集（L19）
- 数字前缀脚本需 import 时配 `_NN_name.py` 桥（L20）
- prompt 模板含字面花括号禁 .format()，用 {{ }} 或 .replace()（L24）
- VLM 空 content 自动重试（L23，vision-exp 约 14% 空响应）
- llama-server 多模态必须 cache_prompt:false（L17）

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `src/amta/geometry.py` | bbox/IoU/union/sub_tier/碎片过滤/容器展平 | Modify |
| `src/amta/images.py` | 图像工具（墨量计算） | Modify（新增 ink_ratio） |
| `src/amta/audit.py` | audit 纯函数：prompt 构造、报告解析、方位框映射、repair 应用、重新编号 | Create |
| `scripts/02.5_audit.py` | audit CLI：读 canon+整页图 → VLM → audit_report.json | Create |
| `scripts/02.6_repair.py` | repair CLI：读 canon+audit+detection → canon_repaired.json | Create |
| `scripts/02_ocr.py` | OCR 工位：加墨量拒框+碎片过滤+容器去重+sub_tier | Modify |
| `src/amta/translate.py` | 翻译核心：suggestions 守卫、lookup 前缀匹配、category prompt | Modify |
| `scripts/merge_suggestions.py` | 术语合并：门槛改 ≥3 页 confirmed / 2 页 inferred | Modify |
| `scripts/00_run_all.py` | 编排器：接入 02.5/02.6，03 读 canon_repaired | Modify |
| `tests/test_shared_lib.py` | geometry/images/merge 测试 | Modify |
| `tests/test_pipeline_flow.py` | 02_ocr/00_run_all 流程测试 | Modify |
| `tests/test_translate.py` | translate 修复测试 | Modify |
| `tests/test_audit.py` | audit/repair 纯函数测试 | Create |
| `scripts/probe_audit.py` | 一次性 VLM 准确率探针（用完即删，不入库） | Create（临时） |

---

## Task 0: 02.5 audit VLM 准确率探针（前置验证，非 TDD）

> **目的：** 在写 audit 工位之前，先用 5 页真实数据验证 VLM（deepseek-v4-flash-vision-exp）的"文字存在性判断"靠不靠谱。准确率 >80% 再做完整 repair 闭环；<60% 降级为纯报告人工看。
> **此脚本为一次性探针，跑完即删，不入库、不写测试。**

**Files:**
- Create: `scripts/probe_audit.py`（临时）

- [ ] **Step 1: 写探针脚本**

```python
"""02.5 audit VLM 准确率探针（一次性，跑完即删）。

用法: python scripts/probe_audit.py --work-id <id> --pages 11-15
构造: 取 02_ocr 的 canon，手动注入 3 类已知错误（幻觉/误读/漏检），
      调 VLM 看能否准确指出，统计准确率。
"""
from __future__ import annotations
import argparse, copy, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import translate
from amta.ocr_engines import image_data_uri
import requests

PROBE_PROMPT = """你是漫画翻译质检。请对照整页图和以下 OCR 文本清单，找出差异：
1. 清单里有但图上没有的文字（幻觉）
2. 清单文字与图上明显不符的（误读）
3. 图上有但清单没列的文字（漏检），只描述大致方位（上/下/左/右/中/左上等），不报坐标

OCR 清单：
{canon_list}

输出 JSON：{{"differences":[{{"type":"hallucination|misread|missed","region_id":"...","location":"...","reason":"..."}}]}}"""

def probe_page(cfg, image_path, canon, injected):
    canon_list = "\n".join(f'{r["region_id"]}|{r["text"]}' for r in canon)
    payload = {"model": "deepseek-v4-flash-vision-exp", "messages": [{"role":"user","content":[
        {"type":"text","text": PROBE_PROMPT.format(canon_list=canon_list)},
        {"type":"image_url","image_url":{"url": image_data_uri(image_path)}},
    ]}], "max_tokens": 1200}
    r = requests.post(cfg["base_url"]+"/chat/completions",
                      headers={"Authorization":f"Bearer {cfg['api_key']}"}, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--pages", default="11-15")
    args = ap.parse_args()
    from amta.workstate import work_dir
    ws = work_dir(args.work_id)
    cfg = translate.get_chat_config()
    start, end = map(int, args.pages.split("-"))
    for n in range(start, end+1):
        canon_path = ws / "artifacts" / f"page_{n-1}_canon.json"
        raw_path = ws / "artifacts" / "crops"  # crops dir for ref; raw page elsewhere
        if not canon_path.exists():
            print(f"[probe] page {n}: canon not found, skip"); continue
        canon = json.loads(canon_path.read_text(encoding="utf-8"))
        # 注入已知错误（在副本上操作，不改原文件）
        injected = copy.deepcopy(canon)
        if len(injected) >= 3:
            injected[1]["text"] = injected[1]["text"] + " injectedhallucination"  # 幻觉
            injected[2]["text"] = "ZZZZZZZZ"  # 误读
        # 漏检：删一个 region（不告诉 VLM）
        missed_rid = injected[0]["region_id"] if injected else None
        injected_audit = injected[1:]  # 模拟漏检第一个
        print(f"\n===== page {n} (injected: hallucination on {injected[1]['region_id']}, "
              f"misread on {injected[2]['region_id']}, missed {missed_rid}) =====")
        # 注意：raw 页图路径按实际 workspace 调整
        raw_img = ws / "raw" / f"{n}.jpg"
        if not raw_img.exists():
            print(f"[probe] raw image {raw_img} not found, skip"); continue
        out = probe_page(cfg, raw_img, injected_audit, injected)
        print(out)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑探针，人工核对 VLM 能否指出注入的 3 类错误**

Run: `python scripts/probe_audit.py --work-id <your-work-id> --pages 11-15`
Expected: 每页输出 VLM 的 JSON 判断。人工核对：
- 幻觉（injectedhallucination）是否被指出
- 误读（ZZZZZZZZ）是否被指出
- 漏检（被删的 region）是否被指出并描述方位
- 统计 5 页 × 3 类 = 15 个注入点的命中率

- [ ] **Step 3: 根据命中率决策**

- 命中率 ≥80%：继续 Task 1-14（完整 repair 闭环）
- 命中率 60-80%：repair 只做 hallucination 自动删，misread/missed 全进工单
- 命中率 <60%：02.5 audit 降级为纯报告生成（不做 02.6 repair），人工看报告决定
- 记录结论到 `7_ADR/` 新 ADR 后再继续

- [ ] **Step 4: 删除探针脚本**

```bash
rm scripts/probe_audit.py
```

---

## Task 1: A4 — bubble_type 引擎优先级合并

**Files:**
- Modify: `src/amta/geometry.py`（`union_blocks` 函数，L53-68）
- Test: `tests/test_shared_lib.py`

**Interfaces:**
- Consumes: `DETECTOR_STEPS`（`src/amta/pipeline.py`，4 引擎 dict 有序）
- Produces: `union_blocks(detections, threshold=0.5, type_priority=None) -> list[dict]`，每个 dict 含 `node_id/bbox/bubble_type/text`，bubble_type 按优先级取首个非空非 unknown 值

- [ ] **Step 1: 写失败测试**

在 `tests/test_shared_lib.py` 末尾追加：

```python
class TestUnionBlocksTypePriority:
    def test_prefers_bubble_detector_type(self):
        from amta.geometry import union_blocks
        detections = {
            "pp-doclayout-v3": [{"bbox": [10,10,100,100], "bubble_type": "dialogue", "node_id": "a"}],
            "comic-text-detector": [{"bbox": [12,12,98,98], "bubble_type": "dialogue", "node_id": "b"}],
            "anime-text": [{"bbox": [11,11,99,99], "bubble_type": "sfx", "node_id": "c"}],
            "comic-text-bubble-detector": [{"bbox": [10,10,100,100], "bubble_type": "sfx", "node_id": "d"}],
        }
        out = union_blocks(detections)
        assert len(out) == 1
        assert out[0]["bubble_type"] == "sfx"

    def test_falls_back_when_high_priority_unknown(self):
        from amta.geometry import union_blocks
        detections = {
            "pp-doclayout-v3": [{"bbox": [0,0,50,50], "bubble_type": "unknown", "node_id": "a"}],
            "comic-text-detector": [{"bbox": [0,0,50,50], "bubble_type": "sfx", "node_id": "b"}],
            "anime-text": [{"bbox": [0,0,50,50], "bubble_type": "unknown", "node_id": "c"}],
            "comic-text-bubble-detector": [{"bbox": [0,0,50,50], "bubble_type": "unknown", "node_id": "d"}],
        }
        out = union_blocks(detections)
        assert out[0]["bubble_type"] == "sfx"

    def test_all_unknown_defaults_unknown(self):
        from amta.geometry import union_blocks
        detections = {
            "pp-doclayout-v3": [{"bbox": [0,0,50,50], "bubble_type": "unknown", "node_id": "a"}],
            "comic-text-bubble-detector": [{"bbox": [0,0,50,50], "bubble_type": None, "node_id": "d"}],
        }
        out = union_blocks(detections)
        assert out[0].get("bubble_type") in (None, "unknown")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_shared_lib.py -v -k TypePriority`
Expected: FAIL — 当前 `union_blocks` 保留首个引擎（pp-doclayout）的 dialogue，不是 sfx

- [ ] **Step 3: 实现**

修改 `src/amta/geometry.py` 的 `union_blocks`（替换 L53-68 整个函数）：

```python
# 引擎类型优先级：漫画专用 detector 的 bubble_type 比文档模型可信（ADR-A4）
DEFAULT_TYPE_PRIORITY = (
    "comic-text-bubble-detector",
    "comic-text-detector",
    "anime-text",
    "pp-doclayout-v3",
)


def _pick_bubble_type(group: list[tuple[str, dict]], priority: tuple[str, ...]) -> str | None:
    """按引擎优先级取首个非空非 unknown 的 bubble_type。"""
    by_eng = {eng: blk for eng, blk in group}
    for eng in priority:
        bt = by_eng.get(eng, {}).get("bubble_type")
        if bt and bt != "unknown":
            return bt
    # 全部 unknown/None：返回首个非 None 值（可能是 unknown），否则 None
    for eng, blk in group:
        bt = blk.get("bubble_type")
        if bt is not None:
            return bt
    return None


def union_blocks(detections: dict[str, list[dict]], threshold: float = 0.5,
                 type_priority: tuple[str, ...] = DEFAULT_TYPE_PRIORITY) -> list[dict]:
    """多 detector 并集，保留首个命中框的 bbox，bubble_type 按引擎优先级合并。

    IoU > threshold 视为重复；重复组内 bubble_type 按 type_priority 取首个
    非空非 unknown 值（修 A4：pp-doclayout 元数据不再覆盖漫画专用 detector）。
    """
    seen: list[dict] = []  # [{"bbox": [...], "group": [(eng, blk), ...]}]
    for eng, blocks in detections.items():
        for b in blocks:
            bb = tuple(bbox_from_block(b))
            match = next((s for s in seen if iou(bb, s["bbox"]) > threshold), None)
            if match is not None:
                match["group"].append((eng, b))
                continue
            seen.append({"bbox": list(bb), "group": [(eng, b)]})
    out = []
    for s in seen:
        # 元数据以优先级最高引擎的 block 为基底，bubble_type 单独合并
        best_eng = next((e for e in type_priority if any(e == g[0] for g in s["group"])),
                        s["group"][0][0])
        base = next(g[1] for g in s["group"] if g[0] == best_eng)
        item = dict(base)
        item["bbox"] = s["bbox"]
        item["bubble_type"] = _pick_bubble_type(s["group"], type_priority)
        out.append(item)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_shared_lib.py -v -k TypePriority`
Expected: 3 passed

- [ ] **Step 5: 全量 fastcheck 回归**

Run: `python scripts/fastcheck.py`
Expected: 全绿（含已有测试，union_blocks 签名向后兼容）

- [ ] **Step 6: 提交**

```bash
git add src/amta/geometry.py tests/test_shared_lib.py
git commit -m "fix(detect): A4 bubble_type 按引擎优先级合并，不再被 pp-doclayout 覆盖"
```

---

## Task 2: C10 — 碎片框面积比过滤

**Files:**
- Modify: `src/amta/geometry.py`（新增 `merge_fragments`）
- Test: `tests/test_shared_lib.py`

**Interfaces:**
- Consumes: 扁平 blocks（含 bbox）
- Produces: `merge_fragments(blocks, area_ratio=0.15, ioa_thresh=0.3) -> list[dict]`，丢弃被大框包含的小碎片框

- [ ] **Step 1: 写失败测试**

```python
class TestMergeFragments:
    def test_drops_small_fragment_overlapping_large_box(self):
        from amta.geometry import merge_fragments
        blocks = [
            {"bbox": [0,0,200,200], "node_id": "big"},
            {"bbox": [180,180,210,210], "node_id": "frag"},  # 面积 900，大框 40000，2.25%
        ]
        out = merge_fragments(blocks)
        assert len(out) == 1
        assert out[0]["node_id"] == "big"

    def test_keeps_independent_small_box(self):
        from amta.geometry import merge_fragments
        blocks = [
            {"bbox": [0,0,200,200], "node_id": "big"},
            {"bbox": [300,300,330,330], "node_id": "small"},  # 不重叠
        ]
        out = merge_fragments(blocks)
        assert len(out) == 2

    def test_keeps_normal_size_box(self):
        from amta.geometry import merge_fragments
        blocks = [
            {"bbox": [0,0,200,200], "node_id": "big"},       # 40000
            {"bbox": [50,50,150,150], "node_id": "medium"},  # 10000 = 25% > 15%
        ]
        out = merge_fragments(blocks)
        assert len(out) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_shared_lib.py -v -k MergeFragments`
Expected: FAIL — `merge_fragments` not defined

- [ ] **Step 3: 实现**

在 `src/amta/geometry.py` 末尾追加：

```python
def merge_fragments(blocks: list[dict], area_ratio: float = 0.15,
                    ioa_thresh: float = 0.3) -> list[dict]:
    """丢弃碎片小框：面积 < 同页最大框 area_ratio 且与某大框 IoA≥ioa_thresh → 丢弃。

    修 C10：大拟声词边缘碎片框（如「ゴン」旁的小框）被 baberu 误读。
    小框必须同时满足"面积小"和"与大框重叠"才丢弃，避免误杀独立小字。
    """
    if not blocks:
        return []
    areas = [_area(b["bbox"]) for b in blocks]
    max_area = max(areas) or 1.0
    kept = []
    for b, area in zip(blocks, areas):
        if area >= max_area * area_ratio:
            kept.append(b)
            continue
        # 小框：检查是否与某个更大的框重叠
        absorbed = any(
            _area2(b["bbox"], other["bbox"]) / area >= ioa_thresh
            for other, oa in zip(blocks, areas)
            if oa > area and not (other is b)
        )
        if not absorbed:
            kept.append(b)
    return kept


def _area2(child: Sequence[float], parent: Sequence[float]) -> float:
    """child 与 parent 的交集面积。"""
    x0 = max(child[0], parent[0]); y0 = max(child[1], parent[1])
    x1 = min(child[2], parent[2]); y1 = min(child[3], parent[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_shared_lib.py -v -k MergeFragments`
Expected: 3 passed

- [ ] **Step 5: fastcheck 回归 + 提交**

Run: `python scripts/fastcheck.py` → 全绿
```bash
git add src/amta/geometry.py tests/test_shared_lib.py
git commit -m "fix(detect): C10 碎片框面积比过滤，挡住拟声词边缘误读"
```

---

## Task 3: C9 — 墨量拒框

**Files:**
- Modify: `src/amta/images.py`（新增 `ink_ratio`）
- Test: `tests/test_shared_lib.py`

**Interfaces:**
- Produces: `ink_ratio(img: PIL.Image) -> float`，返回黑色像素（灰度<128）占比

- [ ] **Step 1: 写失败测试**

```python
class TestInkRatio:
    def test_blank_image_zero_ink(self):
        from amta.images import ink_ratio
        from PIL import Image
        img = Image.new("L", (100, 100), 255)
        assert ink_ratio(img) == 0.0

    def test_full_black_image(self):
        from amta.images import ink_ratio
        from PIL import Image
        img = Image.new("L", (100, 100), 0)
        assert ink_ratio(img) == 1.0

    def test_text_image_has_ink(self):
        from amta.images import ink_ratio
        from PIL import Image, ImageDraw
        img = Image.new("L", (200, 50), 255)
        d = ImageDraw.Draw(img)
        d.text((10, 10), "こんにちは", fill=0)
        assert ink_ratio(img) > 0.01
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_shared_lib.py -v -k InkRatio`
Expected: FAIL — `ink_ratio` not defined

- [ ] **Step 3: 实现**

在 `src/amta/images.py` 末尾追加（如果文件不存在则创建，保留已有内容）：

```python
def ink_ratio(img, threshold: int = 128) -> float:
    """计算黑色像素占比（灰度 < threshold 的像素比例）。

    修 C9：detector 误检的空白/近空白框墨量极低，<1% 直接跳过 OCR，
    防 baberu 从噪声幻觉出整句。
    """
    from PIL import Image
    if img.mode != "L":
        img = img.convert("L")
    hist = img.histogram()
    total = sum(hist) or 1
    dark = sum(hist[:threshold])
    return dark / total
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_shared_lib.py -v -k InkRatio`
Expected: 3 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add src/amta/images.py tests/test_shared_lib.py
git commit -m "feat(ocr): C9 墨量拒框 ink_ratio，空白框不送 OCR 防幻觉"
```

---

## Task 4: A3 — 容器展平标记 + 单字面积 sub_tier

**Files:**
- Modify: `src/amta/geometry.py`（`flatten_regions` 加 `is_container`/`parent_node_id`；新增 `assign_sub_tier_by_area`）
- Test: `tests/test_shared_lib.py`

**Interfaces:**
- Produces: `flatten_regions(regions) -> list[dict]`，每个 block 带 `is_container: bool` 和 `parent_node_id: str|None`
- Produces: `assign_sub_tier_by_area(items, ratio=1.4) -> list[dict]`，输入 OCR 后的 items（含 bbox+text），输出带 sub_tier

- [ ] **Step 1: 写失败测试**

```python
class TestFlattenRegionsWithContainer:
    def test_container_marked_and_child_has_parent(self):
        from amta.geometry import flatten_regions
        regions = [{
            "node_id": "container1", "bbox": [0,0,200,200], "bubble_type": "dialogue",
            "child_lines": [
                {"node_id": "child1", "bbox": [10,10,180,80], "bubble_type": "dialogue"},
                {"node_id": "child2", "bbox": [10,100,180,190], "bubble_type": "dialogue"},
            ]
        }]
        out = flatten_regions(regions)
        containers = [b for b in out if b.get("is_container")]
        children = [b for b in out if not b.get("is_container")]
        assert len(containers) == 1
        assert containers[0]["node_id"] == "container1"
        assert len(children) == 2
        assert all(c.get("parent_node_id") == "container1" for c in children)

    def test_independent_region_not_marked_container(self):
        from amta.geometry import flatten_regions
        regions = [{"node_id": "solo", "bbox": [0,0,50,50], "bubble_type": "sfx", "child_lines": []}]
        out = flatten_regions(regions)
        assert len(out) == 1
        assert out[0].get("is_container") is not True


class TestSubTierByArea:
    def test_large_text_primary_small_text_aside(self):
        from amta.geometry import assign_sub_tier_by_area
        items = [
            {"bbox": [0,0,200,100], "text": "大字"},       # 面积/字 = 10000
            {"bbox": [0,120,60,140], "text": "小字"},      # 面积/字 = 600
        ]
        out = assign_sub_tier_by_area(items)
        assert out[0]["sub_tier"] == "primary"
        assert out[1]["sub_tier"] == "aside"

    def test_similar_size_both_primary(self):
        from amta.geometry import assign_sub_tier_by_area
        items = [
            {"bbox": [0,0,100,50], "text": "AB"},
            {"bbox": [0,60,100,110], "text": "CD"},
        ]
        out = assign_sub_tier_by_area(items)
        assert all(i["sub_tier"] == "primary" for i in out)

    def test_empty_text_skipped(self):
        from amta.geometry import assign_sub_tier_by_area
        items = [{"bbox": [0,0,100,50], "text": ""}]
        out = assign_sub_tier_by_area(items)
        assert out[0].get("sub_tier") in (None, "primary")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_shared_lib.py -v -k "FlattenRegionsWithContainer or SubTierByArea"`
Expected: FAIL

- [ ] **Step 3: 实现**

替换 `src/amta/geometry.py` 的 `flatten_regions`（L187-200）：

```python
def flatten_regions(regions: list[dict]) -> list[dict]:
    """展平 regions[] 为 blocks[]：容器自身（is_container=True）+ 每个 child_line。

    容器带 is_container=True；child 带 parent_node_id=容器 node_id。
    独立 region 不带 is_container。02_ocr 对所有框 OCR 后做容器文本去重。
    """
    out: list[dict] = []
    for r in regions:
        children = r.get("child_lines") or []
        if children:
            container = {k: v for k, v in r.items() if k != "child_lines"}
            container["is_container"] = True
            out.append(container)
            for line in children:
                item = dict(line)
                item["parent_node_id"] = r.get("node_id")
                out.append(item)
        else:
            item = dict(r)
            out.append(item)
    return out
```

在文件末尾追加：

```python
def assign_sub_tier_by_area(items: list[dict], ratio: float = 1.4) -> list[dict]:
    """按单字面积判定 sub_tier（修 A3：行宽比对竖排混排失效）。

    单字面积 = bbox 面积 / max(len(text),1)。与同页最大单字面积比 < 1/ratio
    的标 aside（小字），否则 primary。无 text 的不标。
    """
    if not items:
        return list(items)
    def _char_area(it):
        w = max(0.0, it["bbox"][2] - it["bbox"][0])
        h = max(0.0, it["bbox"][3] - it["bbox"][1])
        n = max(len(str(it.get("text", ""))), 1)
        return w * h / n
    areas = [_char_area(it) for it in items]
    max_area = max(areas) or 1.0
    out = []
    for it, ca in zip(items, areas):
        item = dict(it)
        if str(it.get("text", "")).strip():
            item["sub_tier"] = "aside" if (ca / max_area) < (1.0 / ratio) else "primary"
        out.append(item)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_shared_lib.py -v -k "FlattenRegionsWithContainer or SubTierByArea"`
Expected: 5 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add src/amta/geometry.py tests/test_shared_lib.py
git commit -m "feat(detect): A3 容器展平标记 is_container + 单字面积 sub_tier 判定"
```

---

## Task 5: 02_ocr 接入碎片过滤 + 墨量拒框 + 容器去重 + sub_tier

**Files:**
- Modify: `scripts/02_ocr.py`（`_crop_by_region` 和 `run`）
- Test: `tests/test_pipeline_flow.py`

**Interfaces:**
- Consumes: `merge_fragments`/`ink_ratio`/`assign_sub_tier_by_area`（Task 2/3/4）
- Produces: 02_ocr 输出 canon items 带 `category`/`sub_tier`，容器重复文本已去重

- [ ] **Step 1: 写失败测试**

在 `tests/test_pipeline_flow.py` 追加：

```python
class TestOcrFilters:
    def test_skips_low_ink_crop(self, tmp_path, monkeypatch):
        """墨量 <1% 的框不送 OCR。"""
        from PIL import Image
        import scripts._02_ocr as ocr_mod
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        raw = tmp_path / "blank.jpg"; img.save(raw)
        blocks = [{"bbox": [10, 10, 50, 50], "node_id": "n1", "bubble_type": "dialogue"}]
        crop_dir = tmp_path / "crops"
        pairs = ocr_mod._crop_by_region(raw, blocks, 0, crop_dir, ink_threshold=0.01)
        # 全白框墨量 0 < 1%，被跳过
        assert len(pairs) == 0

    def test_container_text_dedup(self, tmp_path):
        """容器 OCR 文本 ≈ child 拼接 → 丢弃容器。"""
        import scripts._02_ocr as ocr_mod
        items = [
            {"region_id": "u00", "text": "こんにちは世界", "is_container": True,
             "parent_node_id": None, "bbox": [0,0,200,100]},
            {"region_id": "u01", "text": "こんにちは", "is_container": False,
             "parent_node_id": "c1", "bbox": [0,0,200,50]},
            {"region_id": "u02", "text": "世界", "is_container": False,
             "parent_node_id": "c1", "bbox": [0,50,200,100]},
        ]
        out = ocr_mod._dedupe_containers(items)
        rids = [i["region_id"] for i in out]
        assert "u00" not in rids  # 容器文本 = child 拼接，丢弃
        assert "u01" in rids and "u02" in rids

    def test_container_with_independent_text_kept(self, tmp_path):
        """容器有 child 没覆盖的文字 → 保留容器。"""
        import scripts._02_ocr as ocr_mod
        items = [
            {"region_id": "u00", "text": "大字标题", "is_container": True,
             "parent_node_id": None, "bbox": [0,0,200,100]},
            {"region_id": "u01", "text": "小字", "is_container": False,
             "parent_node_id": "c1", "bbox": [0,80,200,100]},
        ]
        out = ocr_mod._dedupe_containers(items)
        assert "u00" in [i["region_id"] for i in out]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline_flow.py -v -k OcrFilters`
Expected: FAIL — `_crop_by_region` 不接受 ink_threshold，`_dedupe_containers` 不存在

- [ ] **Step 3: 实现**

修改 `scripts/02_ocr.py`。

首先改 `_crop_by_region` 签名和逻辑（加碎片过滤 + 墨量检查）：

```python
def _crop_by_region(raw: Path, blocks: list[dict], page_idx: int,
                    crop_dir: Path, ink_threshold: float = 0.01) -> list[tuple[str, dict, Path]]:
    """按 bbox 裁框。碎片框先过滤（C10），墨量 <ink_threshold 跳过（C9）。"""
    from amta.geometry import merge_fragments
    from amta.images import ink_ratio
    blocks = merge_fragments(blocks)  # C10：丢弃碎片小框
    img = Image.open(raw)
    out = []
    crop_dir.mkdir(parents=True, exist_ok=True)
    i = 0
    for b in blocks:
        bb = b.get("bbox")
        if not bb or len(bb) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img.crop((x1, y1, x2, y2))
        if ink_threshold > 0 and ink_ratio(crop) < ink_threshold:
            continue  # C9：空白框不送 OCR
        rid = f"page_{page_idx}_u{i:02d}"
        i += 1
        crop_path = crop_dir / f"{rid}.png"
        crop.save(crop_path)
        out.append((rid, b, crop_path))
    return out
```

新增容器去重函数：

```python
def _dedupe_containers(items: list[dict], sim_threshold: float = 0.8) -> list[dict]:
    """A3：容器 OCR 文本与 child 拼接高度相似 → 丢弃容器。

    相似度 = 容器文本中出现在任一 child 文本里的字符比例。
    容器有 child 没覆盖的独立文字时保留。
    """
    from amta.metrics import norm
    containers = [it for it in items if it.get("is_container")]
    if not containers:
        return items
    drop = set()
    for c in containers:
        cid = c.get("node_id") or c.get("parent_node_id") or ""
        children = [it for it in items
                    if not it.get("is_container") and it.get("parent_node_id") == cid]
        if not children:
            continue
        c_text = norm(str(c.get("text", "")))
        if not c_text:
            drop.add(c["region_id"]); continue
        child_chars = set()
        for ch in children:
            child_chars.update(norm(str(ch.get("text", ""))))
        if not child_chars:
            continue
        covered = sum(1 for ch in c_text if ch in child_chars)
        sim = covered / len(c_text)
        if sim >= sim_threshold:
            drop.add(c["region_id"])
    return [it for it in items if it["region_id"] not in drop]
```

修改 `run` 函数，在 OCR 后加容器去重 + sub_tier 判定。找到 `canon = []` 循环之后、`doc = {...}` 之前，加：

```python
    # A3：容器文本去重
    canon_with_meta = []
    for rid, b, crop in pairs:
        text = ocr_by_crop.get(str(crop), "")
        if not text:
            continue
        item = {
            "region_id": rid, "text": text, "page": page_idx,
            "node_id": b.get("node_id"),
        }
        for k in ("category", "sub_tier", "is_container", "parent_node_id"):
            if b.get(k) is not None:
                item[k] = b[k]
        canon_with_meta.append(item)
    canon_with_meta = _dedupe_containers(canon_with_meta)
    # A3：单字面积 sub_tier（覆盖 detect 阶段的行宽比初判）
    from amta.geometry import assign_sub_tier_by_area
    canon_with_meta = assign_sub_tier_by_area(canon_with_meta)
    canon = []
    for item in canon_with_meta:
        clean = {k: v for k, v in item.items()
                 if k in ("region_id", "text", "page", "node_id", "category", "sub_tier")}
        canon.append(clean)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pipeline_flow.py -v -k OcrFilters`
Expected: 3 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add scripts/02_ocr.py tests/test_pipeline_flow.py
git commit -m "feat(ocr): A3/C9/C10 接入墨量拒框+碎片过滤+容器去重+单字面积sub_tier"
```

---

## Task 6: 02.5 audit 纯函数（prompt 构造 + 报告解析）

**Files:**
- Create: `src/amta/audit.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Produces: `build_audit_prompt(canon) -> str`
- Produces: `parse_audit_report(raw, canon_ids) -> dict`（含 audit_parse_failed 容错）
- Produces: `location_to_bbox(location, width, height) -> list[float]`（九宫格）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_audit.py`：

```python
import pytest


class TestBuildAuditPrompt:
    def test_includes_region_list(self):
        from amta.audit import build_audit_prompt
        canon = [{"region_id": "u00", "text": "こんにちは"},
                 {"region_id": "u01", "text": "世界"}]
        prompt = build_audit_prompt(canon)
        assert "u00|こんにちは" in prompt
        assert "u01|世界" in prompt


class TestParseAuditReport:
    def test_valid_json(self):
        from amta.audit import parse_audit_report
        raw = '{"differences":[{"type":"hallucination","region_id":"u02","reason":"图上无此文字","confidence":"high"}]}'
        out = parse_audit_report(raw, ["u00", "u01", "u02"])
        assert out["parse_failed"] is False
        assert len(out["differences"]) == 1
        assert out["differences"][0]["type"] == "hallucination"

    def test_invalid_json(self):
        from amta.audit import parse_audit_report
        out = parse_audit_report("garbage text", ["u00"])
        assert out["parse_failed"] is True

    def test_hallucination_region_not_in_canon_ignored(self):
        from amta.audit import parse_audit_report
        raw = '{"differences":[{"type":"hallucination","region_id":"u99","reason":"x"}]}'
        out = parse_audit_report(raw, ["u00"])
        assert len(out["differences"]) == 0

    def test_missed_does_not_need_region_id(self):
        from amta.audit import parse_audit_report
        raw = '{"differences":[{"type":"missed","location":"右下角","reason":"有小字未列","confidence":"high"}]}'
        out = parse_audit_report(raw, ["u00"])
        assert len(out["differences"]) == 1
        assert out["differences"][0]["location"] == "右下角"

    def test_strips_markdown_code_fence(self):
        from amta.audit import parse_audit_report
        raw = '```json\n{"differences":[]}\n```'
        out = parse_audit_report(raw, [])
        assert out["parse_failed"] is False


class TestLocationToBbox:
    def test_bottom_right(self):
        from amta.audit import location_to_bbox
        bb = location_to_bbox("右下角", 1000, 2000)
        assert bb == [600, 1200, 1000, 2000]

    def test_center(self):
        from amta.audit import location_to_bbox
        bb = location_to_bbox("中", 1000, 1000)
        assert bb == [300, 300, 700, 700]

    def test_unknown_location_defaults_full_page(self):
        from amta.audit import location_to_bbox
        bb = location_to_bbox("不知道哪里", 1000, 1000)
        assert bb == [0, 0, 1000, 1000]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 实现**

创建 `src/amta/audit.py`：

```python
"""02.5 audit 纯函数：prompt 构造、差异报告解析、方位框映射。

VLM 只做存在性判断（有/没有/对不上），不报坐标不报正确文本（L1/L10/L13 教训）。
"""
from __future__ import annotations
import json
import re

AUDIT_SYSTEM = "你是漫画翻译质检，只做文字存在性判断，不报坐标，不提供正确文本。"

AUDIT_PROMPT = """请对照整页图和以下 OCR 文本清单，找出差异：
1. 清单里有但图上没有的文字（hallucination）
2. 清单文字与图上明显不符的（misread）
3. 图上有但清单没列的文字（missed），只描述大致方位（上/下/左/右/中/左上/右上/左下/右下），不报坐标

OCR 清单：
{canon_list}

输出严格 JSON（不要 markdown）：
{{"differences":[{{"type":"hallucination|misread|missed","region_id":"...","location":"...","reason":"...","confidence":"high|medium|low"}}]}}
没有差异则返回 {{"differences":[]}}"""

VALID_TYPES = {"hallucination", "misread", "missed"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def build_audit_prompt(canon: list[dict]) -> str:
    canon_list = "\n".join(f'{r["region_id"]}|{r["text"]}' for r in canon)
    return AUDIT_PROMPT.replace("{canon_list}", canon_list)


def parse_audit_report(raw: str, canon_ids: list[str]) -> dict:
    """解析 VLM 输出为差异报告。解析失败返回 parse_failed=True。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"parse_failed": True, "differences": [], "raw": raw[:500]}
    if not isinstance(data, dict):
        return {"parse_failed": True, "differences": [], "raw": raw[:500]}
    ids = set(canon_ids)
    diffs = []
    for d in data.get("differences", []):
        if not isinstance(d, dict):
            continue
        dtype = d.get("type")
        if dtype not in VALID_TYPES:
            continue
        rid = d.get("region_id")
        if dtype in ("hallucination", "misread") and rid not in ids:
            continue  # region_id 不在 canon 中，忽略
        conf = d.get("confidence", "medium")
        if conf not in VALID_CONFIDENCE:
            conf = "medium"
        diffs.append({
            "type": dtype,
            "region_id": rid,
            "location": d.get("location"),
            "reason": d.get("reason", ""),
            "confidence": conf,
        })
    return {"parse_failed": False, "differences": diffs}


# 九宫格方位 → [x1,y1,x2,y2] 比例
_LOCATION_MAP = {
    "上": [0.0, 0.0, 1.0, 0.4], "下": [0.0, 0.6, 1.0, 1.0],
    "左": [0.0, 0.0, 0.4, 1.0], "右": [0.6, 0.0, 1.0, 1.0],
    "中": [0.3, 0.3, 0.7, 0.7],
    "左上": [0.0, 0.0, 0.4, 0.4], "右上": [0.6, 0.0, 1.0, 0.4],
    "左下": [0.0, 0.6, 0.4, 1.0], "右下": [0.6, 0.6, 1.0, 1.0],
}


def location_to_bbox(location: str, width: int, height: int) -> list[int]:
    """方位词 → 像素 bbox（九宫格粗略框）。未知方位返回整页。"""
    ratios = _LOCATION_MAP.get(str(location or "").strip())
    if ratios is None:
        return [0, 0, width, height]
    return [int(ratios[0]*width), int(ratios[1]*height),
            int(ratios[2]*width), int(ratios[3]*height)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audit.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/audit.py tests/test_audit.py
git commit -m "feat(audit): 02.5 audit 纯函数 prompt构造+报告解析+九宫格方位框"
```

---

## Task 7: 02.5 audit CLI

**Files:**
- Create: `scripts/02.5_audit.py`
- Create: `scripts/_02_5_audit.py`（import 桥，L20）
- Test: `tests/test_audit.py`（CLI mock 测试）

**Interfaces:**
- Consumes: `canon.json`（02_ocr 产物）+ 整页原图
- Produces: `audit_report.json`

- [ ] **Step 1: 写失败测试**

在 `tests/test_audit.py` 追加：

```python
class TestAuditCli:
    def test_audit_writes_report(self, tmp_path, monkeypatch):
        import scripts._02_5_audit as audit_cli
        canon = [{"region_id": "u00", "text": "テスト"}]
        canon_path = tmp_path / "canon.json"
        import json
        canon_path.write_text(json.dumps(canon), encoding="utf-8")
        # 造一张小图
        from PIL import Image
        img_path = tmp_path / "11.jpg"; Image.new("RGB",(100,100)).save(img_path)
        out_path = tmp_path / "audit.json"
        # mock VLM 返回空差异
        monkeypatch.setattr(audit_cli, "_call_vlm", lambda cfg, img, prompt: '{"differences":[]}')
        monkeypatch.setattr(audit_cli.translate, "get_chat_config",
                            lambda: {"base_url":"http://x","model":"m","api_key":"k"})
        result = audit_cli.run(canon_path, img_path, out_path)
        assert result["parse_failed"] is False
        assert result["differences"] == []
        assert out_path.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v -k AuditCli`
Expected: FAIL — module not found

- [ ] **Step 3: 实现**

创建 `scripts/02.5_audit.py`：

```python
"""02.5_audit 工位 — 整页图 + canon 清单 → VLM 存在性审核 → audit_report.json。

VLM 只判断：清单有图无（幻觉）、内容不符（误读）、图有清单无（漏检）。
不报坐标不报正确文本（L1/L10/L13）。
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import requests
from amta import translate
from amta.audit import AUDIT_SYSTEM, build_audit_prompt, parse_audit_report
from amta.ocr_engines import image_data_uri


def _call_vlm(cfg: dict, image_path: Path, prompt: str, model: str = "deepseek-v4-flash-vision-exp",
              retries: int = 2) -> str:
    payload = {"model": model, "messages": [
        {"role": "system", "content": AUDIT_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_uri(image_path)}},
        ]}], "max_tokens": 1500}
    for _ in range(retries + 1):
        r = requests.post(cfg["base_url"] + "/chat/completions",
                          headers={"Authorization": f"Bearer {cfg['api_key']}"},
                          json=payload, timeout=180)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"] or ""
        if content.strip():
            return content
    return ""


def run(canon_path: Path, image_path: Path, out_path: Path, model: str = "deepseek-v4-flash-vision-exp") -> dict:
    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    cfg = translate.get_chat_config()
    prompt = build_audit_prompt(canon)
    raw = _call_vlm(cfg, image_path, prompt, model=model)
    report = parse_audit_report(raw, [r["region_id"] for r in canon])
    report["work_id"] = canon_path.stem.split("_canon")[0] if "_canon" in canon_path.stem else ""
    report["page"] = canon[0].get("page") if canon else None
    report["model"] = model
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="02.5 audit 工位")
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default="deepseek-v4-flash-vision-exp")
    args = ap.parse_args()
    r = run(args.canon, args.raw, args.out, model=args.model)
    n = len(r.get("differences", []))
    print(f"[02.5_audit] parse_failed={r['parse_failed']} differences={n} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

创建 `scripts/_02_5_audit.py`（import 桥，L20）：

```python
"""import 桥：允许 tests import scripts/02.5_audit.py（数字前缀不可直接 import）。"""
import importlib.util, pathlib
_p = pathlib.Path(__file__).resolve().parent / "02.5_audit.py"
_spec = importlib.util.spec_from_file_location("_02_5_audit", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
for _n in dir(_mod):
    if not _n.startswith("_") or _n == "_call_vlm":
        globals()[_n] = getattr(_mod, _n)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audit.py -v -k AuditCli`
Expected: 1 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add scripts/02.5_audit.py scripts/_02_5_audit.py tests/test_audit.py
git commit -m "feat(audit): 02.5_audit CLI 工位，整页VLM存在性审核"
```

---

## Task 8: 02.6 repair 纯函数（差异应用 + 重新编号）

**Files:**
- Modify: `src/amta/audit.py`（新增 `apply_repairs`、`renumber_canon`）
- Test: `tests/test_audit.py`

**Interfaces:**
- Produces: `apply_repairs(canon, report, det_blocks, image_size, ocr_fn) -> (repaired, needs_review)`
- Produces: `renumber_canon(canon, page_idx) -> canon`

- [ ] **Step 1: 写失败测试**

```python
class TestApplyRepairs:
    def test_hallucination_high_confidence_deleted(self):
        from amta.audit import apply_repairs
        canon = [{"region_id": "u00", "text": "a", "page": 10, "bbox":[0,0,10,10]},
                 {"region_id": "u01", "text": "fake", "page": 10, "bbox":[0,0,10,10]}]
        report = {"differences":[{"type":"hallucination","region_id":"u01","confidence":"high","reason":"x"}]}
        repaired, nr = apply_repairs(canon, report, [], (100,100), lambda crops: [""]*len(crops))
        assert "u01" not in [r["region_id"] for r in repaired]
        assert len(nr) == 0

    def test_hallucination_low_confidence_needs_review(self):
        from amta.audit import apply_repairs
        canon = [{"region_id": "u00", "text": "a", "page": 10, "bbox":[0,0,10,10]}]
        report = {"differences":[{"type":"hallucination","region_id":"u00","confidence":"low","reason":"x"}]}
        repaired, nr = apply_repairs(canon, report, [], (100,100), lambda crops: [""]*len(crops))
        assert len(repaired) == 1  # 不删
        assert len(nr) == 1

    def test_misread_triggers_reocr(self):
        from amta.audit import apply_repairs
        canon = [{"region_id": "u00", "text": "old", "page": 10, "bbox":[0,0,50,50]}]
        report = {"differences":[{"type":"misread","region_id":"u00","confidence":"high","reason":"x"}]}
        det = [{"node_id":"n1","bbox":[0,0,50,50]}]
        repaired, nr = apply_repairs(canon, report, det, (100,100), lambda crops: ["new_text"])
        assert repaired[0]["text"] == "new_text"

    def test_missed_goes_to_needs_review(self):
        from amta.audit import apply_repairs
        canon = [{"region_id": "u00", "text": "a", "page": 10, "bbox":[0,0,10,10]}]
        report = {"differences":[{"type":"missed","location":"右下","confidence":"high","reason":"x"}]}
        repaired, nr = apply_repairs(canon, report, [], (100,100), lambda crops: ["found_text"])
        assert len(nr) == 1  # missed 全部人工确认
        assert nr[0]["type"] == "missed"


class TestRenumberCanon:
    def test_renumber_continuous(self):
        from amta.audit import renumber_canon
        canon = [{"region_id":"u00","text":"a","page":10},
                 {"region_id":"u02","text":"b","page":10},  # u01 被删
                 {"region_id":"u05","text":"c","page":10}]
        out = renumber_canon(canon, 10)
        assert [r["region_id"] for r in out] == ["page_10_u00","page_10_u01","page_10_u02"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v -k "ApplyRepairs or RenumberCanon"`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `src/amta/audit.py` 末尾追加：

```python
def apply_repairs(canon: list[dict], report: dict, det_blocks: list[dict],
                  image_size: tuple[int, int], ocr_fn) -> tuple[list[dict], list[dict]]:
    """应用 audit 差异到 canon。返回 (repaired_canon, needs_review)。

    hallucination + high → 删除；low/medium → needs_review（不删）
    misread → 用原 bbox 重跑 ocr_fn 替换文本
    missed → 方位框 OCR，结果进 needs_review（不自动合入）
    ocr_fn: callable(list[crop_path]) -> list[text]
    """
    import tempfile
    from PIL import Image
    from pathlib import Path as _P
    w, h = image_size
    by_id = {r["region_id"]: dict(r) for r in canon}
    needs_review = []
    # node_id → bbox 映射
    bbox_by_node = {b.get("node_id"): b.get("bbox") for b in det_blocks}
    for d in report.get("differences", []):
        dtype, rid, conf = d["type"], d.get("region_id"), d.get("confidence", "medium")
        if dtype == "hallucination":
            if conf == "high" and rid in by_id:
                del by_id[rid]
            else:
                needs_review.append({"type": "hallucination", "region_id": rid,
                                     "reason": d.get("reason"), "confidence": conf})
        elif dtype == "misread" and rid in by_id:
            bb = by_id[rid].get("bbox") or bbox_by_node.get(by_id[rid].get("node_id"))
            if bb:
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                        tmp_path = _P(tf.name)
                    Image.new("RGB", (w, h), (255,255,255)).save(tmp_path)  # placeholder; CLI 传真图
                    new_text = ocr_fn([str(tmp_path)])[0]
                    tmp_path.unlink(missing_ok=True)
                    if new_text and not new_text.startswith("__ERROR__"):
                        by_id[rid]["text"] = new_text
                    else:
                        needs_review.append({"type":"misread","region_id":rid,
                                             "reason":"re-OCR empty/error","confidence":conf})
                except Exception as e:
                    needs_review.append({"type":"misread","region_id":rid,
                                         "reason":f"re-OCR failed: {e}","confidence":conf})
        elif dtype == "missed":
            needs_review.append({"type": "missed", "location": d.get("location"),
                                 "reason": d.get("reason"), "confidence": conf,
                                 "suggested_bbox": location_to_bbox(d.get("location",""), w, h)})
    return list(by_id.values()), needs_review


def renumber_canon(canon: list[dict], page_idx: int) -> list[dict]:
    """重新连续编号 region_id（u00 起），保留顺序和其他字段。"""
    out = []
    for i, r in enumerate(canon):
        item = dict(r)
        item["region_id"] = f"page_{page_idx}_u{i:02d}"
        out.append(item)
    return out
```

注意：`apply_repairs` 的 misread 重 OCR 需要真图裁框，上面 placeholder 逻辑由 CLI（Task 9）覆盖——纯函数测试用 mock ocr_fn 验证调用契约，CLI 负责真裁框。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audit.py -v -k "ApplyRepairs or RenumberCanon"`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/audit.py tests/test_audit.py
git commit -m "feat(repair): 02.6 apply_repairs 三分类修复 + renumber_canon 重新编号"
```

---

## Task 9: 02.6 repair CLI

**Files:**
- Create: `scripts/02.6_repair.py`
- Create: `scripts/_02_6_repair.py`（import 桥）
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `canon.json` + `audit_report.json` + `detection.json`（取 bbox）+ 整页原图
- Produces: `canon_repaired.json` + `needs_review` 条目（写入 page_N_needs_review.json）

- [ ] **Step 1: 写失败测试**

```python
class TestRepairCli:
    def test_repair_writes_repaired_canon(self, tmp_path, monkeypatch):
        import scripts._02_6_repair as repair_cli
        import json
        canon = [{"region_id":"page_10_u00","text":"a","page":10,"node_id":"n1","bbox":[0,0,50,50]}]
        report = {"differences":[]}
        det = {"blocks":[{"node_id":"n1","bbox":[0,0,50,50]}]}
        (tmp_path/"canon.json").write_text(json.dumps(canon),encoding="utf-8")
        (tmp_path/"audit.json").write_text(json.dumps(report),encoding="utf-8")
        (tmp_path/"det.json").write_text(json.dumps(det),encoding="utf-8")
        from PIL import Image
        raw = tmp_path/"11.jpg"; Image.new("RGB",(100,100)).save(raw)
        out = tmp_path/"canon_repaired.json"
        res = repair_cli.run(tmp_path/"canon.json", tmp_path/"audit.json",
                             tmp_path/"det.json", raw, out, ocr_engine="baberu")
        assert out.exists()
        assert res["n_repaired"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v -k RepairCli`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `scripts/02.6_repair.py`：

```python
"""02.6_repair 工位 — 消费 audit_report.json 修复 canon → canon_repaired.json。

hallucination(high) → 删；misread → 原 bbox 重跑 baberu OCR；
missed → 方位框 OCR → needs_review（不自动合入）。
"""
from __future__ import annotations
import argparse, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.audit import apply_repairs, renumber_canon
from amta.paths import write_json


def _reocr_crops(raw_path: Path, bboxes: list[list], engine: str = "auto") -> list[str]:
    """对给定 bbox 列表从原图裁框并 OCR，返回文本列表。"""
    from PIL import Image
    from amta.ocr_engines import ocr_batch
    img = Image.open(raw_path)
    crops = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="amta_repair_"))
    for i, bb in enumerate(bboxes):
        x1,y1,x2,y2 = [max(0,int(v)) for v in bb]
        x2,y2 = min(img.width,x2), min(img.height,y2)
        if x2<=x1 or y2<=y1:
            crops.append(None); continue
        p = tmp_dir / f"reocr_{i}.png"
        img.crop((x1,y1,x2,y2)).save(p)
        crops.append(str(p))
    valid = [c for c in crops if c]
    results = ocr_batch(valid, engine=engine) if valid else []
    text_map = {r["crop"]: (r.get("ocr") or "").strip() for r in results}
    return [text_map.get(c, "") if c else "" for c in crops]


def run(canon_path: Path, audit_path: Path, det_path: Path, raw_path: Path,
        out_path: Path, ocr_engine: str = "auto") -> dict:
    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    det = json.loads(det_path.read_text(encoding="utf-8"))
    det_blocks = det.get("blocks", [])
    page_idx = canon[0].get("page", 0) if canon else 0

    # misread 需要重 OCR：收集 bbox，批量 OCR
    misread_bboxes = []
    misread_rids = []
    for d in report.get("differences", []):
        if d["type"] == "misread" and d.get("region_id"):
            r = next((x for x in canon if x["region_id"] == d["region_id"]), None)
            if r and r.get("bbox"):
                misread_bboxes.append(r["bbox"])
                misread_rids.append(d["region_id"])
    reocr_texts = _reocr_crops(raw_path, misread_bboxes, engine=ocr_engine) if misread_bboxes else []
    reocr_map = dict(zip(misread_rids, reocr_texts))

    # 用预取的 OCR 结果构造 ocr_fn
    def ocr_fn(crops):
        return [reocr_texts.pop(0) if reocr_texts else ""]

    # apply_repairs 的 misread 分支需要 bbox（canon item 已带 bbox）
    # 给 canon item 补 bbox（从 det_blocks 按 node_id 映射）
    bbox_by_node = {b.get("node_id"): b.get("bbox") for b in det_blocks}
    for r in canon:
        if "bbox" not in r and r.get("node_id") in bbox_by_node:
            r["bbox"] = bbox_by_node[r["node_id"]]

    repaired, needs_review = apply_repairs(canon, report, det_blocks,
                                           (0,0), ocr_fn)  # image_size 不用于 misread（已有 bbox）
    # misread 直接用预取结果覆盖（apply_repairs 内部 placeholder 逻辑在 CLI 层不用）
    for d in report.get("differences", []):
        if d["type"] == "misread" and d.get("region_id") in reocr_map:
            rid = d["region_id"]
            for r in repaired:
                if r["region_id"] == rid:
                    new_t = reocr_map[rid]
                    if new_t and not new_t.startswith("__ERROR__"):
                        r["text"] = new_t

    # missed 方位框 OCR（进 needs_review，附 OCR 结果供人工确认）
    from PIL import Image as _Img
    from amta.audit import location_to_bbox
    img = _Img.open(raw_path)
    for nr in needs_review:
        if nr["type"] == "missed":
            bb = nr.get("suggested_bbox", [0,0,img.width,img.height])
            texts = _reocr_crops(raw_path, [bb], engine=ocr_engine)
            nr["reocr_text"] = texts[0] if texts else ""

    # 清理 bbox 字段（不落 canon_repaired）
    for r in repaired:
        r.pop("bbox", None)
        r.pop("is_container", None)
        r.pop("parent_node_id", None)
    repaired = renumber_canon(repaired, page_idx)
    write_json(out_path, repaired)

    nr_path = out_path.parent / f"page_{page_idx}_needs_review.json"
    if needs_review:
        write_json(nr_path, {"needs_review": needs_review})

    return {"n_repaired": len(repaired), "n_needs_review": len(needs_review),
            "out": str(out_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="02.6 repair 工位")
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--audit", required=True, type=Path)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ocr-engine", default="auto")
    args = ap.parse_args()
    r = run(args.canon, args.audit, args.det, args.raw, args.out, ocr_engine=args.ocr_engine)
    print(f"[02.6_repair] repaired={r['n_repaired']} needs_review={r['n_needs_review']} -> {args.out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

创建 `scripts/_02_6_repair.py`（import 桥，同 Task 7 模式）：

```python
import importlib.util, pathlib
_p = pathlib.Path(__file__).resolve().parent / "02.6_repair.py"
_spec = importlib.util.spec_from_file_location("_02_6_repair", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
for _n in dir(_mod):
    if not _n.startswith("__"):
        globals()[_n] = getattr(_mod, _n)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audit.py -v -k RepairCli`
Expected: 1 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add scripts/02.6_repair.py scripts/_02_6_repair.py tests/test_audit.py
git commit -m "feat(repair): 02.6_repair CLI，消费audit报告修复canon"
```

---

## Task 10: A1 — suggestions 守卫

**Files:**
- Modify: `src/amta/translate.py`（`SuggestionsExtractor.extract`，L454-469）
- Test: `tests/test_translate.py`

**Interfaces:**
- Produces: `SuggestionsExtractor.extract` 对译文 >12 字或含句末标点的不产出 suggestion

- [ ] **Step 1: 写失败测试**

```python
class TestSuggestionsGuard:
    def test_skips_long_translation(self):
        from amta.translate import SuggestionsExtractor
        ex = SuggestionsExtractor()
        canon = [{"region_id":"u0","text":"サグメ","page":1}]
        trans = {"u0": "说起来探女你在做什么研究啊这个太长了"}
        out = ex.extract(canon, trans)
        assert len(out) == 0

    def test_skips_sentence_punctuation(self):
        from amta.translate import SuggestionsExtractor
        ex = SuggestionsExtractor()
        canon = [{"region_id":"u0","text":"サグメ","page":1}]
        trans = {"u0": "探女。"}
        out = ex.extract(canon, trans)
        assert len(out) == 0

    def test_allows_short_term(self):
        from amta.translate import SuggestionsExtractor
        ex = SuggestionsExtractor()
        canon = [{"region_id":"u0","text":"サグメ","page":1}]
        trans = {"u0": "探女"}
        out = ex.extract(canon, trans)
        assert len(out) == 1
        assert out[0]["term"] == "サグメ"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_translate.py -v -k SuggestionsGuard`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `src/amta/translate.py` 的 `SuggestionsExtractor` 类中加守卫常量和检查。在 `_KATAKANA_STOP` 之后加：

```python
# A1：译文守卫——超过此长度或含句末标点的译文不产生 suggestion（防整句污染术语库）
_SUGG_MAX_LEN = 12
_SUGG_PUNCT = set("。！？…!?.")
```

修改 `extract` 方法，在 `suggestions.append` 之前加：

```python
    def extract(self, canon: list[dict], translations: dict[str, str]) -> list[dict]:
        suggestions = []
        for r in canon:
            text = r["text"] or ""
            translated = (translations.get(r["region_id"], "") or "").strip()
            # A1 守卫：长句/含句末标点 → 不是术语译名，跳过
            if len(translated) > _SUGG_MAX_LEN or any(p in translated for p in _SUGG_PUNCT):
                continue
            for m in _KATAKANA_TERM.finditer(text):
                term = m.group(0)
                if term in self.existing or term in _KATAKANA_STOP:
                    continue
                suggestions.append({
                    "term": term,
                    "source": r.get("region_id", ""),
                    "page": r.get("page", 0),
                    "translation": translated,
                    "status": "candidate",
                })
        return suggestions
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_translate.py -v -k SuggestionsGuard`
Expected: 3 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "fix(translate): A1 suggestions 守卫，长句/句末标点不产生术语候选"
```

---

## Task 11: A2 — lookup_term 前缀匹配 + aliases

**Files:**
- Modify: `src/amta/translate.py`（`execute_tool` 的 lookup_term 分支，L233-250）
- Test: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
class TestLookupTermFuzzy:
    def test_exact_match(self):
        from amta.translate import execute_tool
        ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "p3"}}}
        out = execute_tool("lookup_term", {"term": "サグメ"}, ws)
        assert "探女" in out

    def test_prefix_match(self):
        from amta.translate import execute_tool
        ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "p3"}},
              "characters": {}}
        out = execute_tool("lookup_term", {"term": "サグ姉様"}, ws)
        assert "サグメ" in out and "探女" in out
        assert "相关" in out or "自行判断" in out

    def test_alias_match(self):
        from amta.translate import execute_tool
        ws = {"characters": {"探女": {"aliases": ["サグメ"], "canon_translation": "探女",
                                      "status": "confirmed", "source": "p1"}}, "terms": {}}
        out = execute_tool("lookup_term", {"term": "サグメ"}, ws)
        assert "探女" in out

    def test_no_match(self):
        from amta.translate import execute_tool
        out = execute_tool("lookup_term", {"term": "ZZZZ"}, {"terms":{},"characters":{}})
        assert "未找到" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_translate.py -v -k LookupTermFuzzy`
Expected: FAIL — 前缀匹配不命中

- [ ] **Step 3: 实现**

替换 `execute_tool` 中 `if name == "lookup_term":` 整个分支（L233-250）：

```python
    if name == "lookup_term":
        term = str(args.get("term", "")).strip()
        if not term:
            return "参数缺失：请提供 term"
        # 1. 精确匹配 terms + characters（含 aliases）
        hit = None
        for pool, kind in ((ws.get("terms", {}), "术语"), (ws.get("characters", {}), "角色")):
            for k, v in pool.items():
                if k == term or norm(k) == norm(term):
                    hit = {**v, "kind": kind, "key": k}; break
                aliases = v.get("aliases", []) if isinstance(v, dict) else []
                if term in aliases or norm(term) in [norm(a) for a in aliases]:
                    hit = {**v, "kind": kind, "key": k}; break
            if hit: break
        if hit:
            trans = hit.get("translation") or hit.get("canon_translation") or "?"
            return f"{hit['kind']}「{hit['key']}」= {trans}（status={hit.get('status','?')}，来源 {hit.get('source','?')}）"
        # 2. 前缀匹配（前2字符），返回相关词条供模型自判（A2）
        prefix = term[:2]
        related = []
        for pool, kind in ((ws.get("terms", {}), "术语"), (ws.get("characters", {}), "角色")):
            for k, v in pool.items():
                if norm(k).startswith(norm(prefix)):
                    trans = v.get("translation") or v.get("canon_translation") or "?"
                    related.append(f"{kind}「{k}」= {trans}（status={v.get('status','?')}）")
                for a in (v.get("aliases", []) if isinstance(v, dict) else []):
                    if norm(a).startswith(norm(prefix)):
                        trans = v.get("translation") or v.get("canon_translation") or "?"
                        related.append(f"{kind}「{k}」(alias {a}) = {trans}")
        if related:
            return (f"未找到精确词条「{term}」，相关词条（请基于上下文自行判断是否适用）：\n"
                    + "\n".join(related[:5]))
        return f"未找到术语「{term}」的已确认译名（可基于上下文自行判断）"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_translate.py -v -k LookupTermFuzzy`
Expected: 4 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "fix(translate): A2 lookup_term 前缀匹配+aliases搜索，未命中返回相关词条"
```

---

## Task 12: category prompt 指导

**Files:**
- Modify: `src/amta/translate.py`（`_prompt_parts` L148-161、`_current_block` L324-326）
- Test: `tests/test_translate.py`

- [ ] **Step 1: 写失败测试**

```python
class TestCategoryPrompt:
    def test_user_block_includes_category_prefix(self):
        from amta.translate import _build_current_content
        batch = [{"region_id":"u0","text":"ビフン","category":"sfx"}]
        content = _build_current_content("", batch)
        assert "[sfx]" in content

    def test_system_prompt_includes_category_strategies(self):
        from amta.translate import build_translation_prompt
        prompt = build_translation_prompt([{"region_id":"u0","text":"x","category":"dialogue_bubble"}], {})
        assert "sfx" in prompt["system"]
        assert "拟声词" in prompt["system"]

    def test_no_category_no_prefix(self):
        from amta.translate import _build_current_content
        batch = [{"region_id":"u0","text":"こんにちは"}]
        content = _build_current_content("", batch)
        assert "[" not in content.split("|")[0]  # region_id 前无 [category]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_translate.py -v -k CategoryPrompt`
Expected: FAIL

- [ ] **Step 3: 实现**

修改 `_prompt_parts` 的 system_lines（L156）：

```python
    system_lines = [
        "你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。",
        "翻译策略（按 region 的 category 标注）：",
        "- dialogue_bubble（对白气泡）：自然口语中文",
        "- sfx（拟声词）：译成中文拟声词（如 ドキドキ→心跳加速/咚咚），不要音译成片假名",
        "- overlay_text（压脸/框外字）：简短标注，贴合画面",
        "- aside（小字碎碎念）：轻声补充语气，可稍小随意",
        "未标注 category 的按普通对白处理。",
    ]
```

修改 `_current_block`（L324-326）：

```python
def _current_block(canon: list[dict]) -> str:
    lines = []
    for r in canon:
        cat = r.get("category")
        prefix = f"[{cat}] " if cat else ""
        lines.append(f'{prefix}{r["region_id"]}|{r["text"]}')
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_translate.py -v -k CategoryPrompt`
Expected: 3 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): category prompt 指导，sfx/overlay/aside/对白分策略"
```

---

## Task 13: 术语确认门槛 ≥3 页

**Files:**
- Modify: `scripts/merge_suggestions.py`（`merge` 函数，L17-35）
- Test: `tests/test_shared_lib.py`

- [ ] **Step 1: 写失败测试**

```python
class TestMergeThreshold:
    def test_three_pages_consistent_confirmed(self):
        from merge_suggestions import merge
        state = {"terms": {}}
        suggestions = [
            {"term":"サグメ","translation":"探女","page":1},
            {"term":"サグメ","translation":"探女","page":2},
            {"term":"サグメ","translation":"探女","page":3},
        ]
        out = merge(state, suggestions)
        assert out["terms"]["サグメ"]["status"] == "confirmed"

    def test_two_pages_consistent_inferred(self):
        from merge_suggestions import merge
        state = {"terms": {}}
        suggestions = [
            {"term":"サグメ","translation":"探女","page":1},
            {"term":"サグメ","translation":"探女","page":2},
        ]
        out = merge(state, suggestions)
        assert out["terms"]["サグメ"]["status"] == "inferred"

    def test_inconsistent_candidate(self):
        from merge_suggestions import merge
        state = {"terms": {}}
        suggestions = [
            {"term":"サグメ","translation":"探女","page":1},
            {"term":"サグメ","translation":"萨格","page":2},
        ]
        out = merge(state, suggestions)
        assert out["terms"]["サグメ"]["status"] == "candidate"
```

注意：`merge_suggestions.py` 在 scripts/ 下，测试需要 import 桥。如果已有 `_merge_suggestions.py` 桥则用，否则在测试中用 importlib。检查 tests/ 目录是否已有桥文件；若无，在测试文件顶部加：

```python
import importlib.util, pathlib, sys
_bridge = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "_merge_suggestions.py"
if _bridge.exists():
    import importlib
    _mod = importlib.import_module("scripts._merge_suggestions")
else:
    # 直接按文件路径加载
    _p = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "merge_suggestions.py"
    _spec = importlib.util.spec_from_file_location("merge_suggestions", _p)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
merge = _mod.merge
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_shared_lib.py -v -k MergeThreshold`
Expected: FAIL — 2 页一致当前升 confirmed

- [ ] **Step 3: 实现**

修改 `scripts/merge_suggestions.py` 的 `merge` 函数中 `consistent` 和 `status` 行（L27-28）：

```python
        consistent = len(translations) == 1
        n_pages = len(pages)
        if consistent and n_pages >= 3:
            status = "confirmed"
        elif consistent and n_pages >= 2:
            status = "inferred"
        else:
            status = "candidate"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_shared_lib.py -v -k MergeThreshold`
Expected: 3 passed

- [ ] **Step 5: fastcheck + 提交**

```bash
git add scripts/merge_suggestions.py tests/test_shared_lib.py
git commit -m "fix(terms): 术语确认门槛≥3页confirmed，2页一致inferred不进glossary强制"
```

---

## Task 14: 00_run_all 接入 02.5/02.6

**Files:**
- Modify: `scripts/00_run_all.py`
- Test: `tests/test_pipeline_flow.py`

**Interfaces:**
- 02_ocr 后 → 02.5_audit（读 canon.json → audit_report.json）→ 02.6_repair（读 canon+audit+det → canon_repaired.json）
- 03_translate 读 canon_repaired.json（存在时）

- [ ] **Step 1: 写失败测试**

```python
class TestRunAllAuditIntegration:
    def test_translate_reads_repaired_canon(self, tmp_path):
        """canon_repaired.json 存在时 03 读它而非 canon.json。"""
        import scripts._00_run_all as runall
        ws = tmp_path / "ws"; artifacts = ws / "artifacts"; artifacts.mkdir(parents=True)
        (artifacts / "page_10_canon.json").write_text("[]", encoding="utf-8")
        (artifacts / "page_10_canon_repaired.json").write_text('[{"region_id":"page_10_u00","text":"fixed","page":10}]', encoding="utf-8")
        chosen = runall._select_canon_path(artifacts, "page_10")
        assert chosen.name == "page_10_canon_repaired.json"

    def test_select_canon_fallback_to_original(self, tmp_path):
        import scripts._00_run_all as runall
        ws = tmp_path / "ws"; artifacts = ws / "artifacts"; artifacts.mkdir(parents=True)
        (artifacts / "page_10_canon.json").write_text("[]", encoding="utf-8")
        chosen = runall._select_canon_path(artifacts, "page_10")
        assert chosen.name == "page_10_canon.json"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline_flow.py -v -k RunAllAudit`
Expected: FAIL — `_select_canon_path` 不存在

- [ ] **Step 3: 实现**

在 `scripts/00_run_all.py` 加辅助函数：

```python
def _select_canon_path(artifacts: Path, page: str) -> Path:
    """03 优先读 canon_repaired.json（02.6 产物），回退 canon.json。"""
    repaired = artifacts / f"{page}_canon_repaired.json"
    if repaired.exists():
        return repaired
    return artifacts / f"{page}_canon.json"
```

在 `run` 函数的 02_ocr 之后、03_translate 之前插入 audit + repair 步骤。找到 `# ---- 03 translate ----` 之前加：

```python
            # ---- 02.5 audit ----
            audit_path = _out(ws_root, f"{page}_audit.json")
            if audit_path.exists():
                log.add_span(run_id, step="02.5_audit", page=page, status="skipped",
                             input=str(canon_path), output=str(audit_path))
            else:
                t0 = time.time()
                _run_cli([str(HERE / "02.5_audit.py"),
                          "--canon", str(canon_path), "--raw", str(raw),
                          "--out", str(audit_path)])
                log.add_span(run_id, step="02.5_audit", page=page, status="ok",
                             input=str(canon_path), output=str(audit_path),
                             duration_s=time.time() - t0)

            # ---- 02.6 repair ----
            repaired_path = _out(ws_root, f"{page}_canon_repaired.json")
            if repaired_path.exists():
                log.add_span(run_id, step="02.6_repair", page=page, status="skipped",
                             input=str(audit_path), output=str(repaired_path))
            else:
                t0 = time.time()
                _run_cli([str(HERE / "02.6_repair.py"),
                          "--canon", str(canon_path), "--audit", str(audit_path),
                          "--det", str(det_path), "--raw", str(raw),
                          "--out", str(repaired_path), "--ocr-engine", ocr_engine])
                log.add_span(run_id, step="02.6_repair", page=page, status="ok",
                             input=str(audit_path), output=str(repaired_path),
                             duration_s=time.time() - t0)
```

修改 03_translate 的 `--canon` 参数，把 `str(canon_path)` 改为 `str(_select_canon_path(_out(ws_root, "").parent, page))`。更清晰的做法：在 03 段前加：

```python
            canon_for_translate = _select_canon_path(_out(ws_root, "").parent, page)
```

然后把 03 段的 `"--canon", str(canon_path)` 改为 `"--canon", str(canon_for_translate)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pipeline_flow.py -v -k RunAllAudit`
Expected: 2 passed

- [ ] **Step 5: 全量 fastcheck 回归**

Run: `python scripts/fastcheck.py`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add scripts/00_run_all.py tests/test_pipeline_flow.py
git commit -m "feat(orchestrator): 接入02.5_audit+02.6_repair，03优先读canon_repaired"
```

---

## Task 15: 端到端冒烟验证（1 页）

**Files:** 无代码改动，验证任务

- [ ] **Step 1: 确认引擎存活**

```powershell
curl http://127.0.0.1:4000/api/v1/health
```

- [ ] **Step 2: 跑单页全链路**

```powershell
python scripts/00_run_all.py --work-id touhou-single-wing `
  --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" `
  --start-page 11 --end-page 11 --ocr-engine auto
```

Expected: 01→02→02.5→02.6→03 全 ok，artifacts 下有：
- page_10_detection.json
- page_10_canon.json
- page_10_audit.json
- page_10_canon_repaired.json
- page_10_translation.json

- [ ] **Step 3: 人工核对 audit 报告**

打开 `page_10_audit.json`，人工核对 differences 是否合理（VLM 有没有乱判）。

- [ ] **Step 4: 断点续跑验证**

重跑同一命令，确认所有步骤 skipped。删除 page_10_canon_repaired.json 重跑，确认只从 02.6 续跑。

- [ ] **Step 5: 记录结论**

把单页冒烟结果记录到 `4_progress.md`，准备 11-20 全量重跑。

---

## Self-Review

**1. Spec coverage:**
- A4 bubble_type 优先级 → Task 1 ✅
- A3 容器文本+sub_tier → Task 4+5 ✅
- C10 碎片框 → Task 2+5 ✅
- C9 墨量拒框 → Task 3+5 ✅
- 02.5 audit 报告版 → Task 6+7 ✅
- 02.6 repair 三分类 → Task 8+9 ✅
- A1 suggestions 守卫 → Task 10 ✅
- A2 lookup 前缀匹配 → Task 11 ✅
- category prompt 指导 → Task 12 ✅
- 术语门槛 ≥3 页 → Task 13 ✅
- 00_run_all 接入 → Task 14 ✅
- VLM 探针前置验证 → Task 0 ✅
- 03.5 评审不升级（本次范围外）✅
- 04/05 渲染（本次范围外）✅

**2. Placeholder scan:** 无 TBD/TODO；Task 8 的 apply_repairs misread placeholder 逻辑已在 Task 9 CLI 层用真裁框覆盖，纯函数测试用 mock 验证契约。

**3. Type consistency:**
- region_id 格式统一 `page_{idx}_u{MM}`
- category 枚举 `dialogue_bubble/overlay_text/sfx`（canon_schema.py 已校验）
- sub_tier 枚举 `primary/aside`
- confidence 枚举 `high/medium/low`
- `merge_fragments`/`ink_ratio`/`assign_sub_tier_by_area`/`build_audit_prompt`/`parse_audit_report`/`location_to_bbox`/`apply_repairs`/`renumber_canon` 函数名全篇一致
- 02.5/02.6 import 桥命名 `_02_5_audit`/`_02_6_repair` 一致

**4. 执行顺序约束：** Task 0（探针）必须在 Task 6-9 之前；Task 1-5 可按序；Task 6-9 依赖 Task 1-5 的产物契约；Task 10-13 互相独立可并行；Task 14 依赖全部；Task 15 最后。
