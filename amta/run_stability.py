"""3.jpg 多次重复 VLM 裁决实验：验证 deepseek 视觉模型的稳定性。

对同一个 canon（规则过滤后的 9 框）连续跑 N 次 VLM 三态裁决，
记录每次的 keep/fix/drop 结果，对比差异。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from amta.vlm_filter import vlm_filter_v2  # noqa: E402

# === 配置 ===
CANON = ROOT / "output" / "compare" / "page_2_canon_rule.json"
RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地\3.jpg")
N_RUNS = 5
OUT = ROOT / "output" / "compare" / "page_2_vlm_stability.json"


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
    # deepseek VLM
    env["VLM_BASE_URL"] = "https://api.deepseek.com"
    env["VISION_MODEL"] = "deepseek-v4-flash-vision-exp"
    env["VLM_API_KEY"] = env.get("CHAT_API_KEY", "")
    return env


def main() -> int:
    env = load_env()
    os.environ.update({k: v for k, v in env.items() if k not in os.environ})
    # 强制覆盖
    os.environ["VLM_BASE_URL"] = env["VLM_BASE_URL"]
    os.environ["VISION_MODEL"] = env["VISION_MODEL"]
    os.environ["VLM_API_KEY"] = env["VLM_API_KEY"]

    # 重新加载 vlm_filter 模块以应用新环境变量
    import importlib
    import amta.vlm_filter as vf
    importlib.reload(vf)
    from amta.vlm_filter import vlm_filter_v2

    canon = json.loads(CANON.read_text(encoding="utf-8"))
    blocks = [dict(b) for b in canon.get("items", [])]
    print(f"输入: {len(blocks)} blocks")
    for i, b in enumerate(blocks):
        print(f"  r{i:02d}: \"{b.get('text','')[:40]}\" bbox={b.get('bbox')} type={b.get('bubble_type')}")

    runs = []
    for run_idx in range(N_RUNS):
        print(f"\n--- Run {run_idx + 1}/{N_RUNS} ---")
        # 每次用独立的 block 副本
        blocks_copy = [dict(b) for b in canon.get("items", [])]
        t0 = time.time()
        kept, fixed, dropped = vlm_filter_v2(RAW, blocks_copy)
        elapsed = time.time() - t0

        result = {
            "run": run_idx + 1,
            "elapsed_s": round(elapsed, 1),
            "n_kept": len(kept),
            "n_fixed": len(fixed),
            "n_dropped": len(dropped),
            "kept_ids": [b.get("region_id", b.get("_rid", "")) for b in kept],
            "fixed": [{"region_id": b.get("region_id", b.get("_rid", "")),
                       "original": b.get("original_text", ""),
                       "corrected": b.get("text", ""),
                       "reason": b.get("filter_reason", "")} for b in fixed],
            "dropped": [{"region_id": b.get("region_id", b.get("_rid", "")),
                         "text": b.get("original_text", b.get("text", "")),
                         "reason": b.get("filter_reason", "")} for b in dropped],
        }
        runs.append(result)
        print(f"  keep={result['n_kept']} fix={result['n_fixed']} drop={result['n_dropped']} ({elapsed:.1f}s)")
        print(f"  kept: {result['kept_ids']}")
        for f in result["fixed"]:
            print(f"  FIX {f['region_id']}: \"{f['original'][:30]}\" -> \"{f['corrected'][:30]}\"")
        for d in result["dropped"]:
            print(f"  DROP {d['region_id']}: \"{d['text'][:30]}\" — {d['reason'][:50]}")

    # 稳定性分析
    print(f"\n{'='*60}")
    print("稳定性分析")
    print(f"{'='*60}")
    drop_sets = [tuple(sorted(r["dropped_ids"])) for r in runs]
    fix_sets = [tuple(sorted(f["region_id"] for f in r["fixed"])) for r in runs]
    unique_drops = set(drop_sets)
    unique_fixes = set(fix_sets)
    print(f"drop 组合数: {len(unique_drops)}/{N_RUNS}")
    for i, ds in enumerate(unique_drops):
        count = drop_sets.count(ds)
        print(f"  组合 {i+1} ({count}次): {ds}")
    print(f"fix 组合数: {len(unique_fixes)}/{N_RUNS}")
    for i, fs in enumerate(unique_fixes):
        count = fix_sets.count(fs)
        print(f"  组合 {i+1} ({count}次): {fs}")

    out_data = {"runs": runs, "n_runs": N_RUNS,
                "unique_drop_patterns": len(unique_drops),
                "unique_fix_patterns": len(unique_fixes),
                "drop_patterns": [{"ids": list(ds), "count": drop_sets.count(ds)} for ds in unique_drops],
                "fix_patterns": [{"ids": list(fs), "count": fix_sets.count(fs)} for fs in unique_fixes]}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果 -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
