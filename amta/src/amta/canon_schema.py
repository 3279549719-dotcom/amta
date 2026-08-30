"""pre-translate Input schema 校验（ADR-016）— 逻辑已收编 amta.artifacts（深接口改造）。

保留模块与函数名作兼容别名：scripts/03_translate.py 与旧测试仍 import 本处。
"""
from __future__ import annotations

from amta.artifacts import CATEGORIES, SUB_TIERS, validate_canon_items

__all__ = ["validate_canon", "CATEGORIES", "SUB_TIERS"]

# 兼容别名（原唯一实现迁移至 artifacts.validate_canon_items，语义不变）
validate_canon = validate_canon_items
