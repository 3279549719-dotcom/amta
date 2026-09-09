"""Q1 最小成本验证：29 个目标框单独翻译 + HTML 对比页。

目标框 = 20 个瓦片化新增框 + 被旧几何规则(extreme_aspect/edge_box)滤除的真框
- 排除 pure_punct/pure_number（这些本来就该被滤掉）
- 翻译时加入"乱码输出为空"条款
- 输出 HTML：原图裁剪 + OCR 文本 + 翻译结果 + 框信息

用法：uv run python scripts/probes/q1_target_boxes_translate.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 清除代理环境变量 — deepseek 是国内 API，不需要走 Clash 代理
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PIL import Image  # noqa: E402
from amta.guards.rule_filter import is_pure_punct, is_pure_number  # noqa: E402
from amta.backends.ocr_engines import ocr_batch  # noqa: E402
from amta.translation.translate import translate_plain  # noqa: E402
from amta.backends.chat_client import chat_text  # noqa: E402
from amta.common.config import get_chat_config  # noqa: E402

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "detection"
OUT_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "q1_target_audit"
CROP_DIR = OUT_DIR / "crops"

# 旧几何规则参数（从 git e9aa9af 取出）
EDGE_MARGIN = 8
EXTREME_ASPECT_RATIO = 8.0


def is_edge_box(bbox, img_w, img_h, margin=EDGE_MARGIN):
    x1, y1, x2, y2 = bbox
    return (x1 <= margin) or (y1 <= margin) or (x2 >= img_w - margin) or (y2 >= img_h - margin)


def is_extreme_aspect(bbox, max_ratio=EXTREME_ASPECT_RATIO):
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return (w / h > max_ratio) or (h / w > max_ratio)


def find_target_boxes():
    """找出所有目标框：瓦片化新增 + 被旧几何规则滤除的框。

    注意：detection 阶段没有 text 字段，pure_punct/pure_number 过滤在 OCR 后执行。
    """
    target_boxes = []
    stats = {"tiled": 0, "extreme_aspect": 0, "edge_box": 0}

    for f in sorted(DET_DIR.glob("page_*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        page = int(doc["page"].split("_")[1])
        img_w = doc.get("img_w", 2243)
        img_h = doc.get("img_h", 3465)

        for b in doc["blocks"]:
            bbox = b.get("bbox", [0, 0, 0, 0])
            is_tiled = "rtdetr-v2-tiled" in b.get("source_engines", [])
            is_ea = is_extreme_aspect(bbox)
            is_eb = is_edge_box(bbox, img_w, img_h)

            reasons = []
            if is_tiled:
                reasons.append("tiled_new")
                stats["tiled"] += 1
            if is_ea:
                reasons.append("extreme_aspect_rescued")
                stats["extreme_aspect"] += 1
            if is_eb:
                reasons.append("edge_box_rescued")
                stats["edge_box"] += 1

            if reasons:
                target_boxes.append({
                    "page": page,
                    "region_id": b["region_id"],
                    "bbox": bbox,
                    "confidence": b.get("confidence", 0),
                    "bubble_type": b.get("bubble_type", ""),
                    "source_engines": b.get("source_engines", []),
                    "reasons": reasons,
                    "img_w": img_w,
                    "img_h": img_h,
                })

    return target_boxes, stats


def run_ocr(target_boxes):
    """对目标框跑 OCR。"""
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    crop_paths = []
    box_by_crop = {}

    # 按页分组裁剪
    pages = sorted(set(b["page"] for b in target_boxes))
    for page in pages:
        raw_path = RAW_DIR / f"{page}.jpg"
        if not raw_path.exists():
            continue
        img = Image.open(raw_path)
        page_boxes = [b for b in target_boxes if b["page"] == page]
        for b in page_boxes:
            x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img.crop((x1, y1, x2, y2))
            crop_path = CROP_DIR / f"p{page}_{b['region_id']}.png"
            crop.save(crop_path)
            crop_paths.append(str(crop_path))
            box_by_crop[str(crop_path)] = b

    print(f"  裁剪 {len(crop_paths)} 个框，跑 OCR ...")
    ocr_rows = ocr_batch(crop_paths, engine="hayai")
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}

    for b in target_boxes:
        crop_path = str(CROP_DIR / f"p{b['page']}_{b['region_id']}.png")
        b["ocr_text"] = ocr_by_crop.get(crop_path, "")

    return target_boxes


def run_translation(target_boxes, batch_size=5):
    """对目标框跑翻译，加入'乱码输出为空'条款。小批量调用避免超时。"""
    # 构造 LLM 函数
    cfg = get_chat_config()
    api_key = cfg.get("api_key", "")
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    model = cfg.get("model", "deepseek-chat")

    def llm(messages):
        return chat_text(base_url, model, messages, api_key=api_key, timeout=180, temperature=0.3)

    # 乱码输出为空条款
    system_extra = "如果输入内容是乱码、无法识别的字符或非日文常用文字，输出空字符串。"

    # 构造 canon 格式
    canon = []
    for b in target_boxes:
        canon.append({
            "region_id": f"p{b['page']}_{b['region_id']}",
            "text": b["ocr_text"],
        })

    print(f"  翻译 {len(canon)} 个框（每批 {batch_size} 个，加乱码条款）...")
    all_results = {}
    for i in range(0, len(canon), batch_size):
        batch = canon[i:i + batch_size]
        batch_ids = [c["region_id"] for c in batch]
        print(f"    批次 {i // batch_size + 1}/{(len(canon) + batch_size - 1) // batch_size}: {batch_ids[0]} ~ {batch_ids[-1]}", flush=True)
        try:
            result = translate_plain(batch, llm, system_extra=system_extra, context_enabled=False, max_retries=1)
            all_results.update(result)
            print(f"      成功: {len(result)}/{len(batch)}", flush=True)
        except Exception as e:
            print(f"      失败: {e}", flush=True)
            for c in batch:
                all_results[c["region_id"]] = ""

    for b in target_boxes:
        key = f"p{b['page']}_{b['region_id']}"
        b["translation"] = all_results.get(key, "")

    return target_boxes


def generate_html(target_boxes, stats):
    """生成 HTML 对比页。"""
    # 按页分组
    pages = sorted(set(b["page"] for b in target_boxes))
    by_page = {p: [b for b in target_boxes if b["page"] == p] for p in pages}

    cards_html = ""
    for page in pages:
        boxes = by_page[page]
        page_cards = ""
        for b in boxes:
            crop_rel = f"crops/p{page}_{b['region_id']}.png"
            reasons_str = ", ".join(b["reasons"])
            ocr_text = b["ocr_text"].replace("\n", "<br>") or "<em>(空)</em>"
            trans_text = b["translation"].replace("\n", "<br>") or "<em>(空)</em>"
            is_garbled = "乱码" in b.get("translation", "") or (not b["translation"] and b["ocr_text"] and not is_pure_punct(b["ocr_text"]))
            garbled_tag = '<span style="background:#EA6668;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px;">疑似乱码→空</span>' if is_garbled else ""

            page_cards += f'''
            <div style="background:#fff;border:1px solid #E4E3DD;border-radius:10px;padding:12px;margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-weight:600;font-size:13px;color:#1A1B1C;">p{page} / {b["region_id"]}</span>
                <span style="font-size:11px;color:#6B7280;">conf={b["confidence"]:.3f} · {b["bubble_type"]}</span>
              </div>
              <div style="font-size:11px;color:#8BC8EA;margin-bottom:8px;">{reasons_str} {garbled_tag}</div>
              <div style="display:flex;gap:12px;flex-wrap:wrap;">
                <div style="flex:0 0 auto;">
                  <img src="{crop_rel}" style="max-width:200px;max-height:150px;border:1px solid #E4E3DD;border-radius:6px;" />
                </div>
                <div style="flex:1;min-width:200px;">
                  <div style="font-size:11px;color:#6B7280;margin-bottom:2px;">OCR 原文</div>
                  <div style="font-size:13px;color:#1A1B1C;margin-bottom:8px;line-height:1.5;">{ocr_text}</div>
                  <div style="font-size:11px;color:#6B7280;margin-bottom:2px;">翻译结果</div>
                  <div style="font-size:13px;color:#1A1B1C;line-height:1.5;">{trans_text}</div>
                </div>
              </div>
            </div>'''

        cards_html += f'''
        <div style="margin-bottom:24px;">
          <h3 style="font-size:15px;font-weight:600;color:#1A1B1C;border-left:3px solid #8BC8EA;padding-left:8px;margin-bottom:12px;">第 {page} 页（{len(boxes)} 个框）</h3>
          {page_cards}
        </div>'''

    # 统计摘要
    summary_html = f'''
    <div style="background:#fff;border:1px solid #E4E3DD;border-radius:10px;padding:16px;margin-bottom:24px;">
      <h3 style="font-size:14px;font-weight:600;color:#1A1B1C;margin-bottom:12px;">账目统计</h3>
      <div style="display:flex;gap:16px;flex-wrap:wrap;">
        <div style="flex:1;min-width:120px;"><div style="font-size:20px;font-weight:600;color:#8BC8EA;">{len(target_boxes)}</div><div style="font-size:11px;color:#6B7280;">目标框总数</div></div>
        <div style="flex:1;min-width:120px;"><div style="font-size:20px;font-weight:600;color:#94D8C3;">{stats["tiled"]}</div><div style="font-size:11px;color:#6B7280;">瓦片化新增</div></div>
        <div style="flex:1;min-width:120px;"><div style="font-size:20px;font-weight:600;color:#F4B393;">{stats["extreme_aspect"]}</div><div style="font-size:11px;color:#6B7280;">extreme_aspect 救回</div></div>
        <div style="flex:1;min-width:120px;"><div style="font-size:20px;font-weight:600;color:#DEBEF8;">{stats["edge_box"]}</div><div style="font-size:11px;color:#6B7280;">edge_box 救回</div></div>
      </div>
      <div style="margin-top:12px;font-size:11px;color:#6B7280;">
        排除 pure_punct: {stats["pure_punct_skipped"]} · 排除 pure_number: {stats["pure_number_skipped"]} ·
        分布页数: {len(pages)} 页 · 翻译已加"乱码→空"条款
      </div>
    </div>'''

    html = f'''<!DOCTYPE html>
<html style="margin:0;padding:0;">
<head><meta charset="utf-8"><title>Q1 目标框审计</title></head>
<body style="margin:0;padding:0;background:#F4F3EE;font-family:"PingFang SC","Segoe UI",Arial,sans-serif;">
<div style="max-width:900px;margin:0 auto;padding:20px;">
  <h1 style="font-size:18px;font-weight:600;color:#1A1B1C;margin-bottom:4px;">Q1 目标框翻译审计</h1>
  <p style="font-size:12px;color:#6B7280;margin-bottom:20px;">瓦片化新增框 + 被旧几何规则救回的真框 · 翻译加"乱码→空"条款 · 最小成本验证</p>
  {summary_html}
  {cards_html}
</div>
</body>
</html>'''

    html_path = OUT_DIR / "q1_target_audit.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main():
    print("=" * 60)
    print("Q1 最小成本验证：目标框翻译 + HTML 对比页")
    print("=" * 60)

    # Step 1: 找出目标框
    print("\n[Step 1] 找出目标框...")
    target_boxes, stats = find_target_boxes()
    print(f"  候选框总数: {len(target_boxes)}")
    print(f"  瓦片化新增: {stats['tiled']}")
    print(f"  extreme_aspect 命中: {stats['extreme_aspect']}")
    print(f"  edge_box 命中: {stats['edge_box']}")
    pages = sorted(set(b["page"] for b in target_boxes))
    print(f"  分布页数: {len(pages)} 页: {pages}")

    # Step 2: OCR
    print("\n[Step 2] 裁剪 + OCR...")
    target_boxes = run_ocr(target_boxes)

    # Step 2.5: OCR 后过滤 pure_punct/pure_number（这些本来就该被滤掉）
    print("\n[Step 2.5] 过滤 pure_punct/pure_number...")
    pp_skipped = 0
    pn_skipped = 0
    filtered = []
    for b in target_boxes:
        text = b.get("ocr_text", "")
        if is_pure_punct(text):
            pp_skipped += 1
            b["filter_reason"] = "pure_punct"
            continue
        if is_pure_number(text):
            pn_skipped += 1
            b["filter_reason"] = "pure_number"
            continue
        filtered.append(b)
    stats["pure_punct_skipped"] = pp_skipped
    stats["pure_number_skipped"] = pn_skipped
    target_boxes = filtered
    print(f"  排除 pure_punct: {pp_skipped}")
    print(f"  排除 pure_number: {pn_skipped}")
    print(f"  剩余待翻译: {len(target_boxes)} 个框")

    # Step 3: 翻译
    print("\n[Step 3] 翻译（加乱码条款）...")
    target_boxes = run_translation(target_boxes)

    # Step 4: 生成 HTML
    print("\n[Step 4] 生成 HTML 对比页...")
    html_path = generate_html(target_boxes, stats)
    print(f"  HTML 已生成: {html_path}")

    # 保存 JSON 数据
    json_path = OUT_DIR / "q1_target_boxes.json"
    json_path.write_text(json.dumps(target_boxes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON 数据: {json_path}")

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
