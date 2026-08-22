"""输出工件结构校验：被入库的 benchmark/label JSON 必须可解析且含必要字段。

对应教训 L2（假数据落盘）——落盘的数字要有可查文件，且文件结构可被机器校验。
缺失文件则跳过（保持克隆/裁剪环境的健壮性），存在则严格校验。
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str):
    p = ROOT / rel
    if not p.is_file():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


class OutputSchemaTest(unittest.TestCase):
    def test_benchmark_a_schema(self):
        d = _load("output/data/benchmark_a.json")
        if d is None:
            self.skipTest("output/data/benchmark_a.json 不存在")
        for k in ("n_candidates", "fp_non_text", "detection_precision", "rows"):
            self.assertIn(k, d)
        for cls in ("dialogue_in", "dialogue_out", "sfx", "bg_text"):
            self.assertIn(cls, d["rows"])

    def test_benchmark_b_sfx_schema(self):
        d = _load("output/data/benchmark_b_sfx.json")
        if d is None:
            self.skipTest("output/data/benchmark_b_sfx.json 不存在")
        self.assertIn("engine", d)
        self.assertIn("n_sfx", d)
        self.assertIsInstance(d["rows"], list)

    def test_label_manifest_schema(self):
        d = _load("output/data/label_manifest.json")
        if d is None:
            self.skipTest("output/data/label_manifest.json 不存在")
        self.assertEqual(d.get("version"), 1)
        self.assertEqual(d.get("bench"), "a")
        self.assertIsInstance(d.get("items"), list)
        for it in d["items"]:
            for k in ("id", "crop", "page", "bbox"):
                self.assertIn(k, it, f"manifest item 缺字段 {k}")

    def test_recall_result_parses(self):
        d = _load("output/data/recall_result.json")
        if d is None:
            self.skipTest("output/data/recall_result.json 不存在")
        self.assertIsNotNone(d)  # 已能 json.load，即结构可解析


if __name__ == "__main__":
    unittest.main()
