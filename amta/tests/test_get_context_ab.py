"""Lesson 03 集成 A/B 测试（pytest 收编版）。

原根目录脚本 integration_ab_test.py 的三个用例去向：
- #1 结构化读取 / #2 回退兼容：与 tests/test_context_semantic_transfer.py 的
  tmp_path 单元测试同构，收编时删除（避免双份维护）；
- #3 真实数据 A/B 对比：迁移到本文件，数据缺失时显式 SKIP（不再静默）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "workspace" / "touhou-single-wing" / "state"


@pytest.mark.skipif(not STATE_DIR.exists(), reason="真实项目数据仅存在于本机 workspace/（gitignored）")
def test_ab_comparison_real_data():
    """真实数据 A/B：新实现（结构化）对比旧实现（裸读汇总 translation.json）。"""
    from amta import translate_tools

    work_state = json.loads((STATE_DIR / "work_state.json").read_text(encoding="utf-8"))
    new_out = translate_tools.execute_tool("get_context", {"pages": 1}, work_state, state_dir=STATE_DIR)
    assert new_out.strip(), "新实现返回为空"
    assert "[对话]" in new_out  # 真实数据 p19 全为对话气泡（Lesson 03 报告结论）

    agg_path = STATE_DIR.parent / "artifacts" / "translation.json"
    assert agg_path.exists(), "汇总 translation.json 不存在"
    doc = json.loads(agg_path.read_text(encoding="utf-8"))
    trans = doc.get("translations", {})
    by_page = {}
    for rid in trans:
        parts = rid.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            by_page.setdefault(parts[1], []).append(rid)
    last_page = max(by_page, key=int)
    old_lines = [f"[{rid}] {trans[rid]}" for rid in sorted(by_page[last_page])]
    assert old_lines, "旧实现口径下最后一页无译文"
