"""编排器冒烟测试 — 用 fake 工位验证页面循环、阶段循环、断点续跑、错误处理。

不依赖真实 OCR/翻译模型，纯逻辑验证。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.orchestrator import (
    PipelineConfig,
    StationContext,
    StationResult,
    run_pipeline,
)
from amta.orchestrator import registry as _reg_module


def _make_fake_station(stage_name: str, should_fail: bool = False):
    """创建一个 fake 工位函数，记录调用次数，产出空 artifact 文件。"""
    state = {"calls": 0}
    # stage 名 → artifact_paths 的 key（produces 名）
    _STAGE_TO_ARTIFACT = {"detect": "detection", "ocr": "canon", "translate": "translation"}

    def fake_station(ctx: StationContext) -> StationResult:
        state["calls"] += 1
        if should_fail:
            return StationResult(
                page=ctx.page, stage=stage_name, status="failed",
                error=f"fake {stage_name} failure",
            )
        # 写一个空 artifact 文件，模拟产出
        from amta import artifacts
        artifact_key = _STAGE_TO_ARTIFACT.get(stage_name, stage_name)
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)[artifact_key]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"fake": True, "stage": stage_name}), encoding="utf-8")
        return StationResult(
            page=ctx.page, stage=stage_name, status="ok",
            output_artifact=out_path, duration_s=0.01,
            stats={"calls": state["calls"]},
        )

    fake_station.state = state
    return fake_station


def _setup_fake_registry():
    """用 fake 工位替换注册表中的真实工位。"""
    fake_detect = _make_fake_station("detect")
    fake_ocr = _make_fake_station("ocr")
    fake_translate = _make_fake_station("translate")

    _reg_module._REGISTRY = {
        "detect": _reg_module.StageSpec(name="detect", station=fake_detect, consumes=[], produces="detection"),
        "ocr": _reg_module.StageSpec(name="ocr", station=fake_ocr, consumes=["detect"], produces="canon"),
        "translate": _reg_module.StageSpec(name="translate", station=fake_translate, consumes=["ocr"], produces="translation"),
    }
    return fake_detect, fake_ocr, fake_translate


def test_basic_pipeline(tmp_path, monkeypatch):
    """测试基本管线：3 页 × 3 阶段，全部成功。"""
    fake_detect, fake_ocr, fake_translate = _setup_fake_registry()

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        # 创建 3 张假图片
        for n in [1, 2, 3]:
            (src_dir / f"{n}.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-smoke",
            src_dir=src_dir,
            start_page=1, end_page=3,
            stages=["detect", "ocr", "translate"],
        )
        result = run_pipeline(config)

        assert result.run_id, "run_id should not be empty"
        assert len(result.pages) == 3, f"expected 3 pages, got {len(result.pages)}"
        assert len(result.failed_pages) == 0, f"no failures expected, got {result.failed_pages}"
        assert fake_detect.state["calls"] == 3, f"detect called {fake_detect.state['calls']} times, expected 3"
        assert fake_ocr.state["calls"] == 3, f"ocr called {fake_ocr.state['calls']} times, expected 3"
        assert fake_translate.state["calls"] == 3, f"translate called {fake_translate.state['calls']} times, expected 3"
        print("✓ test_basic_pipeline passed")


def test_skip_existing(tmp_path, monkeypatch):
    """测试断点续跑：第二次运行所有阶段 skipped。"""
    fake_detect, fake_ocr, fake_translate = _setup_fake_registry()

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-skip",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["detect", "ocr", "translate"],
        )
        # 第一次运行
        run_pipeline(config)
        assert fake_detect.state["calls"] == 1

        # 第二次运行（不 force_rerun）
        result2 = run_pipeline(config)
        assert fake_detect.state["calls"] == 1, "detect should not be called again (skipped)"
        assert fake_ocr.state["calls"] == 1, "ocr should not be called again (skipped)"
        page_result = result2.results["page_1"]
        assert page_result["detect"].status == "skipped"
        assert page_result["ocr"].status == "skipped"
        assert page_result["translate"].status == "skipped"
        print("✓ test_skip_existing passed")


def test_force_rerun(tmp_path, monkeypatch):
    """测试 force_rerun：即使产物存在也重跑。"""
    fake_detect, fake_ocr, fake_translate = _setup_fake_registry()

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-force",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["detect", "ocr", "translate"],
        )
        run_pipeline(config)
        assert fake_detect.state["calls"] == 1

        config.force_rerun = True
        run_pipeline(config)
        assert fake_detect.state["calls"] == 2, "detect should be called again (force_rerun)"
        print("✓ test_force_rerun passed")


def test_stage_failure_stops(tmp_path, monkeypatch):
    """测试阶段失败：默认情况下失败后停止。"""
    fake_detect = _make_fake_station("detect")
    fake_ocr = _make_fake_station("ocr", should_fail=True)
    fake_translate = _make_fake_station("translate")

    _reg_module._REGISTRY = {
        "detect": _reg_module.StageSpec(name="detect", station=fake_detect, consumes=[], produces="detection"),
        "ocr": _reg_module.StageSpec(name="ocr", station=fake_ocr, consumes=["detect"], produces="canon"),
        "translate": _reg_module.StageSpec(name="translate", station=fake_translate, consumes=["ocr"], produces="translation"),
    }

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-fail",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["detect", "ocr", "translate"],
        )
        result = run_pipeline(config)

        assert len(result.failed_pages) == 1
        assert result.failed_step["stage"] == "ocr"
        assert fake_translate.state["calls"] == 0, "translate should not run after ocr fails"
        print("✓ test_stage_failure_stops passed")


def test_missing_upstream_dependency(tmp_path, monkeypatch):
    """测试上游依赖缺失：跳过 detect 后，ocr 应该报上游缺失。"""
    fake_ocr = _make_fake_station("ocr")
    fake_translate = _make_fake_station("translate")

    _reg_module._REGISTRY = {
        "ocr": _reg_module.StageSpec(name="ocr", station=fake_ocr, consumes=["detect"], produces="canon"),
        "translate": _reg_module.StageSpec(name="translate", station=fake_translate, consumes=["ocr"], produces="translation"),
    }

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-dep",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["ocr", "translate"],  # 跳过 detect
        )
        result = run_pipeline(config)

        assert len(result.failed_pages) == 1
        page_result = result.results["page_1"]
        assert "上游阶段缺失" in page_result["ocr"].error
        assert fake_translate.state["calls"] == 0
        print("✓ test_missing_upstream_dependency passed")


if __name__ == "__main__":
    test_basic_pipeline()
    test_skip_existing()
    test_force_rerun()
    test_stage_failure_stops()
    test_missing_upstream_dependency()
    print("\n=== All smoke tests passed ===")
