"""inpaint_station 单元测试 — 验证本地 lama-manga inpaint 工位逻辑。

测试 amta.inpaint_station.run()，mock LocalLamaInpainter 避免加载真实模型。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw


def test_station_fill_white_and_inpaint(tmp_path, monkeypatch):
    """涂白 + inpaint 双路径：bubble 涂白，sfx 走本地 inpaint。"""
    import amta.inpaint_station as station

    raw = tmp_path / "1.jpg"
    img = Image.new("RGB", (200, 100), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 90, 40], fill="black")     # bubble → 涂白
    d.rectangle([110, 50, 190, 80], fill="black")   # sfx → inpaint
    img.save(raw)

    det = {"work_id": "w", "page": "page_1",
           "image_meta": {"width": 200, "height": 100, "channels": 3},
           "blocks": [
               {"region_id": "r00", "bubble_type": "text_bubble",
                "bbox": [10, 10, 90, 40]},
               {"region_id": "r01", "bubble_type": "text_free",
                "bbox": [110, 50, 190, 80]},
           ]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")

    # Mock LocalLamaInpainter：返回整页白色图（模拟已擦除）
    class FakeInpainter:
        calls = []

        def inpaint(self, image, mask):
            self.calls.append(("inpaint", image.size, mask.size))
            return Image.new("RGB", image.size, "white")

    fake = FakeInpainter()
    monkeypatch.setattr(station, "_get_inpainter", lambda: fake)

    out = tmp_path / "page_1_inpaint.json"
    clean_dir = tmp_path / "clean"
    station.run("w", det_path, raw, out, clean_dir=clean_dir)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["checks"]["filled"] == 1
    assert data["checks"]["inpainted"] == 1
    assert data["checks"]["pixel_diff_ratio"] > 0
    assert data["clean_image"] == "clean/page_1_clean.png"
    clean = Image.open(clean_dir / "page_1_clean.png")
    assert clean.size == (200, 100)
    assert clean.getpixel((50, 25)) == (255, 255, 255)  # bubble 区域已涂白
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "inpaint"


def test_station_dry_run_no_execution(tmp_path):
    """dry_run 只规划不执行，不写 clean 图。"""
    import amta.inpaint_station as station

    raw = tmp_path / "1.jpg"
    Image.new("RGB", (100, 100), "white").save(raw)
    det = {"work_id": "w", "page": "page_1", "image_meta": {"width": 100, "height": 100},
           "blocks": [{"region_id": "r00", "bubble_type": "text_bubble",
                       "bbox": [0, 0, 10, 10]}]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")
    out = tmp_path / "p.json"
    station.run("w", det_path, raw, out, clean_dir=tmp_path / "clean", dry_run=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["filled"] == 1
    assert data["dry_run"] is True
    assert not (tmp_path / "clean" / "page_1_clean.png").exists()


def test_station_no_inpaint_boxes_only_fill_white(tmp_path, monkeypatch):
    """只有涂白框、没有 inpaint 框时，不调用 inpainter。"""
    import amta.inpaint_station as station

    raw = tmp_path / "1.jpg"
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle([10, 10, 50, 50], fill="black")
    img.save(raw)
    det = {"work_id": "w", "page": "page_1",
           "blocks": [{"region_id": "r00", "bubble_type": "text_bubble",
                       "bbox": [10, 10, 50, 50]}]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")
    monkeypatch.setattr(station, "_get_inpainter",
                        lambda: (_ for _ in ()).throw(AssertionError("inpainter should not be called")))

    out = tmp_path / "page_1_inpaint.json"
    station.run("w", det_path, raw, out, clean_dir=tmp_path / "clean")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["filled"] == 1
    assert data["checks"]["inpainted"] == 0


