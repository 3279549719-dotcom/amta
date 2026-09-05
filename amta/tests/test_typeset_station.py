import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta import typeset_station as station


def _fixture(tmp_path):
    img = Image.new("RGB", (400, 300), "white")
    clean = tmp_path / "clean.png"
    img.save(clean)
    canon = [
        {"region_id": "page_0_u00", "text": "你好世界", "page": 0,
         "category": "dialogue_bubble"},
        {"region_id": "page_0_u01", "text": "月都", "page": 0,
         "category": "overlay_text"},
    ]
    trans = {"translations": {"page_0_u00": "你好世界", "page_0_u01": "月都"}}
    det = {"work_id": "w", "page": "page_1",
           "blocks": [
               {"region_id": "page_0_u00", "bbox": [50, 50, 250, 150], "category": "dialogue_bubble"},
               {"region_id": "page_0_u01", "bbox": [300, 30, 340, 270], "category": "overlay_text"},
           ]}
    canon_path = tmp_path / "canon.json"
    trans_path = tmp_path / "translation.json"
    det_path = tmp_path / "det.json"
    canon_path.write_text(json.dumps(canon), encoding="utf-8")
    trans_path.write_text(json.dumps(trans), encoding="utf-8")
    det_path.write_text(json.dumps(det), encoding="utf-8")
    return clean, canon_path, trans_path, det_path


def test_station_renders_all_and_checks_coverage(tmp_path):
    clean, canon_p, trans_p, det_p = _fixture(tmp_path)
    out = tmp_path / "page_0_typeset.json"
    final = tmp_path / "final.png"
    station.run("w", canon_p, trans_p, det_p, clean, out, final)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["rendered"] == 2
    assert data["checks"]["translated"] == 2
    assert data["checks"]["coverage_complete"] is True
    assert len(data["rendered_items"]) == 2
    assert len(data["layout"]) == 2
    assert data["final_image"] == "final/page_1_final.png"
    overlay = [r for r in data["rendered_items"] if r["region_id"] == "page_0_u01"][0]
    # ADR-031: 方向由双方向计算选最优，不再强制overlay_text竖排
    assert overlay["layout_direction"] in ("horizontal", "vertical")
    assert overlay["font_size"] >= 25
    assert final.exists()
    final_img = Image.open(final)
    inked = any(final_img.getpixel((x, y)) != (255, 255, 255)
                for x in range(0, 400, 10) for y in range(0, 300, 10))
    assert inked


def test_station_skips_missing_bbox(tmp_path):
    clean, canon_p, trans_p, det_p = _fixture(tmp_path)
    det = json.loads(det_p.read_text(encoding="utf-8"))
    det["blocks"][0]["region_id"] = "ghost"
    det_p.write_text(json.dumps(det), encoding="utf-8")
    out = tmp_path / "p.json"
    station.run("w", canon_p, trans_p, det_p, clean, out, tmp_path / "f.png")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["skipped_no_bbox"] == ["page_0_u00"]
    assert data["checks"]["coverage_complete"] is False
