"""Stage 1 检测工位 — raw 页图 → DetectionArtifact（深模块，修 F5/F8 检测侧）。

藏匿：KoharuClient 生命周期、4-detector 并集 → compact → union_blocks →
assign_category → mark_contained → region_id 单空间重编、raw_engines 落盘、
trace 落盘、image_meta。接缝：client 注入（协议=KoharuClient 方法面），
测试用 tests/fakes.FakeKoharu。脚本 01_detect.py 只剩 CLI。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.geometry import assign_category, mark_contained, union_blocks
from amta.koharu_client import KoharuClient
from amta.paths import write_json
from amta.pipeline import DETECTOR_STEPS
from amta.runner import compact_blocks, run_all_pages

_FIELDS = ("node_id", "bbox", "bubble_type", "text")


def detect_page(work_id: str, raw_page: Path, artifacts_dir: Path, *,
                page_idx: int | None = None, client: KoharuClient | None = None,
                host: str = "127.0.0.1", port: int = 4000,
                out_path: Path | None = None) -> dict:
    """一页图 → 检测产物（落盘 + 返回 doc）。修 F3/F5/F7。"""
    client = client or KoharuClient(host=host, port=port)
    client.wait_server(timeout=60)
    idx = page_idx if page_idx is not None else artifacts.page_idx_from_raw(raw_page)
    page = artifacts.page_key(idx)
    artifacts_dir = Path(artifacts_dir)

    results = run_all_pages(client, [raw_page], DETECTOR_STEPS,
                            prefix="amta-det", timeout=1200, label="01_detect")
    per_engine = next(iter(results.values()))["engines"]
    comp = {eng: compact_blocks(blks, _FIELDS, source_engine=eng)
            for eng, blks in per_engine.items()}

    # Tracing: 并集前落盘 4-detector 原始框（未去重），杜绝黑盒缺口（原 01 语义保留）
    write_json(artifacts_dir / f"{page}_detect_raw_engines.json", {
        "work_id": work_id, "page": page, "source": str(raw_page),
        "engines": {eng: list(blks) for eng, blks in comp.items()},
        "per_engine_count": {eng: len(blks) for eng, blks in comp.items()},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })

    blocks = union_blocks(comp)
    after_union = len(blocks)
    blocks = assign_category(blocks)
    for b in blocks:
        if not isinstance(b.get("source_engines"), list):
            b["source_engines"] = []
    blocks = mark_contained(blocks)
    blocks = artifacts.normalize_region_ids(blocks, idx)  # 单空间（修 F3）

    img = Image.open(raw_page)
    artifacts.write_trace(artifacts_dir, page, "01_detect", {
        "per_engine_raw": {eng: len(blks) for eng, blks in comp.items()},
        "after_union": after_union,
        "after_mark_contained": len(blocks),
        "contained_pairs": [(b["region_id"], b["contained_in"])
                            for b in blocks if b.get("contained_in")],
        "detect_steps": list(DETECTOR_STEPS.keys()),
    })

    doc = artifacts.stamp({
        "work_id": work_id, "page": page, "source": str(raw_page),
        "image_meta": {"width": img.width, "height": img.height,
                       "channels": len(img.getbands())},
        "blocks": blocks, "n_boxes": len(blocks),
        "detect_steps": list(DETECTOR_STEPS.keys()),
        "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
    }, work_id, page)
    dest = Path(out_path) if out_path else artifacts.artifact_paths(artifacts_dir, page)["detection"]
    write_json(dest, doc)
    return doc
