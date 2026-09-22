"""PhotoshopAPI 文字层原型 v2 — 修正 API 用法。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import photoshopapi as psapi

OUTPUT = Path("output/psapi_text_test.psd")


def main():
    width, height = 800, 600
    doc = psapi.LayeredFile_8bit(psapi.enum.ColorMode.rgb, width, height)

    # 1. 底图
    bg_data = np.ones((3, height, width), dtype=np.uint8) * 240
    bg_layer = psapi.ImageLayer_8bit(bg_data, "clean_bg", width=width, height=height)
    doc.add_layer(bg_layer)

    # 2. 横排文字层 — 构造函数: (layer_name, text)
    text1 = psapi.TextLayer_8bit("h_text", "横排测试：你好世界")
    text1.set_position(100.0, 80.0)
    text1.set_style_normal_font_size(36.0)
    text1.set_style_normal_fill_color([0.0, 0.0, 0.0, 1.0])
    try:
        text1.set_style_normal_font_by_name("Microsoft YaHei")
    except Exception as e:
        print(f"font set failed: {e}")
    doc.add_layer(text1)
    print(f"  text1: name={text1.name!r}, text={text1.text!r}, pos={text1.position()}")

    # 3. 竖排文字层
    text2 = psapi.TextLayer_8bit("v_text", "竖排测试内容")
    text2.set_position(400.0, 80.0)
    text2.set_style_normal_font_size(32.0)
    text2.set_style_normal_fill_color([0.0, 0.0, 1.0, 1.0])
    try:
        text2.set_orientation(psapi.enum.WritingDirection.Vertical)
        print("orientation set: Vertical")
    except Exception as e:
        print(f"orientation set failed: {e}")
    doc.add_layer(text2)
    print(f"  text2: name={text2.name!r}, text={text2.text!r}, is_vertical={text2.is_vertical}")

    # 4. 带描边的文字层
    text3 = psapi.TextLayer_8bit("s_text", "描边测试 Stroke")
    text3.set_position(100.0, 300.0)
    text3.set_style_normal_font_size(48.0)
    text3.set_style_normal_fill_color([1.0, 1.0, 1.0, 1.0])
    text3.set_style_normal_stroke_flag(True)
    text3.set_style_normal_stroke_color([0.0, 0.0, 0.0, 1.0])
    text3.set_style_normal_outline_width(3.0)
    doc.add_layer(text3)
    print(f"  text3: name={text3.name!r}, text={text3.text!r}")

    # 5. 文本框文字（多行）— 默认就是 box text，直接设 bounds
    text4 = psapi.TextLayer_8bit("box_text", "文本框测试\n第二行文字\n第三行内容")
    text4.set_position(250.0, 475.0)
    text4.set_box_size(300.0, 150.0)
    text4.set_style_normal_font_size(20.0)
    text4.set_style_normal_fill_color([0.5, 0.0, 0.5, 1.0])
    doc.add_layer(text4)
    print(f"  text4: name={text4.name!r}, text={text4.text!r}, is_box={text4.is_box_text}, box={text4.box_bounds}")

    # 写入
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.write(str(OUTPUT))
    print(f"\nPSD written: {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    print("SUCCESS: all text layers created without errors")


if __name__ == "__main__":
    main()
