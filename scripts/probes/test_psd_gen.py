"""测试 PSD 生成器 — 用单翼停留之地第5页的真实数据生成 PSD 并验证。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image, ImageDraw, ImageFont

from amta.common.paths import read_json
from amta.typeset.psd_writer import write_psd

WORKSPACE = Path("workspace/touhou-single-wing/artifacts")
PAGE = "page_5"
OUTPUT = Path("output/test_psd_page5.psd")


def render_text_layer(item: dict, canvas_size: tuple[int, int]) -> Image.Image:
    """在透明画布上渲染一个文字项，返回 RGBA 图像。"""
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    text = item.get("text", "")
    if not text:
        return layer

    font_family = item.get("font_family", "msyh.ttc")
    font_size = int(item.get("font_size", 24))
    color_hex = item.get("rendered_color", "#000000")
    stroke = int(item.get("rendered_stroke", 0))
    lines = item.get("lines", [text])
    anchor = item.get("anchor_pos", [0, 0])
    direction = item.get("layout_direction", "horizontal")

    # 解析颜色
    color = tuple(int(color_hex[i:i+2], 16) for i in (1, 3, 5)) + (255,)

    # 字体路径
    font_path = Path("C:/Windows/Fonts") / font_family
    if not font_path.exists():
        # fallback 到项目字体目录
        font_path = Path("fonts") / font_family
    try:
        font = ImageFont.truetype(str(font_path), font_size)
    except Exception:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(layer)
    cx, cy = int(anchor[0]), int(anchor[1])

    if direction == "vertical":
        # 竖排：多列从右到左
        col_w = font.getlength("字")
        ascent, descent = font.getmetrics()
        lh = ascent + descent
        n_cols = len(lines)
        total_w = n_cols * col_w
        x_start = cx + total_w / 2 - col_w
        max_col_h = max(len(c) for c in lines) * lh
        y_base = cy - max_col_h // 2
        for col_idx, col_text in enumerate(lines):
            x = x_start - col_idx * col_w
            y = y_base
            for ch in col_text:
                draw.text((x, y), ch, font=font, fill=color,
                          stroke_width=stroke, stroke_fill=(255, 255, 255, 255))
                y += lh
    else:
        # 横排：多行居中
        ascent, descent = font.getmetrics()
        lh = ascent + descent
        total_h = len(lines) * lh
        y = cy - total_h // 2
        for line in lines:
            w = font.getlength(line)
            x = cx - w / 2
            draw.text((x, y), line, font=font, fill=color,
                      stroke_width=stroke, stroke_fill=(255, 255, 255, 255))
            y += lh

    return layer


def main():
    # 读取干净底图
    inpaint_doc = read_json(WORKSPACE / "inpaint" / f"{PAGE}.json")
    clean_rel = inpaint_doc.get("clean_image", "")
    clean_path = WORKSPACE / clean_rel
    print(f"clean image: {clean_path} (exists={clean_path.exists()})")

    clean_img = Image.open(clean_path).convert("RGBA")
    canvas_size = clean_img.size
    print(f"canvas size: {canvas_size}")

    # 读取 typeset 数据
    typeset_doc = read_json(WORKSPACE / "typeset" / f"{PAGE}.json")
    items = typeset_doc.get("rendered_items", [])
    print(f"rendered items: {len(items)}")

    # 构建图层列表：底图 + 每个文字区域
    layers: list[tuple[str, Image.Image, int, int]] = []
    layers.append(("clean_bg", clean_img, 0, 0))

    for i, item in enumerate(items):
        rid = item.get("region_id", f"r{i}")
        text = item.get("text", "")
        # 图层名：region_id + 文字前20字
        layer_name = f"{rid}: {text[:20]}"
        text_layer = render_text_layer(item, canvas_size)
        layers.append((layer_name, text_layer, 0, 0))
        print(f"  layer {i+1}: {layer_name} (font_size={item.get('font_size')})")

    # 生成 PSD
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    write_psd(layers, canvas_size[0], canvas_size[1], OUTPUT)
    print(f"\nPSD written: {OUTPUT}")
    print(f"file size: {OUTPUT.stat().st_size:,} bytes")

    # 验证：用 PIL 打开
    try:
        verify = Image.open(OUTPUT)
        print(f"PIL verify: size={verify.size}, mode={verify.mode}, format={verify.format}")
        print("SUCCESS: PSD is valid and readable by PIL")
    except Exception as e:
        print(f"PIL verify FAILED: {e}")


if __name__ == "__main__":
    main()
