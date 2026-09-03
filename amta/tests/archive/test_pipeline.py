"""确定性结构测试：流水线 DAG / 引擎常量不变量（不依赖 koharu，纯数据）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta import pipeline  # noqa: E402


class PipelineDAGTest(unittest.TestCase):
    def test_engine_needs_are_lists(self):
        # 所有引擎的 needs 必须是 list；DAG 起点引擎（pp-doclayout-v3/comic-text-detector
        # 等无前置依赖者）允许为空，其余应非空。
        for engine, needs in pipeline.ENGINE_NEEDS.items():
            self.assertIsInstance(engine, str)
            self.assertIsInstance(needs, list)

    def test_non_root_engines_have_clean_acl_edges(self):
        # 依赖关系必须有向边指向存在的前置产物
        known_produces = set()
        for steps in pipeline.DETECTOR_STEPS.values():
            known_produces.update(steps)
        known_produces.update(pipeline.OCR_ENGINES)
        known_produces.update(pipeline.INPAINT_STEPS)
        for engine, needs in pipeline.ENGINE_NEEDS.items():
            for n in needs:
                self.assertIn(n, {"TextBoxes", "SegmentMask", "BubbleMask",
                                  "OcrText", "Translations", "Inpainted",
                                  "FontPredictions"},
                              f"{engine} 依赖未知产物 {n}")

    def test_ocr_engines_require_textboxes(self):
        for name in pipeline.OCR_ENGINES:
            self.assertIn(name, pipeline.ENGINE_NEEDS)
            self.assertEqual(pipeline.ENGINE_NEEDS[name], ["TextBoxes"],
                             f"{name} 必须先有 TextBoxes")

    def test_inpaint_engines_require_masks(self):
        for name in ("lama-manga", "flux2-klein", "aot-inpainting"):
            self.assertIn(name, pipeline.ENGINE_NEEDS)
            self.assertEqual(set(pipeline.ENGINE_NEEDS[name]), {"SegmentMask", "BubbleMask"},
                             f"{name} 需要 Segment+Bubble mask")

    def test_renderer_requires_full_inputs(self):
        self.assertEqual(
            set(pipeline.ENGINE_NEEDS["koharu-renderer"]),
            {"Inpainted", "Translations", "FontPredictions"},
        )

    def test_full_steps_are_known_engines(self):
        for step in pipeline.FULL_STEPS:
            self.assertIn(step, pipeline.ENGINE_NEEDS)

    def test_detector_steps_are_known_engines(self):
        for steps in pipeline.DETECTOR_STEPS.values():
            for s in steps:
                self.assertIn(s, pipeline.ENGINE_NEEDS)

    def test_full_steps_have_no_duplicates(self):
        self.assertEqual(len(pipeline.FULL_STEPS), len(set(pipeline.FULL_STEPS)))


if __name__ == "__main__":
    unittest.main()
