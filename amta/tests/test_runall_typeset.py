# -*- coding: utf-8 -*-
"""00_run_all --with-typeset 编排测试(Stage 5)。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image


def _impl(name: str):
    import importlib.util
    real = name.lstrip("_") + ".py"
    path = Path(__file__).resolve().parents[1] / "scripts" / real
    spec = importlib.util.spec_from_file_location(name + "_impl", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_fake_cli(tmp_path, calls):
    def fake_cli(args):
        calls.append(Path(args[0]).name)
        name = Path(args[0]).name
        base = tmp_path / "ws" / "t" / "artifacts"
        base.mkdir(parents=True, exist_ok=True)
        if name == "01_detect.py":
            (base / "page_1_detection.json").write_text(
                json.dumps({"work_id": "t", "page": "1",
                            "image_meta": {"width": 100, "height": 100},
                            "blocks": [], "regions": []}), encoding="utf-8")
        elif name == "02_ocr.py":
            (base / "page_1_canon.json").write_text(json.dumps([]), encoding="utf-8")
        elif name == "03_translate.py":
            (base / "page_1_translation.json").write_text(
                json.dumps({"translations": {}}), encoding="utf-8")
        elif name == "04_inpaint.py":
            (base / "page_1_inpaint.json").write_text(
                json.dumps({"checks": {"filled": 0, "inpainted": 0, "skipped": 0}}),
                encoding="utf-8")
            (base / "clean").mkdir(exist_ok=True)
            Image.new("RGB", (100, 100), "white").save(base / "clean" / "page_1_clean.png")
        elif name == "05_typeset.py":
            (base / "page_1_typeset.json").write_text(
                json.dumps({"checks": {"rendered": 0, "translated": 0,
                                       "coverage_complete": True,
                                       "overflow": [], "skipped_no_bbox": []}}),
                encoding="utf-8")
    return fake_cli


def _mk_fake_ensure(tmp_path):
    def fake_ensure(wid):
        d = tmp_path / "ws" / wid
        for sub in ("raw", "artifacts", "state"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d
    return fake_ensure


def test_run_all_with_typeset_flag_invokes_05(tmp_path, monkeypatch):
    impl = _impl("_00_run_all")
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "1.jpg")

    calls = []
    monkeypatch.setattr(impl, "_run_cli", _mk_fake_cli(tmp_path, calls))
    monkeypatch.setattr(impl, "ensure_workspace", _mk_fake_ensure(tmp_path))

    impl.run("t", src, 1, 1, with_inpaint=True, with_typeset=True)
    assert "05_typeset.py" in calls
    assert "04_inpaint.py" in calls


def test_run_all_without_typeset_skips_05(tmp_path, monkeypatch):
    impl = _impl("_00_run_all")
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "1.jpg")

    calls = []
    monkeypatch.setattr(impl, "_run_cli", _mk_fake_cli(tmp_path, calls))
    monkeypatch.setattr(impl, "ensure_workspace", _mk_fake_ensure(tmp_path))

    impl.run("t", src, 1, 1, with_inpaint=True)
    assert "05_typeset.py" not in calls
