"""共享库确定性测试：metrics（norm/levenshtein/cer/best_match/match_score）+ geometry（bbox/iou/union）。

锁定 /simplify 合并后的唯一实现行为（含修复：norm 保留数字）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta import geometry, metrics  # noqa: E402


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

    def test_absorb_contained_drops_nested_fragment(self):
        # u04「ぽ」全嵌套于 u05「ぽっらん」,IoU≈0 但 IoA=1.0 → 丢弃子框
        blocks = [
            {"node_id": "big", "bbox": [1256, 497, 1643, 799]},   # 容器
            {"node_id": "frag", "bbox": [1264, 509, 1377, 616]},  # 全嵌套碎片
            {"node_id": "disjoint", "bbox": [0, 0, 100, 100]},    # 独立框保留
        ]
        out = geometry.absorb_contained(blocks)
        ids = sorted(b["node_id"] for b in out)
        self.assertEqual(ids, ["big", "disjoint"])

    def test_absorb_contained_keeps_partial_overlap(self):
        # 仅部分重叠(IoA<0.75)不吸收
        blocks = [
            {"node_id": "a", "bbox": [0, 0, 100, 100]},
            {"node_id": "b", "bbox": [50, 0, 150, 100]},  # 与 a 部分重叠
        ]
        out = geometry.absorb_contained(blocks)
        self.assertEqual(len(out), 2)

    def test_assign_sub_tier_primary_vs_aside(self):
        # 容器内两行: 与最大行宽比 >= 1.4 → 判定为 aside(碎碎念), 否则 primary
        lines = [
            {"bbox": [100, 100, 500, 200]},  # 宽 400
            {"bbox": [100, 220, 160, 260]},  # 宽 60, 与最大行宽比 400/60≈6.7 → aside
        ]
        out = geometry.assign_sub_tier(lines, ratio=1.4)
        self.assertEqual(out[0]["sub_tier"], "primary")
        self.assertEqual(out[1]["sub_tier"], "aside")

    def test_assign_sub_tier_all_primary_when_ratio_low(self):
        lines = [{"bbox": [0, 0, 100, 30]}, {"bbox": [0, 40, 110, 70]}]  # 宽 100/110 → 比值<1.4
        out = geometry.assign_sub_tier(lines, ratio=1.4)
        self.assertEqual([line["sub_tier"] for line in out], ["primary", "primary"])

    def test_assign_sub_tier_empty(self):
        self.assertEqual(geometry.assign_sub_tier([]), [])

    def test_build_regions_nests_child_lines(self):
        # 容器大框 + 内部碎片子框 → 子框挂 child_lines, 独立框自成 region
        blocks = [
            {"node_id": "container", "bbox": [0, 0, 200, 200], "bubble_type": "dialogue"},
            {"node_id": "inner", "bbox": [10, 10, 190, 60], "bubble_type": "dialogue"},  # 全嵌套
            {"node_id": "separate", "bbox": [300, 300, 400, 400], "bubble_type": "sfx"},   # 独立
        ]
        regions = geometry.build_regions(blocks)
        self.assertEqual(len(regions), 2)
        cont = next(r for r in regions if r["node_id"] == "container")
        self.assertEqual(len(cont["child_lines"]), 1)
        self.assertEqual(cont["child_lines"][0]["node_id"], "inner")
        # child_lines 被赋予 sub_tier
        self.assertIn(cont["child_lines"][0]["sub_tier"], ("primary", "aside"))

    def test_build_regions_dedup_overlapping_fragment(self):
        # p17 案例: primary 与嵌套 aside 几乎完全重合(IoA≈1.0) → 碎片去重只留一个
        blocks = [
            {"node_id": "container", "bbox": [1615, 2100, 1840, 2921], "bubble_type": "dialogue"},
            {"node_id": "primary", "bbox": [1720, 2094, 1843, 2778], "bubble_type": "dialogue"},
            {"node_id": "frag", "bbox": [1749, 2119, 1814, 2762], "bubble_type": "dialogue"},  # 完全重叠
            {"node_id": "aside2", "bbox": [1629, 2643, 1698, 2915], "bubble_type": "dialogue"},  # 独立段
        ]
        regions = geometry.build_regions(blocks)
        cont = next(r for r in regions if r["node_id"] == "container")
        ids = [line["node_id"] for line in cont["child_lines"]]
        # frag 与 primary 重叠被去重, 保留 primary + aside2
        self.assertEqual(sorted(ids), ["aside2", "primary"])
        self.assertNotIn("frag", ids)

    def test_build_regions_no_nesting(self):
        blocks = [{"node_id": "a", "bbox": [0, 0, 50, 50]},
                  {"node_id": "b", "bbox": [100, 100, 150, 150]}]
        regions = geometry.build_regions(blocks)
        self.assertEqual(len(regions), 2)
        self.assertTrue(all(r["child_lines"] == [] for r in regions))


if __name__ == "__main__":
    unittest.main()
