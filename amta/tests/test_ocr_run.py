"""ocr_run.py 评测脚手架测试：裁 GT 框（Task 1）+ local 引擎请求构造（Task 2）+ dashscope 云端引擎（Task 4）。

真实引擎调用（llama-server / dashscope）不打网络：请求层用 mock 锁契约，裁框用 PIL 临时白图。
"""
import json
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _build_recall_gt(tmp_path):
    # 最小化 recall_gt，仅 1 页 2 框，避免依赖真实图片
    gt = {
        "pages": {
            "page_1": [
                {"content": "月の都", "type": "bg_text", "bbox": [10, 10, 60, 40]},
                {"content": "空を", "type": "dialogue_in", "bbox": [100, 100, 200, 150]},
            ]
        }
    }
    p = tmp_path / "recall_gt.json"
    p.write_text(json.dumps(gt, ensure_ascii=False), encoding="utf-8")
    return p


def test_crop_regions_uses_recall_gt_bbox(tmp_path):
    from ocr_run import crop_regions
    import PIL.Image as Image

    img = Image.new("RGB", (300, 300), "white")
    img_path = tmp_path / "p1.jpg"
    img.save(img_path)
    gt = _build_recall_gt(tmp_path)
    # 每页需要 path；此处单页注入
    crops, meta = crop_regions(gt, {1: str(img_path)}, tmp_path / "crops")
    assert len(crops) == 2
    assert meta[0]["crop"].endswith(".png")
    assert meta[0]["page"] == 1


def test_local_engine_builds_request(monkeypatch):
    """local 引擎：OpenAI 兼容 completions 端点，无 API key。"""
    import ocr_run

    fake = mock.Mock()
    fake.return_value.status_code = 200
    fake.return_value.json.return_value = {"choices": [{"text": "月の都"}]}
    monkeypatch.setattr(ocr_run.requests, "post", fake)
    out = ocr_run.local_ocr_batch(["a.png"], base_url="http://127.0.0.1:8118/v1", model="ocr")
    assert out[0]["ocr"] == "月の都"
    assert fake.call_args.args[0] == "http://127.0.0.1:8118/v1/completions"


def test_dashscope_engine_uses_env_key(monkeypatch, tmp_path):
    """dashscope 引擎：环境变量 DASHSCOPE_API_KEY 打 Authorization，base64 图走 OpenAI 兼容端点。"""
    import ocr_run

    crop = tmp_path / "a.png"
    crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    fake = mock.Mock()
    fake.return_value.status_code = 200
    fake.return_value.json.return_value = {"choices": [{"message": {"content": "月の都"}}]}
    monkeypatch.setattr(ocr_run.requests, "post", fake)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")

    out = ocr_run.dashscope_ocr_batch([str(crop)], model="qwen-vl-ocr-latest")

    assert out[0]["ocr"] == "月の都"
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert fake.call_args.args[0] == url
    assert fake.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    payload = fake.call_args.kwargs["json"]
    assert payload["model"] == "qwen-vl-ocr-latest"
    parts = payload["messages"][0]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "OCR"}
