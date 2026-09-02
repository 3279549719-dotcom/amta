"""阶段注册表 — 声明式定义每个阶段的工位函数、依赖关系、默认配置。

这是编排器的 Seam（接缝）所在：编排器只依赖这里的 StageSpec 声明，
不需要知道每个工位具体做什么。新增阶段 = 写一个工位函数 + 在这里加一行注册。

设计原则（codebase-design）：
- One adapter means a hypothetical seam. Two adapters means a real one.
  这里已经有 detect / ocr / translate 三个 adapter，后续还有 inpaint / typeset / segment，
  所以这个 seam 是真实存在的，不是假设的。
- 阶段之间的依赖关系用 consumes / produces 声明，编排器自动解析上游产物路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import StationFn


@dataclass
class StageSpec:
    """一个阶段的声明 — 工位函数是谁、依赖什么上游、产出什么、默认配置是什么。

    consumes: 依赖的上游阶段名列表（编排器会把这些阶段的产物路径放进 ctx.inputs）
    produces: 产出的产物类型名（编排器用这个名字在 artifacts_dir 里找产物文件做断点判断）
    default_config: 默认配置，调用方可以通过 PipelineConfig.stage_configs 覆盖
    """
    name: str
    station: StationFn
    consumes: list[str] = field(default_factory=list)
    produces: str = ""
    default_config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 阶段注册表 — 所有阶段在这里声明
# ---------------------------------------------------------------------------
# 注意：这里 import 的是适配器（adapters），不是原始工位函数。
# 适配器把统一的 StationContext 转换成原始工位的参数，把原始返回值转换成 StationResult。
# 这样原始工位不需要改，编排器也不需要知道原始工位的签名差异。

def _build_registry() -> dict[str, StageSpec]:
    """延迟构建注册表，避免循环 import。"""
    from .adapters.detect import run as detect_run
    from .adapters.ocr import run as ocr_run
    from .adapters.translate import run as translate_run

    return {
        "detect": StageSpec(
            name="detect",
            station=detect_run,
            consumes=[],
            produces="detection",
            default_config={
                "detectors": "all",
                "conf_threshold": 0.7,
                "host": "127.0.0.1",
                "port": 4000,
            },
        ),
        "ocr": StageSpec(
            name="ocr",
            station=ocr_run,
            consumes=["detect"],
            produces="canon",
            default_config={
                "engine": "auto",
                "vlm_enabled": False,
                "rule_filter": False,
            },
        ),
        "translate": StageSpec(
            name="translate",
            station=translate_run,
            consumes=["ocr"],
            produces="translation",
            default_config={
                "mode": "minimal",
                "vlm_enabled": True,
            },
        ),
        # ------------------------------------------------------------------
        # 后续阶段预留 — 工位函数待实现，这里先声明依赖关系和默认配置
        # 实现后把 station 换成真实的适配器即可，编排器不需要改
        # ------------------------------------------------------------------
        "inpaint": StageSpec(
            name="inpaint",
            station=_not_implemented("inpaint"),
            consumes=["detect"],
            produces="inpaint",
            default_config={
                "engine": "lama",
                "fill_white_bubbles": True,
            },
        ),
        "typeset": StageSpec(
            name="typeset",
            station=_not_implemented("typeset"),
            consumes=["translate", "inpaint"],
            produces="typeset",
            default_config={
                "font": "auto",
                "direction": "auto",
            },
        ),
        "segment": StageSpec(
            name="segment",
            station=_not_implemented("segment"),
            consumes=["detect"],
            produces="segment",
            default_config={},
        ),
    }


def _not_implemented(stage_name: str) -> StationFn:
    """占位工位函数 — 后续阶段未实现时用这个，调用时会报清晰的错误。"""
    def _placeholder(ctx):
        from .context import StationResult
        return StationResult(
            page=ctx.page,
            stage=stage_name,
            status="failed",
            error=f"阶段 {stage_name} 尚未实现，工位函数待接入",
        )
    return _placeholder


# 全局注册表实例（延迟初始化）
_REGISTRY: dict[str, StageSpec] | None = None


def get_registry() -> dict[str, StageSpec]:
    """获取阶段注册表（单例，延迟初始化）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_stage(name: str) -> StageSpec:
    """获取单个阶段的声明。"""
    reg = get_registry()
    if name not in reg:
        raise ValueError(f"未知阶段 {name!r}，可用阶段: {sorted(reg.keys())}")
    return reg[name]


def available_stages() -> list[str]:
    """列出所有可用阶段名。"""
    return list(get_registry().keys())
