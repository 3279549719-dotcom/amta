"""koharu 流水线执行器 — 统一「建项目→传图→跑流水线→等待→回读→关项目」模式。

合并自 benchmark.run_detector / ocr_detect.run_ocr / recall_detect.run_one / smoke_test 的重复实现。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from amta.backends.koharu_client import KoharuClient, KoharuError
from amta.common.geometry import bbox_from_block

_COMPLETED = frozenset({"completed"})


def run_pipeline_once(
    client: KoharuClient,
    page: Path,
    steps: list[str],
    *,
    prefix: str = "amta",
    timeout: int = 1200,
    require_completed: bool = True,
) -> list[dict]:
    """在独立临时项目里跑一次流水线，返回 collect_blocks 结果（自动清理项目）。

    require_completed=False 时 completed_with_errors 也接受（OCR 评测要读部分结果）。
    """
    project = f"{prefix}-{uuid.uuid4().hex[:8]}"
    client.close_current_project()
    client.create_project(project)
    try:
        page_id = client.import_page(page)
        op = client.run_pipeline(page_ids=[page_id], steps=steps)
        result = client.wait_operation(op, timeout=timeout)
        status = result.get("status")
        if status == "failed" or (require_completed and status not in _COMPLETED):
            raise KoharuError(f"{steps} pipeline failed: {result}")
        nodes = client.get_page_nodes(page_id)
        return KoharuClient.collect_blocks(nodes)
    finally:
        client.close_current_project()


def compact_blocks(blocks: list[dict], fields: tuple[str, ...],
                   source_engine: str | None = None) -> list[dict]:
    """collect_blocks 行 → 只保留指定字段 + 计算好的 bbox（评测旧输出形状，消费方依赖 bbox）。

    source_engine 非 None 时注入内部溯源字段 source_engines=[引擎名]（ADR-023），
    供 union_blocks 合并出每个框的检出引擎列表；不传则输出与旧版完全一致。
    """
    out = []
    for b in blocks:
        item = {**{f: b.get(f) for f in fields}, "bbox": bbox_from_block(b)}
        if source_engine is not None:
            item["source_engines"] = [source_engine]
        out.append(item)
    return out


def page_key(page: Path, idx: int) -> str:
    """默认页键：page_{idx}（1 基，page_N ↔ N.jpg）。"""
    return f"page_{idx}"


def run_all_pages(
    client: KoharuClient,
    pages: list[Path],
    steps_by_engine: dict[str, list[str]],
    key_fn: Callable[[Path, int], str] = page_key,
    *,
    prefix: str = "amta",
    timeout: int = 1200,
    require_completed: bool = True,
    label: str = "run",
) -> dict[str, dict]:
    """对每页跑全部引擎；单引擎失败记为 [] 不拖垮整页。

    返回 {page_key: {"path": str, "engines": {engine: [blocks]}}}。
    """
    out: dict[str, dict] = {}
    for idx, page in enumerate(pages):
        key = key_fn(page, idx)
        out[key] = {"path": str(page), "engines": {}}
        for engine, steps in steps_by_engine.items():
            print(f"[{label}] {key} / {engine} ...", flush=True)
            try:
                out[key]["engines"][engine] = run_pipeline_once(
                    client, page, steps, prefix=prefix, timeout=timeout,
                    require_completed=require_completed,
                )
            except Exception as e:  # noqa: BLE001 — 单引擎失败不拖垮整页
                print(f"[{label}] WARN {key} {engine}: {e}", flush=True)
                out[key]["engines"][engine] = []
    return out
