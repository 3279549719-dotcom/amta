"""OCR confidence 过滤门回归测试：只砍瓦片副引擎纯新增框，主引擎框永不砍。

背景：_should_filter_by_conf 的 docstring 说"只对 source_engines==['rtdetr-v2-tiled']
的框过滤"，但实现一度漏掉了 source_engines 检查，导致主引擎真气泡（p33_r01/r02）
因首字 conf<0.4 被误杀。这些测试锁住"主引擎框不被砍"这一契约。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.stations.ocr_station import _should_filter_by_conf


def test_main_engine_box_with_low_conf_is_kept():
    """主引擎框（source_engines=['rtdetr-v2']）首字 conf=0.2 也不能砍。

    这是 p33_r01「ええ/分かってるわよ」的回归：当时首字 conf<0.4 被误杀。
    """
    row = {"first_token_conf": 0.2, "avg_conf": 0.5, "low_ratio": 0.3}
    box = {"source_engines": ["rtdetr-v2"]}
    should_drop, reason = _should_filter_by_conf(row, box)
    assert should_drop is False, f"主引擎框不该被砍: {reason}"


def test_main_engine_overlap_box_is_kept():
    """主副重叠框（source_engines 含 rtdetr-v2-tiled 但不止它）也不砍。"""
    row = {"first_token_conf": 0.1, "avg_conf": 0.3, "low_ratio": 0.9}
    box = {"source_engines": ["rtdetr-v2", "rtdetr-v2-tiled"]}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False


def test_tiled_only_box_with_low_conf_is_dropped():
    """瓦片副引擎纯新增框（source_engines==['rtdetr-v2-tiled']）conf<0.4 仍然砍。"""
    row = {"first_token_conf": 0.2, "avg_conf": 0.3, "low_ratio": 0.9}
    box = {"source_engines": ["rtdetr-v2-tiled"]}
    should_drop, reason = _should_filter_by_conf(row, box)
    assert should_drop is True
    assert "0.4" in reason or "conf" in reason


def test_tiled_only_box_with_high_conf_is_kept():
    """瓦片副引擎框 conf 正常时保留。"""
    row = {"first_token_conf": 0.9, "avg_conf": 0.8, "low_ratio": 0.1}
    box = {"source_engines": ["rtdetr-v2-tiled"]}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False


def test_no_source_engines_field_defaults_to_keep():
    """旧 box 没有 source_engines 字段时，按主引擎对待（不误砍）。"""
    row = {"first_token_conf": 0.1, "avg_conf": 0.2, "low_ratio": 0.9}
    box = {}
    should_drop, _ = _should_filter_by_conf(row, box)
    assert should_drop is False
