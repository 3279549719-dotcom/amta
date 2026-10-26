"""Missing auxiliary outputs must invalidate a successful stage's cache."""
import json

import pytest

from amta.orchestrator import PipelineConfig, StationResult, run_pipeline
from amta.orchestrator import registry
from amta.stores.artifacts import artifact_paths


@pytest.mark.parametrize("stage_name,image_key,relative_file,export_psd", [
    ("inpaint", "clean_image", "clean/page_1_clean.png", False),
    ("typeset", "final_image", "final/page_1_final.png", False),
    ("typeset", None, "psd/page_1.psd", True),
])
def test_deleted_auxiliary_output_forces_rerun(
    tmp_path, monkeypatch, stage_name, image_key, relative_file, export_psd,
):
    work_dir = tmp_path / "work"
    src_dir = tmp_path / "raw"
    src_dir.mkdir()
    (src_dir / "1.jpg").write_bytes(b"fake image")
    calls = []

    def station(ctx):
        calls.append(ctx.page)
        auxiliary = ctx.artifacts_dir / relative_file
        auxiliary.parent.mkdir(parents=True, exist_ok=True)
        auxiliary.write_bytes(b"generated output")
        out_path = artifact_paths(ctx.artifacts_dir, ctx.page)[stage_name]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {image_key: relative_file} if image_key else {}
        out_path.write_text(json.dumps(doc), encoding="utf-8")
        return StationResult(page=ctx.page, stage=stage_name, status="ok", output_artifact=out_path)

    monkeypatch.setattr(registry, "_REGISTRY", {
        stage_name: registry.StageSpec(name=stage_name, station=station, produces=stage_name),
    })
    monkeypatch.setattr("amta.orchestrator.pipeline.ensure_workspace", lambda _: work_dir)
    config = PipelineConfig(
        work_id="cache-outputs", src_dir=src_dir, start_page=1, end_page=1,
        stages=[stage_name], stage_configs={stage_name: {"export_psd": export_psd}},
    )
    assert run_pipeline(config).results["page_1"][stage_name].status == "ok"
    assert run_pipeline(config).results["page_1"][stage_name].status == "skipped"
    (work_dir / "artifacts" / relative_file).unlink()
    assert run_pipeline(config).results["page_1"][stage_name].status == "ok"
    assert len(calls) == 2


def test_typeset_preserves_clean_asset_for_cached_run_and_later_psd(tmp_path, monkeypatch):
    from amta.typeset import psd_jsx_export

    work_dir = tmp_path / 'work'
    src_dir = tmp_path / 'raw'
    src_dir.mkdir()
    (src_dir / '1.jpg').write_bytes(b'raw')
    calls = []
    def station(ctx, stage_name):
        calls.append(stage_name)
        relative = 'clean/page_1_clean.png' if stage_name == 'inpaint' else 'final/page_1_final.png'
        image = ctx.artifacts_dir / relative
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b'image')
        doc = {'clean_image' if stage_name == 'inpaint' else 'final_image': relative}
        artifact = artifact_paths(ctx.artifacts_dir, ctx.page)[stage_name]
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(doc), encoding='utf-8')
        return StationResult(page=ctx.page, stage=stage_name, status='ok', output_artifact=artifact)
    monkeypatch.setattr(registry, '_REGISTRY', {
        'inpaint': registry.StageSpec(name='inpaint', station=lambda ctx: station(ctx, 'inpaint'), produces='inpaint'),
        'typeset': registry.StageSpec(name='typeset', station=lambda ctx: station(ctx, 'typeset'),
                                     produces='typeset', consumes=['inpaint']),
    })
    monkeypatch.setattr('amta.orchestrator.pipeline.ensure_workspace', lambda _: work_dir)
    config = PipelineConfig(work_id='retained-clean', src_dir=src_dir, pages=[1], start_page=1, end_page=1,
                            stages=['inpaint', 'typeset'], stage_configs={'typeset': {'export_psd': False}})
    run_pipeline(config)
    result = run_pipeline(config)
    assert calls == ['inpaint', 'typeset']
    assert result.results['page_1']['inpaint'].status == 'skipped'
    assert result.results['page_1']['typeset'].status == 'skipped'

    def export(**kwargs):
        from pathlib import Path
        assert Path(kwargs['clean_image_path']).read_bytes() == b'image'
        return kwargs['output_psd_path']
    monkeypatch.setattr(psd_jsx_export, 'export_psd_with_jsx', export)
    output = tmp_path / 'later.psd'
    assert psd_jsx_export.export_page_psd(work_dir / 'artifacts', 'page_1', output) == str(output)
