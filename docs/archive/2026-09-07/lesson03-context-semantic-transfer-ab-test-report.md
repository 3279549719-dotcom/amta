# Lesson 03 实践：get_context 语义化传递 — A/B 测试报告

> 日期：2026-08-29
> 分支：feature/context-semantic-transfer
> Commit：5f0ab9f
> 测试集：touhou-single-wing 第 10-19 页

## 1. 测试背景和目的

### 背景
Lesson 03 概念课学习了 Context Management，核心洞察是"数据存在 ≠ 上下文到达"。当前 `get_context` 工具返回的是裸文本，LLM 拿到后不知道哪句是角色对话、哪句是旁白、谁在说话、角色之间什么关系。

### 目的
验证"结构化上下文传递"（category 标注 + relationships 附加 + 术语筛选）相比"裸文本传递"的：
1. 信息丰富度提升
2. token 开销增加幅度
3. 回退兼容性
4. 潜在风险

## 2. 测试方法

### 实现改动
修改 `src/amta/translate_tools.py` 的 `execute_tool` 的 get_context 分支，新增 5 个辅助函数：
- `_build_semantic_context`：主入口，组装结构化上下文
- `_read_page_blocks_from_artifacts`：读单页 canon+translation，按 region_id 匹配
- `_read_fallback_context`：回退到旧的汇总 translation.json / prev_pages 方式
- `_format_relationships`：格式化角色关系（最多3条，confirmed优先，inferred标低置信度）
- `_format_relevant_terms`：筛选前页相关术语（最多5条，norm模糊匹配）

### 常量
- `CATEGORY_LABELS`：dialogue_bubble→对话，overlay_text→覆盖文字，sfx→拟声
- `MAX_REGIONS_PER_PAGE = 15`：每页最多返回 region 数
- `MAX_RELATIONSHIPS = 3`：最多附加关系数
- `MAX_TERMS = 5`：最多附加术语数

### 测试用例（TDD，5个测试全部通过）
1. `test_get_context_reads_canon_category_and_labels`：读取 canon category，返回标注
2. `test_get_context_falls_back_to_plain_when_canon_missing`：canon 不存在时回退到纯文本
3. `test_get_context_appends_confirmed_and_inferred_relationships`：附加 confirmed + inferred 关系
4. `test_get_context_filters_relevant_terms_from_prev_pages`：筛选前页相关术语
5. `test_get_context_limits_relationships_to_three`：relationships 条数限制

### 回归测试
- 旧的 `test_execute_get_context_from_state_dir`（汇总 translation.json 回退）通过
- 旧的 `test_tools_context_lookup_and_prev`（build_tools_context）通过
- 旧的 `test_execute_lookup_term_hit_and_miss`（lookup_term）通过

## 3. 测试结果

### 3.1 单元级 A/B 对比（第19页）

| 维度 | 旧实现（裸文本） | 新实现（结构化） | 差异 |
|---|---|---|---|
| 返回值格式 | `[page_19_u00] 译文` | `[对话] u00: 译文` | 带 category 标注，region_id 简化 |
| 条数 | 11 条 | 11 条 + 1 条术语 | 附加相关术语 |
| relationships | 无 | 无（work_state 里为 0） | 数据缺失，功能未生效 |
| 返回值长度 | 323 chars | 364 chars | +41 chars（+12.7%） |
| category 标注 | 无 | 全部 `[对话]` | 测试集全是 dialogue_bubble |

### 3.2 新旧返回值对比示例

**旧实现：**
```
前页译文：
[page_19_u00] 这么说来，也是呢。
[page_19_u01] 想象一下健谈又开朗的探女吧。
[page_19_u02] 月之民是如何从地面移居到月球的呢——
...
```

**新实现：**
```
前页上下文：
--- 第19页（共11条）---
[对话] u00: 这么说来，也是呢。
[对话] u01: 想象一下健谈又开朗的探女吧。
[对话] u02: 月之民是如何从地面移居到月球的呢——
...

前页相关术语：
- サグメ = 说起来，探女你在做什么研究？（status=candidate）
```

### 3.3 category 分布（10-19页）

| 页码 | category 分布 |
|---|---|
| page_10 | dialogue_bubble: 9 |
| page_11 | dialogue_bubble: 7 |
| page_12 | dialogue_bubble: 12 |
| page_13 | dialogue_bubble: 17 |
| page_14 | dialogue_bubble: 9 |
| page_15 | dialogue_bubble: 12 |
| page_16 | dialogue_bubble: 10 |
| page_17 | dialogue_bubble: 11 |
| page_18 | dialogue_bubble: 8 |
| page_19 | dialogue_bubble: 11 |

**发现**：10-19 页全是 dialogue_bubble，没有 sfx 或 overlay_text。这意味着在这个测试集上，category 标注的价值有限（全是"对话"），但在有 sfx/overlay_text 的页面上会有明显价值。

### 3.4 work_state 数据概览

| 字段 | 数量 | 说明 |
|---|---|---|
| relationships | 0 | 角色关系为空，relationships 附加功能未生效 |
| terms | 13 | 有术语，但部分数据质量不高（见问题 2） |
| characters | 5 | 有角色数据 |

## 4. 发现的问题

### 问题 1：work_state 里 relationships=0
- **现象**：角色关系附加功能在 touhou-single-wing 项目上完全没生效
- **原因**：work_state.json 里没有 relationships 数据（可能是之前的流水线没有写入）
- **影响**：relationships 附加功能无法在这个项目上验证效果
- **建议**：后续可以在翻译过程中自动提取角色关系写入 work_state，或者手动补充

### 问题 2：术语数据质量不高
- **现象**：`サグメ` 的 translation 是"说起来，探女你在做什么研究？"——这不是术语翻译，是一整句话
- **原因**：可能是之前的术语提取逻辑把整句话当成了术语
- **影响**：附加的术语可能对 LLM 产生干扰
- **建议**：后续可以优化术语提取逻辑，或者在 `_format_relevant_terms` 里过滤掉过长的术语（比如超过 20 个字的不认为是术语）

### 问题 3：测试集全是 dialogue_bubble
- **现象**：10-19 页没有 sfx 或 overlay_text，category 标注价值有限
- **原因**：这几页是纯对话场景
- **影响**：无法在这个测试集上验证 sfx/overlay_text 标注的效果
- **建议**：后续可以在有 sfx 的页面（比如前几页或动作场景）上验证

### 问题 4：token 开销增加约 12.7%
- **现象**：第19页从 323 chars 增加到 364 chars
- **原因**：category 标注（`[对话] ` 5 chars × 11 条 = 55 chars）+ 术语附加（约 40 chars）- region_id 简化（节省约 50 chars）
- **影响**：对于 128k 上下文的模型来说微不足道
- **评估**：可接受，信息丰富度提升大于 token 开销

## 5. 结论和建议

### 结论
1. **功能实现完整**：5 个 TDD 测试全部通过，旧的回归测试也通过，回退兼容性良好
2. **信息丰富度提升**：返回值带 category 标注，附加相关术语和角色关系（数据完整时）
3. **token 开销可接受**：增加约 12.7%，对于大上下文模型微不足道
4. **数据依赖明显**：relationships 和术语附加功能的效果高度依赖 work_state 数据质量

### 建议
1. **可以合并到 master**：功能完整，回退兼容，token 开销可接受
2. **后续优化术语过滤**：在 `_format_relevant_terms` 里过滤掉过长的术语（>20字），避免低质量术语干扰
3. **后续补充 relationships 数据**：在翻译过程中自动提取角色关系，或者手动补充到 work_state
4. **后续在有 sfx 的页面验证**：在动作场景页面上验证 sfx/overlay_text 标注的效果

## 6. 后续集成测试计划（需要调用 LLM）

单元级 A/B 测试只验证了返回值格式，没有验证对翻译质量的实际影响。后续需要做集成级 A/B 测试：

### 测试设计
- **A（基线）**：用旧的 get_context（裸文本）跑 11-20 页翻译
- **B（实验）**：用新的 get_context（结构化上下文）跑同样的 11-20 页
- **对比维度**：
  - 称呼语一致性（同一角色在不同页的自称/他称是否一致）
  - 角色对话连贯性（跨页对话是否衔接）
  - 误报率（结构化上下文是否引入新的翻译错误）
  - LLM 调用 get_context 的频率（结构化上下文是否让 LLM 更愿意调用）
- **通过标准**：至少有 1 个可观测的改进案例，且无新误报

### 前置条件
- 需要 API key（DeepSeek）
- 需要补充 work_state 的 relationships 数据（否则 relationships 附加功能无法验证）
- 需要选择有 sfx/overlay_text 的页面（否则 category 标注价值有限）

## 7. 文件清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/amta/translate_tools.py` | 修改 | 重写 get_context 分支，新增 5 个辅助函数和 4 个常量 |
| `tests/test_context_semantic_transfer.py` | 新增 | 5 个 TDD 测试 |
| `uv.lock` | 修改 | pytest 依赖 |

## 8. 与 manga-image-translator 的对比

| 维度 | manga-image-translator | 本项目（新实现） |
|---|---|---|
| 注入方式 | 预取式（set_prev_context 自动注入） | 按需式（get_context 工具，LLM 决定何时调） |
| category 标注 | 无（前页上下文是纯文本） | 有（dialogue_bubble/overlay_text/sfx） |
| 角色关系 | 独立 RelationshipMemory（方向性关系+冲突检测+置信度） | work_state.relationships（简单结构，无冲突检测） |
| 风格指南 | 独立 YAML 文件 | work_state.terms（分散） |
| 条数限制 | context_pages: 0..20 | MAX_REGIONS_PER_PAGE=15, MAX_RELATIONSHIPS=3, MAX_TERMS=5 |

**关键差异**：manga-image-translator 是预取式（每次翻译都注入），本项目是按需式（LLM 主动调）。按需式更省 token，但依赖 LLM 主动调用。本项目的 category 标注比 manga 更细（manga 的前页上下文是纯文本，没有 category 标注）。
