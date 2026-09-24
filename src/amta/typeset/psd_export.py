"""PSD 导出 — 从 clean 底图 + typeset 排版数据生成分层 PSD（可编辑文字层）。

依赖 PhotoshopAPI（C++ 库 + Python 绑定），生成的 PSD 在 Photoshop 中打开后：
- 底图层：干净底图（inpaint 产物，文字已抹除）
- 每个文字区域一个可编辑文字层：双击可直接改文字、字体、字号、颜色
- 图层名 = "region_id: 文字前30字"，方便定位

文字层属性映射：
- 译文内容 → 文字层 text（用 typeset 的断行结果，\n 连接）
- anchor_pos → 文字层位置（中心点）
- font_family → 字体名（文件名→PS字体名映射表）
- font_size → 字号
- rendered_color → 填充色
- rendered_stroke → 描边宽度（>0 时开启描边，白色描边）
- layout_direction=vertical → 竖排
- bbox → 文本框大小
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from amta.common.paths import read_json

# 字体文件名 → Photoshop 字体名映射
# PS 的 set_style_normal_font_by_name 接受字体家族名；找不到时 PS 自动用默认字体替代。
_FONT_NAME_MAP: dict[str, str] = {
    "msyh.ttc": "Microsoft YaHei",
    "msyhbd.ttc": "Microsoft YaHei",  # 粗体用 faux bold 或同家族
    "simkai.ttf": "KaiTi",
    "simhei.ttf": "SimHei",
    "FZSTK.TTF": "FZShuTi",
    "simsun.ttc": "SimSun",
}


def _hex_to_rgba01(hex_color: str) -> list[float]:
    """#RRGGBB → [r, g, b, 1.0]，值范围 0-1。"""
    hex_color = hex_color.lstrip("#")
    return [
        int(hex_color[0:2], 16) / 255.0,
        int(hex_color[2:4], 16) / 255.0,
        int(hex_color[4:6], 16) / 255.0,
        1.0,
    ]


def _resolve_ps_font_name(font_family: str) -> str:
    """字体文件名 → PS 字体名；未映射的返回文件名（去掉扩展名）。"""
    if font_family in _FONT_NAME_MAP:
        return _FONT_NAME_MAP[font_family]
    return Path(font_family).stem


def _pil_to_numpy_chw(img: Image.Image) -> np.ndarray:
    """PIL RGB Image → numpy (3, H, W) uint8，PhotoshopAPI ImageLayer 期望的格式。"""
    arr = np.array(img.convert("RGB"), dtype=np.uint8)  # (H, W, 3)
    return np.transpose(arr, (2, 0, 1))  # (3, H, W)


def export_page_psd(
    artifacts_dir: Path,
    page_key: str,
    output_path: Path,
) -> Path:
    """为单页生成 PSD 文件（可编辑文字层）。

    artifacts_dir: 工作区的 artifacts 目录（包含 clean/, typeset/, translation/, inpaint/）
    page_key: 页面键，如 "page_5"
    output_path: 输出 PSD 路径

    返回 output_path。
    """
    import photoshopapi as psapi

    # 1. 读取干净底图
    inpaint_doc = read_json(artifacts_dir / "inpaint" / f"{page_key}.json")
    clean_rel = inpaint_doc.get("clean_image", "")
    if not clean_rel:
        raise ValueError(f"inpaint/{page_key}.json 缺少 clean_image 字段")
    clean_path = artifacts_dir / clean_rel
    if not clean_path.exists():
        raise FileNotFoundError(f"干净底图不存在: {clean_path}")
    clean_img = Image.open(clean_path).convert("RGB")
    width, height = clean_img.size

    # 2. 读取翻译文字（region_id -> 译文）
    trans_doc = read_json(artifacts_dir / "translation" / f"{page_key}.json")
    translations: dict[str, str] = trans_doc.get("translations", {})

    # 3. 读取排版数据
    typeset_doc = read_json(artifacts_dir / "typeset" / f"{page_key}.json")
    items = typeset_doc.get("rendered_items", [])

    # 4. 创建 PSD 文档
    doc = psapi.LayeredFile_8bit(psapi.enum.ColorMode.rgb, width, height)

    # 5. 添加底图层
    bg_data = _pil_to_numpy_chw(clean_img)
    page_num = page_key.replace("page_", "")
    bg_layer = psapi.ImageLayer_8bit(bg_data, f"clean page {page_num}", width=width, height=height)
    doc.add_layer(bg_layer)

    # 6. 每个文字区域一个可编辑文字层
    for item in items:
        rid = item.get("region_id", "")
        text = translations.get(rid, "")
        if not text:
            continue

        # 图层名：region_id + 文字前30字
        layer_name = f"{rid}: {text[:30]}" if rid else f"text: {text[:30]}"

        # 文字内容：用 typeset 的断行结果（保持排版一致），没有则用原文
        lines = item.get("lines") or [text]
        layer_text = "\n".join(lines)

        # 创建文字层
        tl = psapi.TextLayer_8bit(layer_name, layer_text)

        # 位置：anchor_pos 是中心点，set_position 也是中心点
        anchor = item.get("anchor_pos", [0, 0])
        tl.set_position(float(anchor[0]), float(anchor[1]))

        # 字号
        font_size = float(item.get("font_size", 24))
        tl.set_style_normal_font_size(font_size)

        # 字体
        ps_font = _resolve_ps_font_name(item.get("font_family", "msyh.ttc"))
        try:
            tl.set_style_normal_font_by_name(ps_font)
        except Exception:
            pass  # 字体找不到时 PS 自动用默认字体替代

        # 填充色
        fill_color = _hex_to_rgba01(item.get("rendered_color", "#000000"))
        tl.set_style_normal_fill_color(fill_color)

        # 竖排
        if item.get("layout_direction") == "vertical":
            try:
                tl.set_orientation(psapi.enum.WritingDirection.Vertical)
            except Exception:
                pass

        # 描边（>0 时开启，白色描边）
        stroke_width = float(item.get("rendered_stroke", 0))
        if stroke_width > 0:
            try:
                tl.set_style_normal_stroke_flag(True)
                tl.set_style_normal_stroke_color([1.0, 1.0, 1.0, 1.0])  # 白色描边
                tl.set_style_normal_outline_width(stroke_width)
            except Exception:
                pass

        # 文本框大小：用 bbox 的宽高
        bbox = item.get("bbox")
        if bbox and len(bbox) == 4:
            box_w = float(bbox[2] - bbox[0])
            box_h = float(bbox[3] - bbox[1])
            try:
                tl.set_box_size(box_w, box_h)
            except Exception:
                pass

        doc.add_layer(tl)

    # 7. 写入 PSD
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.write(output_path)
    return output_path
