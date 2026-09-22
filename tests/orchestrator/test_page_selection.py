"""tests/orchestrator/test_page_selection.py"""
from pathlib import Path

from amta.orchestrator.context import PipelineConfig
from amta.orchestrator.pipeline import _resolve_page_list


def test_resolve_pages_discrete(tmp_path: Path):
    """离散页选择：pages=[3, 7, 10] 只返回这三页。"""
    for n in (3, 7, 10, 5):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")
    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=10,  # 被 pages 覆盖
        pages=[3, 7, 10],
    )
    result = _resolve_page_list(config)
    assert [p[0] for p in result] == [3, 7, 10]


def test_resolve_pages_range_when_pages_none(tmp_path: Path):
    """pages=None 时回退到 start_page/end_page 连续区间。"""
    for n in (1, 2, 3):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")
    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=3, pages=None,
    )
    result = _resolve_page_list(config)
    assert [p[0] for p in result] == [1, 2, 3]


def test_vlm_pages_injected_into_config(tmp_path: Path):
    """vlm_pages 中的页，ocr/translate/typeset 的 config 应包含 vlm_mode=True。"""
    from amta.orchestrator.pipeline import _build_context
    from amta.orchestrator.registry import get_stage

    for n in (1, 60):
        (tmp_path / f"{n}.jpg").write_bytes(b"fake")

    config = PipelineConfig(
        work_id="test", src_dir=tmp_path,
        start_page=1, end_page=60, pages=[1, 60],
        vlm_pages=[60],
        stages=["ocr"],
    )

    artifacts_dir = tmp_path / "artifacts"
    state_dir = tmp_path / "state"
    artifacts_dir.mkdir(exist_ok=True)
    state_dir.mkdir(exist_ok=True)

    # 第 1 页（非 VLM）→ vlm_mode 不应存在
    ctx_normal = _build_context(
        config, 1, "page_1", tmp_path / "1.jpg",
        artifacts_dir, state_dir, get_stage("ocr"), {},
    )
    assert ctx_normal.config.get("vlm_mode") is not True

    # 第 60 页（VLM）→ vlm_mode=True
    ctx_vlm = _build_context(
        config, 60, "page_60", tmp_path / "60.jpg",
        artifacts_dir, state_dir, get_stage("ocr"), {},
    )
    assert ctx_vlm.config.get("vlm_mode") is True
