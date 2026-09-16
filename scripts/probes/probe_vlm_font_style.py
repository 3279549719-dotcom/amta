"""实验探针 v3：VLM 看整页带框图 → 自由观察有几种字体风格。

v3 改动（the bitter lesson 路线）：
- 不再拼 contact sheet，改为在整页原图上画框+编号
- VLM 自由观察：这页有几种文字风格、各在哪些编号
- 不预设枚举标签数量，让 VLM 自己聚类
- 关键词匹配把 VLM 的自由描述映射到字体文件
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.common.config import get_vlm_api_key
from amta.common.paths import ROOT, read_json, write_json
from amta.typeset.typeset_engine import fit_font_size
from amta.typeset.typeset_render import render_item

FONT_DIR = Path("C:/Windows/Fonts")
VLM_MODEL = "deepseek-v4-flash-vision-exp"
VLM_BASE_URL = "https://api.deepseek.com/chat/completions"

# 关键词 → 字体文件 + 描边
# VLM 自由描述风格，这里做关键词匹配
KEYWORD_FONTS = [
    (("手写", "书道", "笔", "走り書き", "手书", "潦草", "飞白"),
     ("FZSTK.TTF", 2.5, "handwritten")),
    (("宋", "明", "衬线", "mincho", "セリフ"),
     ("simsun.ttc", 0, "print_mincho")),
    (("圆", "丸", "round", "丸文字", "圆润"),
     ("msyh.ttc", 0, "rounded_gothic")),
]
DEFAULT_FONT = ("msyhbd.ttc", 0, "print_gothic")


def draw_boxes_on_page(raw_img: Image.Image, blocks: list[dict]) -> Image.Image:
    """在整页图上画框和编号（1 基）。"""
    img = raw_img.copy()
    draw = ImageDraw.Draw(img)
    try:
        num_font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        num_font = ImageFont.load(size=36)

    for i, b in enumerate(blocks):
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        # 画框
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=4)
        # 画编号（框左上角外侧，避免挡住字）
        num = str(i + 1)
        ny = max(0, y1 - 42)
        draw.rectangle([x1, ny, x1 + 50, ny + 40], fill=(255, 0, 0))
        draw.text((x1 + 8, ny + 4), num, fill=(255, 255, 255), font=num_font)
    return img


def classify_fonts_full_page(page_img: Image.Image, n_boxes: int,
                             api_key: str) -> tuple[dict[int, str], str, float]:
    """给 VLM 看整页带框图，让它自由描述每个编号的字体风格。

    Returns:
        {编号(1基): 风格描述词}, raw_output, elapsed
    """
    buf = io.BytesIO()
    # 整页图可能很大，缩到最长边 2000 以内（VLM 限制）
    max_side = 2000
    if max(page_img.size) > max_side:
        r = max_side / max(page_img.size)
        page_img = page_img.resize(
            (int(page_img.width * r), int(page_img.height * r)),
            Image.LANCZOS)
    page_img.save(buf, format="JPEG", quality=85)
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = (
        f"这是一页漫画，上面画了 {n_boxes} 个红色框，框左上角的红色编号标记了文字区域（1~{n_boxes}）。\n"
        "请观察每个编号框内的文字，判断它的**字形风格**（不是文字内容、不是语气）。\n"
        "你需要做的：自由描述每个编号的字看起来是什么风格——比如"
        "「印刷黑体」「手写体」「宋体/明朝体」「圆体」等。\n"
        "如果多个编号是同一种字体，给它们相同的描述词。\n"
        "注意：不要根据文字内容或感叹号判断，只看字形外观（笔画粗细、衬线、倾斜、圆润度）。\n"
        "\n输出严格 JSON：{\"1\": \"风格描述\", \"2\": \"风格描述\", ...}，不要输出任何其他内容。"
    )

    payload = {
        "model": VLM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "high",
                }},
            ],
        }],
        "max_tokens": 2000,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    import requests
    t0 = time.time()
    resp = requests.post(VLM_BASE_URL, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    elapsed = time.time() - t0

    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    result: dict[int, str] = {}
    for i in range(1, n_boxes + 1):
        result[i] = str(data.get(str(i), "")).strip()
    return result, raw, elapsed


def map_style_to_font(desc: str) -> tuple[Path, int, str]:
    """把 VLM 的自由风格描述映射到字体文件。"""
    desc_lower = desc.lower()
    for keywords, (fname, stroke, label) in KEYWORD_FONTS:
        for kw in keywords:
            if kw in desc or kw.lower() in desc_lower:
                p = FONT_DIR / fname
                if p.exists():
                    return p, stroke, label
    # 默认
    fname, stroke, label = DEFAULT_FONT
    return FONT_DIR / fname, stroke, label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--src-dir", default=r"D:\我的汉化\汉化作品\东方\单翼停留之地")
    args = ap.parse_args()

    work_dir = ROOT / "workspace" / args.work_id / "artifacts"
    page_key = f"page_{args.page}"
    src_img = Path(args.src_dir) / f"{args.page}.jpg"

    # 1. 读 detection + canon + translation
    det = read_json(work_dir / "detection" / f"{page_key}.json")
    canon_doc = read_json(work_dir / "canon" / f"{page_key}.json")
    trans_doc = read_json(work_dir / "translation" / f"{page_key}.json")
    blocks = det.get("blocks", [])
    trans = trans_doc.get("translations", {})
    canon_items = canon_doc.get("items", [])
    canon_by_rid = {c["region_id"]: c for c in canon_items}
    print(f"[1/5] detection: {len(blocks)} boxes, canon: {len(canon_items)} items")

    # 2. 在整页原图上画框+编号
    raw_img = Image.open(src_img)
    boxed_img = draw_boxes_on_page(raw_img, blocks)
    bbox_by_rid = {b["region_id"]: b["bbox"] for b in blocks}
    crop_names = [b["region_id"] for b in blocks]
    print(f"[2/5] drew {len(blocks)} boxes on full page")

    # 3. 调 VLM 看整页带框图
    api_key = get_vlm_api_key()
    print(f"[3/5] calling VLM ({VLM_MODEL}) on full page...")
    styles_raw, raw_vlm, elapsed = classify_fonts_full_page(boxed_img, len(blocks), api_key)
    print(f"      done in {elapsed:.1f}s")

    # 4. 把 VLM 的自由描述映射到字体
    styles: dict[str, str] = {}
    font_meta: dict[str, tuple[Path, int, str]] = {}
    for i, rid in enumerate(crop_names):
        desc = styles_raw.get(i + 1, "")
        font_path, stroke, label = map_style_to_font(desc)
        styles[rid] = label
        font_meta[rid] = (font_path, stroke, label)
        print(f"        {rid} (box {i+1}): VLM说=\"{desc}\" -> {label} ({font_path.name})")

    # 5. 复用主线 typeset 字号逻辑渲染
    clean_path = work_dir / "clean" / f"{page_key}_clean.png"
    img = Image.open(clean_path).convert("RGB")
    img_long_side = max(img.size)

    item_contexts = []
    for rid in crop_names:
        text = trans.get(rid)
        if not text:
            continue
        bbox = bbox_by_rid.get(rid)
        if not bbox:
            continue
        font_path, stroke, label = font_meta[rid]

        canon_item = canon_by_rid.get(rid, {})
        src_text = canon_item.get("baberu_text") or canon_item.get("text") or text
        src_base_size, _, _ = fit_font_size(src_text, Path(font_path), bbox)

        src_len = max(1, len(src_text.strip()))
        dst_len = len(text.strip())
        length_increase = max(0.0, (dst_len - src_len) / src_len)
        scale = max(0.6, min(1.0, 1.0 / (1.0 + length_increase * 0.5)))
        min_font_size = max(12, img_long_side / 200)
        target_size = max(min_font_size, src_base_size * scale)

        item_contexts.append({
            "rid": rid, "text": text, "font_path": str(font_path),
            "stroke": stroke, "bbox": bbox, "target_size": target_size,
        })

    rendered = []
    for ctx in item_contexts:
        meta = render_item(img, ctx["text"], ctx["font_path"], ctx["bbox"],
                          stroke=ctx["stroke"], base_size=ctx["target_size"])
        rendered.append({
            "rid": ctx["rid"],
            "vlm_desc": styles_raw.get(crop_names.index(ctx["rid"]) + 1, ""),
            "style": styles[ctx["rid"]],
            "font": Path(ctx["font_path"]).name,
            "font_size": meta["font_size"],
        })

    out_dir = ROOT / "workspace" / args.work_id / "vlm_font_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    img.save(out_dir / f"{page_key}_vlm_font.png")
    write_json(out_dir / f"{page_key}_vlm_font.json", {
        "work_id": args.work_id, "page": page_key,
        "vlm_elapsed": round(elapsed, 1),
        "vlm_raw": raw_vlm,
        "styles": styles, "rendered": rendered,
    })
    print(f"[5/5] saved: {out_dir / f'{page_key}_vlm_font.png'}")


if __name__ == "__main__":
    main()
