"""pipeline 中间产物自动清理测试。

需求：typeset 跑完后，自动删掉上游中间位图（clean/、crops/），
保留 final/ 成品图和所有 JSON（增量缓存用）。

TDD：先写失败测试，再实现。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.orchestrator import (
    PipelineConfig,
    StationContext,
    StationResult,
    run_pipeline,
)
from amta.orchestrator import registry as _reg_module


def _make_fake_station(stage_name: str, produces: str, should_fail: bool = False):
    """创建 fake 工位，产出空 artifact + 模拟中间位图。"""
    state = {"calls": 0}

    def fake_station(ctx: StationContext) -> StationResult:
        state["calls"] += 1
        if should_fail:
            return StationResult(
                page=ctx.page, stage=stage_name, status="failed",
                error=f"fake {stage_name} failure",
            )
        from amta.stores import artifacts
        out_path = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)[produces]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"fake": True, "stage": stage_name}), encoding="utf-8")

        # 模拟各阶段产生的中间位图
        if stage_name == "ocr":
            # OCR 产生 crops 裁剪图（文件名用 region_id 格式）
            crops_dir = ctx.artifacts_dir / "crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            for i in range(3):
                (crops_dir / f"{ctx.page}_u{i:02d}.png").write_bytes(b"\x89PNG fake")
        if stage_name == "inpaint":
            # inpaint 产生 clean 干净图
            clean_dir = ctx.artifacts_dir / "clean"
            clean_dir.mkdir(parents=True, exist_ok=True)
            (clean_dir / f"{ctx.page}_clean.png").write_bytes(b"\x89PNG fake")
            # inpaint JSON 里记录 clean_image 路径
            out_path.write_text(json.dumps({
                "fake": True, "clean_image": f"clean/{ctx.page}_clean.png",
            }), encoding="utf-8")
        if stage_name == "typeset":
            # typeset 产生 final 成品图
            final_dir = ctx.artifacts_dir / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / f"{ctx.page}_final.png").write_bytes(b"\x89PNG fake")
            out_path.write_text(json.dumps({
                "fake": True, "final_image": f"final/{ctx.page}_final.png",
            }), encoding="utf-8")

        return StationResult(
            page=ctx.page, stage=stage_name, status="ok",
            output_artifact=out_path, duration_s=0.01,
            stats={"calls": state["calls"]},
        )

    fake_station.state = state
    return fake_station


def _setup_full_fake_registry():
    """用 fake 工位替换完整管线（detect→ocr→translate→inpaint→typeset）。"""
    fake_detect = _make_fake_station("detect", "detection")
    fake_ocr = _make_fake_station("ocr", "canon")
    fake_translate = _make_fake_station("translate", "translation")
    fake_inpaint = _make_fake_station("inpaint", "inpaint")
    fake_typeset = _make_fake_station("typeset", "typeset")

    _reg_module._REGISTRY = {
        "detect": _reg_module.StageSpec(name="detect", station=fake_detect, consumes=[], produces="detection"),
        "ocr": _reg_module.StageSpec(name="ocr", station=fake_ocr, consumes=["detect"], produces="canon"),
        "translate": _reg_module.StageSpec(name="translate", station=fake_translate, consumes=["ocr"], produces="translation"),
        "inpaint": _reg_module.StageSpec(name="inpaint", station=fake_inpaint, consumes=["detect", "translate"], produces="inpaint"),
        "typeset": _reg_module.StageSpec(name="typeset", station=fake_typeset, consumes=["detect", "ocr", "translate", "inpaint"], produces="typeset"),
    }
    return fake_detect, fake_ocr, fake_translate, fake_inpaint, fake_typeset


def _run_full_pipeline(tmp_path: Path, pages: list[int] = None) -> Path:
    """跑完整管线，返回 artifacts_dir。"""
    if pages is None:
        pages = [1]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
    # 绕过 book_store 依赖
    monkeypatch.setattr("amta.common.book_store.book_id_from_src_dir", lambda d: "test-book")
    monkeypatch.setattr("amta.common.book_store.save_meta", lambda *a, **kw: None)
    monkeypatch.setattr("amta.common.book_store.has_glossary", lambda *a, **kw: False)

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "raw"
        src_dir.mkdir()
        for n in pages:
            (src_dir / f"{n}.jpg").write_bytes(b"\xff\xd8\xff fake jpg")

        config = PipelineConfig(
            work_id="test-cleanup",
            src_dir=src_dir,
            start_page=min(pages),
            end_page=max(pages),
            pages=pages,
            stages=["detect", "ocr", "translate", "inpaint", "typeset"],
        )
        run_pipeline(config)

    return tmp_path / "test-cleanup" / "artifacts"


class TestTypesetCleanup:
    """typeset 成功后自动清理中间位图。"""

    def test_typeset_success_removes_clean_image(self, tmp_path):
        """typeset 成功后，该页的 clean/page_N_clean.png 被删除。"""
        _setup_full_fake_registry()
        artifacts_dir = _run_full_pipeline(tmp_path, pages=[1])

        clean_file = artifacts_dir / "clean" / "page_1_clean.png"
        assert not clean_file.exists(), (
            f"typeset 成功后 clean 图应被删除，但 {clean_file} 还在"
        )

    def test_typeset_success_keeps_final_image(self, tmp_path):
        """typeset 成功后，final/page_N_final.png 必须保留。"""
        _setup_full_fake_registry()
        artifacts_dir = _run_full_pipeline(tmp_path, pages=[1])

        final_file = artifacts_dir / "final" / "page_1_final.png"
        assert final_file.exists(), "typeset 成品图不能删"

    def test_typeset_success_keeps_json_artifacts(self, tmp_path):
        """typeset 成功后，所有阶段的 JSON 产物必须保留（增量缓存用）。"""
        _setup_full_fake_registry()
        artifacts_dir = _run_full_pipeline(tmp_path, pages=[1])

        for stage in ["detection", "canon", "translation", "inpaint", "typeset"]:
            json_file = artifacts_dir / stage / "page_1.json"
            assert json_file.exists(), f"{stage} JSON 不能删，这是增量缓存的基础"

    def test_typeset_success_clears_crops_dir(self, tmp_path):
        """全部跑完后，crops/ 目录被清空。"""
        _setup_full_fake_registry()
        artifacts_dir = _run_full_pipeline(tmp_path, pages=[1])

        crops_dir = artifacts_dir / "crops"
        if crops_dir.exists():
            remaining = list(crops_dir.glob("*.png"))
            assert len(remaining) == 0, (
                f"crops/ 应被清空，但还剩 {len(remaining)} 个文件: {remaining}"
            )

    def test_typeset_failure_keeps_clean_image(self, tmp_path):
        """typeset 失败时，不清理中间产物（方便调试）。"""
        # 用一个会失败的 typeset
        fake_typeset_fail = _make_fake_station("typeset", "typeset", should_fail=True)
        fake_detect, fake_ocr, fake_translate, fake_inpaint, _ = _setup_full_fake_registry()
        # 替换 typeset 为失败版本
        _reg_module._REGISTRY["typeset"] = _reg_module.StageSpec(
            name="typeset", station=fake_typeset_fail,
            consumes=["detect", "ocr", "translate", "inpaint"], produces="typeset",
        )

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda wid: tmp_path / wid)
        monkeypatch.setattr("amta.common.book_store.book_id_from_src_dir", lambda d: "test-book")
        monkeypatch.setattr("amta.common.book_store.save_meta", lambda *a, **kw: None)
        monkeypatch.setattr("amta.common.book_store.has_glossary", lambda *a, **kw: False)

        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "raw"
            src_dir.mkdir()
            (src_dir / "1.jpg").write_bytes(b"\xff\xd8\xff fake jpg")

            config = PipelineConfig(
                work_id="test-cleanup-fail",
                src_dir=src_dir,
                start_page=1,
                end_page=1,
                pages=[1],
                stages=["detect", "ocr", "translate", "inpaint", "typeset"],
                continue_on_error=True,
            )
            run_pipeline(config)

        artifacts_dir = tmp_path / "test-cleanup-fail" / "artifacts"
        clean_file = artifacts_dir / "clean" / "page_1_clean.png"
        assert clean_file.exists(), "typeset 失败时 clean 图应保留，方便调试"

    def test_multi_page_typeset_cleans_all_clean_images(self, tmp_path):
        """多页跑时，每页的 clean 图都被清理。"""
        _setup_full_fake_registry()
        artifacts_dir = _run_full_pipeline(tmp_path, pages=[1, 2, 3])

        for page in [1, 2, 3]:
            clean_file = artifacts_dir / "clean" / f"page_{page}_clean.png"
            assert not clean_file.exists(), f"page_{page} 的 clean 图应被删除"
            final_file = artifacts_dir / "final" / f"page_{page}_final.png"
            assert final_file.exists(), f"page_{page} 的 final 图必须保留"
