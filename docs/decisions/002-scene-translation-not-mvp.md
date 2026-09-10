# ADR-002：场景级翻译不在 MVP

**状态**：已采纳

## 决策

第一里程碑（Benchmark A/B/C）**不做场景级翻译**。翻译上下文优先用 Story Memory + 前页上下文（做法 1：`systemPrompt` 注入），场景级翻译留到 Benchmark D 再定。

## 理由

- MVP 目标是**钉死能力边界**（检测 recall / OCR CER / inpaint 质量），翻译上下文不是当前瓶颈。
- 场景级翻译需要先有稳定的场景切分与 Story Memory 基建，过早引入会拖慢第一个可验证里程碑。
- 用户明确要求**零人工全量标注**，先证明数据链路可用。

## 后果 / 约束

- 翻译通道 = koharu 内 `llm` 引擎 + `systemPrompt` 注入（角色表/术语表/Story Memory）。
- Benchmark D 再评估是否需要真正的 scene-level 翻译。
