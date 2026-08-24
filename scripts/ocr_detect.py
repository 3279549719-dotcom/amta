"""Benchmark B (跑) OCR 探测：对每页跑 detector+OCR 流水线，收集 3 引擎的识别文字。

输出 output/data/ocr_result.json:
  { page_N: { path, engines: { "<ocr_engine>": [{bbox, ocr, confidence}], ... } }, ... }
用法: python scripts/ocr_detect.py <src_dir> [page_count]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import DATA, write_json  # noqa: E402
from amta.pipeline import OCR_ENGINES  # noqa: E402
from amta.runner import compact_blocks, run_all_pages  # noqa: E402

OUT = DATA / "ocr_result.json"
DETECTOR = "comic-text-detector"  # produce TextBoxes，作为 OCR 前置


def _page_key(page: Path, idx: int) -> str:
    return f"page_{idx}"


def main(argv: list[str]) -> int:
    src = Path(argv[0])
    max_pages = int(argv[1]) if len(argv) > 1 else 10
    pages = sorted(src.glob("*.jpg"), key=lambda p: int(p.stem))[:max_pages]
    steps = {eng: [DETECTOR, eng] for eng in OCR_ENGINES}
    print(f"[ocr] {len(pages)} pages, ocr_engines={OCR_ENGINES}, detector={DETECTOR}", flush=True)
    client = KoharuClient()
    client.wait_server()
    out = run_all_pages(client, pages, steps, _page_key, prefix="amta-ocr",
                        timeout=1800, require_completed=False, label="ocr")
    # 兼容旧输出形状：只留 {bbox, ocr, confidence}（下游评测依赖 bbox 字段）
    for entry in out.values():
        entry["engines"] = {eng: compact_blocks(blocks, ("ocr", "confidence"))
                            for eng, blocks in entry["engines"].items()}
    write_json(OUT, out)
    print(f"[ocr] done -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
