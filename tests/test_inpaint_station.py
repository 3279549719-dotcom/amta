import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw


def _load_impl():
    import importlib.util
    # 直接加载真实脚本(与 test_pipeline_flow 一致),monkeypatch 需真实模块全局命名空间
    p = Path(__file__).resolve().parents[1] / "scripts" / "04_inpaint.py"
    spec = importlib.util.spec_from_file_location("_04_inpaint_impl", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_station_fill_white_and_inpaint(tmp_path, monkeypatch):
    impl = _load_impl()
    raw = tmp_path / "1.jpg"
    img = Image.new("RGB", (200, 100), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 90, 40], fill="black")     # bubble → 涂白
    d.rectangle([110, 50, 190, 80], fill="black")   # sfx → inpaint
    img.save(raw)

    det = {"work_id": "w", "page": "1",
           "image_meta": {"width": 200, "height": 100, "channels": 3},
           "regions": [
               {"region_id": "page_0_u00", "category": "dialogue_bubble",
                "bbox": [10, 10, 90, 40]},
               {"region_id": "page_0_u01", "category": "sfx",
                "bbox": [110, 50, 190, 80]},
           ]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")

    class FakeK:
        def __init__(self):
            self.calls = []

        def wait_server(self, **kw):
            pass

        def close_current_project(self):
            pass

        def create_project(self, name):
            return "proj1"

        def import_page(self, p):
            return "pg1"

        def run_inpaint(self, page_id, masks, **kw):
            self.calls.append(("run_inpaint", sorted(masks.keys()), len(masks["segment"])))
            return {"status": "completed"}

        def fetch_inpainted(self, page_id):
            # 返回整页白色图(模拟 koharu 已擦除)
            import io
            buf = io.BytesIO()
            Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
            return buf.getvalue()

    fake = FakeK()
    monkeypatch.setattr(impl, "KoharuClient", lambda **kw: fake)

    out = tmp_path / "page_0_inpaint.json"
    clean_dir = tmp_path / "clean"
    impl.run("w", det_path, raw, out, clean_dir=clean_dir)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["checks"]["filled"] == 1
    assert data["checks"]["inpainted"] == 1
    assert data["checks"]["size_ok"] is True
    assert data["checks"]["pixel_diff_ratio"] > 0  # 有擦除发生(黑块变白)
    clean = Image.open(clean_dir / "page_0_clean.png")
    assert clean.size == (200, 100)
    assert clean.getpixel((50, 25)) == (255, 255, 255)  # bubble 区域已涂白
    assert any(c[0] == "run_inpaint" for c in fake.calls)
    call = [c for c in fake.calls if c[0] == "run_inpaint"][0]
    assert call[1] == ["bubble", "segment"]  # 双 mask 上传
    assert call[2] > 0  # PNG 字节非空


def test_station_dry_run_no_execution(tmp_path):
    impl = _load_impl()
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (100, 100), "white").save(raw)
    det = {"work_id": "w", "page": "1", "image_meta": {"width": 100, "height": 100},
           "regions": [{"region_id": "page_0_u00", "category": "dialogue_bubble",
                        "bbox": [0, 0, 10, 10]}]}
    det_path = tmp_path / "det.json"
    det_path.write_text(json.dumps(det), encoding="utf-8")
    out = tmp_path / "p.json"
    impl.run("w", det_path, raw, out, clean_dir=tmp_path / "clean", dry_run=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["filled"] == 1
    assert not (tmp_path / "clean" / "page_0_clean.png").exists()
