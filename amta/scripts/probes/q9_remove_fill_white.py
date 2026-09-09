"""Q9 实验：移除 fill_white，所有框全走 lama inpaint。

对第 6-10 页跑完整流程：
- detect（RT-DETR-v2，CPU，有缓存很快）
- OCR（hayai，有指纹缓存）
- translate（复用旧翻译文本，不重新调用 LLM）
- inpaint（全走 lama，ADR-030 移除 fill_white）
- typeset（出 final.png 成品图）

最终输出 5 页成品图，对比 fill_white vs 全 lama 的效果。
"""
from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

# 清除代理（本地模型不需要代理）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

# hayai OCR 离线模式
os.environ["HF_HUB_OFFLINE"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from amta.detect_station import detect_page
from amta.ocr_station import ocr_page
from amta.inpaint_station import run as inpaint_run
from amta.typeset_station import run as typeset_run
from amta.translate import translate_plain
from amta.chat_client import chat_text
from amta.config import get_chat_config
from amta.paths import read_json, write_json

# ---- 配置 ----
WORK_ID = "exp-q9-remove-fill-white"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OLD_TRANS_DIR = Path(r"E:\manga translator agent\amta\workspace\touhou-single-wing\artifacts")
OUT_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q9-remove-fill-white")
ARTIFACTS_DIR = OUT_DIR / "artifacts"
CLEAN_DIR = ARTIFACTS_DIR / "clean"
FINAL_DIR = OUT_DIR / "final"

PAGES = [6, 7, 8, 9, 10]
CONF_THRESHOLD = 0.7
TILING_ENABLED = False  # 主链模式，和正式管线一致


def main():
    print("=" * 60)
    print(f"Q9 实验：移除 fill_white，全走 lama inpaint")
    print(f"页面: {PAGES}")
    print(f"输出: {OUT_DIR}")
    print("=" * 60)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for page_idx in PAGES:
        page = f"page_{page_idx}"
        raw_page = SRC_DIR / f"{page_idx}.jpg"
        if not raw_page.exists():
            print(f"\n[{page}] 原图不存在，跳过")
            continue

        print(f"\n{'='*60}")
        print(f"[{page}] 开始处理")
        print(f"{'='*60}")

        # ---- Step 1: detect ----
        det_path = ARTIFACTS_DIR / f"{page}_detection.json"
        t0 = time.time()
        if det_path.exists():
            print(f"  [detect] 缓存命中，跳过")
            det = read_json(det_path)
        else:
            print(f"  [detect] 运行中...")
            det = detect_page(WORK_ID, raw_page, ARTIFACTS_DIR,
                               page_idx=page_idx, conf_threshold=CONF_THRESHOLD,
                               tiling_enabled=TILING_ENABLED)
        print(f"  [detect] {det.get('n_boxes', 0)} 框, {time.time()-t0:.1f}s")

        # ---- Step 2: OCR ----
        canon_path = ARTIFACTS_DIR / "canon" / f"{page}.json"
        t0 = time.time()
        if canon_path.exists():
            print(f"  [ocr] 缓存命中，跳过")
            canon = read_json(canon_path)
        else:
            print(f"  [ocr] 运行中（hayai）...")
            canon = ocr_page(WORK_ID, det, raw_page, ARTIFACTS_DIR,
                             page_idx=page_idx, engine="hayai",
                             rule_filter_enabled=False)
        print(f"  [ocr] {canon.get('n_regions', 0)} 框, {time.time()-t0:.1f}s")

        # ---- Step 3: 翻译（重新跑，新旧 detection 框不匹配）----
        trans_path = ARTIFACTS_DIR / f"{page}_translation.json"
        t0 = time.time()
        if trans_path.exists() and trans_path.stat().st_size > 100:
            print(f"  [translate] 缓存命中，跳过")
            trans_doc = read_json(trans_path)
        else:
            print(f"  [translate] 运行中（deepseek）...")
            cfg = get_chat_config()
            def llm(messages):
                return chat_text(cfg["base_url"], cfg["model"], messages,
                                 api_key=cfg.get("api_key"), timeout=180, temperature=0.3)
            canon_items = canon.get("items", [])
            translate_input = [{"region_id": item["region_id"],
                                 "text": item.get("text") or item.get("baberu_text") or ""}
                                for item in canon_items]
            system_extra = "如果输入内容是乱码、无法识别的字符或非日文常用文字，输出空字符串。"
            result = translate_plain(translate_input, llm, system_extra=system_extra,
                                      context_enabled=False, max_retries=0)
            translations = dict(result)  # key 是 r00/r01 格式，和 canon region_id 一致
            trans_doc = {
                "work_id": WORK_ID,
                "page": page,
                "translations": translations,
                "source": "rerun with deepseek-v4-flash",
            }
            write_json(trans_path, trans_doc)
            print(f"  [translate] {len(translations)} 条")
        print(f"  [translate] {time.time()-t0:.1f}s")

        # ---- Step 4: inpaint（全走 lama）----
        inpaint_path = ARTIFACTS_DIR / f"{page}_inpaint.json"
        clean_path = CLEAN_DIR / f"{page}_clean.png"
        t0 = time.time()
        if clean_path.exists() and inpaint_path.exists():
            print(f"  [inpaint] 缓存命中，跳过")
        else:
            print(f"  [inpaint] 运行中（全走 lama）...")
            inpaint_doc = inpaint_run(WORK_ID, det_path, raw_page, inpaint_path,
                                       clean_dir=CLEAN_DIR, refine_mask=False)
            print(f"  [inpaint] filled={inpaint_doc['checks']['filled']} "
                  f"inpainted={inpaint_doc['checks']['inpainted']} "
                  f"skipped={inpaint_doc['checks']['skipped']} "
                  f"diff={inpaint_doc['checks']['pixel_diff_ratio']}")
        print(f"  [inpaint] {time.time()-t0:.1f}s")

        # ---- Step 5: typeset ----
        typeset_path = ARTIFACTS_DIR / f"{page}_typeset.json"
        final_path = FINAL_DIR / f"{page}_final.png"
        t0 = time.time()
        if final_path.exists() and typeset_path.exists():
            print(f"  [typeset] 缓存命中，跳过")
        else:
            print(f"  [typeset] 运行中...")
            typeset_doc = typeset_run(WORK_ID, canon_path, trans_path, det_path,
                                       clean_path, typeset_path, final_path)
            print(f"  [typeset] rendered={typeset_doc['checks']['rendered']} "
                  f"coverage={typeset_doc['checks']['coverage_complete']} "
                  f"overflow={len(typeset_doc['checks']['overflow'])}")
        print(f"  [typeset] {time.time()-t0:.1f}s")

        results.append({
            "page": page_idx,
            "n_boxes": det.get("n_boxes", 0),
            "n_regions": canon.get("n_regions", 0),
            "n_translations": len(translations),
            "final_path": str(final_path),
        })
        print(f"  [done] {final_path}")

    # ---- 汇总 ----
    print(f"\n{'='*60}")
    print("汇总")
    print(f"{'='*60}")
    for r in results:
        print(f"  page {r['page']}: {r['n_boxes']} 框 / {r['n_regions']} OCR / {r['n_translations']} 翻译 -> {r['final_path']}")
    print(f"\n成品图目录: {FINAL_DIR}")
    print("完成！")


if __name__ == "__main__":
    main()
