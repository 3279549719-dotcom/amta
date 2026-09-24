"""Touhou Manga Translator GUI server — FastAPI 端点单元测试。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from amta.gui.server import app

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
