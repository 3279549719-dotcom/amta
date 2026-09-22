"""tests/stations/test_vlm_ocr.py"""
from pathlib import Path

from PIL import Image

from amta.stations.ocr_station import ocr_page


def _make_detection(tmp_path: Path, page_idx: int = 1) -> dict:
    """构造一个最小 detection artifact。"""
    img = Image.new("RGB", (100, 100), "white")
    raw_path = tmp_path / f"{page_idx}.jpg"
    img.save(raw_path)
    return {
        "page": page_idx,
        "blocks": [
            {"region_id": f"r{page_idx}_00", "bbox": [10, 10, 90, 40]},
            {"region_id": f"r{page_idx}_01", "bbox": [10, 50, 90, 90]},
        ],
    }


def _fake_vlm_layout(raw: Path, blocks: list[dict], cached: dict | None = None) -> dict:
    """Fake VLM 读取：返回固定排版观察结果。"""
    regions = []
    for b in blocks:
        regions.append({
            "region_id": b["region_id"],
            "text": "テスト文字",
            "source_lines": ["テスト文字"],
            "direction": "horizontal",
            "align": "center",
            "font": "sans",
            "background": "paper",
            "font_size_ratio": 0.04,
            "color": "#000000",
            "stroke_color": None,
            "stroke_ratio": 0.0,
            "bbox": b["bbox"],
        })
    return {"regions": regions, "image_size": [100, 100],
            "request_sha256": "fake", "model": "fake", "endpoint": "fake"}


def test_ocr_vlm_paratext_engine(tmp_path: Path):
    """engine='vlm-paratext' 时应调用 VLM 视觉读取，输出 canon 含 layout_observation。"""
    det = _make_detection(tmp_path)
    raw_path = tmp_path / "1.jpg"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    doc = ocr_page(
        work_id="test", det=det, raw_page=raw_path,
        artifacts_dir=artifacts_dir, page_idx=1,
        engine="vlm-paratext",
        vlm_layout_fn=_fake_vlm_layout,
    )

    assert doc["ocr_engine"] == "vlm-paratext"
    assert doc["n_regions"] == 2
    assert "layout_observation" in doc
    assert doc["items"][0]["text"] == "テスト文字"
    assert doc["items"][0]["ocr_engine"] == "vlm-paratext"
