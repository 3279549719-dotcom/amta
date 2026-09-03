"""AMTA 冒烟测试：验证 koharu headless API 通路（建项目→传图→跑检测→读场景→关项目）。"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.koharu_client import KoharuClient  # noqa: E402

PAGE = Path(r"D:\我的汉化\output\单翼停留之地\process\01\page.jpg")
if not PAGE.is_file():
    # 兜底：尝试常见候选页
    for cand in [
        Path(r"D:\我的汉化\output\单翼停留之地\process\01\rendered.png"),
        Path(r"D:\我的汉化\output\灵梦和妹红\process\01\page.jpg"),
    ]:
        if cand.is_file():
            PAGE = cand
            break


def main() -> int:
    c = KoharuClient()
    c.wait_server()
    print(f"[smoke] koharu reachable: {c.base}")

    llm = c.llm_status()
    print(f"[smoke] llm status: {llm.get('status')} model={llm.get('model')}")

    if not PAGE.is_file():
        print(f"[smoke] WARN: no test page found (looked for {PAGE}); skipping pipeline test")
        return 0

    proj = f"amta-smoke-{uuid.uuid4().hex[:8]}"
    c.close_current_project()
    pid = c.create_project(proj)
    print(f"[smoke] project created: {proj} ({pid})")

    page_id = c.import_page(PAGE)
    print(f"[smoke] page imported: {page_id}")

    # 本 smoke 验证 koharu headless API 通路（引擎健康，inpaint/segment 仍依赖 koharu）。
    # 直接跑 koharu 自带的 comic-text-detector；生产检测走 scripts/01_detect.py 本地 ONNX
    # RTDetrDetector（见 test_final_integration::TestDeprecatedCodeRemoved），不在此验证。
    op = c.run_pipeline(page_ids=[page_id], steps=["comic-text-detector"])
    print(f"[smoke] detection pipeline started: {op}")
    result = c.wait_operation(op, timeout=600)
    print(f"[smoke] detection status: {result.get('status')}")

    nodes = c.get_page_nodes(page_id)
    blocks = KoharuClient.collect_blocks(nodes)
    print(f"[smoke] text blocks detected: {len(blocks)}")
    for b in blocks[:5]:
        print(f"   - {b['bubble_type']}: {b['ocr'][:40]!r}")

    seg_ref = c.get_mask_blob_hash(page_id, "segment")
    bubble_ref = c.get_mask_blob_hash(page_id, "bubble")
    print(f"[smoke] segment mask blob: {seg_ref}")
    print(f"[smoke] bubble mask blob: {bubble_ref}")

    c.close_current_project()
    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
