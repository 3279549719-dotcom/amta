"""amta.translation — Stage 3 翻译核心（minimal 纯文本 LLM 路径，ADR-014/016/023）。

- translate         — 翻译编排 minimal：VLM refine + LLM 翻译 + 机械护栏（入口模块）
- stage3_minimal    — Stage 3 最小实现（1 LLM call/page, zero tools；VLM refine 已移除）
- translate_station — Stage 3 工位薄封装（canon → TranslationArtifact）

依赖: amta.guards、amta.backends(chat_client)、amta.stores、amta.common。
"""
