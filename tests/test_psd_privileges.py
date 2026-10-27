"""Fail fast on the privilege mismatch observed in the real GUI audit."""
import os

from amta.typeset import psd_export, psd_windows


def test_elevated_photoshop_is_rejected_for_standard_workbench(monkeypatch):
    monkeypatch.setattr(psd_windows, "photoshop_pid", lambda: 123)
    monkeypatch.setattr(psd_windows, "is_elevated", lambda pid: pid == 123)
    assert "管理员" in psd_windows.privilege_problem()


def test_matching_privilege_or_no_photoshop_needs_no_intervention(monkeypatch):
    monkeypatch.setattr(psd_windows, "photoshop_pid", lambda: 123)
    monkeypatch.setattr(psd_windows, "is_elevated", lambda pid: True)
    assert psd_windows.privilege_problem() is None
    monkeypatch.setattr(psd_windows, "photoshop_pid", lambda: None)
    assert psd_windows.privilege_problem() is None


def test_unknown_privilege_is_not_misreported_as_admin(monkeypatch):
    monkeypatch.setattr(psd_windows, "photoshop_pid", lambda: 123)
    monkeypatch.setattr(psd_windows, "is_elevated", lambda pid: False if pid == os.getpid() else None)
    assert psd_windows.privilege_problem() is None


def test_permission_error_reaches_gui_without_launching_or_waiting(tmp_path, monkeypatch):
    clean = tmp_path / "clean.png"
    clean.write_bytes(b"fixture")
    events = []
    monkeypatch.setattr(psd_export, "find_photoshop_executable", lambda: "photoshop")
    monkeypatch.setattr(psd_export, "privilege_problem", lambda: "请以普通权限启动 Photoshop")
    monkeypatch.setattr(psd_export.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch")))
    assert psd_export.export_psd_with_jsx(str(clean), {}, str(tmp_path / "out.psd"), progress_callback=events.append) is None
    assert events == [{"stage": "error", "error": "请以普通权限启动 Photoshop"}]
