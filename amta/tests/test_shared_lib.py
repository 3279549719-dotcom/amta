"""共享库确定性测试：metrics（norm/levenshtein/cer/best_match/match_score）+ geometry（bbox/iou/union）。

锁定 /simplify 合并后的唯一实现行为（含修复：norm 保留数字）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common import geometry, metrics


class NormTest(unittest.TestCase):
    def test_strips_punct_and_whitespace(self):
        self.assertEqual(metrics.norm("月の都 は、狭い！"), "月の都は狭い")

    def test_keeps_digits(self):
        # 修复点：recall_score 旧版丢 0-9，统一版必须保留（半角数字）
        self.assertEqual(metrics.norm("1205"), "1205")

    def test_empty(self):
        self.assertEqual(metrics.norm(""), "")
        self.assertEqual(metrics.norm(None), "")

    def test_wave_dash_and_long_vowel_mark(self):
        # 现行口径：ー(U+30FC) 保留（片假名区间内）；〜(U+301C)/～(U+FF5E) 被剔除。
        # researcher 调研：〜 vs ー 有真实语气差异，主流评测不删符号；
        # 双轨（nCER/lCER，ADR-010）落地前此处即当前口径，改动须经 ADR-010。
        self.assertEqual(metrics.norm("もーわがまま"), "もーわがまま")
        self.assertEqual(metrics.norm("も〜わがまま"), "もわがまま")


class CerTest(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(metrics.cer("月の都", "月の都"), 0.0)

    def test_punct_ignored(self):
        # 归一化后一致 → CER=0（报告口径：换行/标点不计）
        self.assertEqual(metrics.cer("月の都は狭い", "月の都は\n狭い"), 0.0)

    def test_one_char_flip(self):
        # くぃくぃ → くいくい：2 处替换 / 4 字 = 0.5
        self.assertEqual(metrics.cer("くぃ くぃ", "くいくい"), 0.5)

    def test_empty_gt_nonempty_pred(self):
        self.assertEqual(metrics.cer("", "あ"), 1.0)

    def test_both_empty(self):
        self.assertEqual(metrics.cer("", ""), 0.0)


class LevenshteinTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(metrics.levenshtein("abc", "abc"), 0)
        self.assertEqual(metrics.levenshtein("abc", "ab"), 1)
        self.assertEqual(metrics.levenshtein("abc", "axc"), 1)

    def test_internal_norm(self):
        self.assertEqual(metrics.levenshtein("a b", "ab"), 0)


class BestMatchTest(unittest.TestCase):
    def test_picks_lowest_cer(self):
        cer, pred = metrics.best_match("月の都", ["月の", "月の都", "東京"])
        self.assertEqual(pred, "月の都")
        self.assertEqual(cer, 0.0)

    def test_empty_pool(self):
        cer, pred = metrics.best_match("月", [])
        self.assertEqual(cer, 1.0)
        self.assertEqual(pred, "")


class MatchScoreTest(unittest.TestCase):
    def test_substring_is_one(self):
        self.assertEqual(metrics.match_score("月の都", "月の都は狭い"), 1.0)

    def test_overlap_ratio(self):
        # 字符集合重合度
        s = metrics.match_score("月の都", "月の民")
        self.assertGreater(s, 0.0)
        self.assertLess(s, 1.0)

    def test_empty(self):
        self.assertEqual(metrics.match_score("", "あ"), 0.0)


class GeometryTest(unittest.TestCase):
    def test_bbox_from_transform(self):
        block = {"transform": {"x": 10, "y": 20, "w": 30, "h": 40}}
        self.assertEqual(geometry.bbox_from_block(block), [10.0, 20.0, 40.0, 60.0])

    def test_bbox_rounds(self):
        block = {"transform": {"x": 1.234, "y": 2.345, "width": 3.456, "height": 4.567}}
        out = geometry.bbox_from_block(block)
        self.assertEqual(out, [round(1.234, 1), round(2.345, 1), round(1.234 + 3.456, 1), round(2.345 + 4.567, 1)])

    def test_iou_overlap(self):
        self.assertEqual(geometry.iou([0, 0, 10, 10], [5, 5, 15, 15]), 25 / 175)

    def test_iou_disjoint(self):
        self.assertEqual(geometry.iou([0, 0, 10, 10], [20, 20, 30, 30]), 0.0)

    def test_union_dedupes(self):
        detections = {
            "eng1": [{"transform": {"x": 0, "y": 0, "w": 10, "h": 10}}],
            "eng2": [{"transform": {"x": 0, "y": 0, "w": 10, "h": 10}}, {"transform": {"x": 100, "y": 100, "w": 5, "h": 5}}],
        }
        out = geometry.union_boxes(detections)
        self.assertEqual(len(out), 2)

    def test_union_blocks_keeps_metadata_and_dedupes(self):
        detections = {
            "ctd": [
                {"node_id": "a", "bubble_type": "dialogue", "text": None,
                 "transform": {"x": 0, "y": 0, "w": 10, "h": 10}},
            ],
            "anime": [
                {"node_id": "b", "bubble_type": "sfx", "text": None,
                 "transform": {"x": 0, "y": 0, "w": 10, "h": 10}},  # 与 a 重复
                {"node_id": "c", "bubble_type": "dialogue", "text": None,
                 "transform": {"x": 100, "y": 100, "w": 5, "h": 5}},
            ],
        }
        out = geometry.union_blocks(detections)
        self.assertEqual(len(out), 2)
        # 保留首个命中框元数据 + bbox 字段
        self.assertEqual(out[0]["node_id"], "a")
        self.assertEqual(out[0]["bbox"], [0.0, 0.0, 10.0, 10.0])
        self.assertEqual(out[1]["node_id"], "c")

# CategoryTest 已移除：assign_category 在 ADR-031 随 bubble_type 一起移除。



if __name__ == "__main__":
    unittest.main()
