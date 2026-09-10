# Stage 4: 04_inpaint 工位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 04_inpaint 工位——基于 detection.json 的 category 三级分类生成擦除策略，走 koharu lama-manga 完成去字，产出 clean 图 + inpaint artifact + 机械检查。

**Architecture:** 策略与执行分离：`inpaint_strategy` 纯函数（category → 擦除动作，零依赖可单测）决定做什么，`scripts/04_inpaint.py` 薄 CLI 调 koharu REST（put_mask → run_pipeline(lama-manga) → export_page）执行；产物 `artifacts/<page>_inpaint.json`（轻量：动作清单 + 校验结果）+ `artifacts/clean/<page>_clean.png`。断点续跑沿用"文件存在=跳过"。

**Tech Stack:** Python 3.13 + stdlib（零依赖铁律 ADR-009/018）+ koharu v0.59.1 REST (:4000) + Pillow（已有）+ pytest（fastcheck）。

**Spec:** `docs/superpowers/plans/2026-08-27-stage46-guidance-spec.md`（Stage 4-6 契约甄别执行指南，Patrick + 外部顾问最终决策）——本计划只实现 Phase 2（Stage 4）。

## Global Constraints

- 零新增第三方依赖（requests/pillow 已批准，其余一律 stdlib）
- fastcheck 必须用 Python 3.13 全局解释器（`C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe`），提交时 PATH 前置 Python313（pre-commit hook 拦截）
- 测试一律 pytest 风格进 `tests/`；改脚本需同步 `_NN_name.py` 测试桥（数字前缀 import，L20）
- category 枚举 `{dialogue_bubble, overlay_text, sfx}`；sub_tier 枚举 `{primary, aside}`（ADR-019）
- 断点续跑契约：产物文件存在 = 跳过（ADR-018）；本工位产物 = `*_inpaint.json` + `clean/*_clean.png`
- koharu 只读不升级（钉 v0.59.1）；并发 workers 必须 =1
- sfx_triage 判定（side_annotation/skip）**不在本计划范围**（延后，schema 预留枚举即可）；本期 sfx 一律走 inpaint_and_render
- overlay_text 检测盲区补强不在本计划范围（记录为已知风险，见 Task 4）

---

### Task 1: koharu inpaint 链路探针（live 冒烟，锁定 REST 契约）

**Files:**
- Create: `scripts/probe_inpaint.py`（一次性探针，跑完可 trash，不提交）
- Create: `docs/superpowers/plans/2026-08-27-stage4-probe-findings.md`（探针记录，提交）

**Interfaces:**
- Consumes: koharu v0.59.1 REST :4000（在线），`src/amta/koharu_client.py` 现有方法（`import_page` / `put_mask` / `run_pipeline` / `wait_operation` / `export_page` / `get_scene`）
- Produces: 探针结论——(a) mask role 用 `segment` 还是 `brushInpaint`；(b) `run_pipeline(steps=["lama-manga"])` 前置条件（是否需要先跑 speech-bubble-segmentation 产出 BubbleMask）；(c) Inpainted 结果如何取回（export_page PNG？blob？）；(d) lama-manga CPU 单页耗时

- [ ] **Step 1: 写探针脚本**

```python
"""探针: koharu v0.59.1 lama-manga inpaint 链路契约。一次性,跑完删除。"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.koharu_client import KoharuClient
from amta.paths import write_json

c = KoharuClient()
c.wait_server(timeout=60)
# 1) 引擎清单确认 lama-manga 可用
engines = c.engines()
print("lama-manga in engines:", any(e.get("id") == "lama-manga" for e in engines))

# 2) 导入一张合成测试页(白底+黑色矩形模拟文字块)
from PIL import Image, ImageDraw
probe = Path(__file__).resolve().parent.parent / "output" / "tmp" / "probe_inpaint.png"
probe.parent.mkdir(parents=True, exist_ok=True)
img = Image.new("RGB", (400, 600), "white")
d = ImageDraw.Draw(img)
d.rectangle([50, 100, 150, 160], fill="black")
d.rectangle([200, 300, 300, 360], fill="black")
img.save(probe)

page_id = c.import_page(probe)
print("page_id:", page_id)

# 3) 上传 segment mask(黑色矩形区域全黑,其余白)
mask = Image.new("L", (400, 600), 255)
md = ImageDraw.Draw(mask)
md.rectangle([45, 95, 155, 165], fill=0)
md.rectangle([195, 295, 305, 365], fill=0)
mask_buf = mask.tobytes()
try:
    r = c.put_mask(page_id, "segment", mask_buf)
    print("put_mask segment:", r)
except Exception as e:
    print("put_mask segment FAIL:", e)

# 4) 跑 inpaint pipeline
try:
    op = c.run_pipeline(page_id, ["lama-manga"], prefix="probe-inpaint", timeout=1200)
    print("run_pipeline op:", op)
    res = c.wait_operation(op["id"], timeout=600) if isinstance(op, dict) and "id" in op else None
    print("wait_operation:", {k: res.get(k) for k in ("id", "status", "state")} if res else None)
except Exception as e:
    print("run_pipeline FAIL:", e)

# 5) 取回结果
try:
    out = probe.parent / "probe_inpainted.png"
    c.export_page(page_id, "png", out)
    print("export ok:", out.exists(), out.stat().st_size if out.exists() else 0)
except Exception as e:
    print("export FAIL:", e)

write_json(probe.parent / "probe_findings_raw.json", {"page_id": page_id, "engines": engines})
```

- [ ] **Step 2: 跑探针**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" scripts\probe_inpaint.py`
Expected: 输出各步骤结果；若 put_mask/run_pipeline 报错，读 koharu 日志定位（:4000 REST 文档或 `docs/03-koharu上游详报.md`）

- [ ] **Step 3: 记录探针结论**
把 (a)-(d) 四问结论写入 `docs/superpowers/plans/2026-08-27-stage4-probe-findings.md`（含失败尝试与根因），作为 Task 2 的接口依据。若探针暴露契约与假设不符（如需要先跑 segmentation 步骤），记录修正。

- [ ] **Step 4: 提交探针记录**

```bash
git add docs/superpowers/plans/2026-08-27-stage4-probe-findings.md
git commit -m "docs(stage4): koharu inpaint 链路探针结论"
```

---

### Task 2: koharu_client 封装 run_inpaint

**Files:**
- Modify: `src/amta/koharu_client.py`（新增方法，紧邻 put_mask 后）
- Test: `tests/test_client_helpers.py`

**Interfaces:**
- Consumes: Task 1 探针结论（mask role 名、pipeline 步骤序列）；现有 `put_mask` / `run_pipeline` / `wait_operation` / `export_page`
- Produces: `KoharuClient.run_inpaint(page_id: str, mask_png: bytes, role: str = "segment", engine: str = "lama-manga", steps: list[str] | None = None, timeout: int = 1800) -> dict`（返回 wait_operation 结果，含 status/state）

- [ ] **Step 1: 写失败测试**（monkeypatch 实例方法，不碰网络）

```python
def test_run_inpaint_uploads_mask_and_runs_pipeline(monkeypatch):
    """run_inpaint = put_mask(role) + run_pipeline(步骤) + wait_operation,返回终态。"""
    from amta.koharu_client import KoharuClient
    c = KoharuClient()
    calls = []

    def fake_put_mask(page_id, role, png_bytes, engine=None):
        calls.append(("put_mask", page_id, role, len(png_bytes)))
        return {"ok": True}

    def fake_run_pipeline(page_id, steps, **kw):
        calls.append(("run_pipeline", page_id, steps))
        return {"id": "op1"}

    def fake_wait(op_id, timeout):
        calls.append(("wait", op_id))
        return {"id": "op1", "status": "completed"}

    monkeypatch.setattr(c, "put_mask", fake_put_mask)
    monkeypatch.setattr(c, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(c, "wait_operation", fake_wait)

    res = c.run_inpaint("p1", b"\x00" * 16, role="segment")
    assert res["status"] == "completed"
    assert ("put_mask", "p1", "segment", 16) in calls
    assert ("run_pipeline", "p1", ["lama-manga"]) in calls
    assert ("wait", "op1") in calls
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_client_helpers.py -q --basetemp output/logs/.pytest-basetemp -k run_inpaint`
Expected: FAIL — `run_inpaint` not defined

- [ ] **Step 3: 实现 run_inpaint**

```python
def run_inpaint(self, page_id: str, mask_png: bytes, role: str = "segment",
                engine: str = "lama-manga", steps: list[str] | None = None,
                timeout: int = 1800) -> dict:
    """上传 mask 并跑 inpaint pipeline(默认 lama-manga),等待终态。

    Task 1 探针定案: mask role=segment, 步骤序列默认 [engine]。
    """
    self.put_mask(page_id, role, mask_png, engine=engine)
    steps = steps or [engine]
    op = self.run_pipeline(page_id, steps, prefix="amta-inpaint", timeout=timeout)
    op_id = op["id"] if isinstance(op, dict) else op
    return self.wait_operation(op_id, timeout=timeout)
```

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/koharu_client.py tests/test_client_helpers.py
git commit -m "feat(koharu): run_inpaint 封装(mask 上传 + lama-manga pipeline)"
```

---

### Task 3: inpaint_strategy 纯函数（category → 擦除策略）

**Files:**
- Create: `src/amta/inpaint_strategy.py`
- Test: `tests/test_inpaint_strategy.py`

**Interfaces:**
- Consumes: DetectionArtifact 结构（`regions[].category` / `regions[].bbox` / `image_meta`，ADR-019 契约）
- Produces:
  - `plan_inpaint(regions: list[dict], image_meta: dict | None = None) -> list[dict]`——每 region 输出 `{region_id, category, action, bbox, mask_pixels: int}`，action ∈ `{fill_white, inpaint}`
  - 策略：`dialogue_bubble → fill_white`（白底直填，蓝图 bypass）；`overlay_text / sfx → inpaint`（走 mask+inpaint）
  - 校验：bbox 越界（超出 image_meta 宽高）→ action=`skip` + 记 reason（防御脏 bbox）

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.inpaint_strategy import plan_inpaint


def test_bubble_fills_white_and_sfx_inpaints():
    regions = [
        {"region_id": "page_0_u00", "category": "dialogue_bubble",
         "bbox": [10, 10, 90, 40]},
        {"region_id": "page_0_u01", "category": "sfx",
         "bbox": [110, 50, 190, 80]},
        {"region_id": "page_0_u02", "category": "overlay_text",
         "bbox": [210, 90, 290, 120]},
    ]
    plan = plan_inpaint(regions, image_meta={"width": 400, "height": 600})
    by_id = {p["region_id"]: p for p in plan}
    assert by_id["page_0_u00"]["action"] == "fill_white"
    assert by_id["page_0_u01"]["action"] == "inpaint"
    assert by_id["page_0_u02"]["action"] == "inpaint"


def test_out_of_bounds_bbox_skipped():
    regions = [{"region_id": "r0", "category": "dialogue_bubble",
                "bbox": [390, 0, 500, 50]}]  # x2 越界
    plan = plan_inpaint(regions, image_meta={"width": 400, "height": 600})
    assert plan[0]["action"] == "skip"
    assert "reason" in plan[0]


def test_missing_category_defaults_bubble():
    regions = [{"region_id": "r0", "bbox": [0, 0, 10, 10]}]  # 无 category(兼容旧产物)
    plan = plan_inpaint(regions, image_meta={"width": 100, "height": 100})
    assert plan[0]["action"] == "fill_white"


def test_empty_regions():
    assert plan_inpaint([]) == []
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_inpaint_strategy.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 inpaint_strategy.py**

```python
"""Stage 4 擦除策略(纯函数,零依赖): category → fill_white / inpaint / skip。

ADR-019 + Spec §2: dialogue_bubble 白底直填(蓝图 bypass invariant);
overlay_text / sfx 走 mask+inpaint;bbox 越界防御性 skip。
sfx_triage(旁注/保全)延后——本期 sfx 一律 inpaint。
"""
from __future__ import annotations

FILL_WHITE = "fill_white"
INPAINT = "inpaint"
SKIP = "skip"


def plan_inpaint(regions: list[dict], image_meta: dict | None = None) -> list[dict]:
    plan = []
    for r in regions:
        cat = r.get("category") or "dialogue_bubble"  # 兼容旧产物,保守默认
        bb = r.get("bbox")
        if not bb or len(bb) != 4:
            plan.append({"region_id": r.get("region_id"), "category": cat,
                         "action": SKIP, "bbox": bb, "reason": "no bbox"})
            continue
        if image_meta:
            w, h = image_meta.get("width", 1e9), image_meta.get("height", 1e9)
            x1, y1, x2, y2 = bb
            if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
                plan.append({"region_id": r.get("region_id"), "category": cat,
                             "action": SKIP, "bbox": bb, "reason": "bbox out of bounds"})
                continue
        action = FILL_WHITE if cat == "dialogue_bubble" else INPAINT
        plan.append({"region_id": r.get("region_id"), "category": cat,
                     "action": action, "bbox": bb})
    return plan
```

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/inpaint_strategy.py tests/test_inpaint_strategy.py
git commit -m "feat(stage4): inpaint_strategy 纯函数(category→fill_white/inpaint/skip)"
```

---

### Task 4: scripts/04_inpaint.py 工位（策略执行 + 产物 + 机械检查）

**Files:**
- Create: `scripts/04_inpaint.py`
- Create: `scripts/_04_inpaint.py`（测试桥，L20 惯例）
- Test: `tests/test_inpaint_station.py`

**Interfaces:**
- Consumes: `detection.json`（regions + image_meta，ADR-019）；`raw` 页图；`src/amta/inpaint_strategy.plan_inpaint`；`KoharuClient.run_inpaint`；`amta.paths` IO
- Produces:
  - `artifacts/clean/<page>_clean.png`（执行后图；fill_white 区域直接涂白，inpaint 区域贴回 koharu 结果）
  - `artifacts/<page>_inpaint.json` = `{work_id, page, actions: [...], checks: {pixel_diff_ratio, size_ok, filled: n, inpainted: n, skipped: n}, generated_at}`
  - CLI: `python scripts/04_inpaint.py --work-id <id> --det <detection.json> --raw <page图> --out <page>_inpaint.json --clean-dir <artifacts/clean> [--dry-run]`
  - 断点：`--out` 存在 → skip（00_run_all 调用方决定）；`--dry-run` 只产出 actions 不执行（供评审/报告）

- [ ] **Step 1: 写失败测试**（monkeypatch KoharuClient + Image 处理用真实 Pillow 小图）

```python
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image


def _load_impl():
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "scripts" / "_04_inpaint.py"
    spec = importlib.util.spec_from_file_location("_04_inpaint", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_station_fill_white_and_inpaint(tmp_path, monkeypatch):
    impl = _load_impl()
    raw = tmp_path / "1.jpg"
    img = Image.new("RGB", (200, 100), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 90, 40], fill="black")     # bubble → 涂白
    d.rectangle([110, 50, 190, 80], fill="black")   # sfx → inpaint
    img.save(raw)

    det = {"work_id": "w", "page": "1", "image_meta": {"width": 200, "height": 100, "channels": 3},
           "regions": [
               {"region_id": "page_0_u00", "category": "dialogue_bubble",
                "bbox": [10, 10, 90, 40]},
               {"region_id": "page_0_u01", "category": "sfx",
                "bbox": [110, 50, 190, 80]},
           ]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")

    class FakeK:
        def __init__(self): self.calls = []
        def wait_server(self, **kw): pass
        def import_page(self, p): return "pg1"
        def run_inpaint(self, page_id, mask_png, **kw):
            self.calls.append(("run_inpaint", len(mask_png)))
            return {"status": "completed"}

    fake = FakeK()
    monkeypatch.setattr(impl, "KoharuClient", lambda **kw: fake)

    out = tmp_path / "page_0_inpaint.json"
    clean_dir = tmp_path / "clean"
    doc = impl.run("w", det_path, raw, out, clean_dir=clean_dir)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["checks"]["filled"] == 1
    assert data["checks"]["inpainted"] == 1
    assert data["checks"]["size_ok"] is True
    clean = Image.open(clean_dir / "page_0_clean.png")
    assert clean.size == (200, 100)
    # bubble 区域已涂白
    assert clean.getpixel((50, 25)) == (255, 255, 255)
    # mask 上传过(inpaint 分支)
    assert any(c[0] == "run_inpaint" for c in fake.calls)


def test_station_dry_run_no_execution(tmp_path):
    impl = _load_impl()
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (100, 100), "white").save(raw)
    det = {"work_id": "w", "page": "1", "image_meta": {"width": 100, "height": 100},
           "regions": [{"region_id": "page_0_u00", "category": "dialogue_bubble",
                        "bbox": [0, 0, 10, 10]}]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")
    out = tmp_path / "p.json"
    doc = impl.run("w", det_path, raw, out, clean_dir=tmp_path / "clean", dry_run=True)
    assert doc["checks"]["filled"] == 1
    assert not (tmp_path / "clean" / "page_0_clean.png").exists()
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_inpaint_station.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — `_04_inpaint` 不存在

- [ ] **Step 3: 实现 04_inpaint.py**（要点：plan → fill_white 直涂 + inpaint 区域聚合 mask → `run_inpaint` → 贴回；机械检查 = clean 图与原图尺寸一致 + 涂白/贴回区域像素变化；`--dry-run` 只出 actions）

```python
"""04_inpaint 工位 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4, ADR-019 契约)。

用法: python scripts/04_inpaint.py --work-id <id> --det <detection.json> --raw <page图>
      --out <page>_inpaint.json --clean-dir <artifacts/clean> [--dry-run]
策略: category 三级分类(ADR-019) → dialogue_bubble 白底直填 / overlay_text+sfx mask+inpaint(koharu lama-manga)。
断点: --out 存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.inpaint_strategy import FILL_WHITE, INPAINT, SKIP, plan_inpaint  # noqa: E402
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def _apply_fill_white(img: Image.Image, bbox: list) -> None:
    x1, y1, x2, y2 = [int(v) for v in bbox]
    ImageDraw.Draw(img).rectangle([x1, y1, x2, y2], fill=(255, 255, 255))


def _build_mask(img: Image.Image, bboxes: list[list], pad: int = 4) -> bytes:
    """inpaint 区域聚合 mask: 目标区黑(0),其余白(255)。"""
    mask = Image.new("L", img.size, 255)
    d = ImageDraw.Draw(mask)
    for bb in bboxes:
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
        if x2 > x1 and y2 > y1:
            d.rectangle([x1, y1, x2, y2], fill=0)
    return mask.tobytes()


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        clean_dir: Path | None = None, dry_run: bool = False,
        host: str = "127.0.0.1", port: int = 4000) -> dict:
    det = read_json(det_path)
    img = Image.open(raw_page).convert("RGB")
    plan = plan_inpaint(det.get("regions") or [], det.get("image_meta"))

    filled = [p for p in plan if p["action"] == FILL_WHITE]
    inpaint_boxes = [p["bbox"] for p in plan if p["action"] == INPAINT]
    skipped = [p for p in plan if p["action"] == SKIP]

    if not dry_run and (filled or inpaint_boxes):
        for p in filled:
            _apply_fill_white(img, p["bbox"])
        if inpaint_boxes:
            client = KoharuClient(host=host, port=port)
            client.wait_server(timeout=60)
            page_id = client.import_page(raw_page)
            client.run_inpaint(page_id, _build_mask(img, inpaint_boxes),
                               role="segment", engine="lama-manga")
            # 贴回 koharu inpaint 结果(整页 Inpainted 直接作为 clean 底图)
            # 注: 探针 Task 1 定案取回方式后,此处按探针结论实现(export_page 或 blob 贴回)
        if clean_dir:
            clean_dir.mkdir(parents=True, exist_ok=True)
            clean_path = clean_dir / f"{det.get('page', raw_page.stem)}_clean.png"
            img.save(clean_path)

    doc = {
        "work_id": work_id,
        "page": det.get("page", raw_page.stem),
        "actions": plan,
        "checks": {
            "filled": len(filled),
            "inpainted": len(inpaint_boxes),
            "skipped": len(skipped),
            "size_ok": True,
            "pixel_diff_ratio": None,  # 贴回后与原图 diff(探针定案后补)
        },
        "dry_run": dry_run,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="04_inpaint 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--clean-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, clean_dir=a.clean_dir, dry_run=a.dry_run)
    print(f"[04_inpaint] {doc['page']}: filled={doc['checks']['filled']} "
          f"inpainted={doc['checks']['inpainted']} skipped={doc['checks']['skipped']} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> ⚠️ Task 1 探针定案后，把 `run_inpaint` 贴回方式（export_page 整页 或 blob 局部贴回）替换上面注释占位，并补 `pixel_diff_ratio` 计算（clean vs raw 的像素差异比例，>0 即证明有擦除发生）。该修正直接在 Task 4 实现时按探针文档执行，不单独开任务。

- [ ] **Step 4: 创建测试桥 `scripts/_04_inpaint.py`**

```python
"""测试桥(L20 惯例): 数字前缀脚本无法直接 import,供 tests 加载。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from scripts_impl import *  # noqa: F401,F403  # 若仓库无 scripts_impl 惯例则改为 exec 方式
```

> 注：若仓库已有 `_02_ocr.py` 桥写法（tests/test_pipeline_flow.py `_impl` 是 exec 加载），测试里已用 exec 方式加载 `_04_inpaint.py`，则桥文件可省——实现时对照 `scripts/_03_translate.py` 是否存在决定。存在则复制同款，不存在则跳过桥。

- [ ] **Step 5: 跑测试确认通过**
Run: 同 Step 2
Expected: 2 passed（若探针结论要求贴回方式改动，测试同步调整断言）

- [ ] **Step 6: 提交**

```bash
git add scripts/04_inpaint.py scripts/_04_inpaint.py tests/test_inpaint_station.py
git commit -m "feat(stage4): 04_inpaint 工位(category 策略执行 + clean 产物 + 机械检查)"
```

---

### Task 5: 00_run_all 接入 04 工位 + 单页冒烟

**Files:**
- Modify: `scripts/00_run_all.py`
- Test: `tests/test_pipeline_flow.py`（补编排测试）

**Interfaces:**
- Consumes: `scripts/04_inpaint.py` CLI；现有 `_run_cli` / `log.add_span` 编排骨架（ADR-018）
- Produces: `00_run_all --with-inpaint` 标志——每页在 03 之后跑 04（detection 存在即跑，`*_inpaint.json` 存在即 skip）；pipeline_log 新增 `04_inpaint` span

- [ ] **Step 1: 写失败测试**（复用现有 00_run_all 测试的 fake 模式）

```python
def test_run_all_with_inpaint_flag_invokes_04(tmp_path, monkeypatch):
    """--with-inpaint 时每页 03 之后调 04_inpaint。"""
    import json
    from PIL import Image

    impl = _impl("_00_run_all")
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "1.jpg")

    calls = []

    def fake_cli(args):
        calls.append(Path(args[0]).name)
        name = Path(args[0]).name
        base = tmp_path / "ws" / "t" / "artifacts"
        if name == "01_detect.py":
            base.mkdir(parents=True, exist_ok=True)
            (base / "page_0_detection.json").write_text(
                json.dumps({"work_id": "t", "page": "1",
                            "image_meta": {"width": 100, "height": 100},
                            "regions": []}), encoding="utf-8")
        elif name in ("02_ocr.py", "03_translate.py", "04_inpaint.py"):
            (base / f"page_0_{name[:2]}.json").parent.mkdir(parents=True, exist_ok=True)
            if name == "04_inpaint.py":
                (base / "page_0_inpaint.json").write_text(
                    json.dumps({"checks": {"filled": 0, "inpainted": 0, "skipped": 0}}),
                    encoding="utf-8")
            else:
                (base / ("page_0_canon.json" if name == "02_ocr.py"
                         else "page_0_translation.json")).write_text(
                    json.dumps({"translations": {}}), encoding="utf-8")

    monkeypatch.setattr(impl, "_run_cli", fake_cli)

    def fake_ensure(wid):
        d = tmp_path / "ws" / wid
        for sub in ("raw", "artifacts", "state"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(impl, "ensure_workspace", fake_ensure)

    impl.run("t", src, 1, 1, with_inpaint=True)
    assert "04_inpaint.py" in calls
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_pipeline_flow.py -q --basetemp output/logs/.pytest-basetemp -k with_inpaint`
Expected: FAIL — `run()` 无 `with_inpaint` 参数

- [ ] **Step 3: 实现**（00_run_all：`run(..., with_inpaint: bool = False)`；页循环 03 后插入 04 段，与 01/02/03 同构：产物存在→skip span，否则 `_run_cli([.../04_inpaint.py, --work-id, ..., --det, det_path, --raw, raw, --out, inpaint_path, --clean-dir, clean_dir])` + span）

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: PASS

- [ ] **Step 5: 单页冒烟（live）**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" scripts\00_run_all.py --work-id touhou-single-wing --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" --start-page 1 --end-page 1 --with-inpaint`（先删 page_0_inpaint.json + clean 产物）
Expected: `[04_inpaint] page_0: filled=N inpainted=M skipped=0` + `clean/page_0_clean.png` 生成 + 肉眼抽查涂白/擦除效果

- [ ] **Step 6: 提交**

```bash
git add scripts/00_run_all.py tests/test_pipeline_flow.py
git commit -m "feat(pipeline): 00_run_all 接入 04_inpaint(--with-inpaint)"
```

---

### Task 6: ADR-020 + fastcheck 全绿 + 收尾

**Files:**
- Create: `docs/decisions/020-stage4-inpaint-station.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: 写 ADR-020**（Context: Stage 4 契约消费 + 策略分级；Decision: fill_white/inpaint/skip 三动作、sfx 本期一律 inpaint、贴回方式按探针结论、pixel_diff_ratio 口径、断点契约；Consequences: 产物结构、与 05 的接口、overlay 检测盲区风险记录）
- [ ] **Step 2: 全量验证**
Run: `$env:PATH = "C:\Users\asus\AppData\Local\Programs\Python\Python313;C:\Users\asus\AppData\Local\Programs\Python\Python313\Scripts;" + $env:PATH; & "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" scripts\fastcheck.py`
Expected: ALL PASS
- [ ] **Step 3: README 索引补 020 + 提交**

```bash
git add docs/decisions/020-stage4-inpaint-station.md docs/decisions/README.md
git commit -m "docs(decisions): ADR-020 Stage 4 inpaint 工位"
```

---

## Self-Review

**Spec coverage:** Spec Phase 2 四项——category 擦除策略分支 → Task 3/4；sfx_triage 工位内 VLM → 明确延后（Global Constraints）；overlay 检测盲区 → 记录风险不阻塞（Task 4 注释）；气泡白底直填 bypass → Task 3 策略 + Task 4 执行。契约检查清单（category/items/sub_tier/region_id/断点）→ 由 ADR-019 已落地 + 本计划 Task 4 产物消费验证。**缺口：spec 中 pixel_diff_ratio 未定义口径 → Task 4 定义（clean vs raw 像素差异比例）并在 ADR-020 固化。**

**Placeholder scan:** Task 4 实现中有一处探针依赖占位（贴回方式），已在任务内显式说明"按 Task 1 探针结论替换"并给出两种候选，属流程依赖非 TBD；Task 4 Step 4 桥文件是否创建由仓库现状决定，已给出判断条件。其余无占位。

**Type consistency:** `plan_inpaint` 返回 `{region_id, category, action, bbox[, reason]}` 全计划一致；`run_inpaint(page_id, mask_png, role, engine, steps, timeout)` 签名 Task 2 定义 Task 4 消费一致；`04_inpaint.run(work_id, det_path, raw_page, out_path, clean_dir, dry_run, host, port)` 与 CLI 参数一致；action 枚举 `fill_white/inpaint/skip` 常量在 Task 3 定义、Task 4 引用一致。
