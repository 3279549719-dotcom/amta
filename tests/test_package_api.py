"""包接口冒烟：__all__ 声明的每个导出都必须真实可访问（refactor/modular-architecture）。"""
import amta


def test_all_exports_resolvable():
    assert len(amta.__all__) >= 30
    for name in amta.__all__:
        assert hasattr(amta, name), f"amta.{name} 缺失：__init__ 导出面与实际模块不一致"


def test_key_boundaries_exposed():
    """关键模块边界：区域契约 / 配置接缝 / 翻译编排各自独立成模块。"""
    import amta.regions as regions
    import amta.chat_config as chat_config
    import amta.geometry as geometry

    # geometry 只留纯几何，region 契约唯一归属 regions
    for fn in ("build_regions", "flatten_regions", "mark_contained", "assign_category"):
        assert hasattr(regions, fn)
    assert hasattr(geometry, "iou") and hasattr(geometry, "union_blocks")
    assert hasattr(chat_config, "get_chat_config")
