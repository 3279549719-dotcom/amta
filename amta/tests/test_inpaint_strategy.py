import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.inpaint.inpaint_strategy import plan_inpaint


def test_bubble_fills_white_and_sfx_inpaints():
    regions = [
        {"region_id": "page_0_u00", "category": "dialogue_bubble",
         "bbox": [10, 10, 90, 40]},
        {"region_id": "page_0_u01", "category": "sfx",
         "bbox": [110, 50, 190, 80]},
        {"region_id": "page_0_u02", "category": "overlay_text",
         "bbox": [210, 90, 290, 120]},
    ]
    plan = plan_inpaint(regions, image_meta={"width": 400, "height": 600})
    by_id = {p["region_id"]: p for p in plan}
    assert by_id["page_0_u00"]["action"] == "inpaint"
    assert by_id["page_0_u01"]["action"] == "inpaint"
    assert by_id["page_0_u02"]["action"] == "inpaint"


def test_out_of_bounds_bbox_skipped():
    regions = [{"region_id": "r0", "category": "dialogue_bubble",
                "bbox": [390, 0, 500, 50]}]  # x2 越界
    plan = plan_inpaint(regions, image_meta={"width": 400, "height": 600})
    assert plan[0]["action"] == "skip"
    assert "reason" in plan[0]


def test_missing_category_defaults_bubble():
    regions = [{"region_id": "r0", "bbox": [0, 0, 10, 10]}]  # 无 category(兼容旧产物)
    plan = plan_inpaint(regions, image_meta={"width": 100, "height": 100})
    assert plan[0]["action"] == "inpaint"


def test_empty_regions():
    assert plan_inpaint([]) == []


def test_missing_bbox_skipped():
    regions = [{"region_id": "r0", "category": "sfx"}]  # 无 bbox
    plan = plan_inpaint(regions, image_meta={"width": 100, "height": 100})
    assert plan[0]["action"] == "skip"
    assert plan[0]["reason"] == "no bbox"
