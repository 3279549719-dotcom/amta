# 全页 L2 Semantic A/B 对照实验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 2 个 worktree 做 A/B 对照，验证"翻译后插一个全页 L2 画境审校 semantic"值不值得接入。唯一变量 = 有没有全页 L2 semantic；两组都含三工具翻译（mark_invalid/mark_duplicate 并入翻译层 + lookup_image）+ repair + judge。跑 11-20 页，输出 2 份 HTML 报告，按召回率 vs 成本对比。

**Architecture:** 三条既存链要接线：①三工具翻译（`mark_invalid`/`mark_duplicate` 已实现于 `stage3_planner.py`，但作为独立规划阶段运行，需并入 `translate_tools.py` 的 TOOLS_SCHEMA + execute_tool）；②全页 L2 semantic（全新组件，从零写，输入=整页图+译文清单，只审神态/指代/语气/漏译，不重认日文）；③repair + judge（已存在，但 judge 的 repair 动作被 semantic failed 列表卡住，组B 需脱离）。两条链复用 11-20 页既有 canon（OCR 产物），不重跑 detect/OCR。

**Tech Stack:** Python 3 + DeepSeek API（LLM=deepseek-v4-flash 纯文本，VLM=deepseek-v4-flash-vision-exp）+ 零依赖自造薄层。复用既有 `run_tool_loop`/`execute_tool`/`judge_page`/`repair_failed` 模式。

---

## 实验消费的 OCR 数据源（关键，写死）

**两条链统一消费 `workspace/touhou-single-wing/artifacts/page_{N}_canon.json`（N=11..20）。**

这个 canon 是 **eval_stage2 的产物**（脚本 `scripts/eval_stage2.py` 跑 `02_ocr` 产出，即 baberu + VLM 双引擎的**纯 OCR 输出**），**未经规划层筛选**，因此**天然包含需要被 mark 的框**：
- 噪声/极短框（如 `page_13_u13` text=`1`）→ 翻译层应 `mark_invalid`
- 疑似重复框（如 `page_13_u11`/`u12` 短文本相近）→ 翻译层应 `mark_duplicate`
- 短拟声/单字框（`page_14_u07`「ひょこ」等）

**字段结构（重要）**：canon 每框含多个文本字段——`text`（主 OCR 文本）、`baberu_text`（baberu 引擎输出）、`vlm_text`（VLM 引擎输出）。翻译层读 **`text` 或 `baberu_text`**（baberu 是主要 OCR 引擎），VLM 文本仅作对照。

这正是实验测"三工具并入翻译层"价值的前提：**输入含可 mark 的对象，mark_invalid/mark_duplicate 才有活干。** 若 canon 里没有这些框，mark 工具会空转，实验将无法测出三工具价值。

**不重跑 detect/OCR**：直接用这些既有 canon 文件。每条链产出独立 translation/trace 文件（前缀 `_expA_`/`_expB_`）避免覆盖既有产物。

---

## 前置：分支与 worktree 拓扑

- 实验在 2 个 worktree 上进行，均基于 main（fec0eb7）：
  - **worktree A** `E:\manga translator agent\amta-wt-a`，分支 `feat/exp-l2-semantic` —— 组A：三工具翻译 + 全页 L2 semantic + repair + judge
  - **worktree B** `E:\manga translator agent\amta-wt-b`，分支 `feat/exp-3tool-translate` —— 组B：三工具翻译 + repair + judge（无 semantic）
- 已有 worktree B（`amta-wt-b`）和分支 `feat/exp-3tool-translate`。本次先只实现 worktree B（三工具并入翻译层），worktree A 在 B 验证跑通后创建（复用 B 的三工具改造，再加 L2 semantic）。
- **铁律**：不碰 main；复用 11-20 页既有 canon 产物；每次真实 API 跑批前先跑 mock 单测。

---

## Task 1: 把 mark_invalid / mark_duplicate 并入翻译层工具 schema

**Files:**
- Modify: `src/amta/translate_tools.py`（TOOLS_SCHEMA，在 lookup_image 之后追加两个工具声明）
- Test: `tests/test_translate_tools_plan_tools.py`（新建）

背景：`stage3_planner.py` 已有 `PLAN_TOOLS_SCHEMA`（line 124）和 `execute_plan_tool`（line 47），但它们属于独立的"规划阶段"。本 Task 把这两个工具**声明**并入翻译层的 `TOOLS_SCHEMA`，使翻译 LLM 在 ReAct 循环中可随时调用。工具声明文本复用 stage3_planner 的语义。

- [ ] **Step 1: 写失败测试——TOOLS_SCHEMA 含 mark_invalid/mark_duplicate 声明**

```python
# tests/test_translate_tools_plan_tools.py
"""三工具并入翻译层：mark_invalid / mark_duplicate 出现在 TOOLS_SCHEMA 且参数合法。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta import translate_tools

def _find(schema, name):
    return next((t for t in schema if t.get("function", {}).get("name") == name), None)

def test_schema_has_mark_invalid():
    t = _find(translate_tools.TOOLS_SCHEMA, "mark_invalid")
    assert t is not None
    props = t["function"]["parameters"]["properties"]
    assert "region_id" in props
    assert "reason" in props
    assert "category" in props

def test_schema_has_mark_duplicate():
    t = _find(translate_tools.TOOLS_SCHEMA, "mark_duplicate")
    assert t is not None
    props = t["function"]["parameters"]["properties"]
    assert "region_id" in props
    assert "duplicate_of" in props

def test_schema_keeps_lookup_tools():
    for name in ("lookup_term", "get_context", "lookup_image"):
        assert _find(translate_tools.TOOLS_SCHEMA, name) is not None
```

- [ ] **Step 2: 运行测试确认失败**

运行: `uv run pytest tests/test_translate_tools_plan_tools.py -v`（worktree B 用 `E:\manga translator agent\amta-wt-b\.venv\Scripts\python.exe -m pytest ...`）
预期: FAIL —— `assert t is not None` 失败（mark_invalid/mark_duplicate 不在 schema）

- [ ] **Step 3: 在 TOOLS_SCHEMA 追加两个工具声明**

在 `src/amta/translate_tools.py` 的 `TOOLS_SCHEMA` 列表末尾（lookup_image 条目之后）追加：

```python
    {
        "type": "function",
        "function": {
            "name": "mark_invalid",
            "description": "标记某个 region 为无效框（排线/装饰线/噪声/页码/插画等非有效文字），该框将不翻译、译文留空。当 OCR 文本看起来不是有效对白/旁白时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "要标记无效的 region_id（如 u00），必须与输入中的 region_id 完全一致"},
                    "category": {"type": "string", "description": "无效类别枚举：noise/page_number/decoration/illustration/background_text/other"},
                    "reason": {"type": "string", "description": "为什么标记无效（一句话）"},
                },
                "required": ["region_id", "category", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_duplicate",
            "description": "标记某个 region 是另一 region 的重复副本（重复覆盖框/重叠框），其译文应继承被标记的原框译文，不单独翻译。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "要标记重复的 region_id"},
                    "duplicate_of": {"type": "string", "description": "它重复自哪个 region_id（原框）"},
                    "reason": {"type": "string", "description": "为什么判定重复（一句话）"},
                },
                "required": ["region_id", "duplicate_of", "reason"],
            },
        },
    },
```

- [ ] **Step 4: 运行测试确认通过**

运行: `uv run pytest tests/test_translate_tools_plan_tools.py -v`
预期: PASS（4 tests）

- [ ] **Step 5: 提交**

```bash
git add src/amta/translate_tools.py tests/test_translate_tools_plan_tools.py
git commit -m "feat(translate_tools): mark_invalid/mark_duplicate 并入翻译层 TOOLS_SCHEMA"
```

---

## Task 2: execute_tool 支持 mark_invalid / mark_duplicate（会改状态的工具）

**Files:**
- Modify: `src/amta/translate_tools.py`（execute_tool 增加两个分支；新增一个内部状态容器）
- Test: `tests/test_translate_tools_plan_tools.py`（追加）

背景：现有 `execute_tool` 是**纯查询**（返回字符串，不修改状态）。mark_invalid/mark_duplicate 需要**记录翻译决策**（哪些框无效、哪些重复、继承谁）。设计：在 `work_state` 上挂一个内部键 `_plan`（dict），累积标记；execute_tool 返回"已标记"的可观测信息，翻译结果组装时读取。

- [ ] **Step 1: 写失败测试——execute_tool 处理 mark_invalid/mark_duplicate**

```python
# 追加到 test_translate_tools_plan_tools.py
from amta.translate_tools import execute_tool

def test_execute_mark_invalid_records_and_returns_observable():
    ws = {}
    out = execute_tool("mark_invalid",
                       {"region_id": "u03", "category": "noise", "reason": "排线"},
                       ws)
    assert "已标记" in out and "u03" in out
    assert ws["_plan"]["invalids"]["u03"]["category"] == "noise"

def test_execute_mark_duplicate_records_target():
    ws = {}
    out = execute_tool("mark_duplicate",
                       {"region_id": "u05", "duplicate_of": "u04", "reason": "重叠"},
                       ws)
    assert ws["_plan"]["duplicates"]["u05"] == "u04"

def test_execute_mark_invalid_missing_args():
    ws = {}
    out = execute_tool("mark_invalid", {}, ws)
    assert "参数缺失" in out
```

- [ ] **Step 2: 运行测试确认失败**

预期: FAIL —— `execute_tool` 遇到 mark_invalid 落入 else 分支返回"未知工具"或异常

- [ ] **Step 3: 实现 execute_tool 的两个分支**

在 `src/amta/translate_tools.py` 的 `execute_tool` 里，lookup_image 分支之后追加：

```python
    if name == "mark_invalid":
        rid = str(args.get("region_id", "")).strip()
        category = str(args.get("category", "")).strip()
        reason = str(args.get("reason", "")).strip()
        if not rid or not category:
            return "参数缺失：请提供 region_id 和 category"
        plan = ws.setdefault("_plan", {"invalids": {}, "duplicates": {}})
        plan["invalids"][rid] = {"category": category, "reason": reason}
        n_invalid = len(plan["invalids"])
        return f"已标记 {rid} 为无效（{category}：{reason}）。本页已标 {n_invalid} 个无效框。"
    if name == "mark_duplicate":
        rid = str(args.get("region_id", "")).strip()
        target = str(args.get("duplicate_of", "")).strip()
        reason = str(args.get("reason", "")).strip()
        if not rid or not target:
            return "参数缺失：请提供 region_id 和 duplicate_of"
        plan = ws.setdefault("_plan", {"invalids": {}, "duplicates": {}})
        plan["duplicates"][rid] = target
        n_dup = len(plan["duplicates"])
        return f"已标记 {rid} 为 {target} 的重复副本（{reason}）。本页已标 {n_dup} 个重复框。"
```

注意：`execute_tool` 的签名当前是 `(name, args, work_state, prev_pages=None, state_dir=None, crop_dir=None, vlm_api_key=None)`。work_state 是 `dict`，**可变对象按引用传递**，直接 `ws.setdefault(...)` 会修改调用方的 work_state——这正是我们想要的（跨工具循环累积）。

- [ ] **Step 4: 运行测试确认通过**

预期: PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/translate_tools.py tests/test_translate_tools_plan_tools.py
git commit -m "feat(translate_tools): execute_tool 支持 mark_invalid/mark_duplicate（累积 _plan 状态）"
```

---

## Task 3: 翻译结果组装——消费 _plan 状态

**Files:**
- Modify: `src/amta/translate.py`（translate_with_retry 结束后，若 work_state 含 _plan，则把 invalid 框译文置空、duplicate 框继承原框译文）
- Test: `tests/test_translate_plan_apply.py`（新建）

背景：mark_invalid/mark_duplicate 在翻译过程中被 LLM 调用，决策累积在 `ws["_plan"]`。但 `translate_with_retry` 返回的是 `{region_id: 译文}`，这些决策要**落到最终翻译结果**：invalid → 译文置空，duplicate → 继承 duplicate_of 的译文。需要在 translate_with_retry 返回前应用。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_translate_plan_apply.py
"""翻译结果组装：消费 _plan 状态，invalid 置空、duplicate 继承。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.translate import apply_plan_to_translations

def test_invalid_emptied_and_duplicate_inherited():
    # 翻译函数对 u00,u01,u04 返回译文；u02 被标 invalid，u03 标 duplicate_of u04
    result = {"u00": "a", "u01": "b", "u04": "d"}
    plan = {"invalids": {"u02": {}}, "duplicates": {"u03": "u04"}}
    out = apply_plan_to_translations(result, plan)
    assert out["u02"] == ""          # invalid 置空
    assert out["u03"] == "d"         # duplicate 继承 u04
    assert out["u00"] == "a"         # 其余不变

def test_no_plan_unchanged():
    out = apply_plan_to_translations({"u00": "a"}, {})
    assert out == {"u00": "a"}
```

- [ ] **Step 2: 运行确认失败**

预期: FAIL —— `apply_plan_to_translations` 未定义

- [ ] **Step 3: 实现 `apply_plan_to_translations`**

在 `src/amta/translate.py` 新增：

```python
def apply_plan_to_translations(result: dict[str, str],
                               plan: dict) -> dict[str, str]:
    """把翻译过程中 mark_invalid/mark_duplicate 的决策落到最终译文。

    - invalid 框 → 译文置空
    - duplicate 框 → 继承其 duplicate_of 原框的译文
    - 其余不变
    """
    out = dict(result)
    invalids = (plan or {}).get("invalids", {})
    duplicates = (plan or {}).get("duplicates", {})
    for rid in invalids:
        out[rid] = ""
    for rid, target in duplicates.items():
        out[rid] = out.get(target, "")
    return out
```

- [ ] **Step 4: 在 translate_with_retry 返回前应用**

在 `src/amta/translate.py` 的 `translate_with_retry` 函数末尾（return 之前）加入：

```python
    # 三工具并入：消费翻译过程中 LLM 的 mark_invalid/mark_duplicate 决策
    plan = (ws or {}).get("_plan")
    if plan and (plan.get("invalids") or plan.get("duplicates")):
        final = apply_plan_to_translations(final, plan)
```

（具体变量名 `final` 以 translate_with_retry 实际的返回变量为准——需读该函数 return 前的代码。）

- [ ] **Step 5: 运行测试确认通过 + 全量回归**

运行: `uv run pytest tests/test_translate_plan_apply.py tests/test_translate.py -v`
预期: PASS（新测试 + 既有 translate 测试无回归）

- [ ] **Step 6: 提交**

```bash
git add src/amta/translate.py tests/test_translate_plan_apply.py
git commit -m "feat(translate): 翻译结果消费 _plan 状态（invalid置空/duplicate继承）"
```

---

## Task 4: 组B judge 脱离 semantic——支持无 semantic 的决策路径

**Files:**
- Modify: `src/amta/page_judge.py`（apply_decisions 增加一个 bypass 参数；_build_user_message 在 semantic 为空时不报错）
- Modify: `scripts/00_run_all.py`（组B 调 judge 时传 `bypass_semantic=True`）
- Test: `tests/test_page_judge_bypass.py`（新建）

背景：`apply_decisions` 里 `repairable = [rid for rid in repair_ids if rid in sem_failed_ids]`——judge 的 repair 动作被 semantic failed 列表卡住。组B 没有 semantic，judge 需要能**直接**把 repair 决策传给 repair_failed。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_page_judge_bypass.py
"""组B：judge 脱离 semantic 直接决策 repair。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.page_judge import apply_decisions

def test_bypass_allows_repair_without_semantic_failed():
    judge = {"decisions": [
        {"tool": "repair_region", "args": {"region_id": "u03", "reason": "错译"}}
    ]}
    sem = {"failed": []}   # 无 semantic 信号
    actions = apply_decisions(judge, sem, bypass_semantic=True)
    assert actions["repair"] == ["u03"]   # 不再被 sem_failed_ids 卡住
    assert actions["tickets"] == []       # 不再降级为 hard_case

def test_bypass_false_keeps_old_behavior():
    judge = {"decisions": [
        {"tool": "repair_region", "args": {"region_id": "u03", "reason": "错译"}}
    ]}
    sem = {"failed": []}
    actions = apply_decisions(judge, sem)   # 默认不 bypass
    assert actions["repair"] == []
    assert len(actions["tickets"]) == 1 and actions["tickets"][0]["kind"] == "hard_case"
```

- [ ] **Step 2: 运行确认失败**

预期: FAIL —— `apply_decisions` 不接受 `bypass_semantic` 参数（TypeError）

- [ ] **Step 3: 实现 bypass 参数**

修改 `src/amta/page_judge.py` 的 `apply_decisions`：

```python
def apply_decisions(judge_doc: dict, sem_doc: dict, *,
                    bypass_semantic: bool = False) -> dict:
    """judge 决策 → 可执行动作。

    bypass_semantic=True（组B 无 semantic）：repair 决策直接可执行，不要求
    semantic 已标 fail；也不把 unrepairable 降级为 hard_case 工单。
    """
    decisions = judge_doc.get("decisions", [])
    repair_ids = [d["args"]["region_id"] for d in decisions
                  if d["tool"] == "repair_region" and d.get("args", {}).get("region_id")]
    ticket_args = [d["args"] for d in decisions
                   if d["tool"] == "open_ticket" and d.get("args", {}).get("region_id")]
    if bypass_semantic:
        repairable = repair_ids
        unrepairable = []
    else:
        sem_failed_ids = {f["region_id"] for f in sem_doc.get("failed", [])}
        repairable = [rid for rid in repair_ids if rid in sem_failed_ids]
        unrepairable = [rid for rid in repair_ids if rid not in sem_failed_ids]
    tickets = [{"region_id": t["region_id"], "reason": t.get("reason", ""),
                "kind": t.get("kind", "unknown")} for t in ticket_args]
    tickets += [{"region_id": rid,
                 "reason": "judge 建议修复但 semantic 未标记 fail，需人工确认",
                 "kind": "hard_case"} for rid in unrepairable]
    return {"repair": repairable, "tickets": tickets}
```

- [ ] **Step 4: 运行测试确认通过**

预期: PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/page_judge.py tests/test_page_judge_bypass.py
git commit -m "feat(page_judge): apply_decisions 支持 bypass_semantic（组B 无 semantic 直接决策 repair）"
```

---

## Task 5: 组B 端到端冒烟——跑 2 页（11-12）

**Files:**
- 无需改代码，验证接线。

背景：前面 Task 1-4 完成三工具并入 + judge bypass。现在用 11-12 页真实数据做最小冒烟，证明整条链能跑通、产出合理。复用既有 canon（`workspace/touhou-single-wing/artifacts/page_11_canon.json` 等），不重跑 detect/OCR。

- [ ] **Step 1: 确认既有 canon/crops 就绪**

```bash
# worktree B 内
ls workspace/touhou-single-wing/artifacts/page_11_canon.json
ls workspace/touhou-single-wing/artifacts/crops/page_11/   # 应有 u*.png
```

（若 crops 缺失，lookup_image 会返回"未配置"错误，但不阻断翻译——可接受。）

- [ ] **Step 2: 跑 11 页翻译（带三工具 + lookup_image）**

```bash
cd "E:\manga translator agent\amta-wt-b"
.venv\Scripts\python.exe scripts/03_translate.py \
  --canon workspace/touhou-single-wing/artifacts/page_11_canon.json \
  --out workspace/touhou-single-wing/artifacts/_expB_page_11_translation.json \
  --work-id touhou-single-wing \
  --state-dir workspace/touhou-single-wing/state \
  --crop-dir workspace/touhou-single-wing/artifacts/crops/page_11 \
  --trace workspace/touhou-single-wing/artifacts/_expB_page_11_trace.json
```

预期: 输出 translation.json，含 11 页各框译文；trace 显示 LLM 调用了 lookup_term/get_context（可能 lookup_image）。

- [ ] **Step 3: 跑 judge（组B bypass_semantic）**

因 judge 目前经 00_run_all 调用，先直接改 `scripts/00_run_all.py` 的 judge 分支传 `bypass_semantic=True`（Task 4 Step 已定）。或用一个临时 CLI 直接调 `judge_page` + `apply_decisions(..., bypass_semantic=True)`。

预期: judge 产出 repair/ticket/pass 决策，且 bypass 后 repair 可直接执行。

- [ ] **Step 4: 人工检查产物质量**

打开 translation.json，确认：invalid 框译文为空、duplicate 框继承、关键对白（如「ハ意様」）翻译合理。

- [ ] **Step 5: 提交任何接线修正**

若冒烟发现 bug，先修 + 加单测再提交；无 bug 则跳过。

---

## Task 6: 创建 worktree A，实现全页 L2 semantic

**Files:**
- Create: `src/amta/fullpage_semantic.py`（全新组件）
- Modify: `src/amta/translate_station.py`（翻译后调 fullpage_semantic）
- Modify: `scripts/00_run_all.py`（组A 接 L2 semantic 到 repair/judge）
- Test: `tests/test_fullpage_semantic.py`（新建）

背景：worktree A 从 main 新建，**复用 worktree B 的三工具改造**（Task 1-3 + judge bypass Task 4），在此基础上加全页 L2。核心组件 `fullpage_semantic.py`：输入整页原图 + 译文清单，调 VLM，只审四件事（人物挂错/情绪违和/动作指代错/漏译大号对白），输出结构化 critique。**绝不要求 VLM 重认日文小字。**

- [ ] **Step 1: 写失败测试——L2 评审输出解析**

```python
# tests/test_fullpage_semantic.py
"""全页 L2 semantic：VLM 输出解析 + 结构化 critique。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.fullpage_semantic import parse_critique

def test_parse_critique_no_issues():
    out = '{"has_visual_issues": false, "critiques": []}'
    res = parse_critique(out)
    assert res["has_visual_issues"] is False
    assert res["critiques"] == []

def test_parse_critique_with_issue():
    out = ('{"has_visual_issues": true, "critiques": ['
           '{"region_id": "u03", "issue_type": "emotion_mismatch", '
           '"visual_evidence": "左下角角色面红耳赤", "instruction": "用更激烈语气重写"}]}')
    res = parse_critique(out)
    assert res["has_visual_issues"] is True
    assert len(res["critiques"]) == 1
    assert res["critiques"][0]["region_id"] == "u03"
    assert res["critiques"][0]["issue_type"] == "emotion_mismatch"

def test_parse_critique_malformed_safe():
    res = parse_critique("评审无输出")
    assert res["has_visual_issues"] is False
    assert res["critiques"] == []
```

- [ ] **Step 2: 运行确认失败**

预期: FAIL —— `fullpage_semantic` 模块不存在

- [ ] **Step 3: 实现 fullpage_semantic.py**

```python
"""fullpage_semantic.py — 全页 L2 画境审校 semantic（组A）。

输入：整页原图 + 译文清单。输出：结构化 critique。
只审四件事（绝不让 VLM 重认日文小字）：
  1. speaker mismatch 人物挂错
  2. emotion inconsistency 情绪违和
  3. visual reference error 动作指代错
  4. major visual omission 漏译大号对白
VLM 不适合转写文字（32% 一致率教训），只适合做视觉判断。
"""
from __future__ import annotations
import json
from pathlib import Path

L2_PROMPT = """你是资深漫画汉化监修。你面前是一张完整漫画页面，以及翻译员为各区域提供的【中文译文草稿】。
请不要尝试重新转写日文原文（OCR 已由专业引擎完成）。你的唯一任务是结合整页画面、人物神态、
分镜流向和肢体动作，检查译文是否存在【视觉与语境矛盾】。

【译文清单】:
{translations}

【审查维度】:
1. 人物对应 (speaker): 台词气泡指向的角色，与译文说话人语气是否吻合？
2. 情绪张力 (emotion): 画面人物若在大喊/震惊/哭泣，译文是否过于平淡？反之若在小声嘀咕，是否过于夸张？
3. 画面指代 (visual_reference): 角色手指方向、手中道具（羽毛/帽子），译文代词名词是否与画面一致？
4. 严重漏检 (omission): 画面中是否有明显张嘴大喊的对白，在清单里完全没有对应？

【输出格式 (严格 JSON)】:
{{"has_visual_issues": true/false, "critiques": [{{"region_id": "...", "issue_type": "emotion_mismatch", "visual_evidence": "...", "instruction": "..."}}]}}"""


def _image_data_uri(path: Path) -> str:
    """读整页原图转 base64 data URI（复用 ocr_engines.image_data_uri）。"""
    from amta.ocr_engines import image_data_uri
    return image_data_uri(path)


def build_l2_messages(page_image: Path, translations: dict[str, str]) -> list[dict]:
    import json as _j
    trans_list = _j.dumps(translations, ensure_ascii=False, indent=1)
    return [
        {"role": "user", "content": [
            {"type": "text", "text": L2_PROMPT.format(translations=trans_list)},
            {"type": "image_url", "image_url": {"url": _image_data_uri(page_image)}},
        ]},
    ]


def parse_critique(out: str) -> dict:
    """解析 VLM 输出 → {has_visual_issues, critiques}。容错解析。"""
    text = (out or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"has_visual_issues": False, "critiques": []}
    if not isinstance(data, dict):
        return {"has_visual_issues": False, "critiques": []}
    critiques = data.get("critiques") or []
    if not isinstance(critiques, list):
        critiques = []
    return {
        "has_visual_issues": bool(data.get("has_visual_issues", False)),
        "critiques": [c for c in critiques if isinstance(c, dict) and c.get("region_id")],
    }
```

- [ ] **Step 4: 实现调 VLM 的 run 函数**

在 `fullpage_semantic.py` 追加：

```python
def run_fullpage_semantic(page_image: Path, translations: dict[str, str], *,
                          base_url: str, model: str, api_key: str,
                          retries: int = 2) -> dict:
    """调 VLM 对整页做画境审校，返回 {has_visual_issues, critiques, raw}。"""
    import requests
    messages = build_l2_messages(page_image, translations)
    payload = {"model": model, "messages": messages, "max_tokens": 1200}
    last = ""
    for _ in range(retries + 1):
        r = requests.post(base_url + "/chat/completions",
                          headers={"Authorization": f"Bearer {api_key}"},
                          json=payload, timeout=120)
        r.raise_for_status()
        last = r.json()["choices"][0]["message"]["content"] or ""
        if last.strip():
            break
    parsed = parse_critique(last)
    parsed["raw"] = last
    return parsed
```

- [ ] **Step 5: 在 translate_station.py 接入（翻译后可选调 L2）**

修改 `translate_station.py`：新增参数 `fullpage_semantic: bool = False` 和 `page_image: Path | None = None`；当两者都提供时，翻译完成后调 `run_fullpage_semantic`，把 critique 存入产物信封 `out["l2_critique"]`。

（注：L2 是"升级层非必跑层"——组A 每页都跑用于实验对比，生产可设为"L1 可疑才升级"。）

- [ ] **Step 6: 运行测试确认通过**

预期: PASS

- [ ] **Step 7: 提交**

```bash
git add src/amta/fullpage_semantic.py src/amta/translate_station.py tests/test_fullpage_semantic.py
git commit -m "feat(fullpage_semantic): 全页 L2 画境审校组件 + 翻译工位接入"
```

---

## Task 7: 组A 接 L2 → repair → judge 全链路

**Files:**
- Modify: `scripts/00_run_all.py`（组A：翻译后跑 fullpage_semantic，把 critique 喂给 repair + judge）
- Modify: `src/amta/repair_failed.py`（可消费 critique 的定向修复）

背景：组A 的 repair 要能消费 L2 的 critique（不再依赖旧的 L1 semantic failed 列表）。需要让 repair_failed 接受 critique 列表作为"需修复框"的来源。

- [ ] **Step 1: 写失败测试——repair 消费 critique**

```python
# tests/test_repair_from_critique.py
"""组A：repair_failed 从 L2 critique 取需修复框。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.repair_failed import critiqued_regions

def test_critiqued_regions_extracts_ids():
    critique = {"critiques": [
        {"region_id": "u03", "instruction": "重写"},
        {"region_id": "u08", "instruction": "改语气"},
    ]}
    assert critiqued_regions(critique) == ["u03", "u08"]

def test_critiqued_regions_empty():
    assert critiqued_regions({"critiques": []}) == []
```

- [ ] **Step 2: 运行确认失败**

预期: FAIL —— `critiqued_regions` 未定义

- [ ] **Step 3: 实现 critiqued_regions**

在 `repair_failed.py` 新增：

```python
def critiqued_regions(critique: dict) -> list[str]:
    """从 L2 critique 提取需要修复的 region_id 列表（保持顺序去重）。"""
    seen, out = set(), []
    for c in (critique or {}).get("critiques", []):
        rid = c.get("region_id") if isinstance(c, dict) else None
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

预期: PASS

- [ ] **Step 5: 提交**

```bash
git add src/amta/repair_failed.py tests/test_repair_from_critique.py
git commit -m "feat(repair_failed): 支持从 L2 critique 定向取需修复框"
```

---

## Task 8: 组A / 组B 各跑 11-20 页，生成 2 份 HTML 报告

**Files:**
- Create: `scripts/exp_ab_report.py`（从两条链产物聚合指标，生成 HTML）

背景：两条链各跑 11-20 页（复用 canon），产出 translation + trace + judge 决策。报告对比：召回率（对照人工 ground truth）vs 每页 token 成本。

- [ ] **Step 1: 跑组B 11-20 页**

```bash
# worktree B
.venv\Scripts\python.exe scripts/00_run_all.py \
  --work-id touhou-single-wing --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" \
  --start-page 11 --end-page 20 --with-judge --bypass-semantic
```

（需先给 00_run_all.py 加 `--bypass-semantic` 开关，见 Task 4/5。产物写入独立目录避免覆盖既有。）

- [ ] **Step 2: 跑组A 11-20 页**

```bash
# worktree A
.venv\Scripts\python.exe scripts/00_run_all.py \
  --work-id touhou-single-wing --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" \
  --start-page 11 --end-page 20 --with-judge --fullpage-semantic --page-image-dir <src>
```

- [ ] **Step 3: 写 exp_ab_report.py**

聚合两组：每页的 ①judged 框数 ②VLM 调用次数（trace 统计 lookup_image + L2 semantic）③token 估算（按字符/图片粗略）④judge 的 repair/ticket/pass 决策。输出 HTML 对照表。

- [ ] **Step 4: 对照人工 ground truth**

用 plan-reviewer 人工标注（u05 误报等）评估：组A 的 L2 是否多抓真错、少误报；组B 的 judge bypass 是否漏抓。

- [ ] **Step 5: 生成并检查 2 份 HTML 报告**

---

## Task 9: 分析结论 + 落盘学习记录

- [ ] **Step 1: 对比两组指标，回答"全页 L2 semantic 值不值得接"**
- [ ] **Step 2: 更新 STATE.md / learning-records**
- [ ] **Step 3: 总结到 teaching workspace**

---

## Self-Review

**Spec coverage:**
- 三工具并入翻译层 → Task 1-3 ✅
- 组B judge 脱离 semantic（bypass）→ Task 4 ✅
- 组B 冒烟 2 页 → Task 5 ✅
- 全页 L2 semantic 组件 → Task 6 ✅
- 组A L2→repair→judge 全链路 → Task 7 ✅
- 两条链跑 11-20 + 2 份 HTML 报告 → Task 8 ✅
- 分析结论落盘 → Task 9 ✅

**Placeholder scan:** 已检查，无 TBD/TODO。Task 3 Step 4 标注"以实际返回变量名为准"需执行时确认，属合理（代码需读函数确认），非占位。

**Type consistency:** `execute_tool` 分支用 `ws["_plan"]["invalids"]`；Task 3 `apply_plan_to_translations` 读 `plan["invalids"]`/`plan["duplicates"]`——结构一致 ✅。`critiqued_regions` 读 `critique["critiques"][*]["region_id"]` 与 Task 6 `parse_critique` 输出一致 ✅。`bypass_semantic` 参数在 `apply_decisions` 与调用处一致 ✅。
