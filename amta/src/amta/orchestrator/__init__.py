"""amta.orchestrator — 管线编排器（深模块）。

唯一公共入口：
  run_pipeline(config: PipelineConfig) -> PipelineResult

数据契约：
  PipelineConfig   — 调用方告诉编排器跑什么
  PipelineResult   — 编排器告诉调用方结果
  StationContext   — 编排器传给工位的统一输入
  StationResult    — 工位返回给编排器的统一输出

阶段注册：
  get_registry()   — 获取所有阶段声明
  available_stages() — 列出可用阶段名

设计依据：docs/superpowers/specs/2026-09-02-pipeline-orchestrator-design.md
"""
from .context import (
    PipelineConfig,
    PipelineResult,
    StationContext,
    StationResult,
    StationFn,
)
from .pipeline import run_pipeline
from .registry import (
    StageSpec,
    get_registry,
    get_stage,
    available_stages,
)

__all__ = [
    "run_pipeline",
    "PipelineConfig",
    "PipelineResult",
    "StationContext",
    "StationResult",
    "StationFn",
    "StageSpec",
    "get_registry",
    "get_stage",
    "available_stages",
]
