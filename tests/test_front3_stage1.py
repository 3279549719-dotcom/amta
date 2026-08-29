"""Stage 1 重构单元测试：mark_contained 替代 absorb_contained + source_engines 引擎名溯源。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from amta.geometry import union_blocks
from amta.regions import mark_contained
from amta.runner import compact_blocks
from eval_stage1_robust import detection_path_for


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


# ── Bug 2: source_engines 应为引擎名（而非 node_id） ──────────────


def test_union_blocks_merges_source_engines_in_order():
    """重复命中（IoU>threshold）时把当前引擎名追加到已保留框，去重且顺序稳定。"""
    detections = {
        "pp-doclayout-v3": [{"node_id": "n1", "bbox": [0, 0, 10, 10], "source_engines": ["pp-doclayout-v3"]}],
        "comic-text-detector": [
            {"node_id": "n2", "bbox": [0, 0, 10, 10], "source_engines": ["comic-text-detector"]},  # 与 n1 重复
            {"node_id": "n3", "bbox": [100, 100, 110, 110], "source_engines": ["comic-text-detector"]},
        ],
    }
    out = union_blocks(detections)
    assert len(out) == 2
    assert out[0]["source_engines"] == ["pp-doclayout-v3", "comic-text-detector"], "重复框应追加引擎名且保持首检顺序"
    assert out[1]["source_engines"] == ["comic-text-detector"]


def test_union_blocks_source_engines_dedup():
    """同一引擎重复命中不应重复追加。"""
    detections = {
        "eng1": [{"node_id": "a", "bbox": [0, 0, 10, 10], "source_engines": ["eng1"]}],
        "eng2": [{"node_id": "b", "bbox": [0, 0, 10, 10], "source_engines": ["eng2"]}],
        "eng1b": [{"node_id": "c", "bbox": [0, 0, 10, 10], "source_engines": ["eng1b"]}],
    }
    out = union_blocks(detections)
    assert len(out) == 1
    assert out[0]["source_engines"] == ["eng1", "eng2", "eng1b"]


def test_union_blocks_without_source_engines_unchanged():
    """向后兼容：block 无 source_engines 字段时行为与旧版一致（不新增字段）。"""
    detections = {
        "eng1": [{"node_id": "a", "transform": {"x": 0, "y": 0, "w": 10, "h": 10}}],
        "eng2": [{"node_id": "b", "transform": {"x": 0, "y": 0, "w": 10, "h": 10}}],
    }
    out = union_blocks(detections)
    assert len(out) == 1
    assert out[0]["node_id"] == "a"
    assert "source_engines" not in out[0]


def test_compact_blocks_injects_source_engine():
    """compact 阶段把引擎名注入 block（source_engines 先置 [eng]）。"""
    blocks = [{"node_id": "n1", "bubble_type": "dialogue", "text": None,
               "transform": {"x": 0, "y": 0, "w": 10, "h": 10}}]
    out = compact_blocks(blocks, ("node_id", "bubble_type", "text"), source_engine="pp-doclayout-v3")
    assert out[0]["source_engines"] == ["pp-doclayout-v3"]
    assert out[0]["node_id"] == "n1"
    assert out[0]["bbox"] == [0.0, 0.0, 10.0, 10.0]


def test_compact_blocks_default_no_source_engine():
    """向后兼容：不传 source_engine 时输出与旧版完全一致。"""
    blocks = [{"node_id": "n1", "transform": {"x": 0, "y": 0, "w": 10, "h": 10}}]
    out = compact_blocks(blocks, ("node_id",))
    assert set(out[0]) == {"node_id", "bbox"}


def test_detect_flow_source_engines_are_engine_names():
    """模拟 01_detect 全流程（假数据）：source_engines 是引擎名列表，不是 node_id。"""
    per_engine = {
        "pp-doclayout-v3": [
            {"node_id": "det-n1", "bubble_type": "dialogue", "text": None,
             "transform": {"x": 0, "y": 0, "w": 10, "h": 10}},
        ],
        "comic-text-detector": [
            {"node_id": "det-n2", "bubble_type": "dialogue", "text": None,
             "transform": {"x": 0, "y": 0, "w": 10, "h": 10}},  # 与 det-n1 重复
            {"node_id": "det-n3", "bubble_type": "sfx", "text": None,
             "transform": {"x": 50, "y": 50, "w": 5, "h": 5}},
        ],
    }
    comp = {eng: compact_blocks(blks, ("node_id", "bubble_type", "text"), source_engine=eng)
            for eng, blks in per_engine.items()}
    blocks = union_blocks(comp)
    by_id = {b["node_id"]: b for b in blocks}
    assert by_id["det-n1"]["source_engines"] == ["pp-doclayout-v3", "comic-text-detector"]
    assert by_id["det-n3"]["source_engines"] == ["comic-text-detector"]
    for b in blocks:
        assert b["source_engines"], "每个框都应有引擎来源"
        assert all(not e.startswith("det-") for e in b["source_engines"]), "source_engines 不应是 node_id"


# ── Bug 1: 检测产物文件名页码 off-by-one ─────────────────────────


def test_eval_detection_path_uses_real_page_num():
    """eval_stage1_robust 产物文件名必须用真实页码（off-by-one 回归）。"""
    out = detection_path_for(Path("artifacts"), 11)
    assert out.name == "page_11_detection.json"
    assert out != Path("artifacts") / "page_10_detection.json", "page 11 的数据不应写入 page_10 文件"
    assert detection_path_for(Path("artifacts"), 20).name == "page_20_detection.json"
