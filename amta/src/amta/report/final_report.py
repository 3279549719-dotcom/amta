"""final_report — 三阶段流水线最终报告（自包含 HTML，内嵌原图 base64）。

深接口模块（ADR-024）：scripts/gen_final_report.py 是本模块的薄 CLI。
新报告需求优先用 amta.report.load_from_workspace + render_report（gen_report.py），
本模块保留是因为其 HTML 模板（简洁三阶段视图 + base64 内嵌）与 gen_report 不同。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from amta.artifact_store import ArtifactStore
from amta.paths import ROOT


def img_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_final_report(
    work_id: str,
    src_dir: Path,
    pages: list[int],
    artifacts_dir: Path | None = None,
) -> str:
    """生成三阶段流水线最终 HTML 报告，返回 HTML 字符串。

    Args:
        work_id: workspace 工作区 ID
        src_dir: 源图目录 (N.jpg)
        pages: 页码列表（0-based，与 artifacts 命名一致）
        artifacts_dir: 产物目录，默认 workspace/<work_id>/artifacts
    """
    if artifacts_dir is None:
        artifacts_dir = ROOT / "workspace" / work_id / "artifacts"
    if not artifacts_dir.exists():
        raise FileNotFoundError(f"artifacts dir not found: {artifacts_dir}")

    pages_data = []
    store = ArtifactStore(artifacts_dir)
    for page_idx in pages:
        page = f"page_{page_idx}"
        det_path = store.resolve("detection", page)
        canon_path = store.resolve("canon", page)
        trans_path = store.resolve("translation", page)
        raw_path = src_dir / f"{page_idx}.jpg"

        if (det_path is None or canon_path is None or trans_path is None) or not raw_path.exists():
            print(f"WARN {page}: missing artifacts, skip")
            continue

        det = _load_json(det_path)
        canon = _load_json(canon_path)
        trans = _load_json(trans_path)
        translations = trans.get("translations", {})

        items = []
        for item in canon.get("items", []):
            rid = item.get("region_id", "")
            ocr_text = item.get("text") or item.get("baberu_text") or ""
            trans_text = translations.get(rid, "")
            items.append({
                "region_id": rid,
                "bbox": item.get("bbox", []),
                "bubble_type": item.get("bubble_type", ""),
                "confidence": item.get("confidence", 0),
                "ocr": ocr_text,
                "translation": trans_text,
            })

        pages_data.append({
            "page_idx": page_idx,
            "page_num": page_idx,
            "raw_image": img_to_base64(raw_path),
            "n_detected": det.get("n_boxes", 0),
            "n_ocr": canon.get("n_regions", 0),
            "n_translated": len(translations),
            "detector": det.get("source_engines", ["rtdetr-v2"])[0],
            "conf_threshold": det.get("conf_threshold", 0.3),
            "items": items,
        })

    html_parts = ["""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AMTA 三阶段流水线最终报告</title>
<style>
body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px; }
h2 { color: #16213e; margin-top: 30px; }
.summary { background: white; padding: 15px 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
.summary table { border-collapse: collapse; width: 100%; }
.summary th, .summary td { border: 1px solid #ddd; padding: 8px 12px; text-align: center; }
.summary th { background: #16213e; color: white; }
.page-section { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
.page-header .stats { font-size: 14px; color: #555; }
.page-content { display: flex; gap: 20px; }
.page-image { flex: 1; max-width: 50%; }
.page-image img { width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.page-table { flex: 1; max-height: 600px; overflow-y: auto; }
.page-table table { border-collapse: collapse; width: 100%; font-size: 13px; }
.page-table th { background: #e8e8e8; position: sticky; top: 0; padding: 6px 8px; text-align: left; border-bottom: 2px solid #999; }
.page-table td { padding: 6px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
.page-table .rid { font-family: monospace; color: #666; white-space: nowrap; }
.page-table .ocr { color: #333; }
.page-table .trans { color: #0066cc; font-weight: 500; }
.page-table .empty { color: #ccc; font-style: italic; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge-bubble { background: #e3f2fd; color: #1565c0; }
.badge-free { background: #fff3e0; color: #e65100; }
.footer { text-align: center; color: #999; font-size: 12px; margin-top: 30px; }
</style>
</head>
<body>
<h1>AMTA 三阶段流水线最终报告</h1>
<div class="summary">
<h3 style="margin-top:0">执行摘要</h3>
<table>
<tr><th>页号</th><th>检测 (RT-DETR-v2)</th><th>OCR (baberu)</th><th>翻译 (qwen VLM + deepseek flash)</th></tr>
"""]

    for p in pages_data:
        html_parts.append(f'<tr><td>Page {p["page_num"]}</td><td>{p["n_detected"]} boxes</td><td>{p["n_ocr"]} regions</td><td>{p["n_translated"]} texts</td></tr>\n')

    total_det = sum(p["n_detected"] for p in pages_data)
    total_ocr = sum(p["n_ocr"] for p in pages_data)
    total_trans = sum(p["n_translated"] for p in pages_data)
    html_parts.append(f'<tr style="font-weight:bold;background:#f0f0f0"><td>合计 ({len(pages_data)} 页)</td><td>{total_det} boxes</td><td>{total_ocr} regions</td><td>{total_trans} texts</td></tr>\n')
    html_parts.append('</table></div>\n')

    for p in pages_data:
        html_parts.append('<div class="page-section">\n')
        html_parts.append(f'<div class="page-header"><h2 style="margin:0">Page {p["page_num"]}</h2>')
        html_parts.append(f'<span class="stats">检测 {p["n_detected"]} → OCR {p["n_ocr"]} → 翻译 {p["n_translated"]} | 检测器: {p["detector"]} | conf={p["conf_threshold"]}</span></div>\n')
        html_parts.append('<div class="page-content">\n')
        html_parts.append(f'<div class="page-image"><img src="data:image/jpeg;base64,{p["raw_image"]}" alt="Page {p["page_num"]}"></div>\n')
        html_parts.append('<div class="page-table"><table><tr><th>ID</th><th>类型</th><th>OCR 原文</th><th>译文</th></tr>\n')
        for item in p["items"]:
            btype = item["bubble_type"]
            badge_cls = "badge-bubble" if btype == "text_bubble" else "badge-free"
            ocr_html = f'<span class="ocr">{item["ocr"]}</span>' if item["ocr"] else '<span class="empty">(空)</span>'
            trans_html = f'<span class="trans">{item["translation"]}</span>' if item["translation"] else '<span class="empty">(未译)</span>'
            html_parts.append(f'<tr><td class="rid">{item["region_id"]}</td><td><span class="badge {badge_cls}">{btype}</span></td><td>{ocr_html}</td><td>{trans_html}</td></tr>\n')
        html_parts.append('</table></div></div></div>\n')

    html_parts.append('<div class="footer">AMTA 最终选型: 检测=RT-DETR-v2 | OCR=baberu | 翻译=qwen3.5-omni-plus VLM + deepseek-v4-flash LLM (v2 三态 keep/fix/drop + 上下文 + 术语)</div>\n')
    html_parts.append('</body></html>')

    return "".join(html_parts)
