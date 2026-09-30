"""阶段注册表 — 声明式定义每个阶段的工位函数、依赖关系、默认配置。

这是编排器的 Seam（接缝）所在：编排器只依赖这里的 StageSpec 声明，
不需要知道每个工位具体做什么。新增阶段 = 写一个工位函数 + 在这里加一行注册。

设计原则（codebase-design）：
- One adapter means a hypothetical seam. Two adapters means a real one.
  这里有 detect / ocr / translate / inpaint / typeset 五个 adapter，
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
    code_files: 影响该阶段输出的代码文件（相对于 src/amta/ 的路径，如 "typeset/typeset_engine.py"）
                这些文件的哈希会存入 fingerprint，代码变了自动触发重跑
    """
    name: str
    station: StationFn
    consumes: list[str] = field(default_factory=list)
    produces: str = ""
    default_config: dict[str, Any] = field(default_factory=dict)
    code_files: list[str] = field(default_factory=list)


def _build_registry() -> dict[str, StageSpec]:
    """延迟构建注册表，避免循环 import。"""
    from .adapters.detect import run as detect_run
    from .adapters.inpaint import run as inpaint_run
    from .adapters.ocr import run as ocr_run
    from .adapters.translate import run as translate_run
    from .adapters.typeset import run as typeset_run

    return {
        "detect": StageSpec(
            name="detect",
            station=detect_run,
            consumes=[],
            produces="detection",
            default_config={
                "conf_threshold": 0.5,
                "tiling_enabled": False,
                "tiling_cols": 3,
                "tiling_rows": 4,
                "tiling_conf": 0.3,
                "tiling_nms_iou": 0.5,
                "coverage_thresh": 0.5,
            },
            code_files=[
                "orchestrator/adapters/detect.py",
                "stations/detect_station.py",
                "common/geometry.py",
                "stores/artifacts.py",
                "common/paths.py",
            ],
        ),
        "ocr": StageSpec(
            name="ocr",
            station=ocr_run,
            consumes=["detect"],
            produces="canon",
            default_config={
                "engine": "hayai",
                "vlm_enabled": False,
            },
            code_files=[
                "orchestrator/adapters/ocr.py",
                "backends/vlm_verify.py",
                "backends/chat_client.py",
                "common/config.py",
                "stations/ocr_station.py",
                "backends/ocr_engines.py",
                "stations/vlm_layout.py",
                "guards/canon_schema.py",
                "stores/artifacts.py",
                "common/geometry.py",
                "common/paths.py",
            ],
        ),
        "translate": StageSpec(
            name="translate",
            station=translate_run,
            consumes=["ocr"],
            produces="translation",
            default_config={},
            code_files=[
                "orchestrator/adapters/translate.py",
                "orchestrator/pipeline.py",
                "guards/canon_schema.py",
                "common/config.py",
                "common/metrics.py",
                "common/workstate.py",
                "translation/translate_station.py",
                "translation/translate.py",
                "translation/stage3_minimal.py",
                "guards/guardrails.py",
                "guards/glossary.py",
                "guards/term_dict.py",
                "guards/term_replace.py",
                "guards/pre_scan.py",
                "backends/chat_client.py",
                "stores/artifacts.py",
                "common/paths.py",
            ],
        ),
        "inpaint": StageSpec(
            name="inpaint",
            station=inpaint_run,
            consumes=["detect", "translate"],
            produces="inpaint",
            default_config={
                "inpaint_engine": "lama-manga",
            },
            code_files=[
                "orchestrator/adapters/inpaint.py",
                "inpaint/inpaint_station.py",
                "inpaint/inpaint_strategy.py",
                "inpaint/local_lama_inpainter.py",
                "inpaint/_lama_ffc.py",
                "inpaint/_lama_model.py",
                "inpaint/_lama_util.py",
                "common/images.py",
                "common/geometry.py",
                "stores/artifacts.py",
                "common/paths.py",
            ],
        ),
        "typeset": StageSpec(
            name="typeset",
            station=typeset_run,
            consumes=["detect", "ocr", "translate", "inpaint"],
            produces="typeset",
            default_config={
                "export_psd": False,
            },
            code_files=[
                "orchestrator/adapters/typeset.py",
                "typeset/psd_jsx_export.py",
                "typeset/psd_jsx.py",
                "typeset/psd_export.py",
                "typeset/vertical_punct.py",
                "stations/vlm_layout.py",
                "typeset/typeset_station.py",
                "typeset/typeset_engine.py",
                "typeset/typeset_render.py",
                "typeset/vlm_render.py",
                "typeset/fonts.py",
                "common/geometry.py",
                "stores/artifacts.py",
                "common/paths.py",
            ],
        ),
        "segment": StageSpec(
            name="segment",
            station=_not_implemented("segment"),
            consumes=["detect"],
            produces="segment",
            default_config={},
            code_files=[],
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


_REGISTRY: dict[str, StageSpec] | None = None


def get_registry() -> dict[str, StageSpec]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_stage(name: str) -> StageSpec:
    reg = get_registry()
    if name not in reg:
        raise ValueError(f"未知阶段 {name!r}，可用阶段: {sorted(reg.keys())}")
    return reg[name]


def available_stages() -> list[str]:
    return list(get_registry().keys())
