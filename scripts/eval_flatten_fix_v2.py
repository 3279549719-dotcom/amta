"""eval_flatten_fix_v2.py — 残差保底修复的端到端 eval（轻量版，不重跑 detect）。

策略：用旧 detection.json 中的 regions（build_regions 输出），用修复后的 flatten_regions
重新展平得到新 blocks，然后只重跑 OCR（baberu，koharu 内置，压力小）。
对比修复前后的 blocks 和 OCR 结果，输出 HTML 报告。

用法: python scripts/eval_flatten_fix_v2.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.regions import flatten_regions  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
WS = Path(r"E:\manga translator agent\amta\workspace\touhou-single-wing")
ART = WS / "artifacts"
BACKUP = ART / "backup_pre_fix_eval"
EVAL_DIR = Path(r"E:\manga translator agent\amta\output\eval_flatten_fix")
PY = sys.executable

# Eval 页面：(文件名N.jpg, page_idx=N-1)
EVAL_PAGES = [11, 12, 13, 14, 15, 17]

# 已知漏检区域
MISS_REGIONS = {
    14: [
        {"label": "では豊ちゃん…(大字长句)", "expected_bbox": [1600, 2630, 1870, 3150]},
    ],
    15: [
        {"label": "弟子だからね(大字主台词)", "expected_bbox": [50, 2430, 210, 2870]},
    ],
}


def bbox_area(bb):
    return max(0, bb[2] - bb[0]) * max(0, bb[3] - bb[1])


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = bbox_area(a) + bbox_area(b) - inter
    return inter / ua if ua > 0 else 0


def old_flatten(regions):
    out = []
    for r in regions:
        if r.get("child_lines"):
            for line in r["child_lines"]:
                out.append(dict(line))
        else:
            out.append(dict(r))
    return out


def regenerate_detection(n):
    """用旧 regions + 修复后 flatten_regions 重新生成 detection.json。"""
    page_idx = n - 1
    det_path = ART / f"page_{page_idx}_detection.json"
    old_doc = read_json(det_path)
    regions = old_doc.get("regions", [])

    # 用修复后的 flatten_regions 重新展平
    new_blocks = flatten_regions(regions)

    # 更新 detection.json
    new_doc = dict(old_doc)
    new_doc["blocks"] = new_blocks
    new_doc["n_boxes"] = len(new_blocks)
    new_doc["flatten_fix_applied"] = True
    new_doc["n_fallback"] = sum(1 for b in new_blocks if b.get("fallback_triggered"))
    write_json(det_path, new_doc)

    old_blocks = old_flatten(regions)
    return old_blocks, new_blocks, old_doc


def run_ocr(n):
    page_idx = n - 1
    raw = SRC / f"{n}.jpg"
    det = ART / f"page_{page_idx}_detection.json"
    out = ART / f"page_{page_idx}_canon.json"
    if out.exists():
        out.unlink()
    print(f"  [ocr] page {n} (page_{page_idx}) ...")
    t0 = time.time()
    r = subprocess.run([PY, str(HERE / "02_ocr.py"),
                        "--work-id", "touhou-single-wing",
                        "--det", str(det), "--raw", str(raw),
                        "--out", str(out), "--page-idx", str(page_idx),
                        "--engine", "auto"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    dur = time.time() - t0
    if r.returncode != 0:
        print(f"    ERROR: {r.stderr[-500:]}")
        return None
    print(f"    OK ({dur:.1f}s)")
    return out


def load_canon(path):
    if not path.exists():
        return []
    data = read_json(path)
    if isinstance(data, dict):
        return data.get("items", [])
    return data


def analyze_page(n, old_blocks, new_blocks):
    page_idx = n - 1
    result = {"page": n, "page_idx": page_idx}

    result["old_n_boxes"] = len(old_blocks)
    result["new_n_boxes"] = len(new_blocks)
    result["n_fallback"] = sum(1 for b in new_blocks if b.get("fallback_triggered"))

    # 找出变化的框（fallback 框）
    fallback_boxes = [b for b in new_blocks if b.get("fallback_triggered")]
    result["fallback_boxes"] = [{"bbox": b["bbox"], "w": round(b["bbox"][2]-b["bbox"][0], 1),
                                   "h": round(b["bbox"][3]-b["bbox"][1], 1)} for b in fallback_boxes]

    # 漏检区域覆盖检查
    miss_checks = []
    for mr in MISS_REGIONS.get(n, []):
        exp = mr["expected_bbox"]
        def hits(blocks):
            return [b for b in blocks if iou(b["bbox"], exp) > 0.1 or
                    (exp[0] <= (b["bbox"][0]+b["bbox"][2])/2 <= exp[2] and
                     exp[1] <= (b["bbox"][1]+b["bbox"][3])/2 <= exp[3])]
        old_h = hits(old_blocks)
        new_h = hits(new_blocks)
        old_max_w = max((b["bbox"][2]-b["bbox"][0] for b in old_h), default=0)
        new_max_w = max((b["bbox"][2]-b["bbox"][0] for b in new_h), default=0)
        miss_checks.append({
            "label": mr["label"],
            "old_n_hits": len(old_h),
            "new_n_hits": len(new_h),
            "old_max_w": round(old_max_w, 1),
            "new_max_w": round(new_max_w, 1),
            "old_best_iou": round(max((iou(b["bbox"], exp) for b in old_h), default=0), 3),
            "new_best_iou": round(max((iou(b["bbox"], exp) for b in new_h), default=0), 3),
            "new_fallback": any(b.get("fallback_triggered") for b in new_h),
        })
    result["miss_checks"] = miss_checks

    # OCR 对比
    old_canon = BACKUP / f"page_{page_idx}_canon.json"
    new_canon = ART / f"page_{page_idx}_canon.json"
    old_items = load_canon(old_canon)
    new_items = load_canon(new_canon)
    result["old_n_ocr"] = len(old_items)
    result["new_n_ocr"] = len(new_items)

    old_texts = {item.get("text", "") for item in old_items}
    new_texts = [item.get("text", "") for item in new_items]
    added_texts = [t for t in new_texts if t not in old_texts and t]
    result["added_ocr_texts"] = added_texts
    result["old_ocr_sample"] = [item.get("text", "") for item in old_items[:8]]
    result["new_ocr_sample"] = [item.get("text", "") for item in new_items[:8]]

    return result


def generate_html(results):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    total_old = sum(r["old_n_boxes"] for r in results)
    total_new = sum(r["new_n_boxes"] for r in results)
    total_fb = sum(r["n_fallback"] for r in results)
    total_old_ocr = sum(r["old_n_ocr"] for r in results)
    total_new_ocr = sum(r["new_n_ocr"] for r in results)
    all_added = []
    for r in results:
        all_added.extend(r.get("added_ocr_texts", []))

    rows = ""
    for r in results:
        miss_rows = ""
        for mc in r.get("miss_checks", []):
            improved = mc["new_best_iou"] > mc["old_best_iou"] or mc["new_max_w"] > mc["old_max_w"] * 1.3
            status = "✅ 修复" if improved else "⚠️"
            miss_rows += f"""
            <tr>
              <td>{mc['label']}</td>
              <td>{mc['old_n_hits']}</td>
              <td>{mc['new_n_hits']}</td>
              <td>{mc['old_max_w']:.0f}px</td>
              <td>{mc['new_max_w']:.0f}px</td>
              <td>{mc['old_best_iou']:.3f}</td>
              <td>{mc['new_best_iou']:.3f}</td>
              <td>{'是' if mc['new_fallback'] else '否'}</td>
              <td>{status}</td>
            </tr>"""

        fb_html = ""
        for fb in r.get("fallback_boxes", []):
            fb_html += f"<li>bbox={fb['bbox']} ({fb['w']:.0f}×{fb['h']:.0f})</li>"
        if not fb_html:
            fb_html = "<li style='color:#888'>无</li>"

        added_html = ""
        for t in r.get("added_ocr_texts", []):
            added_html += f"<li>{t}</li>"
        if not added_html:
            added_html = "<li style='color:#888'>无新增</li>"

        rows += f"""
        <div class="page-card">
          <h3>Page {r['page']} (page_{r['page_idx']})</h3>
          <div class="metrics">
            <div class="metric"><span class="label">检测框数</span><span class="value">{r['old_n_boxes']} → {r['new_n_boxes']}</span></div>
            <div class="metric"><span class="label">Fallback 框</span><span class="value highlight">{r['n_fallback']}</span></div>
            <div class="metric"><span class="label">OCR 文本数</span><span class="value">{r['old_n_ocr']} → {r['new_n_ocr']}</span></div>
          </div>
          <div class="fb-list">
            <h4>Fallback 容器框（修复后新增/替换的宽框）：</h4>
            <ul>{fb_html}</ul>
          </div>
          {'<table class="miss-table"><thead><tr><th>漏检区域</th><th>旧命中</th><th>新命中</th><th>旧最大宽</th><th>新最大宽</th><th>旧IoU</th><th>新IoU</th><th>Fallback</th><th>状态</th></tr></thead><tbody>'+miss_rows+'</tbody></table>' if miss_rows else ''}
          <div class="ocr-diff">
            <h4>修复后新增 OCR 文本：</h4>
            <ul>{added_html}</ul>
          </div>
          <div class="ocr-compare">
            <h4>OCR 文本对比（前8条）：</h4>
            <div class="compare-grid">
              <div><strong>修复前：</strong><ul>{''.join(f'<li>{t}</li>' for t in r.get('old_ocr_sample',[]))}</ul></div>
              <div><strong>修复后：</strong><ul>{''.join(f'<li>{t}</li>' for t in r.get('new_ocr_sample',[]))}</ul></div>
            </div>
          </div>
        </div>"""

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>flatten_regions 残差保底修复 Eval 报告</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px;max-width:1200px;margin:0 auto}}
h1{{color:#60a5fa;border-bottom:2px solid #1e3a5f;padding-bottom:12px}}
h2{{color:#93c5fd;margin-top:32px}}
h3{{color:#a5f3fc;margin-top:20px}}
h4{{color:#cbd5e1;margin:12px 0 6px}}
.summary{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;margin:20px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}
.summary .item{{text-align:center}}
.summary .num{{font-size:28px;font-weight:700;color:#60a5fa}}
.summary .lbl{{font-size:12px;color:#94a3b8;margin-top:4px}}
.page-card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px;margin:16px 0}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:12px 0}}
.metric{{background:#0f172a;border-radius:8px;padding:10px}}
.metric .label{{font-size:11px;color:#94a3b8;text-transform:uppercase}}
.metric .value{{font-size:16px;font-weight:600;color:#e2e8f0;margin-top:4px}}
.metric .value.highlight{{color:#fbbf24}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}}
th,td{{padding:8px 10px;border-bottom:1px solid #334155;text-align:left}}
th{{background:#0f172a;color:#93c5fd}}
.fb-list,.ocr-diff,.ocr-compare{{background:#0f172a;border-radius:8px;padding:12px;margin-top:12px}}
.fb-list ul,.ocr-diff ul{{margin:8px 0;padding-left:20px}}
.fb-list li{{margin:4px 0;color:#fbbf24}}
.ocr-diff li{{margin:4px 0;color:#86efac}}
.compare-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.compare-grid ul{{margin:6px 0;padding-left:18px;font-size:13px}}
.compare-grid li{{margin:3px 0}}
.footer{{margin-top:40px;padding-top:16px;border-top:1px solid #334155;color:#64748b;font-size:12px;text-align:center}}
</style>
</head>
<body>
<h1>flatten_regions 残差保底修复 — 端到端 Eval 报告</h1>
<p><strong>修复内容：</strong><code>geometry.py:flatten_regions</code> 增加残差保底律——容器内 child_lines 覆盖率不足 60% 或单子行极窄（容器宽 > 1.5×子行宽）时，丢弃子行、输出完整母体气泡容器送 OCR。</p>
<p><strong>Eval 方法：</strong>用旧 detection.json 中的 regions（build_regions 输出）+ 修复后 flatten_regions 重新展平，只重跑 OCR（baberu）。不重跑 4-detector 并集（避免内存压力）。</p>
<p><strong>Eval 页面：</strong>{', '.join(str(p) for p in EVAL_PAGES)}.jpg（覆盖低保底对照 + 核心漏检 case + 框数变化页）</p>
<p><strong>执行时间：</strong>{time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>汇总</h2>
<div class="summary">
  <div class="item"><div class="num">{total_old} → {total_new}</div><div class="lbl">检测框总数</div></div>
  <div class="item"><div class="num" style="color:#fbbf24">{total_fb}</div><div class="lbl">触发 Fallback 框数</div></div>
  <div class="item"><div class="num">{total_old_ocr} → {total_new_ocr}</div><div class="lbl">OCR 文本总数</div></div>
  <div class="item"><div class="num" style="color:#86efac">{len(all_added)}</div><div class="lbl">修复后新增 OCR 文本</div></div>
</div>

<h2>逐页详情</h2>
{rows}

<div class="footer">
  AMTA Manga Translation Pipeline — flatten_regions Residual Container Fallback Evaluation<br>
  生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
</div>
</body>
</html>"""

    out = EVAL_DIR / "eval_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"\n[eval] HTML report -> {out}")
    return out


def main():
    print("=" * 70)
    print("flatten_regions 残差保底修复 — 端到端 Eval v2（轻量版）")
    print("=" * 70)

    # 1. 用旧 regions + 修复后 flatten_regions 重新生成 detection.json
    print("\n[1/3] 重新展平 regions（修复后 flatten_regions）...")
    page_data = {}
    for n in EVAL_PAGES:
        old_blocks, new_blocks, old_doc = regenerate_detection(n)
        page_data[n] = (old_blocks, new_blocks)
        n_fb = sum(1 for b in new_blocks if b.get("fallback_triggered"))
        print(f"  page {n}: {len(old_blocks)} → {len(new_blocks)} boxes, fallback={n_fb}")

    # 2. 跑 OCR
    print("\n[2/3] 重跑 OCR（baberu）...")
    for n in EVAL_PAGES:
        run_ocr(n)

    # 3. 分析 + 生成 HTML
    print("\n[3/3] 分析差异 + 生成 HTML 报告...")
    results = []
    for n in EVAL_PAGES:
        old_blocks, new_blocks = page_data[n]
        r = analyze_page(n, old_blocks, new_blocks)
        results.append(r)
        print(f"  page {n}: boxes {r['old_n_boxes']}→{r['new_n_boxes']}, "
              f"fallback={r['n_fallback']}, ocr {r['old_n_ocr']}→{r['new_n_ocr']}, "
              f"added={len(r.get('added_ocr_texts',[]))}")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    json_path = EVAL_DIR / "eval_results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON -> {json_path}")

    generate_html(results)
    print("\n[eval] DONE")


if __name__ == "__main__":
    main()
