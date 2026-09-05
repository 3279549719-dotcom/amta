"""临时脚本：用当前代码重跑 p11-15 翻译阶段，验证数组契约+护栏修复生效。

用法：cd "E:\manga translator agent" && python rerun_translation_11_15.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "amta" / "src"))

from amta.stage3_minimal import translate_page_minimal
from amta.guardrails import mechanical_guardrails

WORK = "touhou-e2e-orchestrator"
ART = Path("amta/workspace/touhou-e2e-orchestrator/artifacts")
STATE_DIR = Path("amta/workspace/touhou-e2e-orchestrator")


def main():
    for page in range(11, 16):
        page_key = f"page_{page}"
        canon_path = ART / f"{page_key}_canon.json"
        out_path = ART / f"{page_key}_translation.json"

        if not canon_path.exists():
            print(f"  SKIP {page_key}: canon not found")
            continue

        canon_doc = json.loads(canon_path.read_text(encoding="utf-8"))
        canon_items = canon_doc.get("items", [])
        print(f"\n=== 重跑 {page_key} 翻译（{len(canon_items)}条）===")

        try:
            result = translate_page_minimal(
                work_id=WORK,
                canon=canon_items,
                state_dir=STATE_DIR,
                page=str(page),
                vlm_enabled=False,  # 先禁用VLM，快速验证数组契约
            )
        except Exception as e:
            print(f"  ✗ 翻译失败: {e}")
            continue

        translations = result.get("translations", {})
        print(f"  翻译条数: {len(translations)}")

        # 检查护栏
        problems = mechanical_guardrails(canon_items, translations)
        if problems:
            print(f"  ⚠ 护栏告警 ({len(problems)}):")
            for p in problems[:5]:
                print(f"    - {p}")
        else:
            print(f"  ✓ 护栏通过")

        # 保存
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已保存: {out_path}")

        # p14 特殊验证
        if page == 14:
            print(f"\n  --- p14 错位验证 ---")
            for rid in ["r01", "r02", "r10", "r11"]:
                txt = translations.get(rid, "MISSING")
                print(f"    {rid}: {txt[:40]}")

    print("\n=== 全部完成 ===")


if __name__ == "__main__":
    main()
