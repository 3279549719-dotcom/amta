"""临时脚本：用当前代码重跑 p11-15 typeset 阶段，验证方向修复。

用法：cd "E:\manga translator agent" && python rerun_typeset_11_15.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "amta" / "src"))

from amta.typeset_station import run as typeset_run

WORK = "touhou-e2e-orchestrator"
ART = Path("amta/workspace/touhou-e2e-orchestrator/artifacts")


def main():
    for page in range(11, 16):
        page_key = f"page_{page}"
        canon_path = ART / f"{page_key}_canon.json"
        trans_path = ART / f"{page_key}_translation.json"
        det_path = ART / f"{page_key}_detection.json"
        clean_path = ART / "clean" / f"{page_key}_clean.png"
        out_path = ART / f"{page_key}_typeset.json"
        final_path = ART / "final" / f"{page_key}_final.png"

        if not all(p.exists() for p in [canon_path, trans_path, det_path, clean_path]):
            print(f"  SKIP {page_key}: missing input files")
            for p in [canon_path, trans_path, det_path, clean_path]:
                if not p.exists():
                    print(f"    missing: {p}")
            continue

        print(f"\n=== 重跑 {page_key} typeset ===")
        result = typeset_run(
            work_id=WORK,
            canon_path=canon_path,
            trans_path=trans_path,
            det_path=det_path,
            clean_path=clean_path,
            out_path=out_path,
            final_path=final_path,
        )
        rendered = result.get("rendered_items", [])
        print(f"  渲染条数: {len(rendered)}")
        # 统计方向分布
        dirs = {}
        for item in rendered:
            d = item.get("layout_direction", "?")
            dirs[d] = dirs.get(d, 0) + 1
        print(f"  方向分布: {dirs}")
        # 打印每个区域的方向和首选方向
        for item in rendered:
            rid = item.get("region_id", "?")
            d = item.get("layout_direction", "?")
            pref = item.get("preferred_direction", "?")
            fs = item.get("font_size", "?")
            print(f"    {rid}: layout={d} preferred={pref} size={fs}px")

        # p11 r04 特殊验证
        if page == 11:
            r04 = [x for x in rendered if x.get("region_id") == "r04"]
            if r04:
                print(f"\n  ★ p11 r04 验证: layout={r04[0]['layout_direction']} (期望 horizontal)")
        # p13 r02 特殊验证
        if page == 13:
            r02 = [x for x in rendered if x.get("region_id") == "r02"]
            if r02:
                print(f"\n  ★ p13 r02 验证: layout={r02[0]['layout_direction']} (期望 vertical)")

    print("\n=== 全部完成 ===")


if __name__ == "__main__":
    main()
