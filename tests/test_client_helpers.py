"""koharu_client 纯函数/常量测试：不连引擎，只测可确定性验证的部分。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import koharu_client  # noqa: E402


class TerminalStatusTest(unittest.TestCase):
    def test_terminal_includes_known_states(self):
        """教训 L3：终态必须覆盖 completed_with_errors，否则 wait_operation 卡死。"""
        for s in ("completed", "failed", "cancelled", "completed_with_errors"):
            self.assertIn(s, koharu_client.TERMINAL_STATUSES)


class CollectBlocksTest(unittest.TestCase):
    def test_bubble_type_inference(self):
        nodes = {
            "a": {"kind": {"text": {"text": "hi"}, "narration": {}}},
            "b": {"kind": {"text": {"text": "doon"}, "sfx": {}}},
            "c": {"kind": {"mask": {}}},  # 非文字节点应被跳过
        }
        blocks = koharu_client.KoharuClient.collect_blocks(nodes)
        by = {b["node_id"]: b for b in blocks}
        self.assertEqual(by["a"]["bubble_type"], "narration")
        self.assertEqual(by["b"]["bubble_type"], "sfx")
        self.assertNotIn("c", by)


class SortReadingOrderTest(unittest.TestCase):
    def test_y_asc_then_x_desc(self):
        blocks = [
            {"transform": {"y": 2, "x": 10}},
            {"transform": {"y": 1, "x": 100}},
            {"transform": {"y": 1, "x": 5}},
        ]
        out = koharu_client.KoharuClient.sort_by_reading_order(blocks)
        self.assertEqual([b["transform"]["y"] for b in out], [1, 1, 2])
        self.assertEqual([b["transform"]["x"] for b in out[:2]], [100, 5])


class NoProxyTest(unittest.TestCase):
    def test_ensure_no_proxy_sets_localhost(self):
        koharu_client.ensure_no_proxy()
        val = os.environ.get("NO_PROXY", "") + "," + os.environ.get("no_proxy", "")
        self.assertIn("127.0.0.1", val)
        self.assertIn("localhost", val)


if __name__ == "__main__":
    unittest.main()
