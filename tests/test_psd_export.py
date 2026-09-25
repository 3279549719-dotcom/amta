"""PSD 导出功能测试 — 验证可编辑文字层 PSD 生成。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pytest
from PIL import Image

from amta.typeset.psd_export import (
    _hex_to_rgba01,
    _pil_to_numpy_chw,
    _resolve_ps_font_name,
    export_page_psd,
)

pytest.importorskip("photoshopapi", reason="PhotoshopAPI not installed")


def _make_artifacts(tmp_path: Path) -> Path:
    """构建最小 artifacts 目录。"""
    art = tmp_path / "artifacts"
    for sub in ["inpaint", "clean", "translation", "typeset"]:
        (art / sub).mkdir(parents=True)

    Image.new("RGB", (200, 150), (240, 240, 240)).save(art / "clean" / "page_1_clean.png")
    (art / "inpaint" / "page_1.json").write_text(
        json.dumps({"page": "page_1", "clean_image": "clean/page_1_clean.png"}), encoding="utf-8")
    (art / "translation" / "page_1.json").write_text(
        json.dumps({"page": "page_1", "translations": {"r00": "你好世界", "r01": "竖排文字"}}),
        encoding="utf-8")
    (art / "typeset" / "page_1.json").write_text(json.dumps({
        "page": "page_1",
        "rendered_items": [
            {"region_id": "r00", "font_family": "msyh.ttc", "font_size": 20,
             "layout_direction": "horizontal", "lines": ["你好世界"],
             "anchor_pos": [100, 40], "bbox": [50, 20, 150, 60],
             "rendered_color": "#000000", "rendered_stroke": 0},
            {"region_id": "r01", "font_family": "msyh.ttc", "font_size": 16,
             "layout_direction": "vertical", "lines": ["竖排", "文字"],
             "anchor_pos": [100, 100], "bbox": [80, 80, 120, 130],
             "rendered_color": "#FF0000", "rendered_stroke": 2},
        ],
    }), encoding="utf-8")
    return art


def test_export_page_psd_creates_file(tmp_path):
    """端到端：生成的 PSD 文件存在且非空。"""
    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    result = export_page_psd(art, "page_1", out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_page_psd_smaller_than_pixel_layers(tmp_path):
    """可编辑文字层 PSD 应远小于像素图层 PSD（文字是矢量的）。"""
    art = _make_artifacts(tmp_path)
    out = tmp_path / "page_1.psd"
    export_page_psd(art, "page_1", out)
    # 200x150 底图 + 2个矢量文字层，应该远小于 100KB
    size_kb = out.stat().st_size / 1024
    assert size_kb < 200, f"PSD too large ({size_kb:.0f}KB), text layers may not be vector"


def test_export_page_psd_missing_clean_raises(tmp_path):
    """inpaint.json 缺少 clean_image 时应抛错。"""
    art = tmp_path / "artifacts"
    for sub in ["inpaint", "translation", "typeset"]:
        (art / sub).mkdir(parents=True)
    (art / "inpaint" / "page_1.json").write_text(json.dumps({"page": "page_1"}), encoding="utf-8")
    (art / "translation" / "page_1.json").write_text(json.dumps({"translations": {}}), encoding="utf-8")
    (art / "typeset" / "page_1.json").write_text(json.dumps({"rendered_items": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="clean_image"):
        export_page_psd(art, "page_1", tmp_path / "page_1.psd")


def test_hex_to_rgba01():
    """颜色转换：#RRGGBB → [r,g,b,1.0]。"""
    assert _hex_to_rgba01("#000000") == [0.0, 0.0, 0.0, 1.0]
    assert _hex_to_rgba01("#FFFFFF") == [1.0, 1.0, 1.0, 1.0]
    result = _hex_to_rgba01("#FF0000")
    assert result[0] == pytest.approx(1.0)
    assert result[1] == pytest.approx(0.0)
    assert result[2] == pytest.approx(0.0)


def test_resolve_ps_font_name():
    """字体文件名 → PS 字体名映射。"""
    assert _resolve_ps_font_name("msyh.ttc") == "Microsoft YaHei"
    assert _resolve_ps_font_name("simkai.ttf") == "KaiTi"
    # 未映射的返回去掉扩展名的名字
    assert _resolve_ps_font_name("unknown.ttf") == "unknown"


def test_pil_to_numpy_chw():
    """PIL Image → numpy RGBA (4,H,W) 格式。"""
    img = Image.new("RGB", (10, 20), (255, 0, 0))
    arr = _pil_to_numpy_chw(img)
    assert arr.shape == (4, 20, 10)
    assert arr.dtype == np.uint8
    # 红色和 alpha 通道全255，绿蓝全0
    assert arr[0].min() == 255
    assert arr[1].max() == 0
    assert arr[2].max() == 0
    assert arr[3].min() == 255
