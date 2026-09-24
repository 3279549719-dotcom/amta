"""Touhou Manga Translator GUI server — FastAPI 端点单元测试。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from amta.gui.server import _jobs, app

client = TestClient(app)


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
