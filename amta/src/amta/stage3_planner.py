"""stage3_planner.py — Stage 3 翻译前规划阶段。

让 LLM 在翻译前扫描全页，调用 mark_invalid / mark_duplicate 工具标记问题框：
- mark_invalid: 该框不是有效文字（排线/装饰线/噪声），跳过不翻译
- mark_duplicate: 该框是另一框的副本，译文继承原框

ADR-023 延伸：不硬编码去重/过滤规则，给 LLM 完整上下文（全页文本+bbox+嵌套+整页图）让它裁决。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanResult:
    """规划阶段的结果：哪些框有效、哪些是重复、哪些无效。"""
    canon: list[dict] = field(default_factory=list)
    invalids: dict[str, str] = field(default_factory=dict)   # region_id -> reason
    invalid_categories: dict[str, str] = field(default_factory=dict)  # region_id -> category 枚举
    duplicates: dict[str, str] = field(default_factory=dict)  # region_id -> duplicate_of

    @property
    def valid_regions(self) -> list[str]:
        """返回有效（未被标记为 invalid/duplicate）的 region_id 列表。"""
        marked = set(self.invalids.keys()) | set(self.duplicates.keys())
        return [r["region_id"] for r in self.canon if r["region_id"] not in marked]


# mark_invalid 的 category 枚举（解决 12-u07 招牌无法归类）
INVALID_CATEGORIES = ("noise", "page_number", "decoration", "illustration",
                       "background_text", "other")

# 单工具预算比例（真拦截，防 LLM 把所有框标 invalid）
MARK_INVALID_BUDGET_RATIO = 0.5   # 最多标记一半框为 invalid
MARK_DUPLICATE_BUDGET_RATIO = 1.0  # duplicate 最多不超过总框数


def plan_budgets(canon: list[dict]) -> dict[str, int]:
    """根据本页框数计算规划工具预算（每页一份，跨工具循环共享）。"""
    n = max(1, len(canon))
    return {
        "mark_invalid": max(2, int(n * MARK_INVALID_BUDGET_RATIO)),
        "mark_duplicate": n,
    }


def execute_plan_tool(plan: PlanResult, tool_name: str, args: dict,
                      budgets: dict[str, int] | None = None) -> dict:
    """执行规划阶段的工具调用，返回工具结果（Observation）。

    支持的工具：
    - mark_invalid(region_id, reason, category): 标记为无效框
    - mark_duplicate(region_id, duplicate_of, reason): 标记为重复框

    budgets：单工具调用预算（可选）。传了则超限返回 budget_exhausted 且不标记。
    返回值含累计状态（n_invalid/n_duplicate/invalid_ids/duplicate_ids），
    让 LLM 知道自己已经标了多少（可观测返回）。
    """
    # 预算拦截（在标记前检查）
    if budgets is not None and budgets.get(tool_name, 0) <= 0:
        return {"status": "budget_exhausted", "tool": tool_name,
                "message": f"工具 {tool_name} 本次调用预算已耗尽，请基于现有标记继续规划",
                "n_invalid": len(plan.invalids),
                "n_duplicate": len(plan.duplicates),
                "invalid_ids": list(plan.invalids.keys()),
                "duplicate_ids": list(plan.duplicates.keys())}

    if tool_name == "mark_invalid":
        rid = args["region_id"]
        reason = args.get("reason", "")
        category = str(args.get("category", "other")).strip().lower()
        if category not in INVALID_CATEGORIES:
            category = "other"
        plan.invalids[rid] = reason
        plan.invalid_categories[rid] = category
        if budgets is not None and tool_name in budgets:
            budgets[tool_name] -= 1
        return {"status": "marked_invalid", "region_id": rid, "reason": reason,
                "category": category,
                "n_invalid": len(plan.invalids), "n_duplicate": len(plan.duplicates),
                "invalid_ids": list(plan.invalids.keys()),
                "duplicate_ids": list(plan.duplicates.keys())}

    if tool_name == "mark_duplicate":
        rid = args["region_id"]
        dup_of = args["duplicate_of"]
        reason = args.get("reason", "")
        plan.duplicates[rid] = dup_of
        if budgets is not None and tool_name in budgets:
            budgets[tool_name] -= 1
        return {"status": "marked_duplicate", "region_id": rid, "duplicate_of": dup_of,
                "reason": reason,
                "n_invalid": len(plan.invalids), "n_duplicate": len(plan.duplicates),
                "invalid_ids": list(plan.invalids.keys()),
                "duplicate_ids": list(plan.duplicates.keys())}

    return {"status": "unknown_tool", "tool": tool_name}


def validate_plan(plan: PlanResult, canon: list[dict]) -> list[str]:
    """护栏：校验规划结果的合法性，返回错误列表（空列表=通过）。"""
    errors: list[str] = []
    valid_ids = {r["region_id"] for r in canon}

    # 1. duplicate_of 必须指向 canon 中存在的框
    for rid, dup_of in plan.duplicates.items():
        if dup_of not in valid_ids:
            errors.append(f"mark_duplicate({rid}): duplicate_of='{dup_of}' 不在 canon 中")

    # 2. invalid 必须有非空 reason
    for rid, reason in plan.invalids.items():
        if not reason or not reason.strip():
            errors.append(f"mark_invalid({rid}): reason 不能为空")

    # 3. 一个框不能同时被标记为 invalid 和 duplicate
    both = set(plan.invalids.keys()) & set(plan.duplicates.keys())
    for rid in both:
        errors.append(f"{rid}: 不能同时被标记为 invalid 和 duplicate")

    return errors


# 规划阶段的工具 schema（供 LLM function calling 使用）
PLAN_TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "mark_invalid",
            "description": "标记某个文本框为无效（不是有效文字，如排线、装饰线、图像噪声、OCR 误识别的非文字区域）。"
                           "标记后该框不参与翻译，最终输出中标记为 skipped。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "要标记的框的 region_id，如 u01"},
                    "reason": {"type": "string", "description": "为什么判断为无效，如'排线装饰线'、'图像噪声'、'无意义符号'"},
                    "category": {
                        "type": "string",
                        "enum": list(INVALID_CATEGORIES),
                        "description": "无效框类型：noise=图像噪声/污渍；page_number=页码；decoration=排线/装饰线；illustration=插画/符号；background_text=招牌/背景文字/标题；other=其他"
                    },
                },
                "required": ["region_id", "reason", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_duplicate",
            "description": "标记某个文本框为另一个框的副本（内容重复、bbox 重叠或嵌套包含）。"
                           "标记后该框不单独翻译，译文继承 duplicate_of 指向的框。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "要标记为重复的框的 region_id，如 u02"},
                    "duplicate_of": {"type": "string", "description": "它重复的那个有效框的 region_id，如 u01"},
                    "reason": {"type": "string", "description": "为什么判断为重复，如'文本完全相同'、'bbox 重叠'、'嵌套于父框'"},
                },
                "required": ["region_id", "duplicate_of", "reason"],
            },
        },
    },
]


def _format_region_for_plan(r: dict) -> str:
    """格式化单个 region 供规划阶段 LLM 查看。包含 id、双引擎文本、bbox、嵌套关系。"""
    rid = r["region_id"]
    parts = [f"{rid}:"]

    # 双引擎文本
    baberu = r.get("baberu_text") or r.get("text") or ""
    vlm = r.get("vlm_text")
    vlm_status = r.get("vlm_status", "ok")
    if baberu:
        parts.append(f"[Baberu] {baberu}")
    if vlm is not None:
        parts.append(f"[VLM] {vlm}")
    elif vlm_status and vlm_status != "ok":
        parts.append(f"[VLM: {vlm_status}]")

    # bbox（用于判断重叠）
    bbox = r.get("bbox")
    if bbox:
        parts.append(f"[bbox] {bbox}")

    # 嵌套关系
    contained = r.get("contained_in")
    if contained:
        parts.append(f"[嵌套于 {contained}]")

    return " ".join(parts)


def build_plan_prompt(canon: list[dict]) -> str:
    """构建规划阶段的 user prompt：全页 region 列表 + 任务说明。

    LLM 需要看到所有 region 的文本、bbox、嵌套关系，才能判断重复和无效。
    这是 Context Management 的关键——规划阶段需要全页上下文，不能逐框给。
    """
    regions_text = "\n".join(_format_region_for_plan(r) for r in canon)

    instruction = (
        "你是漫画翻译流水线的质量规划员。在翻译之前，请扫描本页所有文本框，"
        "识别以下两类问题框并使用工具标记：\n\n"
        "1. **无效框（mark_invalid）**：不是有效文字的框，如排线、装饰线、图像噪声、"
        "OCR 误识别的非文字区域。这些框应跳过不翻译。\n\n"
        "2. **重复框（mark_duplicate）**：与另一个框内容重复、bbox 重叠或嵌套包含的框。"
        "这些框不单独翻译，译文继承原框。\n\n"
        "请仔细对比所有框的文本内容和 bbox 位置，判断哪些是重复的。"
        "对于嵌套框（contained_in），如果子框文本是父框的一部分或重复，标记为 duplicate。\n\n"
        "如果没有问题框，不需要调用任何工具，直接回复'扫描完成'即可。\n\n"
        "本页所有文本框：\n"
    )

    return instruction + regions_text


def run_plan_loop(canon: list[dict], llm, *, max_rounds: int = 4) -> PlanResult:
    """规划阶段的 ReAct 循环：LLM 扫描全页，调用 mark_invalid/mark_duplicate 工具。

    与 translate_tools.run_tool_loop 同构，但工具是规划工具而非翻译工具。
    循环终止：LLM 不再调工具，或达到 max_rounds。

    Args:
        canon: 本页所有 region 的列表
        llm: 兼容 (messages, tools=None) -> dict 的 LLM 调用函数
        max_rounds: 最大循环轮次（防死循环）

    Returns:
        PlanResult: 规划结果（invalids, duplicates, valid_regions）
    """
    import json

    plan = PlanResult(canon=canon)
    budgets = plan_budgets(canon)  # 单工具预算（跨循环共享，防 LLM 把所有框标 invalid）
    prompt = build_plan_prompt(canon)
    messages: list[dict] = [
        {"role": "system", "content": "你是漫画翻译质量规划员，使用工具标记无效框和重复框。"},
        {"role": "user", "content": prompt},
    ]

    for _ in range(max_rounds):
        resp = llm(messages, tools=PLAN_TOOLS_SCHEMA)
        tool_calls = resp.get("tool_calls") or []

        if not tool_calls:
            # LLM 不再调工具，规划结束
            break

        # 执行每个工具调用，把结果作为 Observation 注入
        # 注意：assistant 消息只 append 一次（带全部 tool_calls），然后每个 tool_call 对应一个 tool 消息
        messages.append({
            "role": "assistant",
            "content": resp.get("content"),
            "tool_calls": tool_calls,
        })
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            result = execute_plan_tool(plan, name, args, budgets=budgets)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })

    return plan


# ─── 翻译阶段集成 ───

def filter_valid_regions(canon: list[dict], plan: PlanResult) -> list[dict]:
    """根据规划结果过滤 canon，只返回未被标记为 invalid/duplicate 的框。"""
    marked = set(plan.invalids.keys()) | set(plan.duplicates.keys())
    return [r for r in canon if r["region_id"] not in marked]


def translate_with_plan(canon: list[dict], llm, *, plan: PlanResult | None = None,
                        _translate_fn=None, **kwargs) -> dict[str, str]:
    """带规划的翻译：先过滤 invalid/duplicate，翻译 valid 框，再继承 duplicate 译文。

    这是规划阶段与翻译阶段的接缝（Seam）。规划结果决定哪些框需要翻译，
    duplicate 框不单独翻译而是继承原框译文，invalid 框译文为空。

    Args:
        canon: 本页所有 region
        llm: LLM 调用函数（传给 _translate_fn）
        plan: 规划结果；None 时不过滤，行为与原 translate_with_retry 一致
        _translate_fn: 翻译函数（测试用 mock，生产默认 amta.translate.translate_with_retry）
        **kwargs: 透传给翻译函数的参数（work_state, open_questions, tools 等）

    Returns:
        {region_id: 译文}，包含所有 region（duplicate 继承译文，invalid 为空）
    """
    if _translate_fn is None:
        from amta.translate import translate_with_retry as _translate_fn

    # 1. 过滤：只翻译 valid 框
    if plan is not None:
        filtered = filter_valid_regions(canon, plan)
    else:
        filtered = list(canon)

    # 2. 翻译 valid 框
    translations = _translate_fn(filtered, llm, **kwargs)

    # 3. 组装结果：所有 region 都要有条目
    result: dict[str, str] = {}
    for r in canon:
        rid = r["region_id"]
        if rid in translations:
            result[rid] = translations[rid]
        elif plan is not None and rid in plan.duplicates:
            # duplicate 继承原框译文
            source = plan.duplicates[rid]
            result[rid] = translations.get(source, "")
        elif plan is not None and rid in plan.invalids:
            # invalid 为空
            result[rid] = ""
        else:
            result[rid] = ""

    return result
