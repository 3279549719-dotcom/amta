"""conf=0.3 vs conf=0.5 对比实验：纯机械规则（4条规则），完全不用 VLM。

对连续 1-10.jpg 各跑两个版本，统计假框过滤率和真字保留率。
其他条件完全不变：RT-DETR-v2 检测 + baberu OCR + 4条规则 + deepseek-v4-flash 翻译。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(r"E:\manga translator agent\amta\.venv\Scripts\python.exe")
SCRIPTS = ROOT / "scripts"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "output" / "compare_conf"
OUT_DIR.mkdir(parents=True, exist_ok=True)
WORK_ID = "touhou-single-wing"

PAGES = [(f"{i}.jpg", i - 1) for i in range(1, 11)]  # 1-10.jpg, page_idx 0-9
CONFS = [0.3, 0.5]


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    candidates = [ROOT / ".env", ROOT.parent / ".env",
                  ROOT.parent.parent / ".env", ROOT.parent.parent.parent / ".env"]
    env_path = next((p for p in candidates if p.exists()), None)
    if env_path:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def run(cmd: list[str], env: dict, timeout: int = 300) -> tuple[int, str]:
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout,
                       encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        print(f"    ERROR [{elapsed:.1f}s]: {out[-300:]}")
    else:
        print(f"    [{elapsed:.1f}s] OK")
    return r.returncode, out


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    env = load_env()
    results = []

    for fname, page_idx in PAGES:
        page = f"page_{page_idx}"
        raw = RAW_DIR / fname
        if not raw.exists():
            print(f"[SKIP] {raw} not found")
            continue

        print(f"\n{'='*60}")
        print(f"[{page}] {fname}")
        print(f"{'='*60}")

        page_result = {"page": page, "file": fname, "conf_results": {}}

        for conf in CONFS:
            tag = f"conf{conf}"
            print(f"\n  --- conf={conf} ---")
            det_file = OUT_DIR / f"{page}_{tag}_det.json"
            canon_file = OUT_DIR / f"{page}_{tag}_canon.json"
            trans_file = OUT_DIR / f"{page}_{tag}_trans.json"

            # 1. 检测
            if not det_file.exists():
                print(f"  检测 conf={conf}...")
                run([str(PYTHON), str(SCRIPTS / "01_detect.py"),
                     "--work-id", WORK_ID, "--raw", str(raw),
                     "--out", str(det_file), "--page-idx", str(page_idx),
                     "--conf", str(conf)], env)
            det = load_json(det_file)
            n_detected = det.get("n_boxes", 0)
            det_blocks = det.get("blocks", [])
            # 统计置信度分布
            confs = [b.get("score", b.get("confidence", 0)) for b in det_blocks]
            print(f"    检测: {n_detected} boxes, conf range: [{min(confs):.3f}, {max(confs):.3f}]" if confs else f"    检测: {n_detected} boxes")

            # 2. OCR + 规则过滤（--no-vlm）
            if not canon_file.exists():
                print(f"  OCR+规则过滤...")
                run([str(PYTHON), str(SCRIPTS / "02_ocr.py"),
                     "--work-id", WORK_ID, "--det", str(det_file),
                     "--raw", str(raw), "--out", str(canon_file),
                     "--page-idx", str(page_idx), "--no-vlm"], env)
            canon = load_json(canon_file)
            canon_items = canon.get("items", [])
            n_canon = len(canon_items)
            rf = canon.get("rule_filter", {})
            n_rule_removed = rf.get("removed", 0)
            rule_removed_by_reason = rf.get("removed_by_reason", {})
            print(f"    规则过滤后: {n_canon} boxes (移除 {n_rule_removed}: {rule_removed_by_reason})")

            # 3. 翻译（--no-vlm）
            if not trans_file.exists():
                print(f"  翻译...")
                run([str(PYTHON), str(SCRIPTS / "03_translate.py"),
                     "--canon", str(canon_file), "--out", str(trans_file),
                     "--work-id", WORK_ID, "--no-vlm"], env)
            trans = load_json(trans_file)
            trans_map = trans.get("translations", {})
            print(f"    翻译: {len(trans_map)} 条")

            page_result["conf_results"][tag] = {
                "conf": conf,
                "n_detected": n_detected,
                "det_confs": [round(c, 4) for c in confs],
                "n_canon": n_canon,
                "n_rule_removed": n_rule_removed,
                "rule_removed_by_reason": rule_removed_by_reason,
                "n_translations": len(trans_map),
                "canon_items": [{"region_id": it.get("region_id"), "bbox": it.get("bbox"),
                                 "text": it.get("text"), "bubble_type": it.get("bubble_type"),
                                 "confidence": it.get("confidence", it.get("score"))}
                                for it in canon_items],
                "translations": trans_map,
            }

        results.append(page_result)

    # === 汇总对比 ===
    print(f"\n{'='*60}")
    print("汇总对比")
    print(f"{'='*60}")
    summary = {}
    for conf in CONFS:
        tag = f"conf{conf}"
        total_det = sum(r["conf_results"][tag]["n_detected"] for r in results)
        total_canon = sum(r["conf_results"][tag]["n_canon"] for r in results)
        total_rule_removed = sum(r["conf_results"][tag]["n_rule_removed"] for r in results)
        total_trans = sum(r["conf_results"][tag]["n_translations"] for r in results)
        summary[tag] = {"total_detected": total_det, "total_canon": total_canon,
                         "total_rule_removed": total_rule_removed, "total_translations": total_trans}
        print(f"  conf={conf}: 检测={total_det}, 规则过滤后={total_canon}(移除{total_rule_removed}), 翻译={total_trans}")

    # conf=0.5 比 conf=0.3 多砍掉的框
    extra_removed = summary["conf0.3"]["total_canon"] - summary["conf0.5"]["total_canon"]
    print(f"\n  conf=0.5 比 conf=0.3 多砍掉 {extra_removed} 个框（检测阶段）")

    out = {"summary": summary, "pages": results, "extra_removed_by_conf05": extra_removed}
    result_file = OUT_DIR / "compare_conf_results.json"
    result_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果 -> {result_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
