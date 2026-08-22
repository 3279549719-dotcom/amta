"""Benchmark A/B/C — 用数据钉死 koharu v0.59.1 的能力边界。

设计约束（关键）：
  - 判定 oracle（describe_image / VLM）是「会话内」工具，不是 Python 调用。
  - 因此本脚本是**两阶段**工具：
      [1] 驱动 koharu 跑流水线 → 产出 crops + 待标注清单 label_manifest.json
      [2] 我（Agent）对每张 crop 调 describe_image 标注 → 写回 labels JSON
      [3] 本脚本 ingest 标注 → 计算指标 → output/benchmark_{a,b,c}.json
  - 候选真值 = 4 detector 的并集（都漏的不计入分母，属工具能力边界）。
  - 零人工全量标注：人工仅抽查 detector 分歧 / VLM 低置信子集。

用法：
  python scripts/benchmark.py --prescreen <pages...>               # 初筛：产出 4 类覆盖待标注 crop
  python scripts/benchmark.py --bench a --pages <img...>           # 跑四 detector → emit crops+manifest
  python scripts/benchmark.py --ingest --bench a --labels <json>   # 计算指标 → output/data/benchmark_a.json
  python scripts/benchmark.py --all                                # 链式占位
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.koharu_client import KoharuClient, KoharuError  # noqa: E402
from amta.pipeline import DETECTOR_STEPS  # noqa: E402
from amta.geometry import union_boxes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
DATA = OUTPUT / "data"
CROP_DIR = OUTPUT / "crops"
MANIFEST = DATA / "label_manifest.json"

# 四类文本：框内对白 / 框外对白 / SFX / 背景文字（Benchmark A 分类维度）
CLASSES = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]
# Benchmark B 分类维度
OCR_CLASSES = ["人名", "专名", "拟声词", "竖排", "艺术字"]


def ensure_output() -> None:
    for d in (OUTPUT, DATA, CROP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _page_label(path: Path, idx: int) -> str:
    """给源图一个稳定的短标签，如 lm_11（灵梦第 11 页）。"""
    name = path.stem or "page"
    return f"{name}_{idx}"


# ---------------------------------------------------------------------------
# Phase 1a: 驱动 koharu 跑流水线，收集文本块
# ---------------------------------------------------------------------------

def run_detector(client: KoharuClient, page: Path, engine: str) -> list[dict]:
    """跑单个 detector，返回该 engine 检出的文本块（collect_blocks）。"""
    proj = f"amta-bench-{uuid.uuid4().hex[:8]}"
    client.close_current_project()
    _pid = client.create_project(proj)
    try:
        page_id = client.import_page(page)
        op = client.run_pipeline(page_ids=[page_id], steps=DETECTOR_STEPS[engine])
        result = client.wait_operation(op, timeout=1200)
        if result.get("status") != "completed":
            raise KoharuError(f"{engine} pipeline failed: {result}")
        nodes = client.get_page_nodes(page_id)
        blocks = KoharuClient.collect_blocks(nodes)
        return blocks
    finally:
        client.close_current_project()


def gather_detections(pages: list[Path], engines: list[str]) -> dict[str, dict[str, list[dict]]]:
    """对每页跑全部 engines，返回 {page_key: {engine: [blocks]}}。"""
    client = KoharuClient()
    client.wait_server()
    out: dict[str, dict[str, list[dict]]] = {}
    for idx, page in enumerate(pages):
        key = _page_label(page, idx)
        out[key] = {}
        for eng in engines:
            print(f"[A] {key} / {eng} ...", flush=True)
            try:
                out[key][eng] = run_detector(client, page, eng)
            except Exception as e:  # noqa: BLE001 — 单引擎失败不拖垮整页
                print(f"[A] WARN {key} {eng} failed: {e}", flush=True)
                out[key][eng] = []
    return out


# ---------------------------------------------------------------------------
# Phase 1b: 产出 crops + 待标注清单
# ---------------------------------------------------------------------------

def crop_page(page: Path, bbox: tuple, dest: Path, pad: int = 8) -> None:
    """按 bbox 裁出 crop（pad 像素），供 describe_image 标注。"""
    from PIL import Image
    img = Image.open(page).convert("RGB")
    x0, y0, x1, y1 = (max(0, int(v)) for v in bbox)
    x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
    x1 = min(img.width, x1 + pad); y1 = min(img.height, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return
    img.crop((x0, y0, x1, y1)).save(dest)


def emit_manifest(pages: list[Path], detections: dict[str, dict[str, list[dict]]]) -> None:
    """为每页每个候选 bbox 生成 crop + manifest 条目，等待 describe_image 标注。"""
    ensure_output()
    manifest: dict[str, Any] = {"version": 1, "bench": "a", "items": []}
    for idx, page in enumerate(pages):
        key = _page_label(page, idx)
        union = union_boxes(detections.get(key, {}))
        for i, cand in enumerate(union):
            crop = CROP_DIR / f"{key}_cand{i:02d}.png"
            crop_page(page, cand["bbox"], crop)
            manifest["items"].append({
                "id": f"{key}_cand{i:02d}",
                "crop": str(crop),
                "page": key,
                "bbox": list(cand["bbox"]),
            })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[A] manifest: {len(manifest['items'])} crops -> {MANIFEST}")


# ---------------------------------------------------------------------------
# Phase 2: ingest 标注 → 计算指标
# ---------------------------------------------------------------------------

def compute_bench_a(labels: list[dict]) -> dict[str, Any]:
    """输入：describe_image 标注 [{id, is_text, cls}]。

    候选 = 4 detector 并集（N 个）。VLM 对每候选判定：is_text? 若是则归 cls。
      - 判定为文字的候选 → 该 cls 的 TP
      - 判定为非文字 → 全局 FP（并集检出的假框）
    整体检测 Precision = (N - FP) / N；逐类分布 + 该类检出数。
    注：并集 recall≈1（候选即检出框），框外漏检属 detector 均未检出的区域，
    需独立统计（见 manifest 缺 id 之外人工抽查）。precision 是核心数据。
    """
    by_cls: dict[str, dict[str, int]] = {c: {"tp": 0} for c in CLASSES}
    fp = 0
    for lab in labels:
        if not lab.get("is_text"):
            fp += 1
            continue
        cls = lab.get("cls", "dialogue_in")
        if cls not in by_cls:
            cls = "dialogue_in"
        by_cls[cls]["tp"] += 1
    n = len(labels)
    tp = n - fp
    rows = {}
    for cls, v in by_cls.items():
        rows[cls] = {"detected": v["tp"], "share": round(v["tp"] / tp, 3) if tp else 0.0}
    return {
        "n_candidates": n,
        "fp_non_text": fp,
        "detection_precision": round(tp / n, 3) if n else 0.0,
        "rows": rows,
        "note": "precision 即核心；recall(框外漏检)需人工抽查 detector 均漏区域",
    }


def ingest_bench(manifest: dict, labels: list[dict], bench: str) -> dict[str, Any]:
    if bench == "a":
        result = compute_bench_a(labels)
    else:
        result = {"rows": {}, "note": f"bench {bench} ingest 待实现"}
    return result


# ---------------------------------------------------------------------------
# 预筛（prescreen）：4 类覆盖
# ---------------------------------------------------------------------------

def prescreen(pages: list[Path]) -> None:
    """初筛：跑四 detector 取并集，产出全部 crop + manifest，供 describe_image 归 4 类。"""
    detections = gather_detections(pages, list(DETECTOR_STEPS.keys()))
    emit_manifest(pages, detections)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _parse_pages(raw: list[str]) -> list[Path]:
    """解析源图。只接受「原文页」：优先 page.jpg；目录下排除已翻译/已擦除产物
    (rendered.png / inpainted.png / final 等)，避免用中文译文当 benchmark 源图。"""
    def is_source(p: Path) -> bool:
        base = p.name.lower()
        if "rendered" in base or "inpainted" in base or "final" in base:
            return False
        return base in ("page.jpg", "page.jpeg")
    pages = []
    for p in raw:
        if Path(p).is_dir():
            pages.extend(sorted(f for f in Path(p).rglob("*.jpg") if is_source(f)))
            pages.extend(sorted(f for f in Path(p).rglob("*.jpeg") if is_source(f)))
            pages.extend(sorted(f for f in Path(p).rglob("*.png") if is_source(f)))
        elif Path(p).is_file():
            pages.append(Path(p))
    if not pages:
        raise SystemExit("no pages given; pass image paths or a dir of images")
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AMTA Benchmark A/B/C")
    ap.add_argument("--bench", choices=["a", "b", "c", "all"], default="a")
    ap.add_argument("--pages", nargs="+", help="源图路径或含源图的目录")
    ap.add_argument("--ingest", metavar="LABELS.json", help="ingest describe_image 标注并算指标")
    ap.add_argument("--prescreen", action="store_true", help="初筛：四 detector 并集出 crop")
    ap.add_argument("--all", action="store_true", help="链式占位")
    args = ap.parse_args(argv)

    if args.ingest:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        labels = json.loads(Path(args.ingest).read_text(encoding="utf-8"))
        result = ingest_bench(manifest, labels, args.bench)
        report = DATA / f"benchmark_{args.bench}.json"
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ingest] -> {report}")
        print(json.dumps(result["rows"], ensure_ascii=False, indent=2))
        return 0

    if not args.pages:
        ap.error("--pages required unless --ingest")

    pages = _parse_pages(args.pages)
    print(f"[bench] {len(pages)} pages, bench={args.bench}")

    if args.prescreen or args.bench == "a":
        prescreen(pages)
    elif args.bench == "b":
        # OCR 需要先有 TextBoxes：跑 detector 取并集，再对并集 crop 供 OCR 引擎（脚本外）
        detections = gather_detections(pages, list(DETECTOR_STEPS.keys()))
        emit_manifest(pages, detections)
        print("[B] 先用 A 的并集 crops；对每 crop 跑三 OCR 引擎再标注。见 README/benchmark skill。")
    elif args.bench == "c":
        print("[C] 需 mask+inpaint（lama-manga）。当前脚本先跑 detector-seg+bubble 出 mask，")
        print("     inpaint 后导出区域图供 describe_image 1-5 评分。实现见后续迭代。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
