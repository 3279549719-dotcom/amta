"""PSD progress and timeout isolation contracts."""
import json
import re
from pathlib import Path
import pytest

from amta.typeset import psd_export
from amta.typeset.psd_jsx import build_script


@pytest.fixture(autouse=True)
def isolate_desktop_permissions(monkeypatch):
    monkeypatch.setattr(psd_export, "privilege_problem", lambda: None)


def test_progress_is_observed_without_changing_export_result(tmp_path, monkeypatch):
    clean = tmp_path / "clean.png"
    clean.write_bytes(b"fixture")
    output = tmp_path / "result.psd"
    observed = []
    monkeypatch.setattr(psd_export, "find_photoshop_executable", lambda: "photoshop")

    def launch(args, **kwargs):
        script = Path(args[2]).read_text(encoding="utf-8-sig")
        runtime = Path(args[2]).parent
        assert (runtime / "input.png").read_bytes() == clean.read_bytes()
        assert str(clean).replace("\\", "/") not in script
        progress = re.search(r"var PROGRESS_FILE_PATH = '([^']+)'", script)
        assert progress
        Path(progress[1]).write_text(json.dumps({"stage": "layers", "layers_done": 1, "layers_total": 1}) + "\n")
        (runtime / "output.psd").write_bytes(b"PSD")
        (runtime / "complete.txt").write_text("complete")

    monkeypatch.setattr(psd_export.subprocess, "Popen", launch)
    assert psd_export.export_psd_with_jsx(str(clean), {}, str(output), progress_callback=observed.append) == str(output)
    assert [e["stage"] for e in observed] == ["queued", "waiting_photoshop", "layers", "done"]
    assert observed[2]["layers_done"] == 1


def test_script_restores_user_state_and_checks_cancellation(tmp_path):
    script = build_script("clean.png", "out.psd", "error.txt", "complete.txt", {},
                          progress_path=str(tmp_path / "progress.jsonl"), cancel_path=str(tmp_path / "cancel"))
    assert "finally" in script
    assert "app.preferences.rulerUnits = oldRulerUnits" in script
    assert "app.preferences.typeUnits = oldTypeUnits" in script
    assert "app.displayDialogs = oldDialogs" in script
    assert "app.activeDocument = oldDocument" in script
    assert "checkCancelled();" in script
    assert script.index("finally") < script.index("doneFile.write('complete')")
    assert "new File(ERROR_FILE_PATH + '.tmp')" in script
    assert "errFile.rename(new File(ERROR_FILE_PATH).name)" in script


def test_batch_preserves_native_defaults_and_both_font_size_fields():
    data = {"rendered_items": [{"lines": ["text"], "font_size": 24, "anchor_pos": [100, 100]}]}
    script = build_script("clean.png", "out.psd", "error.txt", "complete.txt", data)
    assert "seedText" in script
    assert "seedLayer.remove()" in script
    assert "stringIDToTypeID('impliedFontSize')" in script
    assert "seedText.getEnumerationValue(stringIDToTypeID('antiAlias'))" in script
    legacy = build_script("clean.png", "out.psd", "error.txt", "complete.txt", data, legacy=True)
    assert "seedText" not in legacy
    assert "ti0.contents =" in legacy


def test_clean_only_does_not_create_seed_layer():
    script = build_script("clean.png", "out.psd", "error.txt", "complete.txt", {})
    assert "seedLayer" not in script


def test_partial_json_line_is_retried_without_duplicate_events(tmp_path):
    progress = tmp_path / 'progress.jsonl'
    seen = []
    progress.write_bytes(b'{"stage":"opening"}\n{"stage":"lay')
    offset = psd_export._read_progress(progress, 0, seen.append)
    assert seen == [{'stage': 'opening'}]
    assert psd_export._read_progress(progress, offset, seen.append) == offset
    with progress.open('ab') as stream:
        stream.write(b'ers"}\ninvalid\n')
    offset = psd_export._read_progress(progress, offset, seen.append)
    assert seen == [{'stage': 'opening'}, {'stage': 'layers'}]
    assert offset == progress.stat().st_size


def test_broken_progress_callback_does_not_prevent_export(tmp_path, monkeypatch):
    clean = tmp_path / 'clean.png'
    clean.write_bytes(b'fixture')
    output = tmp_path / 'result.psd'
    monkeypatch.setattr(psd_export, 'find_photoshop_executable', lambda: 'photoshop')
    def launch(args, **kwargs):
        runtime = Path(args[2]).parent
        (runtime / 'output.psd').write_bytes(b'PSD')
        (runtime / 'complete.txt').write_text('complete')
    def broken(event):
        raise RuntimeError('observer error')
    monkeypatch.setattr(psd_export.subprocess, 'Popen', launch)
    assert psd_export.export_psd_with_jsx(str(clean), {}, str(output), progress_callback=broken) == str(output)
