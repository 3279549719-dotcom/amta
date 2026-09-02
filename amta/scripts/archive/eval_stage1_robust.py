"""eval_stage1_robust.py — Stage 1 全量验证（每页重启 koharu 容错版）。

因为 koharu 在 CPU/Vulkan 环境下不稳定，跑完一页可能崩溃。
本脚本每页检测前重启 koharu，确保 10 页都能跑完。

用法：py -3.13 scripts/eval_stage1_robust.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
WORKTREE = Path(__file__).resolve().parent.parent
MAIN_WORKTREE = Path(r"E:\manga translator agent\amta")
WORK_ID = "touhou-single-wing"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS = WORKTREE / "workspace" / WORK_ID / "artifacts"
BACKUP_DIR = ARTIFACTS / "backup_pre_front3"
REPORT_HTML = ARTIFACTS / "eval_stage1_report.html"
REPORT_JSON = ARTIFACTS / "eval_stage1_results.json"

KOHARU_EXE = r"D:\我的汉化\workflow\bin\koharu.exe"
KOHARU_PORT = 4000

# 11.jpg ~ 20.jpg → page_11_detection.json ~ page_20_detection.json（真实页码，与 doc["page"] 一致）
EVAL_PAGES = list(range(11, 21))

# 已知漏检区域（page_num → {label, bbox}）
KNOWN_MISSES = {
    14: {"label": "では豊ちゃん", "bbox": [1600, 2630, 1870, 3150]},
    15: {"label": "弟子だからね", "bbox": [50, 2430, 210, 2870]},
}


def detection_path_for(artifacts: Path, page_num: int) -> Path:
    """检测产物文件名使用真实页码（修复 off-by-one：page_11_detection.json 装 page 11 数据）。"""
    return artifacts / f"page_{page_num}_detection.json"


def bbox_overlap(a: list[float], b: list[float]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    return inter / area_a


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def kill_koharu():
    """终止所有 koharu 进程。"""
    subprocess.run(
        ["taskkill", "/F", "/IM", "koharu.exe"],
        capture_output=True, timeout=10,
    )
    time.sleep(2)


def start_koharu() -> subprocess.Popen:
    """启动 koharu（GUI 模式更稳定），返回进程对象。"""
    env = dict(**__import__("os").environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    proc = subprocess.Popen(
        [KOHARU_EXE, "--port", str(KOHARU_PORT), "--cpu"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def wait_koharu_ready(timeout: int = 120) -> bool:
    """等待 koharu HTTP 就绪。"""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{KOHARU_PORT}/")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def run_detection(page_num: int) -> dict | None:
    """跑单页检测，返回结果 dict 或 None。"""
    raw_path = RAW_DIR / f"{page_num}.jpg"
    out_path = detection_path_for(ARTIFACTS, page_num)

    if not raw_path.exists():
        print(f"  [SKIP] {raw_path} not found")
        return None

    # 已存在则跳过（断点续跑）；文件页码与目标页不符时视为脏缓存，重新检测
    if out_path.exists():
        existing = load_json(out_path)
        if existing and existing.get("n_boxes", 0) > 0:
            if existing.get("page") != str(page_num):
                print(f"  [WARN] cache mismatch: {out_path.name} contains page={existing.get('page')}, re-running")
            else:
                print(f"  [CACHE] page {page_num}: {existing['n_boxes']} boxes")
                return existing

    # 启动 koharu
    print(f"  Starting koharu for page {page_num}...")
    kill_koharu()
    start_koharu()
    if not wait_koharu_ready(timeout=120):
        print(f"  [ERROR] koharu not ready for page {page_num}")
        kill_koharu()
        return None

    # 跑检测
    cmd = [
        sys.executable, str(WORKTREE / "scripts" / "01_detect.py"),
        "--work-id", WORK_ID,
        "--raw", str(raw_path),
        "--out", str(out_path),
    ]
    env = dict(**__import__("os").environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)

    # 关闭 koharu
    kill_koharu()

    if result.returncode != 0:
        print(f"  [ERROR] detection failed for page {page_num}:")
        print(f"    stderr: {result.stderr[-500:]}")
        return None

    data = load_json(out_path)
    if data:
        # 防御：文件名页码必须与数据内 page 字段一致（off-by-one 回归防护）
        if data.get("page") != str(page_num):
            print(f"  [ERROR] page mismatch: {out_path.name} contains page={data.get('page')}, expected {page_num}")
            return None
        print(f"  [OK] page {page_num}: {data.get('n_boxes', 0)} boxes")
    return data


def main():
    print("=" * 60)
    print("Stage 1 全量验证（robust 版，每页重启 koharu）")
    print("=" * 60)

    # 1. 备份旧 detection.json
    print("\n[1/4] 备份旧 detection.json...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    old_main = MAIN_WORKTREE / "workspace" / WORK_ID / "artifacts" / "detection.json"
    if old_main.exists():
        shutil.copy2(old_main, BACKUP_DIR / "detection.json")
        print(f"  Backed up: {old_main}")
    else:
        print(f"  Warning: old detection.json not found at {old_main}")

    old_data = load_json(BACKUP_DIR / "detection.json")
    old_pages = {}
    if old_data and "pages" in old_data:
        for p in old_data["pages"]:
            old_pages[p.get("page")] = p

    # 2. 跑 10 页检测
    print(f"\n[2/4] 跑 {len(EVAL_PAGES)} 页检测（11-20）...")
    new_results = {}
    for page_num in EVAL_PAGES:
        print(f"\n  --- Page {page_num} ---")
        data = run_detection(page_num)
        if data:
            new_results[page_num] = data

    print(f"\n  成功: {len(new_results)}/{len(EVAL_PAGES)} 页")

    # 3. 对比分析
    print("\n[3/4] 对比分析...")
    comparison = []
    for page_num in EVAL_PAGES:
        old = old_pages.get(str(page_num)) or old_pages.get(page_num)
        new = new_results.get(page_num)
        entry = {
            "page": page_num,
            "old_boxes": len(old.get("blocks", [])) if old else 0,
            "new_boxes": new.get("n_boxes", 0) if new else 0,
            "old_per_engine": old.get("per_engine_boxes", {}) if old else {},
            "new_per_engine": new.get("per_engine_boxes", {}) if new else {},
            "contained_in_old": sum(1 for b in (old.get("blocks", []) if old else []) if b.get("contained_in")),
            "contained_in_new": sum(1 for b in (new.get("blocks", []) if new else []) if b.get("contained_in")),
        }
        # 已知漏检覆盖率
        if page_num in KNOWN_MISSES and new:
            miss = KNOWN_MISSES[page_num]
            covered = any(
                bbox_overlap(miss["bbox"], b["bbox"]) > 0.5
                for b in new.get("blocks", [])
            )
            entry["known_miss"] = miss["label"]
            entry["known_miss_covered"] = covered
        comparison.append(entry)

    # 4. 生成报告
    print("\n[4/4] 生成报告...")
    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "work_id": WORK_ID,
        "pages_evaluated": EVAL_PAGES,
        "pages_succeeded": len(new_results),
        "comparison": comparison,
        "summary": {
            "total_old_boxes": sum(c["old_boxes"] for c in comparison),
            "total_new_boxes": sum(c["new_boxes"] for c in comparison),
            "total_old_contained": sum(c["contained_in_old"] for c in comparison),
            "total_new_contained": sum(c["contained_in_new"] for c in comparison),
        },
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {REPORT_JSON}")

    # HTML 报告
    html = generate_html_report(results)
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML: {REPORT_HTML}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("验证摘要")
    print("=" * 60)
    s = results["summary"]
    print(f"  总框数: 旧={s['total_old_boxes']} → 新={s['total_new_boxes']}")
    print(f"  contained_in: 旧={s['total_old_contained']} → 新={s['total_new_contained']}")
    print(f"  成功页数: {len(new_results)}/{len(EVAL_PAGES)}")
    for c in comparison:
        miss_str = ""
        if "known_miss_covered" in c:
            miss_str = f" 漏检{'✓' if c['known_miss_covered'] else '✗'}"
        print(f"  P{c['page']:2d}: 旧={c['old_boxes']:2d} 新={c['new_boxes']:2d} contained旧={c['contained_in_old']} 新={c['contained_in_new']}{miss_str}")

    print("\n完成！")


def generate_html_report(results: dict) -> str:
    rows = ""
    for c in results["comparison"]:
        miss_cell = ""
        if "known_miss_covered" in c:
            color = "#22c55e" if c["known_miss_covered"] else "#ef4444"
            symbol = "✓" if c["known_miss_covered"] else "✗"
            miss_cell = f'<td style="color:{color};font-weight:bold">{symbol} {c.get("known_miss","")}</td>'
        else:
            miss_cell = "<td>-</td>"
        rows += f"""<tr>
            <td>{c['page']}</td>
            <td>{c['old_boxes']}</td>
            <td>{c['new_boxes']}</td>
            <td>{c['contained_in_old']}</td>
            <td>{c['contained_in_new']}</td>
            {miss_cell}
        </tr>"""

    s = results["summary"]
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Stage 1 验证报告</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
h1 {{ color: #1e40af; }}
.summary {{ display: flex; gap: 24px; margin: 24px 0; flex-wrap: wrap; }}
.card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 24px; }}
.card .num {{ font-size: 28px; font-weight: bold; color: #1e40af; }}
.card .label {{ font-size: 12px; color: #64748b; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: center; }}
th {{ background: #1e40af; color: white; }}
tr:nth-child(even) {{ background: #f8fafc; }}
.meta {{ color: #64748b; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<h1>Stage 1 重构验证报告</h1>
<p>work_id: {results['work_id']} | 生成时间: {results['generated_at']}</p>
<div class="summary">
    <div class="card"><div class="num">{s['total_old_boxes']}</div><div class="label">旧总框数</div></div>
    <div class="card"><div class="num">{s['total_new_boxes']}</div><div class="label">新总框数</div></div>
    <div class="card"><div class="num">{s['total_old_contained']}</div><div class="label">旧 contained_in</div></div>
    <div class="card"><div class="num">{s['total_new_contained']}</div><div class="label">新 contained_in</div></div>
    <div class="card"><div class="num">{results['pages_succeeded']}/{len(results['pages_evaluated'])}</div><div class="label">成功页数</div></div>
</div>
<table>
<tr><th>Page</th><th>旧框数</th><th>新框数</th><th>旧 contained</th><th>新 contained</th><th>已知漏检</th></tr>
{rows}
</table>
<p class="meta">front3_version: 2.0 | 检测引擎: pp-doclayout-v3, comic-text-detector, anime-text, comic-text-bubble-detector</p>
</body></html>"""


if __name__ == "__main__":
    main()
