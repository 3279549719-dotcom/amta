"""Stage 3 单元测试：双引擎文本输入 + LLM 选择。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.translate import _current_block


def test_translate_input_dual_engine():
    """翻译输入应包含 baberu_text 和 vlm_text。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "では豊ちゃん…",
        "vlm_text": "では豊ちゃん、輝夜様に…",
        "contained_in": None,
        "source_engines": ["det1"],
        "vlm_status": "ok",
    }
    assert item["baberu_text"]
    assert item["vlm_text"]
    # _current_block 应包含两个引擎的文本
    output = _current_block([item])
    assert "では豊ちゃん" in output
    assert "輝夜様" in output  # VLM 提供了完整文本


def test_translate_vlm_failed_fallback():
    """VLM 失败时应只用 baberu_text。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "テスト",
        "vlm_text": None,
        "vlm_status": "failed",
    }
    assert item["vlm_text"] is None
    output = _current_block([item])
    assert "テスト" in output
    # VLM 失败时不应出现 VLM 相关标记（或应标注失败）


def test_contained_in_merged_translation():
    """嵌套框的文本应在翻译时提示合并关系。"""
    parent = {
        "region_id": "u00",
        "baberu_text": "弟子だからね",
        "vlm_text": "弟子だからね",
        "contained_in": None,
        "vlm_status": "ok",
    }
    child = {
        "region_id": "u01",
        "baberu_text": "落ち着きなさい",
        "vlm_text": "落ち着きなさい",
        "contained_in": "u00",
        "vlm_status": "ok",
    }
    output = _current_block([parent, child])
    assert child["contained_in"] == "u00"
    # 输出应包含嵌套关系提示
    assert "u00" in output
    assert "u01" in output


def test_current_block_backward_compat():
    """旧格式（text 字段）应仍被支持。"""
    item = {
        "region_id": "u00",
        "text": "旧格式文本",
    }
    output = _current_block([item])
    assert "旧格式文本" in output
    assert "u00" in output


def test_current_block_empty_baberu_with_vlm():
    """Baberu 为空但 VLM 有文本时，应使用 VLM 文本。"""
    item = {
        "region_id": "u00",
        "baberu_text": "",
        "vlm_text": "VLMが読み取ったテキスト",
        "vlm_status": "ok",
        "contained_in": None,
    }
    output = _current_block([item])
    assert "VLMが読み取ったテキスト" in output
