"""Deterministic HTTP upload, job, artifact and export integration tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from amta.gui import server
from amta.orchestrator.context import PipelineResult

client = TestClient(server.app)


@pytest.fixture(autouse=True)
def isolated_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "run_environment_check", lambda stages: True)
    monkeypatch.setattr(server, "audit_run", lambda path, pages: [])

    def fake_pipeline(config):
        assert config.pages == [1]
        assert config.vlm_pages == ([1] if config.work_id == "vlm" else [])
        output = tmp_path / "workspace" / config.work_id / "artifacts" / "final"
        output.mkdir(parents=True)
        Image.new("RGB", (2, 2), "white").save(output / "page_1_final.png")
        return PipelineResult("test", config.work_id, ["1"], config.stages)

    monkeypatch.setattr(server, "run_pipeline", fake_pipeline)
    # Execute the actual background handler synchronously, with only the expensive
    # pipeline boundary stubbed. No daemon threads can outlive test patches.
    monkeypatch.setattr(
        server,
        "threading",
        SimpleNamespace(Thread=lambda *, target, args, daemon: SimpleNamespace(start=lambda: target(*args))),
    )
    server._jobs.clear()


@pytest.mark.parametrize("mode", ["default", "vlm"])
def test_upload_translate_poll_and_export(mode: str) -> None:
    data = BytesIO()
    Image.new("RGB", (2, 2), "white").save(data, "PNG")
    uploaded = client.post(
        "/api/upload", files={"files": ("page.png", data.getvalue(), "image/png")}, data={"work_id": mode}
    )
    assert uploaded.status_code == 200
    submitted = client.post(
        "/api/translate",
        json={
            "src_dir": uploaded.json()["src_dir"],
            "work_id": mode,
            "mode": mode,
            "pages": uploaded.json()["pages"],
        },
    )
    assert submitted.status_code == 202
    status = client.get("/api/jobs/" + submitted.json()["job_id"])
    assert status.json()["status"] == "done", status.json()
    artifacts = client.get(f"/api/artifacts/{mode}").json()["artifacts"]
    assert artifacts == [{"page": "1", "url": f"/api/image/{mode}/1"}]
    downloaded = client.get(f"/api/export/{mode}/1/png")
    assert downloaded.status_code == 200
    assert Image.open(BytesIO(downloaded.content)).size == (2, 2)


def test_invalid_mode_rejected() -> None:
    response = client.post("/api/translate", json={"src_dir": ".", "work_id": "safe", "mode": "invalid"})
    assert response.status_code == 400
    assert not server._jobs
