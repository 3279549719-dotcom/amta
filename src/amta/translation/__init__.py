"""amta.translation — Stage 3 翻译核心（minimal 纯文本 LLM 路径，ADR-014/016/023）。

- translate         — 纯文本翻译底层：1 LLM call/page + 术语提取(本地 glossary) + 数组契约 + 机械护栏
- stage3_minimal    — Stage 3 编排（1 LLM call/page, zero tools；VLM refine 2026-09-09 已移除）
- translate_station — Stage 3 工位薄封装（canon → TranslationArtifact）

模型配置走 .env 的 CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY（amta.common.config.get_chat_config）；
导演只做终审/误报驳回/术语校准，不手写译文（ADR-016/017）。
依赖: amta.guards、amta.backends(chat_client)、amta.stores、amta.common。
"""
