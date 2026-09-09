"""amta.guards — 翻译机械护栏 / 术语 / VLM 裁决（Stage 3 质量面）。

- guardrails   — 翻译后机械护栏（结构错/日文残留）
- canon_schema — pre-translate Input schema gate（crop+fallback 校验）
- glossary     — Knowledge guardrail（confirmed 术语逐对校验）
- suggestions  — 片假名术语提取 + 追加 + 合并（SuggestionsExtractor）
- term_dict / term_replace — 术语词典装载/替换
- rule_filter  — 规则过滤（已退役，OCR confidence 替代，保留接口兼容）
- pre_scan     — per-work 锁定术语词典预扫（once per work）
- vlm_filter   — VLM 三态过滤 keep/fix/drop（默认未接入主链）

依赖: amta.common/metrics、amta.stores、amta.backends。
"""
