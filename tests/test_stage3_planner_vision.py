"""test_stage3_planner_vision.py — 方案 B（VLM 整页图规划）TDD 测试。

Seam: amta.stage3_planner_vision.run_plan_loop_vision。
网络 LLM 用脚本化 fake 注入（依赖注入，非 mock 被测单元），走真实规划循环。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_DUMMY_IMG = "data:image/png;base64,AAAA"  # 占位 data URL，避免读磁盘、避免降级到纯文本循环


def _fake_llm_once_invalid_then_stop(rid="u01", reason="排线装饰线，非文字"):
    """第一轮 mark_invalid(rid)，第二轮不再调工具（结束循环）。"""
    calls = {"n": 0}

    def fake_llm(messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "tool_calls": [{
                    "function": {
                        "name": "mark_invalid",
                        "arguments": f'{{"region_id": "{rid}", "reason": "{reason}"}}',
                    }
                }],
                "content": None,
            }
        return {"tool_calls": None, "content": "扫描完成。"}

    return fake_llm, calls


def test_vision_loop_valid_regions_excludes_marked():
    """回归 bug：视觉规划循环必须把 canon 传给 PlanResult，valid_regions 不能恒为 []。

    症状：run_plan_loop_vision 用 PlanResult(invalids={}, duplicates={}) 漏传 canon，
    导致 03_translate.py trace 的 n_valid=len(plan.valid_regions) 恒为 0，
    出现 n_regions != n_valid+n_invalid+n_duplicate 的矛盾。
    """
    from amta.stage3_planner_vision import run_plan_loop_vision

    canon = [
        {"region_id": "u00", "baberu_text": "有効な文字"},
        {"region_id": "u01", "baberu_text": "───"},      # 排线，将被标 invalid
        {"region_id": "u02", "baberu_text": "また有効"},
    ]
    fake_llm, calls = _fake_llm_once_invalid_then_stop("u01")

    plan = run_plan_loop_vision(canon, fake_llm, image_data_url=_DUMMY_IMG)

    assert "u01" in plan.invalids
    assert plan.valid_regions == ["u00", "u02"]  # RED：修复前返回 []
    # trace 隐含不变量：三类框数量之和 == 总框数
    assert (len(plan.valid_regions) + len(plan.invalids) + len(plan.duplicates)
            == len(canon))
    assert calls["n"] == 2  # 一轮调工具 + 一轮结束


def test_vision_loop_without_marks_all_regions_valid():
    """LLM 不标记任何框时，valid_regions 应等于全部 canon。"""
    from amta.stage3_planner_vision import run_plan_loop_vision

    canon = [
        {"region_id": "u00", "baberu_text": "一"},
        {"region_id": "u01", "baberu_text": "二"},
    ]

    def fake_llm(messages, tools=None):
        return {"tool_calls": None, "content": "扫描完成，无问题框。"}

    plan = run_plan_loop_vision(canon, fake_llm, image_data_url=_DUMMY_IMG)

    assert plan.valid_regions == ["u00", "u01"]
    assert plan.invalids == {} and plan.duplicates == {}


def test_vision_loop_respects_mark_invalid_budget():
    """视觉规划循环同样受单工具预算约束：LLM 不能把所有框标 invalid。"""
    from amta.stage3_planner_vision import run_plan_loop_vision

    canon = [{"region_id": f"u{i}", "baberu_text": f"text{i}"} for i in range(5)]
    # 5 框 → mark_invalid 预算 = max(2, 5//2) = 2
    calls = {"n": 0}

    def fake_llm(messages, tools=None):
        calls["n"] += 1
        if calls["n"] <= 5:
            rid = f"u{calls['n'] - 1}"
            return {"tool_calls": [{
                "function": {"name": "mark_invalid",
                             "arguments": f'{{"region_id": "{rid}", "reason": "噪声", "category": "noise"}}'}
            }], "content": None}
        return {"tool_calls": None, "content": "扫描完成"}

    plan = run_plan_loop_vision(canon, fake_llm, image_data_url=_DUMMY_IMG)

    assert len(plan.invalids) == 2
    assert len(plan.valid_regions) == 3
