"""AMTA 纯库包：被 scripts/ 薄 CLI 与 tests/ 引用。

对外稳定接口：
- koharu_client.KoharuClient — koharu REST 封装
- pipeline.* — 引擎 DAG 常量
- metrics.* — CER/EM/归一化/匹配
- geometry.* — bbox/iou/并集
"""
from amta import geometry, koharu_client, metrics, pipeline

__all__ = ["geometry", "koharu_client", "metrics", "pipeline"]