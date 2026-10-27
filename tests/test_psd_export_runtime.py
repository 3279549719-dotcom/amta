"""Photoshop export completion is isolated from pre-existing PSD files."""
import re
import threading
from pathlib import Path

import pytest

from amta.typeset import psd_jsx_export as exporter
from amta.typeset import psd_export


@pytest.fixture(autouse=True)
def isolate_desktop_permissions(monkeypatch):
    monkeypatch.setattr(psd_export, "privilege_problem", lambda: None)


@pytest.fixture
def export_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clean = tmp_path / "clean.png"
    clean.write_bytes(b"fixture")
    output = tmp_path / "page.psd"
    output.write_bytes(b"old psd")
    monkeypatch.setattr(psd_export, "find_photoshop_executable", lambda: "photoshop")
    monkeypatch.setattr(psd_export, "_PHOTOSHOP_LOCK", threading.Lock())
    return clean, output


def test_timeout_preserves_old_psd(export_paths, monkeypatch: pytest.MonkeyPatch):
    clean, output = export_paths
    monkeypatch.setattr(psd_export.subprocess, "Popen", lambda *args, **kwargs: None)
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

    monkeypatch.setattr(psd_export.subprocess, "Popen", launch)
    result = exporter.export_psd_with_jsx(str(clean), {"rendered_items": []},
                                          str(output), timeout=1)
    assert result == (str(output) if outcome == "success" else None)
    assert output.read_bytes() == (b"new psd" if outcome == "success" else b"old psd")
    assert captured and not captured[0].exists()


def test_unmarked_psd_times_out_and_runtime_paths_are_unique(export_paths, monkeypatch):
    clean, output = export_paths
    scripts = []
    clock = [0.0]
    monitors = []
    monkeypatch.setattr(psd_export, "_start_quarantine_monitor", lambda *args: monitors.append(args))

    def launch(args, **kwargs):
        script_path = Path(args[2])
        script = script_path.read_text(encoding="utf-8-sig")
        match = re.search(r"var psdFile = new File\('([^']+)'\)", script)
        assert match
        Path(match[1]).write_bytes(b"unfinished psd")
        scripts.append(script_path)

    def advance(seconds):
        clock[0] += seconds

    monkeypatch.setattr(psd_export.subprocess, "Popen", launch)
    monkeypatch.setattr(psd_export.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(psd_export.time, "sleep", advance)
    for _ in range(2):
        assert exporter.export_psd_with_jsx(str(clean), {"rendered_items": []},
                                            str(output), timeout=1) is None
        assert output.read_bytes() == b"old psd"
        runtime = scripts[-1].parent
        assert (runtime / "cancel").exists()
        assert psd_export._PHOTOSHOP_LOCK.locked()
        assert scripts[-1].exists()
        (runtime / "complete.txt").write_text("complete")
        psd_export._monitor_quarantine(*monitors.pop())
        assert not psd_export._PHOTOSHOP_LOCK.locked()
        assert output.read_bytes() == b"old psd"
    assert scripts[0].parent != scripts[1].parent
    assert all(not script.exists() for script in scripts)


def test_queued_export_times_out_without_launching(export_paths, monkeypatch):
    clean, output = export_paths
    calls = []
    class BusyLock:
        def acquire(self, *, timeout):
            calls.append(timeout)
            return False
        def release(self):
            pytest.fail('must not release another job lock')
    monkeypatch.setattr(psd_export, '_PHOTOSHOP_LOCK', BusyLock())
    monkeypatch.setattr(psd_export.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must not launch'))
    assert exporter.export_psd_with_jsx(str(clean), {}, str(output), timeout=1) is None
    assert calls == [1]
    assert output.read_bytes() == b'old psd'


def test_launch_failure_releases_lock_and_cleans_runtime(export_paths, monkeypatch):
    clean, output = export_paths
    def launch(*args, **kwargs):
        raise OSError('launch failed')
    monkeypatch.setattr(psd_export.subprocess, 'Popen', launch)
    assert exporter.export_psd_with_jsx(str(clean), {}, str(output)) is None
    assert not psd_export._PHOTOSHOP_LOCK.locked()
    assert not list(output.parent.glob('.amta-psd-*'))
    assert output.read_bytes() == b'old psd'
