import json

from PIL import Image

from amta.orchestrator.adapters import typeset
from amta.orchestrator.context import StationContext


def test_requested_psd_failure_is_a_failed_stage(tmp_path, monkeypatch):
    clean = tmp_path / "clean.png"
    Image.new("RGB", (10, 10), "white").save(clean)
    inp = tmp_path / "inpaint.json"
    inp.write_text(json.dumps({"clean_image": "clean.png"}), encoding="utf-8")
    monkeypatch.setattr(typeset, "typeset_run", lambda **kw: {"checks": {}})
    monkeypatch.setattr("amta.typeset.psd_jsx_export.export_page_psd", lambda *a: None)
    ctx = StationContext(work_id="test", page="page_1", page_idx=1,
                         raw_image=clean, artifacts_dir=tmp_path, state_dir=tmp_path,
                         inputs={"detect": inp, "ocr": inp, "translate": inp, "inpaint": inp},
                         config={"export_psd": True})
    result = typeset.run(ctx)
    assert result.status == "failed"
    assert "PSD" in (result.error or "")
    assert "psd" not in result.stats
