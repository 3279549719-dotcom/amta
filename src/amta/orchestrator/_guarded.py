"""Adapter 守卫 — 把五个 adapter 里逐字重复的 try/except/计时/StationResult 包装收编。

每个 adapter 只写自己的业务逻辑（调哪个 station、stats 取哪几个字段），
计时、异常捕获、失败 StationResult 构造都在这里统一做。

用法：
    from .._guarded import guarded

    def run(ctx: StationContext) -> StationResult:
        def _do():
            out_path = ...
            doc = some_station(...)
            return out_path, {"n_foo": doc.get("n_foo", 0)}
        return guarded(ctx, "detect", _do)
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .context import StationContext, StationResult


def guarded(
    ctx: StationContext,
    stage_name: str,
    fn: Callable[[], tuple[Path | None, dict[str, Any]]],
) -> StationResult:
    """跑一个 adapter 函数，统一计时 + 异常捕获 + StationResult 包装。

    fn 返回 (output_artifact, stats_dict)。
    fn 抛异常 → status="failed"，error 截到 200 字符。
    """
    t0 = time.perf_counter()
    try:
        output_artifact, stats = fn()
        return StationResult(
            page=ctx.page,
            stage=stage_name,
            status="ok",
            output_artifact=output_artifact,
            duration_s=round(time.perf_counter() - t0, 2),
            stats=stats,
        )
    except Exception as e:
        return StationResult(
            page=ctx.page,
            stage=stage_name,
            duration_s=round(time.perf_counter() - t0, 2),
            status="failed",
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
