# Plan: Translate Tools 真实现 — function calling 替代预取注入

日期: 2026-08-26
分支: feat/translate-tools-fc
状态: 执行中

## 背景与动机

ADR-016 以"预取注入"(build_tools_context)形态恢复了 Tools,但这是死代码妥协:
- 模型不能主动发起调用,只能被动消费预取文本(塞多了费 token、塞少了没得补)
- VISION_BUDGET 只有常量、未接线
- Context 不是"最小披露+按需扩展",而是"全量预塞"

Patrick 裁决:回归蓝图本意——真 function calling,模型按需动态扩展;
Context 最小披露(当前页 + 待确认事项),术语/前文靠工具按需查。

## 目标

1. `text_chat` 升级:支持 OpenAI 兼容 tools 参数 + tool_calls 响应解析
2. 真工具 x2:`lookup_term`(查 work_state 术语/角色译名)、`get_context`(取前页译文)
3. 工具调用循环:模型请求 → 程序执行(读本地 JSON)→ 结果回传 → 继续,直到纯文本输出
4. 预算真拦截:TERM_BUDGET=10 / GET_CONTEXT_BUDGET=3 每页硬限制,超限拒绝服务;MAX_TOOL_ROUNDS=6 防死循环
5. Context 最小披露:_prompt_parts 移除 rel_chars/rel_terms/prev_pages 预塞,保留 open_questions(量小)
6. vision 工具第一版不接(留 VISION_BUDGET 常量+接口),看图职责归评审③
7. 向后兼容:build_tools_context / tools_ctx 参数保留(旧测试不挂),03 不再使用

## 改动文件

- src/amta/translate.py: chat_with_tools / TOOLS_SCHEMA / execute_tool / 工具循环 / 最小披露
- scripts/03_translate.py: llm 闭包换 chat_with_tools,传 state_dir,去 tools_ctx
- tests/test_translate.py: 改 2 个预塞断言测试,新增工具循环/预算/执行器测试

## 验收标准

- fastcheck 全绿(121 + 新增 ≥ 6,全部通过)
- 真实数据 86 条重跑:03 全译出、机械护栏零错
- 语义评审③重跑,对比通过率(旧基线 83/86 = 96.5%)

## 后续(本 plan 外)

- 导演闭环:3 FAILED 修订 + 重评审 + merge_suggestions + 判例库扩充
- 通过率对比后决定是否加"术语名称清单"披露(仅名称不含译名)
