"""test_stage3_planner.py — Stage 3 规划阶段 TDD 测试。

规划阶段：翻译前让 LLM 扫描全页，调用 mark_invalid / mark_duplicate 工具标记问题框。
Seam: amta.stage3_planner 模块的公共接口。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_execute_plan_tool_mark_invalid():
    """mark_invalid 工具：标记某框为无效（排线/装饰线/噪声），不翻译。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    plan = PlanResult()
    result = execute_plan_tool(plan, "mark_invalid",
                               {"region_id": "u01", "reason": "排线装饰线，非文字"})

    assert "u01" in plan.invalids
    assert plan.invalids["u01"] == "排线装饰线，非文字"
    assert result["status"] == "marked_invalid"
    assert result["region_id"] == "u01"


def test_execute_plan_tool_mark_duplicate():
    """mark_duplicate 工具：标记某框为另一框的副本，译文继承原框。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    plan = PlanResult()
    result = execute_plan_tool(plan, "mark_duplicate",
                               {"region_id": "u02", "duplicate_of": "u01",
                                "reason": "文本完全相同，bbox 重叠"})

    assert plan.duplicates["u02"] == "u01"
    assert result["status"] == "marked_duplicate"
    assert result["duplicate_of"] == "u01"


def test_plan_result_valid_regions_excludes_marked():
    """valid_regions 属性：排除已标记为 invalid/duplicate 的框。"""
    from amta.stage3_planner import PlanResult

    canon = [{"region_id": "u01"}, {"region_id": "u02"}, {"region_id": "u03"}]
    plan = PlanResult(canon=canon)
    plan.invalids["u01"] = "排线"
    plan.duplicates["u02"] = "u03"

    valid = plan.valid_regions
    assert valid == ["u03"]
    assert "u01" not in valid
    assert "u02" not in valid


def test_validate_plan_duplicate_must_point_to_existing_region():
    """护栏：mark_duplicate 的 duplicate_of 必须指向 canon 中存在的框。"""
    from amta.stage3_planner import PlanResult, validate_plan

    canon = [{"region_id": "u01"}, {"region_id": "u02"}]
    plan = PlanResult(canon=canon)
    plan.duplicates["u02"] = "u99"  # 不存在的框

    errors = validate_plan(plan, canon)
    assert len(errors) >= 1
    assert any("u99" in e for e in errors)


def test_validate_plan_invalid_must_have_reason():
    """护栏：mark_invalid 必须有 reason，不能空。"""
    from amta.stage3_planner import PlanResult, validate_plan

    canon = [{"region_id": "u01"}]
    plan = PlanResult(canon=canon)
    plan.invalids["u01"] = ""  # 空 reason

    errors = validate_plan(plan, canon)
    assert any("reason" in e.lower() or "u01" in e for e in errors)


def test_validate_plan_no_region_both_invalid_and_duplicate():
    """护栏：一个框不能同时被标记为 invalid 和 duplicate。"""
    from amta.stage3_planner import PlanResult, validate_plan

    canon = [{"region_id": "u01"}, {"region_id": "u02"}]
    plan = PlanResult(canon=canon)
    plan.invalids["u01"] = "排线"
    plan.duplicates["u01"] = "u02"  # 同一个框既 invalid 又 duplicate

    errors = validate_plan(plan, canon)
    assert any("u01" in e for e in errors)


def test_build_plan_prompt_contains_all_regions():
    """规划 prompt 必须包含所有 region 的 id 和双引擎文本。"""
    from amta.stage3_planner import build_plan_prompt

    canon = [
        {"region_id": "u01", "baberu_text": "こんにちは", "vlm_text": "こんにちは", "vlm_status": "ok"},
        {"region_id": "u02", "baberu_text": "さようなら", "vlm_text": None, "vlm_status": "failed"},
    ]
    prompt = build_plan_prompt(canon)

    assert "u01" in prompt
    assert "u02" in prompt
    assert "こんにちは" in prompt
    assert "さようなら" in prompt
    assert "Baberu" in prompt or "baberu" in prompt.lower()


def test_build_plan_prompt_contains_bbox_and_nesting():
    """规划 prompt 必须包含 bbox（判断重叠）和 contained_in（判断嵌套）。"""
    from amta.stage3_planner import build_plan_prompt

    canon = [
        {"region_id": "u01", "baberu_text": "大きい文字", "bbox": [10, 10, 100, 50]},
        {"region_id": "u02", "baberu_text": "小さい文字", "bbox": [20, 20, 80, 40], "contained_in": "u01"},
    ]
    prompt = build_plan_prompt(canon)

    assert "10" in prompt  # bbox 坐标
    assert "contained_in" in prompt or "嵌套" in prompt
    assert "u01" in prompt and "u02" in prompt


def test_build_plan_prompt_explains_tools():
    """规划 prompt 必须说明可以使用 mark_invalid 和 mark_duplicate 工具。"""
    from amta.stage3_planner import build_plan_prompt

    canon = [{"region_id": "u01", "baberu_text": "test"}]
    prompt = build_plan_prompt(canon)

    assert "mark_invalid" in prompt
    assert "mark_duplicate" in prompt


def test_run_plan_loop_marks_invalid_with_mock_llm():
    """规划循环：mock LLM 返回 mark_invalid 调用，验证 plan 正确更新。"""
    from amta.stage3_planner import run_plan_loop

    canon = [
        {"region_id": "u01", "baberu_text": "有効な文字", "vlm_text": "有効な文字"},
        {"region_id": "u02", "baberu_text": "───", "vlm_text": "───"},  # 排线
    ]

    # mock LLM：第一轮调用 mark_invalid(u02)，第二轮不调工具（结束）
    call_count = {"n": 0}

    def mock_llm(messages, tools=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "tool_calls": [{
                    "function": {
                        "name": "mark_invalid",
                        "arguments": '{"region_id": "u02", "reason": "排线装饰线，非文字"}',
                    }
                }],
                "content": None,
            }
        return {"tool_calls": None, "content": "扫描完成，u02 是排线已标记。"}

    plan = run_plan_loop(canon, mock_llm)

    assert "u02" in plan.invalids
    assert plan.invalids["u02"] == "排线装饰线，非文字"
    assert "u01" in plan.valid_regions
    assert call_count["n"] == 2  # 一轮调工具 + 一轮结束


def test_run_plan_loop_marks_duplicate_with_mock_llm():
    """规划循环：mock LLM 返回 mark_duplicate 调用，验证 plan 正确更新。"""
    from amta.stage3_planner import run_plan_loop

    canon = [
        {"region_id": "u01", "baberu_text": "同じ文字", "vlm_text": "同じ文字"},
        {"region_id": "u02", "baberu_text": "同じ文字", "vlm_text": "同じ文字"},  # 重复
    ]

    call_count = {"n": 0}

    def mock_llm(messages, tools=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "tool_calls": [{
                    "function": {
                        "name": "mark_duplicate",
                        "arguments": '{"region_id": "u02", "duplicate_of": "u01", "reason": "文本完全相同"}',
                    }
                }],
                "content": None,
            }
        return {"tool_calls": None, "content": "扫描完成。"}

    plan = run_plan_loop(canon, mock_llm)

    assert plan.duplicates["u02"] == "u01"
    assert "u01" in plan.valid_regions
    assert "u02" not in plan.valid_regions


# ─── 翻译阶段集成 ───

def test_filter_valid_regions_excludes_marked():
    """filter_valid_regions：只返回未被标记为 invalid/duplicate 的框。"""
    from amta.stage3_planner import PlanResult, filter_valid_regions

    canon = [
        {"region_id": "u01", "baberu_text": "有効"},
        {"region_id": "u02", "baberu_text": "无効"},
        {"region_id": "u03", "baberu_text": "重复"},
    ]
    plan = PlanResult(canon=canon)
    plan.invalids["u02"] = "排线"
    plan.duplicates["u03"] = "u01"

    valid = filter_valid_regions(canon, plan)
    ids = [r["region_id"] for r in valid]
    assert ids == ["u01"]
    assert len(valid) == 1


def test_translate_with_plan_skips_invalid_and_duplicate():
    """translate_with_plan：只翻译 valid 框，invalid/duplicate 不调 LLM。"""
    from amta.stage3_planner import PlanResult, translate_with_plan

    canon = [
        {"region_id": "u01", "baberu_text": "こんにちは"},
        {"region_id": "u02", "baberu_text": "───"},  # 排线，会被标记 invalid
        {"region_id": "u03", "baberu_text": "こんにちは"},  # 重复 u01
    ]
    plan = PlanResult(canon=canon)
    plan.invalids["u02"] = "排线装饰线"
    plan.duplicates["u03"] = "u01"

    # mock translate 函数：记录被调用的 region
    translated_ids = []

    def mock_translate(filtered_canon, llm, **kwargs):
        translated_ids.extend(r["region_id"] for r in filtered_canon)
        return {"u01": "你好"}

    result = translate_with_plan(canon, llm=None, plan=plan,
                                 _translate_fn=mock_translate)

    # 只有 u01 被翻译，u02/u03 不调翻译
    assert translated_ids == ["u01"]
    assert result["u01"] == "你好"


def test_translate_with_plan_duplicate_inherits_translation():
    """translate_with_plan：duplicate 框继承原框的译文。"""
    from amta.stage3_planner import PlanResult, translate_with_plan

    canon = [
        {"region_id": "u01", "baberu_text": "こんにちは"},
        {"region_id": "u02", "baberu_text": "こんにちは"},  # 重复
    ]
    plan = PlanResult(canon=canon)
    plan.duplicates["u02"] = "u01"

    def mock_translate(filtered_canon, llm, **kwargs):
        return {"u01": "你好"}

    result = translate_with_plan(canon, llm=None, plan=plan,
                                 _translate_fn=mock_translate)

    assert result["u01"] == "你好"
    assert result["u02"] == "你好"  # 继承 u01 的译文


def test_translate_with_plan_invalid_gets_empty():
    """translate_with_plan：invalid 框译文为空。"""
    from amta.stage3_planner import PlanResult, translate_with_plan

    canon = [
        {"region_id": "u01", "baberu_text": "有効"},
        {"region_id": "u02", "baberu_text": "───"},
    ]
    plan = PlanResult(canon=canon)
    plan.invalids["u02"] = "排线"

    def mock_translate(filtered_canon, llm, **kwargs):
        return {"u01": "有效"}

    result = translate_with_plan(canon, llm=None, plan=plan,
                                 _translate_fn=mock_translate)

    assert result["u01"] == "有效"
    assert result["u02"] == ""  # invalid 为空


def test_translate_with_plan_no_plan_passes_all_through():
    """translate_with_plan：plan=None 时行为与原 translate_with_retry 一致（全翻译）。"""
    from amta.stage3_planner import translate_with_plan

    canon = [
        {"region_id": "u01", "baberu_text": "テスト1"},
        {"region_id": "u02", "baberu_text": "テスト2"},
    ]

    def mock_translate(filtered_canon, llm, **kwargs):
        return {r["region_id"]: f"译{r['region_id']}" for r in filtered_canon}

    result = translate_with_plan(canon, llm=None, plan=None,
                                 _translate_fn=mock_translate)

    assert result["u01"] == "译u01"
    assert result["u02"] == "译u02"


# ─── 规划工具改进：category 枚举 / 可观测返回 / 单工具预算（TDD） ───

def test_mark_invalid_stores_category():
    """mark_invalid 支持 category 枚举（解决 12-u07 招牌无法归类）。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    plan = PlanResult(canon=[{"region_id": "u07"}])
    result = execute_plan_tool(plan, "mark_invalid",
                               {"region_id": "u07", "reason": "招牌背景文字",
                                "category": "background_text"})

    assert plan.invalids["u07"] == "招牌背景文字"
    assert plan.invalid_categories["u07"] == "background_text"
    assert result["category"] == "background_text"


def test_mark_invalid_category_defaults_other():
    """category 缺省时默认 other，不破坏旧调用（向后兼容）。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    plan = PlanResult(canon=[{"region_id": "u01"}])
    execute_plan_tool(plan, "mark_invalid",
                      {"region_id": "u01", "reason": "排线"})

    assert plan.invalid_categories["u01"] == "other"


def test_execute_plan_tool_returns_cumulative_state():
    """可观测返回：每次工具调用返回累计 invalid/duplicate 数量和 id 列表。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    canon = [{"region_id": f"u{i}"} for i in range(3)]
    plan = PlanResult(canon=canon)

    r1 = execute_plan_tool(plan, "mark_invalid",
                           {"region_id": "u0", "reason": "噪声", "category": "noise"})
    assert r1["n_invalid"] == 1
    assert r1["n_duplicate"] == 0
    assert r1["invalid_ids"] == ["u0"]

    r2 = execute_plan_tool(plan, "mark_duplicate",
                           {"region_id": "u1", "duplicate_of": "u2", "reason": "重复"})
    assert r2["n_invalid"] == 1
    assert r2["n_duplicate"] == 1
    assert r2["duplicate_ids"] == ["u1"]


def test_mark_invalid_budget_enforced():
    """单工具预算：mark_invalid 超限后返回 budget_exhausted，不再标记。"""
    from amta.stage3_planner import PlanResult, execute_plan_tool

    plan = PlanResult(canon=[{"region_id": f"u{i}"} for i in range(5)])
    budgets = {"mark_invalid": 1, "mark_duplicate": 5}

    r1 = execute_plan_tool(plan, "mark_invalid",
                           {"region_id": "u0", "reason": "噪声", "category": "noise"},
                           budgets=budgets)
    assert r1["status"] == "marked_invalid"
    assert budgets["mark_invalid"] == 0

    r2 = execute_plan_tool(plan, "mark_invalid",
                           {"region_id": "u1", "reason": "噪声", "category": "noise"},
                           budgets=budgets)
    assert r2["status"] == "budget_exhausted"
    assert "u1" not in plan.invalids  # 没被标记


def test_run_plan_loop_respects_mark_invalid_budget():
    """规划循环：LLM 试图把所有框标 invalid，但预算只允许标记一半。"""
    from amta.stage3_planner import run_plan_loop

    canon = [{"region_id": f"u{i}", "baberu_text": f"text{i}"} for i in range(5)]
    # 5 框 → mark_invalid 预算 = max(2, 5//2) = 2
    call_count = {"n": 0}

    def fake_llm(messages, tools=None):
        call_count["n"] += 1
        if call_count["n"] <= 5:
            rid = f"u{call_count['n'] - 1}"
            return {"tool_calls": [{
                "function": {"name": "mark_invalid",
                             "arguments": f'{{"region_id": "{rid}", "reason": "噪声", "category": "noise"}}'}
            }], "content": None}
        return {"tool_calls": None, "content": "扫描完成"}

    plan = run_plan_loop(canon, fake_llm)

    assert len(plan.invalids) == 2  # 预算上限，不是 5
    assert len(plan.valid_regions) == 3


def test_run_plan_loop_respects_mark_duplicate_budget():
    """规划循环：mark_duplicate 预算 = 总框数，不会超过。"""
    from amta.stage3_planner import run_plan_loop

    canon = [{"region_id": f"u{i}", "baberu_text": "同じ"} for i in range(3)]
    call_count = {"n": 0}

    def fake_llm(messages, tools=None):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            rid = f"u{call_count['n']}"
            return {"tool_calls": [{
                "function": {"name": "mark_duplicate",
                             "arguments": f'{{"region_id": "{rid}", "duplicate_of": "u0", "reason": "重复"}}'}
            }], "content": None}
        return {"tool_calls": None, "content": "扫描完成"}

    plan = run_plan_loop(canon, fake_llm)

    assert len(plan.duplicates) <= 3  # 不超过总框数
