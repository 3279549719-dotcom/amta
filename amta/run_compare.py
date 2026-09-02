"""deepseek 视觉模型 VLM 裁决对比实验：rule-only vs vlm-filter(deepseek-v4-flash-vision-exp)。

对选定页面跑完整流程：检测 → OCR+规则过滤 → [deepseek VLM 三态过滤] → 翻译。
其他条件完全不变（检测模型、baberu、规则过滤、翻译模型均与原管线一致）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# === 路径配置 ===
ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
SCRIPTS = ROOT / "scripts"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "output" / "compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)
WORK_ID = "touhou-single-wing"

# === 选定页面（文件名, page_idx）===
PAGES = [
    ("1.jpg", 0),
    ("2.jpg", 1),
    ("3.jpg", 2),   # 难页
    ("6.jpg", 5),
    ("15.jpg", 14),
    ("33.jpg", 32),
]

# === 从 .env 读取配置 ===
def load_env() -> dict[str, str]:
    env = os.environ.copy()
    # 搜索多个可能的 .env 位置（worktree 嵌套较深）
    candidates = [
        ROOT / ".env",
        ROOT.parent / ".env",
        ROOT.parent.parent / ".env",
        ROOT.parent.parent.parent / ".env",
    ]
    env_path = next((p for p in candidates if p.exists()), None)
    if env_path is None:
        print(f"WARNING: .env not found in {[str(p) for p in candidates]}")
        return env
    print(f"  loading .env from {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def run(cmd: list[str], env: dict, timeout: int = 300) -> tuple[int, str]:
    """运行命令，返回 (returncode, stdout+stderr)。"""
    print(f"  $ {' '.join(str(c) for c in cmd[:3])}...")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout,
                       encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")
    print(f"    [{elapsed:.1f}s] rc={r.returncode}")
    if r.returncode != 0:
        print(f"    ERROR: {out[-500:]}")
    return r.returncode, out


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    base_env = load_env()

    # === deepseek VLM 环境变量（覆盖默认 dashscope）===
    vlm_env = base_env.copy()
    vlm_env["VLM_BASE_URL"] = "https://api.deepseek.com"
    vlm_env["VISION_MODEL"] = "deepseek-v4-flash-vision-exp"
    vlm_env["VLM_API_KEY"] = base_env.get("CHAT_API_KEY", "")

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

        det_file = OUT_DIR / f"{page}_detection.json"
        canon_rule = OUT_DIR / f"{page}_canon_rule.json"
        canon_vlm = OUT_DIR / f"{page}_canon_vlm.json"
        trans_rule = OUT_DIR / f"{page}_trans_rule.json"
        trans_vlm = OUT_DIR / f"{page}_trans_vlm.json"

        # --- 1. 检测 ---
        if not det_file.exists():
            run([str(PYTHON), str(SCRIPTS / "01_detect.py"),
                 "--work-id", WORK_ID, "--raw", str(raw),
                 "--out", str(det_file), "--page-idx", str(page_idx),
                 "--conf", "0.3"], base_env)
        det = load_json(det_file)
        n_detected = det.get("n_boxes", 0)
        print(f"  检测: {n_detected} boxes")

        # --- 2. OCR + 规则过滤（rule-only，禁用 OCR 阶段 VLM 校验）---
        if not canon_rule.exists():
            run([str(PYTHON), str(SCRIPTS / "02_ocr.py"),
                 "--work-id", WORK_ID, "--det", str(det_file),
                 "--raw", str(raw), "--out", str(canon_rule),
                 "--page-idx", str(page_idx), "--no-vlm"], base_env)
        cr = load_json(canon_rule)
        rule_items = cr.get("items", cr.get("blocks", []))
        n_rule = len(rule_items)
        rf = cr.get("rule_filter", {})
        n_rule_removed = rf.get("removed", 0)
        rule_removed_by_reason = rf.get("removed_by_reason", {})
        print(f"  规则过滤后: {n_rule} boxes (移除 {n_rule_removed}: {rule_removed_by_reason})")

        # --- 3. deepseek VLM 三态过滤 ---
        if not canon_vlm.exists():
            run([str(PYTHON), str(SCRIPTS / "02b_vlm_filter.py"),
                 "--canon", str(canon_rule), "--raw", str(raw),
                 "--out", str(canon_vlm), "--work-id", WORK_ID], vlm_env)
        cv = load_json(canon_vlm)
        vlm_items = cv.get("items", [])
        n_vlm = len(vlm_items)
        vlm_filter_info = cv.get("vlm_filter", {})
        n_vlm_keep = vlm_filter_info.get("keep", 0)
        n_vlm_fix = vlm_filter_info.get("fix", 0)
        n_vlm_drop = len(vlm_filter_info.get("dropped_regions", []))
        print(f"  VLM过滤后: {n_vlm} boxes (keep={n_vlm_keep}, fix={n_vlm_fix}, drop={n_vlm_drop})")

        # --- 4a. rule-only 翻译 ---
        if not trans_rule.exists():
            run([str(PYTHON), str(SCRIPTS / "03_translate.py"),
                 "--canon", str(canon_rule), "--out", str(trans_rule),
                 "--work-id", WORK_ID, "--no-vlm"], base_env)
        tr = load_json(trans_rule)
        trans_rule_map = tr.get("translations", {})

        # --- 4b. vlm-filter 翻译 ---
        if not trans_vlm.exists():
            run([str(PYTHON), str(SCRIPTS / "03_translate.py"),
                 "--canon", str(canon_vlm), "--out", str(trans_vlm),
                 "--work-id", WORK_ID, "--no-vlm"], base_env)
        tv = load_json(trans_vlm)
        trans_vlm_map = tv.get("translations", {})

        print(f"  翻译: rule-only={len(trans_rule_map)} 条, vlm-filter={len(trans_vlm_map)} 条")

        # --- 收集本页数据 ---
        page_result = {
            "page": page,
            "file": fname,
            "raw_path": str(raw),
            "n_detected": n_detected,
            "n_rule": n_rule,
            "n_rule_removed": n_rule_removed,
            "rule_removed_by_reason": rule_removed_by_reason,
            "n_vlm": n_vlm,
            "vlm_keep": n_vlm_keep,
            "vlm_fix": n_vlm_fix,
            "vlm_drop": n_vlm_drop,
            "vlm_dropped": vlm_filter_info.get("dropped_regions", []),
            "vlm_fixed": vlm_filter_info.get("fixed_regions", []),
            "rule_items": [{"region_id": it.get("region_id"), "bbox": it.get("bbox"),
                            "text": it.get("text"), "bubble_type": it.get("bubble_type"),
                            "confidence": it.get("confidence", it.get("score"))}
                           for it in rule_items],
            "vlm_items": [{"region_id": it.get("region_id"), "bbox": it.get("bbox"),
                           "text": it.get("text"), "original_text": it.get("original_text"),
                           "vlm_state": it.get("vlm_state")}
                          for it in vlm_items],
            "trans_rule": trans_rule_map,
            "trans_vlm": trans_vlm_map,
        }
        results.append(page_result)

    # === 汇总 ===
    summary = {
        "total_detected": sum(r["n_detected"] for r in results),
        "total_rule": sum(r["n_rule"] for r in results),
        "total_rule_removed": sum(r["n_rule_removed"] for r in results),
        "total_vlm": sum(r["n_vlm"] for r in results),
        "total_vlm_drop": sum(r["vlm_drop"] for r in results),
        "total_vlm_fix": sum(r["vlm_fix"] for r in results),
        "total_trans_rule": sum(len(r["trans_rule"]) for r in results),
        "total_trans_vlm": sum(len(r["trans_vlm"]) for r in results),
    }

    out = {"summary": summary, "pages": results,
           "vlm_model": "deepseek-v4-flash-vision-exp",
           "vlm_base": "https://api.deepseek.com",
           "conf_threshold": 0.3,
           "work_id": WORK_ID}
    result_file = OUT_DIR / "compare_results.json"
    result_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"汇总: {json.dumps(summary, ensure_ascii=False)}")
    print(f"结果 -> {result_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
