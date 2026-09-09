"""Q3 全量回归测试：用修改后的 OCR confidence 过滤跑全40页。

复用已有 detection 数据（workspace/touhou-tiling-e2e/artifacts/detection/），
只跑 OCR 部分，验证 first_token_conf < 0.4 过滤效果。

输出:
  - workspace/exp-q3-full-ocr-test/canon/page_*.json (OCR canon 结果)
  - workspace/exp-q3-full-ocr-test/summary.json (汇总统计)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 清除代理
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE","1")
os.environ.setdefault("TRANSFORMERS_OFFLINE","1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from amta.stations.ocr_station import ocr_page

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = ROOT / "workspace/touhou-tiling-e2e/artifacts/detection"
OUT_DIR = ROOT / "workspace/exp-q3-full-ocr-test"
CANON_DIR = OUT_DIR / "canon"
TRACE_DIR = OUT_DIR / "trace"
CANON_DIR.mkdir(parents=True, exist_ok=True)
TRACE_DIR.mkdir(parents=True, exist_ok=True)

WORK_ID = "exp-q3-full-ocr-test"


def main():
    det_files = sorted(DET_DIR.glob("page_*.json"))
    print(f"共 {len(det_files)} 页检测数据")

    all_conf_removed = []
    total_raw = 0
    total_kept = 0
    page_results = []

    t_start = time.time()

    for det_file in det_files:
        det = json.loads(det_file.read_text(encoding="utf-8"))
        page = det["page"]
        page_num = int(page.replace("page_", ""))
        raw_path = RAW_DIR / f"{page_num}.jpg"

        if not raw_path.exists():
            print(f"  {page}: 原图不存在，跳过")
            continue

        n_raw = len(det.get("blocks", []))
        print(f"  {page}: {n_raw} 框, 跑 OCR...", end=" ", flush=True)

        try:
            canon = ocr_page(
                WORK_ID, det, raw_path, OUT_DIR,
                page_idx=page_num, engine="hayai",
                vlm_enabled=False, rule_filter_enabled=False,
                crop_dir=OUT_DIR / "crops" / page,
            )
            n_kept = canon["n_regions"]
            n_conf_removed = canon.get("n_conf_removed", 0)

            # 从 trace 读取 conf_removed 详情
            trace_path = OUT_DIR / f"{page}_02_ocr_trace.json"
            conf_removed = []
            if trace_path.exists():
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                conf_removed = trace.get("conf_removed_details", [])

            total_raw += n_raw
            total_kept += n_kept
            for cr in conf_removed:
                cr["page"] = page
                cr["page_num"] = page_num
                all_conf_removed.append(cr)

            page_results.append({
                "page": page, "page_num": page_num,
                "n_raw": n_raw, "n_kept": n_kept,
                "n_conf_removed": n_conf_removed,
            })

            status = f"保留 {n_kept}, 过滤 {n_conf_removed}"
            if conf_removed:
                status += f" ({', '.join(cr['region_id'] for cr in conf_removed)})"
            print(status)

        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - t_start

    # 汇总
    print(f"\n{'='*70}")
    print(f"全量回归测试汇总")
    print(f"{'='*70}")
    print(f"总页数: {len(page_results)}")
    print(f"总原始框数: {total_raw}")
    print(f"总保留框数: {total_kept}")
    print(f"总过滤框数: {len(all_conf_removed)}")
    print(f"过滤率: {len(all_conf_removed)/total_raw*100:.1f}%" if total_raw else "N/A")
    print(f"总耗时: {elapsed/60:.1f} 分钟")

    print(f"\n被 confidence 过滤的框 ({len(all_conf_removed)} 个):")
    print(f"{'页面':<8} {'ID':<6} {'first_conf':<12} {'OCR文本':<30} {'source_engines'}")
    print("-" * 80)
    for cr in sorted(all_conf_removed, key=lambda x: x["first_token_conf"]):
        print(f"p{cr['page_num']:<6} {cr['region_id']:<6} "
              f"{cr['first_token_conf']:<12.4f} {cr['text'][:28]:<30} "
              f"{cr.get('source_engines', [])}")

    # 验证已知杂质框是否被过滤
    print(f"\n已知杂质框验证:")
    known_garbled = [
        (2, "t04", "刻度线", "..."),
        (6, "t08", "黑竖条", "乱码"),
        (31, "t08", "装饰线", "美術館は、"),
    ]
    for page_num, rid, desc, expected in known_garbled:
        found = [cr for cr in all_conf_removed if cr["page_num"] == page_num and cr["region_id"] == rid]
        if found:
            print(f"  ✅ p{page_num} {rid} ({desc}): 已过滤, first_conf={found[0]['first_token_conf']:.4f}, OCR='{found[0]['text'][:20]}'")
        else:
            print(f"  ❌ p{page_num} {rid} ({desc}): 未被过滤!")

    # 保存汇总
    summary = {
        "total_pages": len(page_results),
        "total_raw_boxes": total_raw,
        "total_kept_boxes": total_kept,
        "total_conf_removed": len(all_conf_removed),
        "filter_rate": round(len(all_conf_removed)/total_raw*100, 1) if total_raw else 0,
        "elapsed_minutes": round(elapsed/60, 1),
        "threshold": 0.4,
        "conf_removed_details": all_conf_removed,
        "page_results": page_results,
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n汇总已保存: {summary_path}")


if __name__ == "__main__":
    main()
