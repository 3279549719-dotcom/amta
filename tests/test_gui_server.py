"""Touhou Manga Translator GUI server — FastAPI 端点单元测试。"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from amta.gui.server import _jobs, app
from amta.gui import server
from amta.orchestrator.context import PipelineResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_gui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
    monkeypatch.setattr(
        server, "run_pipeline", lambda config: PipelineResult("test", config.work_id, ["1"], config.stages)
    )
    monkeypatch.setattr(server, "run_environment_check", lambda stages: True, raising=False)
    monkeypatch.setattr(server, "audit_run", lambda path, pages: [], raising=False)
    _jobs.clear()


@pytest.mark.parametrize("work_id", ["../outside", "..\\outside", "", "absolute", ".", "..", "name:stream"])
def test_upload_rejects_unsafe_work_id(work_id: str, tmp_path: Path) -> None:
    from io import BytesIO

    data = BytesIO()
    Image.new("RGB", (2, 2)).save(data, "PNG")
    if work_id == "absolute":
        work_id = str(tmp_path / "outside")
    response = client.post(
        "/api/upload", data={"work_id": work_id}, files={"files": ("a.png", data.getvalue(), "image/png")}
    )
    assert response.status_code in (400, 422)
    assert not (tmp_path / "workspace").exists()


def test_submission_rejects_unsafe_work_id() -> None:
    response = client.post("/api/translate", json={"work_id": "../outside", "src_dir": "."})
    assert response.status_code == 400
    assert not _jobs


def test_upload_rejects_escaping_input_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    work = tmp_path / "workspace" / "safe"
    work.mkdir(parents=True)
    try:
        (work / "input").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(work / "input"), str(outside)], check=True, capture_output=True
        )
    response = client.post(
        "/api/upload", data={"work_id": "safe"}, files={"files": ("bad.png", b"invalid", "image/png")}
    )
    assert response.status_code == 400
    assert sentinel.read_text() == "keep"


def test_artifact_directory_link_cannot_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "workspace" / "safe"
    work.mkdir(parents=True)
    link = work / "artifacts"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    assert client.get("/api/artifacts/safe").status_code == 400
    assert client.get("/api/export/safe/1/png").status_code == 400
    response = client.post("/api/translate", json={"work_id": "safe", "src_dir": "."})
    assert response.status_code == 400


def test_pipeline_level_failure_is_not_done(monkeypatch: pytest.MonkeyPatch) -> None:
    result = PipelineResult(
        "test", "safe", [], [], failed_step={"page": "?", "stage": "pipeline", "reason": "no valid pages found"}
    )
    monkeypatch.setattr(server, "run_pipeline", lambda config: result)
    _jobs["test"] = {}
    server._run_pipeline_background("test", server.TranslateRequest(src_dir=".", work_id="safe", pages=[]))
    assert _jobs["test"]["status"] == "failed"
    assert "no valid pages found" in str(_jobs["test"]["error"])


def test_environment_failure_stops_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "run_environment_check", lambda stages: False, raising=False)

    def forbidden(config):
        pytest.fail("pipeline must not run after failed environment check")

    monkeypatch.setattr(server, "run_pipeline", forbidden)
    _jobs["test"] = {}
    server._run_pipeline_background("test", server.TranslateRequest(src_dir=".", work_id="safe", pages=[1]))
    assert _jobs["test"]["status"] == "failed"


def test_quality_audit_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    from amta.orchestrator.quality_audit import PageFlags

    monkeypatch.setattr(server, "audit_run", lambda path, pages: [PageFlags(page="1", overflow=["r1"])], raising=False)
    _jobs["test"] = {"job_id": "test", "mode": "default", "work_id": "safe"}
    server._run_pipeline_background("test", server.TranslateRequest(src_dir=".", work_id="safe", pages=[1]))
    response = client.get("/api/jobs/test")
    assert response.json()["status"] == "done"
    assert "r1" in response.json()["quality_warning"]


def test_health_check() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": "0.1.0"}


def _make_src_dir(tmp_path: Path, name: str) -> Path:
    """造一个含 1.jpg 白图的源目录。"""
    src = tmp_path / name
    src.mkdir()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(src / "1.jpg")
    return src


def test_submit_translation_job_default(tmp_path: Path) -> None:
    src = _make_src_dir(tmp_path, "pages")
    resp = client.post(
        "/api/translate",
        json={"src_dir": str(src), "work_id": "test-submit-default", "mode": "default"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["status"] == "queued"
    assert body["mode"] == "default"
    assert body["work_id"] == "test-submit-default"
    assert body["error"] is None


def test_job_status_not_found() -> None:
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


def test_job_status_queued() -> None:
    _jobs["fake-job-123"] = {
        "job_id": "fake-job-123",
        "status": "queued",
        "mode": "default",
        "work_id": "fake-work",
        "error": None,
    }
    try:
        resp = client.get("/api/jobs/fake-job-123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "fake-job-123"
        assert body["status"] == "queued"
        assert body["mode"] == "default"
        assert body["work_id"] == "fake-work"
        assert body["error"] is None
    finally:
        del _jobs["fake-job-123"]


def test_artifacts_list_empty() -> None:
    resp = client.get("/api/artifacts/nonexistent-work")
    assert resp.status_code == 200
    body = resp.json()
    assert body["work_id"] == "nonexistent-work"
    assert body["artifacts"] == []


def test_upload_images() -> None:
    from io import BytesIO

    img_bytes = BytesIO()
    Image.new("RGB", (50, 50), "white").save(img_bytes, format="JPEG")
    img_bytes.seek(0)
    resp = client.post(
        "/api/upload",
        files={"files": ("1.jpg", img_bytes, "image/jpeg")},
        data={"work_id": "test-upload"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["work_id"] == "test-upload"
    assert data["page_count"] == 1
    assert "src_dir" in data
    assert data["pages"] == [1]
    # 验证文件确实存为 1.jpg
    assert Path(data["src_dir"], "1.jpg").exists()


def test_export_png_not_found() -> None:
    resp = client.get("/api/export/nonexistent/1/png")
    assert resp.status_code == 404


def test_upload_writes_input_manifest_with_original_names(tmp_path: Path) -> None:
    from io import BytesIO

    def _png() -> bytes:
        buf = BytesIO()
        Image.new("RGB", (5, 5), "white").save(buf, "PNG")
        return buf.getvalue()

    resp = client.post(
        "/api/upload",
        files=[
            ("files", ("cover.png", _png(), "image/png")),
            ("files", ("02.png", _png(), "image/png")),
        ],
        data={"work_id": "naming"},
    )
    assert resp.status_code == 200
    manifest = tmp_path / "workspace" / "naming" / "input_manifest.json"
    import json
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert [p["stem"] for p in doc["pages"]] == ["cover", "02"]


def test_export_png_uses_original_filename(tmp_path: Path) -> None:
    from io import BytesIO

    def _png() -> bytes:
        buf = BytesIO()
        Image.new("RGB", (5, 5), "white").save(buf, "PNG")
        return buf.getvalue()

    client.post(
        "/api/upload",
        files=[("files", ("cover.png", _png(), "image/png"))],
        data={"work_id": "naming"},
    )
    final = tmp_path / "workspace" / "naming" / "artifacts" / "final"
    final.mkdir(parents=True)
    Image.new("RGB", (5, 5), "white").save(final / "page_1_final.png")

    resp = client.get("/api/export/naming/1/png")
    assert resp.status_code == 200
    assert "cover.png" in resp.headers["content-disposition"]


def test_export_png_falls_back_to_page_number_without_manifest(tmp_path: Path) -> None:
    final = tmp_path / "workspace" / "oldwork" / "artifacts" / "final"
    final.mkdir(parents=True)
    Image.new("RGB", (5, 5), "white").save(final / "page_3_final.png")
    resp = client.get("/api/export/oldwork/3/png")
    assert resp.status_code == 200
    assert "3.png" in resp.headers["content-disposition"]
