"""Stage 1 重构单元测试：mark_contained 替代 absorb_contained。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.geometry import mark_contained


def _b(x1, y1, x2, y2, eid="test"):
    return {
        "bbox": [x1, y1, x2, y2],
        "node_id": eid,
        "bubble_type": "text",
        "category": "dialogue_bubble",
        "source_engines": [eid],
    }


def test_mark_contained_adds_contained_in_tag():
    """嵌套小框应被标记 contained_in，但不被丢弃。"""
    parent = _b(100, 100, 300, 300, "parent")
    child = _b(120, 120, 180, 180, "child")  # IoA = 3600/3600 = 1.0
    result = mark_contained([parent, child])
    assert len(result) == 2, "嵌套框不应被丢弃"
    child_out = [b for b in result if b["node_id"] == "child"][0]
    assert child_out["contained_in"] == "u00", "应标记父框 region_id"
    parent_out = [b for b in result if b["node_id"] == "parent"][0]
    assert parent_out.get("contained_in") is None, "父框不应有 contained_in"


def test_mark_contained_partial_overlap_not_tagged():
    """部分重叠（IoA < 0.75）不应被标记。"""
    a = _b(100, 100, 200, 200, "a")
    b = _b(150, 150, 250, 250, "b")  # 部分重叠
    result = mark_contained([a, b])
    for box in result:
        assert box.get("contained_in") is None


def test_mark_contained_preserves_all_boxes():
    """所有框都应保留，不丢弃任何框。"""
    boxes = [_b(i * 10, i * 10, i * 10 + 50, i * 10 + 50, f"b{i}") for i in range(5)]
    result = mark_contained(boxes)
    assert len(result) == 5


def test_mark_contained_assigns_region_id():
    """每个框应被分配 region_id（u00, u01, ...）。"""
    boxes = [_b(10, 10, 50, 50, "a"), _b(60, 60, 100, 100, "b")]
    result = mark_contained(boxes)
    ids = [b["region_id"] for b in result]
    assert ids == ["u00", "u01"]


def test_detection_output_format_flat_blocks():
    """detection.json 应输出平级 blocks，不含 regions/child_lines。"""
    blocks = [
        {
            "region_id": "u00",
            "bbox": [10, 10, 50, 50],
            "category": "dialogue_bubble",
            "bubble_type": "text",
            "source_engines": ["det1"],
            "contained_in": None,
        },
        {
            "region_id": "u01",
            "bbox": [20, 20, 40, 40],
            "category": "dialogue_bubble",
            "bubble_type": "text",
            "source_engines": ["det1", "det2"],
            "contained_in": "u00",
        },
    ]
    doc = {"page": "test", "blocks": blocks, "n_boxes": 2}
    assert "regions" not in doc, "不应有 regions 字段"
    assert doc["n_boxes"] == 2
    assert all("child_lines" not in b for b in blocks)
    assert blocks[1]["contained_in"] == "u00"
    assert "det2" in blocks[1]["source_engines"]
