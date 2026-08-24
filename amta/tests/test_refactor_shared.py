"""重构产物（amta.runner / evalkit / images / ocr_engines / geometry.bbox 优先级）的确定性测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta import evalkit, geometry, images, ocr_engines, runner  # noqa: E402
from amta.koharu_client import KoharuError  # noqa: E402


class _FakeClient:
    """runner 的桩：只实现 run_pipeline_once 用到的接口，不连 koharu。"""

    def __init__(self, nodes: dict, status: str = "completed"):
        self.nodes = nodes
        self.status = status
        self.closed = 0

    def close_current_project(self) -> None:
        self.closed += 1

    def create_project(self, name: str) -> str:
        return "proj"

    def import_page(self, page: Path) -> str:
        return "page1"

    def run_pipeline(self, **kwargs) -> str:
        return "op1"

    def wait_operation(self, op_id: str, timeout: int | None = None) -> dict:
        return {"id": op_id, "status": self.status}

    def get_page_nodes(self, page_id: str) -> dict:
        return self.nodes


class RunnerTest(unittest.TestCase):
    def test_run_pipeline_once_returns_blocks_and_cleans_up(self):
        nodes = {"a": {"kind": {"text": {"text": "hi"}}}}
        client = _FakeClient(nodes)
        blocks = runner.run_pipeline_once(client, Path("x.jpg"), ["comic-text-detector"])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["ocr"], "hi")
        self.assertEqual(client.closed, 2)  # 开头 + finally 各清理一次

    def test_failed_status_raises(self):
        client = _FakeClient({}, status="failed")
        with self.assertRaises(KoharuError):
            runner.run_pipeline_once(client, Path("x.jpg"), ["comic-text-detector"])

    def test_completed_with_errors_rejected_by_default(self):
        client = _FakeClient({}, status="completed_with_errors")
        with self.assertRaises(KoharuError):
            runner.run_pipeline_once(client, Path("x.jpg"), ["comic-text-detector"])

    def test_completed_with_errors_accepted_when_required_false(self):
        client = _FakeClient({}, status="completed_with_errors")
        blocks = runner.run_pipeline_once(
            client, Path("x.jpg"), ["comic-text-detector"], require_completed=False
        )
        self.assertEqual(blocks, [])

    def test_run_all_pages_keeps_going_on_engine_failure(self):
        def fail(*args, **kwargs):
            raise RuntimeError("boom")

        class _FailClient(_FakeClient):
            def run_pipeline(self, **kwargs):
                return "op1"

            def wait_operation(self, op_id, timeout=None):
                raise RuntimeError("boom")

        client = _FailClient({})
        pages = [Path("a.jpg"), Path("b.jpg")]
        out = runner.run_all_pages(
            client, pages, {"eng1": ["comic-text-detector"]},
            lambda p, i: f"page_{i}", label="t",
        )
        self.assertEqual(out["page_0"]["engines"]["eng1"], [])
        self.assertEqual(out["page_1"]["engines"]["eng1"], [])

    def test_compact_blocks_keeps_bbox(self):
        blocks = [{"node_id": "n1", "transform": {"x": 10, "y": 20, "w": 30, "h": 40},
                   "ocr": "  x  ", "bubble_type": "dialogue", "translation": "t"}]
        out = runner.compact_blocks(blocks, ("node_id", "bubble_type", "ocr"))
        self.assertEqual(out[0]["bbox"], [10.0, 20.0, 40.0, 60.0])
        self.assertNotIn("translation", out[0])


class EvalkitTest(unittest.TestCase):
    def test_eval_rows_basename_match(self):
        meta = [{"crop": "output/data/crops/page_1_gt00.png", "content": "月の都", "type": "bg_text"}]
        preds = [{"crop": "E:/x/output/data/crops/page_1_gt00.png", "ocr": "月の都"}]
        rows, summary = evalkit.eval_rows(meta, preds)
        self.assertEqual(rows[0]["cer"], 0.0)
        self.assertEqual(rows[0]["em"], 1)
        self.assertEqual(summary["ALL"]["n"], 1)

    def test_summarize_groups_by_type_and_all(self):
        rows = [
            {"type": "dialogue_in", "cer": 0.0, "em": 1},
            {"type": "dialogue_in", "cer": 0.5, "em": 0},
            {"type": "sfx", "cer": 1.0, "em": 0},
        ]
        s = evalkit.summarize_rows(rows)
        self.assertEqual(s["dialogue_in"]["n"], 2)
        self.assertEqual(s["dialogue_in"]["cer"], 0.25)
        self.assertEqual(s["sfx"]["n"], 1)
        self.assertEqual(s["ALL"]["n"], 3)
        # 未出现类型也应有 n=0 行（输出形状稳定）
        self.assertEqual(s["bg_text"]["n"], 0)

    def test_basename_key_tolerates_path_diff(self):
        self.assertEqual(evalkit.basename_key("a/b/c.png"), evalkit.basename_key("c.png"))


class GeometryBboxPriorityTest(unittest.TestCase):
    def test_bbox_field_wins_over_transform(self):
        block = {"bbox": [1, 2, 3, 4], "transform": {"x": 10, "y": 20, "w": 30, "h": 40}}
        self.assertEqual(geometry.bbox_from_block(block), [1.0, 2.0, 3.0, 4.0])

    def test_transform_fallback_unchanged(self):
        block = {"transform": {"x": 10, "y": 20, "w": 30, "h": 40}}
        self.assertEqual(geometry.bbox_from_block(block), [10.0, 20.0, 40.0, 60.0])


class ImagesTest(unittest.TestCase):
    def test_crop_with_pad_clamps_bounds(self):
        import PIL.Image as Image

        img = Image.new("RGB", (100, 100), "white")
        src = Path(self._testMethodName + ".jpg")  # 不落盘：直接测越界框
        # 越界 bbox：pad 后超出图宽 → 应被 clamp 且保存成功
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.jpg"
            img.save(src)
            dest = Path(td) / "crop.png"
            self.assertTrue(images.crop_with_pad(src, [90, 90, 200, 200], dest, pad=8))
            self.assertTrue(dest.exists())

    def test_crop_with_pad_rejects_empty_box(self):
        import tempfile
        import PIL.Image as Image

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.jpg"
            Image.new("RGB", (100, 100), "white").save(src)
            dest = Path(td) / "crop.png"
            # 越界空框（pad 后 x1 <= x0）：不写文件
            self.assertFalse(images.crop_with_pad(src, [200, 200, 210, 220], dest))
            self.assertFalse(dest.exists())


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

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"choices": [{"message": {"content": "月の都"}}]}
            with mock.patch.object(ocr_engines.requests, "post", fake):
                out = ocr_engines.send_chat("http://127.0.0.1:8118/v1", "paddle", crop, api_key="k")
        self.assertEqual(out, "月の都")
        self.assertEqual(fake.call_args.args[0], "http://127.0.0.1:8118/v1/chat/completions")
        self.assertEqual(fake.call_args.kwargs["headers"]["Authorization"], "Bearer k")

    def test_send_chat_returns_empty_on_malformed_response(self):
        import tempfile
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "a.png"
            crop.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
            fake = mock.Mock()
            fake.return_value.status_code = 200
            fake.return_value.json.return_value = {"unexpected": True}
            with mock.patch.object(ocr_engines.requests, "post", fake):
                out = ocr_engines.send_chat("http://x/v1", "m", crop)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
