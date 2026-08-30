# -*- coding: utf-8 -*-
"""pipeline_log / 01_detect / 02_ocr / 00_run_all 编排器测试(ADR-018)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


_IMPLS = {}


def _impl(name: str):
    """按文件路径加载数字前缀真实脚本(与桥等价),返回实现模块。"""
    if name not in _IMPLS:
        import importlib.util
        real = name.lstrip("_") + ".py"  # _02_ocr -> 02_ocr.py
        path = Path(__file__).resolve().parents[1] / "scripts" / real
        spec = importlib.util.spec_from_file_location(name + "_impl", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _IMPLS[name] = mod
    return _IMPLS[name]


# ---------- pipeline_log ----------

def test_pipeline_log_span_and_fail(tmp_path):
    import json
    from amta.pipeline_log import PipelineLog
    log = PipelineLog(tmp_path / "pipeline_log.json")
    rid = log.start_run("pages 1-1")
    log.add_span(rid, step="01_detect", page="page_0", status="ok",
                 input="1.jpg", output="page_0_detection.json", duration_s=1.5)
    log.fail_run(rid, step="02_ocr", page="page_0", reason="no valid bbox")
    doc = json.loads((tmp_path / "pipeline_log.json").read_text(encoding="utf-8"))
    run = doc["runs"][0]
    assert run["git_head"]  # 记录了代码版本
    assert run["steps"][0]["status"] == "ok"
    assert run["failed_step"]["reason"] == "no valid bbox"


def test_pipeline_log_skip_append(tmp_path):
    from amta.pipeline_log import PipelineLog
    log = PipelineLog(tmp_path / "pl.json")
    r1 = log.start_run("a")
    r2 = log.start_run("b")
    log.add_span(r1, step="s", page="p", status="skipped")
    log.add_span(r2, step="s", page="p", status="ok")
    assert len(log.last_runs(5)) == 2  # append 不覆盖


# ---------- 02_ocr ----------

def test_02_crop_naming_and_canon(tmp_path, monkeypatch):
    """crop 按 region_id 命名(语义评审契约) + canon 双引擎格式(baberu_text, 空 OCR 保留)。"""
    import json
    from PIL import Image

    impl = _impl("_02_ocr")

    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    det = {"work_id": "w", "page": "1", "blocks": [
        {"node_id": "n0", "bbox": [10, 10, 90, 40], "bubble_type": "dialogue_in"},
        {"node_id": "n1", "bbox": [110, 50, 190, 80], "bubble_type": "sfx"},
    ]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")

    def fake_ocr(crops, engine="auto", **kw):
        return [{"crop": c, "ocr": "月の都" if "u00" in c else ""} for c in crops]

    monkeypatch.setattr(impl, "ocr_batch", fake_ocr)  # 打实现模块已绑定引用
    out = tmp_path / "canon.json"
    doc = impl.run("w", det_path, raw, out, page_idx=0)
    canon = json.loads(out.read_text(encoding="utf-8"))["items"]  # 盘上已 doc 化（修 F2）

    assert doc["n_regions"] == 2  # 双引擎契约：空 OCR 不跳过（vlm_text 可兜底）
    assert canon[0]["region_id"] == "page_0_u00"
    assert canon[0]["baberu_text"] == "月の都"
    assert canon[1]["region_id"] == "page_0_u01"
    assert canon[1]["baberu_text"] == ""
    assert (tmp_path / "crops" / "page_0_u00.png").exists()  # region_id 命名
    assert (tmp_path / "crops" / "page_0_u01.png").exists()


# ---------- 00_run_all ----------

def test_refresh_merged_translation(tmp_path):
    """00_run_all 完成后 artifacts/translation.json 合并所有 per-page 译文（get_context 读取）。"""
    import json

    impl = _impl("_00_run_all")
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "page_0_translation.json").write_text(
        json.dumps({"work_id": "w", "translations": {"page_0_u00": "月之都"}}, ensure_ascii=False),
        encoding="utf-8")
    (art / "page_1_translation.json").write_text(
        json.dumps({"work_id": "w", "translations": {"page_1_u00": "污秽"}}, ensure_ascii=False),
        encoding="utf-8")
    impl._refresh_merged_translation(tmp_path)
    merged = json.loads((art / "translation.json").read_text(encoding="utf-8"))
    assert merged["translations"] == {"page_0_u00": "月之都", "page_1_u00": "污秽"}


def test_00_skip_existing_and_fail_anchor(tmp_path, monkeypatch):
    """产物存在=跳过;失败写 failed_step 锚点。"""
    import json
    from PIL import Image

    impl = _impl("_00_run_all")

    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "1.jpg")

    calls = []

    def fake_cli(args):
        calls.append(Path(args[0]).name)
        if "01_detect.py" in args[0]:
            det = tmp_path / "ws" / "t" / "artifacts" / "page_0_detection.json"
            det.parent.mkdir(parents=True, exist_ok=True)
            det.write_text(json.dumps({"work_id": "t", "page": "1", "blocks": []}), encoding="utf-8")
        else:
            raise RuntimeError("boom: no bbox")

    monkeypatch.setattr(impl, "_run_cli", fake_cli)

    def fake_ensure(wid):
        d = tmp_path / "ws" / wid
        for sub in ("raw", "artifacts", "state"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(impl, "ensure_workspace", fake_ensure)

    rc = impl.run("t", src, 1, 1)
    assert rc == 1
    log = json.loads((tmp_path / "ws" / "t" / "state" / "pipeline_log.json").read_text(encoding="utf-8"))
    assert log["runs"][0]["failed_step"]["reason"].startswith("boom")
    assert "01_detect.py" in calls


# ---------- Phase 1 contract hygiene (ADR-019) ----------

def test_02_canon_passthrough_subtier_category_and_items_rename(tmp_path, monkeypatch):
    """canon 透传 sub_tier/category; 返回 doc 字段 regions→items 消除撞名。"""
    import json
    from PIL import Image

    impl = _impl("_02_ocr")

    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    det = {"work_id": "w", "page": "1", "blocks": [
        {"node_id": "n0", "bbox": [10, 10, 90, 40], "bubble_type": "dialogue",
         "category": "dialogue_bubble"},
        {"node_id": "n1", "bbox": [110, 50, 190, 80], "bubble_type": "sfx",
         "category": "sfx", "sub_tier": "aside"},
    ]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")

    def fake_ocr(crops, engine="auto", **kw):
        return [{"crop": c, "ocr": "text"} for c in crops]

    monkeypatch.setattr(impl, "ocr_batch", fake_ocr)
    out = tmp_path / "canon.json"
    doc = impl.run("w", det_path, raw, out, page_idx=0)
    canon = json.loads(out.read_text(encoding="utf-8"))["items"]  # 盘上已 doc 化（修 F2）

    assert "regions" not in doc          # 撞名消除(01_detect 的 regions 是层级结构)
    assert doc["items"][0]["region_id"] == "page_0_u00"
    assert canon[0]["category"] == "dialogue_bubble"
    assert canon[1]["category"] == "sfx"
    assert canon[1]["sub_tier"] == "aside"
    assert canon[0].get("sub_tier") is None  # 无 sub_tier 不硬造(可选字段)
