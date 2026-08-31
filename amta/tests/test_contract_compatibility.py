"""契约回归护栏：01→02→03 假适配器全链，id/键一致性——契约再漂移时 fastcheck 红。"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amta import artifacts
from fakes import FakeKoharu, make_node


def test_stage123_chain_ids_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.detect_station import detect_page
    from amta.ocr_station import ocr_page
    from amta.translate_station import translate_page

    art = tmp_path / "artifacts"
    art.mkdir()
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    client = FakeKoharu({
        "pp-doclayout-v3": [make_node("a", 0, 0, 40, 20, "あ")],
        "comic-text-detector": [make_node("b", 0, 0, 40, 20, "あ"),
                                make_node("c", 60, 60, 30, 30, "い")],
    })
    det = detect_page("w1", raw, art, page_idx=0, client=client)

    def fake_ocr(crops, engine="auto", **kw):
        return [{"crop": c, "ocr": "あです"} for c in crops]

    canon = ocr_page("w1", det, raw, art, page_idx=0, vlm_enabled=False, ocr_fn=fake_ocr)

    # 护栏 1：canon region_ids == detection blocks region_ids（顺序一一对应）
    det_ids = [b["region_id"] for b in det["blocks"]]
    canon_ids = [it["region_id"] for it in canon["items"]]
    assert canon_ids == det_ids

    # 护栏 2：contained_in 引用必在 region_id 集合内（修 F3 回归）
    ids = set(canon_ids)
    assert all(it.get("contained_in") in ids for it in canon["items"] if it.get("contained_in"))

    # 护栏 3：盘上产物均为 doc 信封（修 F2 回归）
    on_disk = artifacts.load_canon(art / "page_0_canon.json")
    assert on_disk["items"] and on_disk["schema_version"] == artifacts.SCHEMA_VERSION

    # 护栏 4：翻译 keys ⊇ canon region_ids
    trans = translate_page("w1", canon, page="page_0", mode="legacy",
                           llm=lambda m, tools=None: {"content": '{"page_0_u00": "你好", "page_0_u01": "好"}'})
    assert set(trans["translations"]) >= set(canon_ids)
