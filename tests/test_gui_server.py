"""Touhou Manga Translator GUI server — FastAPI 端点单元测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from amta.gui.server import app

client = TestClient(app)


def test_health_check() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": "0.1.0"}
