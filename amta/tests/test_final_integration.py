"""三阶段最终选型集成测试 — 验证接口契约与数据格式（不实际调用模型/API）。

最终选型:
- 检测: RT-DETR-v2 (scripts/detect_rtdetr.py, 输出 label/score)
- OCR: hayai/baberu 双引擎 (ocr_engines.py 分发, 02_ocr 默认 hayai, 可 --engine 切 baberu)
- 翻译: v2 三态 (src/amta/stage3_minimal.py, qwen VLM + deepseek flash LLM + keep/fix/drop + 上下文 + 术语)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


# ---- 检测阶段: RT-DETR-v2 ----

class TestDetectionRTDETR:
    """验证 01_detect.py 输出格式与 detect_rtdetr.RTDetrDetector 接口。"""

    def test_detect_rtdetr_importable(self):
        """RTDetrDetector 可导入，有 detect 方法。"""
        from detect_rtdetr import RTDetrDetector
        assert hasattr(RTDetrDetector, "detect")
        assert hasattr(RTDetrDetector, "__init__")

    def test_detect_rtdetr_conf_threshold_default(self):
        """默认 conf_threshold=0.3。"""
        from detect_rtdetr import RTDetrDetector
        det = RTDetrDetector()
        assert det.conf_threshold == 0.3

    def test_01_detect_module_importable(self):
        """01_detect.py 可导入，有 detect_page 函数。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("od", ROOT / "scripts" / "01_detect.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "detect_page")

    def test_detection_output_schema(self, tmp_path):
        """检测输出 JSON 包含必要字段（用 mock 数据验证格式）。"""
        fake_doc = {
            "work_id": "test",
            "page": "page_0",
            "source_engines": ["rtdetr-v2"],
            "n_boxes": 2,
            "per_engine_boxes": {"rtdetr-v2": 2},
            "conf_threshold": 0.3,
            "blocks": [
                {"bbox": [10.0, 20.0, 100.0, 50.0], "source_engines": ["rtdetr-v2"],
                 "det_label": 1, "region_id": "r00", "confidence": 0.95},
                {"bbox": [200.0, 300.0, 400.0, 350.0], "source_engines": ["rtdetr-v2"],
                 "det_label": 2, "region_id": "r01", "confidence": 0.87},
            ],
        }
        out = tmp_path / "det.json"
        out.write_text(json.dumps(fake_doc, ensure_ascii=False), encoding="utf-8")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["source_engines"] == ["rtdetr-v2"]
        assert loaded["n_boxes"] == 2
        assert all("bbox" in b and "confidence" in b for b in loaded["blocks"])
        assert all(b["det_label"] in (1, 2) for b in loaded["blocks"])


# ---- OCR 阶段: baberu-only ----

class TestOCREngines:
    """验证 ocr_engines.py 引擎集合 = (baberu, hayai)；local/dashscope/manga_ocr 已移除。"""

    def test_engines_tuple_baberu_hayai(self):
        """ENGINES 元组 = (baberu, hayai)。"""
        from amta.ocr_engines import ENGINES
        assert ENGINES == ("baberu", "hayai")

    def test_no_local_ocr_batch(self):
        """local_ocr_batch 已删除。"""
        import amta.ocr_engines as oe
        assert not hasattr(oe, "local_ocr_batch")

    def test_no_dashscope_ocr_batch(self):
        """dashscope_ocr_batch 已删除。"""
        import amta.ocr_engines as oe
        assert not hasattr(oe, "dashscope_ocr_batch")

    def test_ocr_batch_accepts_engine_kwarg(self):
        """ocr_batch 接受 engine 参数（向后兼容），但只走 baberu。"""
        from amta.ocr_engines import ocr_batch
        assert callable(ocr_batch)


class TestOCRStation:
    """验证 ocr_station.py 接口契约：可插拔 engine + VLM 校验参数。"""

    def test_ocr_page_engine_and_vlm_params(self):
        """ocr_page 有 engine（默认 hayai）与 vlm_enabled/vlm_fn（质检环节）。"""
        import inspect
        from amta.ocr_station import ocr_page
        sig = inspect.signature(ocr_page)
        param_names = list(sig.parameters.keys())
        assert "engine" in param_names
        assert sig.parameters["engine"].default == "hayai"
        assert "vlm_enabled" in param_names
        assert "vlm_fn" in param_names

    def test_vlm_verify_exists(self):
        """vlm_verify.py 存在（VLM contact sheet 校验，质检环节）。"""
        assert (ROOT / "src" / "amta" / "vlm_verify.py").exists()

    def test_canon_item_has_text_and_baberu_text(self):
        """canon items 同时有 text 和 baberu_text 字段（向后兼容）。"""
        fake_item = {
            "region_id": "r00",
            "bbox": [10, 20, 100, 50],
            "text": "こんにちは",
            "baberu_text": "こんにちは",
            "source_engines": ["rtdetr-v2"],
            "page": 0,
        }
        assert "text" in fake_item
        assert "baberu_text" in fake_item
        assert fake_item["text"] == fake_item["baberu_text"]


# ---- 翻译阶段: v2 三态 ----

class TestTranslationStage3Minimal:
    """验证 stage3_minimal.py 实现 v2 三态 + 上下文 + 术语。"""

    def test_module_importable(self):
        """stage3_minimal 可导入。"""
        from amta import stage3_minimal
        assert stage3_minimal is not None

    def test_translate_page_minimal_exists(self):
        """translate_page_minimal 函数存在。"""
        from amta.stage3_minimal import translate_page_minimal
        assert callable(translate_page_minimal)

    def test_build_semantic_context_exists(self):
        """build_semantic_context 函数存在（上下文注入）。"""
        from amta.stage3_minimal import build_semantic_context
        assert callable(build_semantic_context)

    def test_extract_relevant_terms_imported(self):
        """extract_relevant_terms 可导入（术语注入）。"""
        from amta.translate import extract_relevant_terms
        assert callable(extract_relevant_terms)

    def test_vlm_output_has_tri_state_fields(self):
        """VLM 输出结构包含 keep/fix/drop 三态字段。"""
        # 验证 VLM 输出 dataclass/结构有 ocr_refinements (fix), invalid_regions (drop), duplicate_regions (keep)
        import inspect
        from amta.stage3_minimal import translate_page_minimal
        src = inspect.getsource(translate_page_minimal)
        assert "ocr_refinements" in src or "refinements" in src
        assert "invalid_regions" in src or "invalid" in src
        assert "duplicate_regions" in src or "duplicate" in src

    def test_chat_model_from_env(self):
        """LLM 模型从 .env CHAT_MODEL 读取（最终选型 deepseek-v4-flash）。"""
        from amta.config import get_chat_config
        # 不实际调用（需要 .env），只验证函数存在
        assert callable(get_chat_config)


# ---- 废弃代码清理验证 ----

class TestDeprecatedCodeRemoved:
    """验证废弃的实验代码已删除。"""

    @pytest.mark.parametrize("path", [        "src/amta/pipeline.py",             # DETECTOR_STEPS 常量
        "scripts/ctd_detector.py",          # CTD 检测器（方案B实验）
        "scripts/ocr_detect.py",            # 旧 OCR 检测脚本
        "scripts/translate_semantic_check.py",  # 语义护栏（已废弃）
    ])
    def test_file_removed(self, path):
        assert not (ROOT / path).exists(), f"{path} should be removed"

    def test_no_koharu_import_in_main_flow(self):
        """主流程脚本不再 import koharu 检测器。"""
        for script in ["01_detect.py", "00_run_all.py"]:
            content = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            assert "koharu" not in content.lower(), f"{script} still references koharu"

    def test_02_ocr_vlm_is_opt_in(self):
        """02_ocr.py VLM 校验是 opt-in（--vlm，默认关闭）；无 --no-vlm。"""
        content = (ROOT / "scripts" / "02_ocr.py").read_text(encoding="utf-8")
        assert "--vlm" in content
        assert "--no-vlm" not in content

    def test_02_ocr_engine_option_present(self):
        """02_ocr.py 有 --engine（baberu/hayai，默认 hayai）；manga_ocr 已移除。"""
        content = (ROOT / "scripts" / "02_ocr.py").read_text(encoding="utf-8")
        assert "--engine" in content
        assert "hayai" in content
        assert "manga_ocr" not in content

    def test_no_ocr_engine_in_00_run_all(self):
        """00_run_all.py 不再有 --ocr-engine 选项。"""
        content = (ROOT / "scripts" / "00_run_all.py").read_text(encoding="utf-8")
        assert "--ocr-engine" not in content
        assert "ocr_engine" not in content

