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
    """测试断点续跑：第二次运行所有阶段 skipped（artifact_cache cache hit）。"""
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

        # 第二次运行（不 force_rerun）— artifact_cache 判断指纹一致，cache hit
        result2 = run_pipeline(config)
        assert fake_detect.state["calls"] == 1, "detect should not be called again (cache hit)"
        assert fake_ocr.state["calls"] == 1, "ocr should not be called again (cache hit)"
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


def test_artifact_cache_fingerprint_created(tmp_path, monkeypatch):
    """验证 artifact_cache 集成：工位执行成功后生成 .fingerprint 文件。"""
    fake_detect, fake_ocr, fake_translate = _setup_fake_registry()

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

        config = PipelineConfig(
            work_id="test-fp",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["detect", "ocr", "translate"],
        )
        run_pipeline(config)

        # 验证每个阶段的产物旁边都有 .fingerprint 文件（新布局：<stage>/page_1.json 的兄弟）
        art_dir = tmp_path / "test-fp" / "artifacts"
        for stage_name, artifact_name in [("detect", "detection"), ("ocr", "canon"), ("translate", "translation")]:
            fp_path = art_dir / artifact_name / "page_1.json.fingerprint"
            assert fp_path.exists(), f"{stage_name} 的 .fingerprint 文件未生成: {fp_path}"
            # 验证 fingerprint 文件内容包含必要字段
            fp = json.loads(fp_path.read_text(encoding="utf-8"))
            assert fp["stage"] == stage_name
            assert fp["page"] == "page_1"
            assert "input_hash" in fp
            assert "code_hash" in fp
            assert "config_hash" in fp
        print("✓ test_artifact_cache_fingerprint_created passed")


def test_artifact_cache_rerun_when_input_changes(tmp_path, monkeypatch):
    """验证 artifact_cache 增量构建：修改上游输入后，下游阶段自动重跑。"""
    fake_detect, fake_ocr, fake_translate = _setup_fake_registry()

    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "raw"
        src_dir.mkdir()
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-v1")

        config = PipelineConfig(
            work_id="test-rerun",
            src_dir=src_dir,
            start_page=1, end_page=1,
            stages=["detect", "ocr", "translate"],
        )
        # 第一次运行
        run_pipeline(config)
        assert fake_detect.state["calls"] == 1
        assert fake_ocr.state["calls"] == 1
        assert fake_translate.state["calls"] == 1

        # 修改原始图片（detect 的输入）
        (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-v2-changed")

        # 第二次运行：detect 应该重跑（输入变了），下游也跟着重跑
        run_pipeline(config)
        assert fake_detect.state["calls"] == 2, "detect 输入变了应该重跑"
        assert fake_ocr.state["calls"] == 2, "ocr 上游 detect 重跑了应该跟着重跑"
        assert fake_translate.state["calls"] == 2, "translate 上游 ocr 重跑了应该跟着重跑"

        # 第三次运行：什么都没改，全部 cache hit
        run_pipeline(config)
        assert fake_detect.state["calls"] == 2, "没变化应该 cache hit"
        assert fake_ocr.state["calls"] == 2
        assert fake_translate.state["calls"] == 2
        print("✓ test_artifact_cache_rerun_when_input_changes passed")


if __name__ == "__main__":
    test_basic_pipeline()
    test_skip_existing()
    test_force_rerun()
    test_stage_failure_stops()
    test_missing_upstream_dependency()
    test_artifact_cache_fingerprint_created()
    test_artifact_cache_rerun_when_input_changes()
    print("\n=== All smoke tests passed ===")
