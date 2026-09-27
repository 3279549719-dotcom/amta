"""Photoshop export completion is isolated from pre-existing PSD files."""
import re
from pathlib import Path

import pytest

from amta.typeset import psd_jsx_export as exporter


@pytest.fixture
def export_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clean = tmp_path / "clean.png"
    clean.write_bytes(b"fixture")
    output = tmp_path / "page.psd"
    output.write_bytes(b"old psd")
    monkeypatch.setattr(exporter, "_find_photoshop_executable", lambda: "photoshop")
    return clean, output


def test_timeout_preserves_old_psd(export_paths, monkeypatch: pytest.MonkeyPatch):
    clean, output = export_paths
    monkeypatch.setattr(exporter.subprocess, "Popen", lambda *args, **kwargs: None)
    result = exporter.export_psd_with_jsx(str(clean), {"rendered_items": [
        {"lines": ["text"], "font_size": 20, "anchor_pos": [20, 20]}
    ]}, str(output), timeout=0)
    assert result is None
    assert output.read_bytes() == b"old psd"


def test_script_only_supports_clean_only_page(export_paths):
    clean, output = export_paths
    result = exporter.export_psd_with_jsx(str(clean), {"rendered_items": []},
                                          str(output), script_only=True)
    assert result == str(output.with_suffix(".jsx"))
    script = Path(result).read_text(encoding="utf-8-sig")
    assert "doc.saveAs" in script
    assert str(output).replace("\\", "/") in script


@pytest.mark.parametrize("outcome", ["success", "missing", "empty", "error"])
def test_only_completed_nonempty_stage_replaces_final(export_paths, monkeypatch, outcome):
    clean, output = export_paths
    captured = []

    def launch(args, **kwargs):
        script_path = Path(args[2])
        script = script_path.read_text(encoding="utf-8-sig")
        stage_match = re.search(r"var psdFile = new File\('([^']+)'\)", script)
        done_match = re.search(r"var COMPLETION_FILE_PATH = '([^']+)'", script)
        error_match = re.search(r"var ERROR_FILE_PATH = '([^']+)'", script)
        assert stage_match and done_match and error_match
        stage = Path(stage_match[1])
        assert stage != output
        assert not stage.exists()
        assert output.read_bytes() == b"old psd"
        captured.append(script_path)
        if outcome != "missing":
            stage.write_bytes(b"" if outcome == "empty" else b"new psd")
        Path(done_match[1]).write_text("complete")
        if outcome == "error":
            Path(error_match[1]).write_text("save failed")

    monkeypatch.setattr(exporter.subprocess, "Popen", launch)
    result = exporter.export_psd_with_jsx(str(clean), {"rendered_items": []},
                                          str(output), timeout=1)
    assert result == (str(output) if outcome == "success" else None)
    assert output.read_bytes() == (b"new psd" if outcome == "success" else b"old psd")
    assert captured and not captured[0].exists()


def test_unmarked_psd_times_out_and_runtime_paths_are_unique(export_paths, monkeypatch):
    clean, output = export_paths
    scripts = []
    clock = [0.0]

    def launch(args, **kwargs):
        script_path = Path(args[2])
        script = script_path.read_text(encoding="utf-8-sig")
        match = re.search(r"var psdFile = new File\('([^']+)'\)", script)
        assert match
        Path(match[1]).write_bytes(b"unfinished psd")
        scripts.append(script_path)

    def advance(seconds):
        clock[0] += seconds

    monkeypatch.setattr(exporter.subprocess, "Popen", launch)
    monkeypatch.setattr(exporter.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(exporter.time, "sleep", advance)
    for _ in range(2):
        assert exporter.export_psd_with_jsx(str(clean), {"rendered_items": []},
                                            str(output), timeout=1) is None
        assert output.read_bytes() == b"old psd"
    assert scripts[0].parent != scripts[1].parent
    assert all(not script.exists() for script in scripts)
