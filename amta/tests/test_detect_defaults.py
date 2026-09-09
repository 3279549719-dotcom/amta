"""detect 阶段默认配置测试 — TDD RED。

验证：
1. detect_page 的默认 conf_threshold 是 0.5（ADR-Q1: 0.7→0.5 甜点）
2. orchestrator registry 的 detect 阶段默认 conf_threshold 是 0.5
3. tiling_enabled 默认是 False（瓦片化为可选功能，默认关闭）
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.detect_station import detect_page  # noqa: E402


class TestDetectPageDefaults:
    """detect_page 函数签名的默认参数。"""

    def test_default_conf_threshold_is_0_5(self):
        """ADR-Q1: 主链 conf 默认从 0.7 降到 0.5（甜点：+6真小字，0杂质，0额外时间）。"""
        sig = inspect.signature(detect_page)
        default = sig.parameters["conf_threshold"].default
        assert default == 0.5, f"expected conf_threshold default=0.5, got {default}"

    def test_tiling_enabled_default_is_false(self):
        """瓦片化为可选功能，默认关闭（时间成本8.5倍，收益有限）。"""
        sig = inspect.signature(detect_page)
        default = sig.parameters["tiling_enabled"].default
        assert default is False, f"expected tiling_enabled default=False, got {default}"


class TestOrchestratorRegistryDefaults:
    """orchestrator registry 的 detect 阶段默认配置。"""

    def test_detect_stage_default_conf_threshold_is_0_5(self):
        """编排器注册表的 detect 阶段默认 conf_threshold 应该和 detect_page 一致。"""
        from amta.orchestrator.registry import _build_registry
        registry = _build_registry()
        assert "detect" in registry
        default_conf = registry["detect"].default_config.get("conf_threshold")
        assert default_conf == 0.5, f"expected registry detect conf_threshold=0.5, got {default_conf}"

    def test_detect_stage_default_tiling_disabled(self):
        """编排器注册表的 detect 阶段默认不开启瓦片化。"""
        from amta.orchestrator.registry import _build_registry
        registry = _build_registry()
        tiling = registry["detect"].default_config.get("tiling_enabled")
        assert tiling is False, f"expected registry detect tiling_enabled=False, got {tiling}"
