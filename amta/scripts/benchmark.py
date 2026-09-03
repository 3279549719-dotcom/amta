"""Benchmark A/B/C — 用数据钉死 koharu v0.59.1 的能力边界。

设计约束（关键）：
  - 判定 oracle（describe_image / VLM）是「会话内」工具，不是 Python 调用。
  - 因此本脚本是**两阶段**工具：
      [1] 驱动 koharu 跑流水线 → 产出 crops + 待标注清单 label_manifest.json
      [2] 我（Agent）对每张 crop 调 describe_image 标注 → 写回 labels JSON
      [3] 本脚本 ingest 标注 → 计算指标 → output/benchmark_{a,b,c}.json
  - 候选真值 = 4 detector 的并集（都漏的不计入分母，属工具能力边界）。

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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.evalkit import TEXT_CLASSES  # noqa: E402
from amta.geometry import union_boxes  # noqa: E402
from amta.images import crop_with_pad  # noqa: E402
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import CROPS, DATA, ensure_output, read_json, write_json  # noqa: E402
from amta.runner import run_all_pages  # noqa: E402

# Benchmark 钉的是 koharu v0.59.1 的 4 detector 能力边界（pp-doclayout/comic-text 等）。
# 旧 amta.pipeline.DETECTOR_STEPS 常量已随 koharu-检测时代删除（见
# test_final_integration::TestDeprecatedCodeRemoved）；每个引擎的 steps = [自身]（恒等），
# 故内联为引擎名列表即可，无需复活已删模块。
KOHARU_DETECTORS = (
    "pp-doclayout-v3",
    "comic-text-detector",
    "anime-text",
    "comic-text-bubble-detector",
)

MANIFEST = DATA / "label_manifest.json"
SOURCE_PAGE_NAMES = ("page.jpg", "page.jpeg", "page.png")


def _page_label(path: Path, idx: int) -> str:
    """给源图一个稳定的短标签，如 lm_11（灵梦第 11 页）。"""
    name = path.stem or "page"
    return f"{name}_{idx}"


def _is_source_page(p: Path) -> bool:
    """只接受「原文页」：命名 page.jpg/.jpeg/.png；排除已翻译/已擦除产物。"""
    base = p.name.lower()
    if "rendered" in base or "inpainted" in base or "final" in base:
        return False
    return base in SOURCE_PAGE_NAMES


# ---------------------------------------------------------------------------
# Phase 1a: 驱动 koharu 跑流水线，收集文本块
# ---------------------------------------------------------------------------

def gather_detections(pages: list[Path], engines: list[str] | None = None) -> dict[str, dict]:
    """对每页跑全部 engines，返回 {page_key: {path, engines: {engine: [blocks]}}}。"""
    steps = {eng: [eng] for eng in (engines or list(KOHARU_DETECTORS))}
    client = KoharuClient()
    client.wait_server()
    return run_all_pages(client, pages, steps, _page_label, prefix="amta-bench", timeout=1200, label="A")


# ---------------------------------------------------------------------------
# Phase 1b: 产出 crops + 待标注清单
# ---------------------------------------------------------------------------

def emit_manifest(pages: list[Path], detections: dict[str, dict]) -> None:
    """为每页每个候选 bbox 生成 crop + manifest 条目，等待 describe_image 标注。"""
    ensure_output()
    manifest: dict[str, Any] = {"version": 1, "bench": "a", "items": []}
    for idx, page in enumerate(pages):
        key = _page_label(page, idx)
        engines = detections.get(key, {}).get("engines", {})
        union = union_boxes(engines)
        for i, cand in enumerate(union):
            crop = CROPS / f"{key}_cand{i:02d}.png"
            crop_with_pad(page, cand["bbox"], crop)
            manifest["items"].append({
                "id": f"{key}_cand{i:02d}",
                "crop": str(crop),
                "page": key,
                "bbox": list(cand["bbox"]),
            })
    write_json(MANIFEST, manifest)
    print(f"[A] manifest: {len(manifest['items'])} crops -> {MANIFEST}")


# ---------------------------------------------------------------------------
# Phase 2: ingest 标注 → 计算指标
# ---------------------------------------------------------------------------

def compute_bench_a(labels: list[dict]) -> dict[str, Any]:
    """输入：describe_image 标注 [{id, is_text, cls}]。

    候选 = 4 detector 并集（N 个）。VLM 对每个候选判定：is_text? 若是则归 cls。
      - 判定为文字的候选 → 记该 cls 的 TP
      - 判定为非文字 → 全局 FP（并集检出的假阳）
    整体检测 Precision = (N - FP) / N；逐类分布 + 该类检出数。
    注：并集 recall≤1（候选即检出框），框外漏检属 detector 均未检出的区域，
    需独立统计（见 manifest 缺 id 之外人工抽检）。
    """
    by_cls: dict[str, dict[str, int]] = {c: {"tp": 0} for c in TEXT_CLASSES}
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
        "note": "precision 即核心；recall(框外漏检)需人工抽检 detector 均漏区域",
    }


def ingest_bench(manifest: dict, labels: list[dict], bench: str) -> dict[str, Any]:
    if bench == "a":
        result = compute_bench_a(labels)
    else:
        result = {"rows": {}, "note": f"bench {bench} ingest 待实现"}
    return result


# ---------------------------------------------------------------------------
# 初筛（prescreen）：4 类覆盖
# ---------------------------------------------------------------------------

def prescreen(pages: list[Path]) -> None:
    """初筛：跑 4 detector 取并集，产出全部 crop + manifest，供 describe_image 判 4 类。"""
    detections = gather_detections(pages)
    emit_manifest(pages, detections)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _parse_pages(raw: list[str]) -> list[Path]:
    """解析源图。只接受「原文页」（page.jpg/.jpeg/.png）：目录递归收集，文件直接收；
    排除已翻译/已擦除产物（rendered.png / inpainted.png / final 等）。"""
    pages = []
    for p in raw:
        path = Path(p)
        if path.is_dir():
            for suffix in ("*.jpg", "*.jpeg", "*.png"):
                pages.extend(sorted(f for f in path.rglob(suffix) if _is_source_page(f)))
        elif path.is_file():
            pages.append(path)
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
        manifest = read_json(MANIFEST)
        labels = read_json(args.ingest)
        result = ingest_bench(manifest, labels, args.bench)
        report = DATA / f"benchmark_{args.bench}.json"
        write_json(report, result)
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
        detections = gather_detections(pages)
        emit_manifest(pages, detections)
        print("[B] 先用 A 的并集 crops；对每 crop 跑三 OCR 引擎再标注。见 README/benchmark skill。")
    elif args.bench == "c":
        print("[C] 需 mask+inpaint（lama-manga）。当前脚本先跑 detector-seg+bubble 出 mask，")
        print("     inpaint 后对输出区域图供 describe_image 1-5 评分。实现见后续迭代。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
