"""depguard 自身的解析与间接运行时依赖回归。"""
from __future__ import annotations

from scripts import depguard


def test_scan_third_party_accepts_utf8_bom(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "station.py").write_text("import onnxruntime\n", encoding="utf-8-sig")
    monkeypatch.setattr(depguard, "ROOT", tmp_path)
    monkeypatch.setattr(depguard, "SCAN_DIRS", ("src",))

    found = depguard._scan_third_party()

    assert found["src\\station.py"] == {"onnxruntime"}


def test_indirect_runtime_dependencies_are_explicit():
    assert depguard.INDIRECT_RUNTIME_DEPS == {"httpx", "python-multipart"}
