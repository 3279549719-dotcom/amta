"""实验探针：VLM 看 crop 判断字体风格 → 用风格标签驱动 typeset 选字体。

流程：
1. 读 detection.json 拿 bbox
2. 从原图裁 crops
3. 拼 contact sheet 调 VLM，让它对每个 crop 输出字体视觉风格标签
4. 读 translation，按标签选字体，重新渲染到 clean 图上
5. 保存新图 + VLM 决策记录

用法：
    uv run python scripts/probes/probe_vlm_font_style.py --work-id touhou-p17-20-e2e --page 14
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

from PIL import Image

from amta.backends.vlm_verify import make_contact_sheet
from amta.common.config import get_vlm_api_key
from amta.common.paths import ROOT, read_json, write_json
from amta.typeset.typeset_render import render_item

# 字体风格标签 → (字体文件, 描边宽度)
# 实验阶段先用现有系统字体，重点验证 VLM 分类准不准
STYLE_FONT_MAP = {
    "rounded_gothic":   ("msyh.ttc",   0),     # 圆润黑体（普通对白）
    "bold_gothic":      ("msyhbd.ttc", 0),     # 粗黑体（怒吼/大喊）
    "mincho":           ("simsun.ttc", 0),     # 明朝/宋体（旁白/解说）
    "kaisho":           ("simkai.ttf", 2.5),   # 楷体（内心独白/压脸）
    "handwritten":      ("FZSTK.TTF", 2.5),    # 手写体（拟声词/便签）
    "printed_sign":     ("msyhbd.ttc", 0),     # 印刷招牌（标题/告示）
}
DEFAULT_STYLE = "rounded_gothic"
FONT_DIR = Path("C:/Windows/Fonts")

VLM_MODEL = "deepseek-v4-flash-vision-exp"
VLM_BASE_URL = "https://api.deepseek.com/chat/completions"


def classify_font_styles(crops: list[Image.Image], crop_names: list[str],
                        api_key: str) -> dict[str, str]:
    """调 VLM 对每个 crop 判断字体视觉风格，返回 {crop_name: style_tag}。"""
    sheet = make_contact_sheet(crops, cols=3, max_cell_h=400)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    n = len(crops)
    prompt = (
        f"这是一页漫画的 {n} 个文字区域截图，每个左上角有蓝色数字编号（1~{n}）。\n"
        "请按编号逐个判断该区域文字的**视觉字体风格**，只看字形本身的外观，不猜剧情。\n"
        "每个编号从以下 6 个标签中选一个：\n"
        "- rounded_gothic: 圆润黑体，常见于对话气泡（笔画均匀、无衬线、圆润）\n"
        "- bold_gothic: 粗黑体，笔画厚重，常见于怒吼/大喊/强调\n"
        "- mincho: 明朝/宋体，有衬线、横细竖粗，常见于旁白/解说/叙述\n"
        "- kaisho: 楷体/手写正楷，有笔锋，常见于内心独白/压脸字\n"
        "- handwritten: 潦草手写体/书法体，常见于拟声词/便签/注释\n"
        "- printed_sign: 印刷招牌/标题字，方正锐利，常见于告示/技能名/章节标题\n"
        "\n输出严格 JSON：{\"1\": \"标签\", \"2\": \"标签\", ...}，不要输出任何其他内容。"
    )

    payload = {
        "model": VLM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
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

    # 解析 JSON
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)

    result: dict[str, str] = {}
    for i, name in enumerate(crop_names):
        tag = str(data.get(str(i + 1), DEFAULT_STYLE)).strip()
        if tag not in STYLE_FONT_MAP:
            tag = DEFAULT_STYLE
        result[name] = tag
    return result, raw, elapsed


def resolve_style_font(style: str) -> tuple[Path, int]:
    fname, stroke = STYLE_FONT_MAP.get(style, STYLE_FONT_MAP[DEFAULT_STYLE])
    p = FONT_DIR / fname
    if not p.exists():
        # 降级到雅黑
        p = FONT_DIR / "msyh.ttc"
        stroke = 0
    return p, stroke


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--src-dir", default=r"D:\我的汉化\汉化作品\东方\单翼停留之地")
    args = ap.parse_args()

    work_dir = ROOT / "workspace" / args.work_id / "artifacts"
    page_key = f"page_{args.page}"
    src_img = Path(args.src_dir) / f"{args.page}.jpg"
    if not src_img.exists():
        print(f"[ERROR] source image not found: {src_img}", file=sys.stderr)
        sys.exit(1)

    # 1. 读 detection
    det = read_json(work_dir / "detection" / f"{page_key}.json")
    blocks = det.get("blocks", [])
    print(f"[1/5] detection: {len(blocks)} boxes")

    # 2. 读原图，按 bbox 裁 crops
    raw_img = Image.open(src_img)
    crops: list[Image.Image] = []
    crop_names: list[str] = []
    for b in blocks:
        rid = b["region_id"]
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        pad = 8
        x1 = max(0, x1 - pad); y1 = max(0, y1 - pad)
        x2 = min(raw_img.width, x2 + pad); y2 = min(raw_img.height, y2 + pad)
        crop = raw_img.crop((x1, y1, x2, y2))
        crops.append(crop)
        crop_names.append(rid)
    print(f"[2/5] cropped {len(crops)} regions from {src_img.name}")

    # 3. 调 VLM
    api_key = get_vlm_api_key()
    if not api_key:
        print("[ERROR] no VLM_API_KEY / CHAT_API_KEY", file=sys.stderr)
        sys.exit(1)
    print(f"[3/5] calling VLM ({VLM_MODEL})...")
    styles, raw_vlm, elapsed = classify_font_styles(crops, crop_names, api_key)
    print(f"      done in {elapsed:.1f}s")
    for rid in crop_names:
        print(f"        {rid}: {styles[rid]}")

    # 4. 读 translation + clean 图，按风格重新渲染
    trans_doc = read_json(work_dir / "translation" / f"{page_key}.json")
    trans = trans_doc.get("translations", {})
    clean_path = work_dir / "clean" / f"{page_key}_clean.png"
    img = Image.open(clean_path).convert("RGB")

    # 建 bbox lookup
    bbox_by_rid = {b["region_id"]: b["bbox"] for b in blocks}

    rendered = []
    for rid in crop_names:
        text = trans.get(rid)
        if not text:
            continue
        bbox = bbox_by_rid.get(rid)
        if not bbox:
            continue
        style = styles.get(rid, DEFAULT_STYLE)
        font_path, stroke = resolve_style_font(style)
        meta = render_item(img, text, str(font_path), bbox, stroke=stroke)
        rendered.append({
            "rid": rid, "style": style,
            "font": font_path.name, "font_size": meta["font_size"],
        })

    # 5. 保存
    out_dir = ROOT / "workspace" / args.work_id / "vlm_font_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_img = out_dir / f"{page_key}_vlm_font.png"
    img.save(out_img)

    out_json = out_dir / f"{page_key}_vlm_font.json"
    write_json(out_json, {
        "work_id": args.work_id, "page": page_key,
        "vlm_model": VLM_MODEL, "vlm_elapsed": round(elapsed, 1),
        "vlm_raw": raw_vlm,
        "styles": styles,
        "rendered": rendered,
        "output_image": str(out_img),
    })
    print(f"[5/5] saved: {out_img}")
    print(f"      meta:  {out_json}")


if __name__ == "__main__":
    main()
