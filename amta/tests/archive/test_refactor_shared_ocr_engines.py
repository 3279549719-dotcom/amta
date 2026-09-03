# -*- coding: utf-8 -*-
"""归档：OcrEnginesTest — 测已删除的 ocr_engines 旧多引擎辅助函数。

build_payload/send_chat/local_ocr_batch/dashscope_ocr_batch 均已随 baberu/hayai/manga_ocr
三引擎重构移除（test_final_integration::TestDeprecatedCodeRemoved 断言删除）。
留在 tests/archive/ 备查，git mv 可恢复；不参与任何门禁。
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


class OcrEnginesTest(unittest.TestCase):
    def test_build_payload_shape(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            payload = ocr_engines.build_payload("paddle", p)
        self.assertEqual(payload["model"], "paddle")
        parts = payload["messages"][0]["content"]
        self.assertEqual(parts[0]["type"], "image_url")
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(parts[1], {"type": "text", "text": "OCR"})

    def test_send_chat_sends_to_base_url_with_auth(self):
        import tempfile
        import unittest.mock as mock

        from amta import chat_client

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"choices": [{"message": {"content": "月の都"}}]}
            with mock.patch.object(chat_client.requests, "post", fake):
                out = ocr_engines.send_chat("http://127.0.0.1:8118/v1", "paddle", crop, api_key="k")
        self.assertEqual(out, "月の都")
        self.assertEqual(fake.call_args.args[0], "http://127.0.0.1:8118/v1/chat/completions")
        self.assertEqual(fake.call_args.kwargs["headers"]["Authorization"], "Bearer k")

    def test_send_chat_returns_empty_on_malformed_response(self):
        import tempfile
        import unittest.mock as mock

        from amta import chat_client

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"unexpected": True}
            with mock.patch.object(chat_client.requests, "post", fake):
                out = ocr_engines.send_chat("http://x/v1", "m", crop)
        self.assertEqual(out, "")
    def test_local_payload_disables_prompt_cache(self):
        """L17：多模态 cache 误命中不同图像——本地引擎请求必须带 cache_prompt:false。"""
        import tempfile
        import unittest.mock as mock

        from amta import chat_client

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"choices": [{"message": {"content": "x"}}]}
            with mock.patch.object(chat_client.requests, "post", fake):
                ocr_engines.local_ocr_batch([str(crop)])
        self.assertIs(fake.call_args.kwargs["json"]["cache_prompt"], False)

    def test_dashscope_payload_has_no_cache_prompt(self):
        """DashScope 兼容端点不认识 cache_prompt，不应携带（L17）。"""
        import tempfile
        import unittest.mock as mock

        from amta import chat_client

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"choices": [{"message": {"content": "x"}}]}
            with mock.patch.object(chat_client.requests, "post", fake):
                with mock.patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk"}):
                    ocr_engines.dashscope_ocr_batch([str(crop)])
        self.assertNotIn("cache_prompt", fake.call_args.kwargs["json"])


