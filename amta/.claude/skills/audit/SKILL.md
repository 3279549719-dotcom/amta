---
name: audit
description: 周期性 Harness 审计（/audit）——检测 Harness 熵：记忆膨胀、规则重复/过时、架构漂移、验证缺口、可晋升为自动化的手写规则、仓库卫生。建议频率：每 2-4 周或大里程碑后，不必每次任务都跑。
---

# Audit（Harness 熵审计）

> 目的：检测"Harness 熵"并给出**可行动建议**，不是产出巨型报告。频率：每 2-4 周 / 每个大里程碑后跑一次。`npm run audit` 跑确定性部分；本 skill 跑需要判断的部分。

## 先跑确定性部分

```
npm run audit
```

自动检查：CLAUDE.md 是否过大、lessons.md 每条是否含模板小节、decisions 是否有索引、入库 JSON 是否可解析、被忽略产物是否意外入库。

## 人工判断清单（每条给 建议 / 无需动作 / 已自动化）

### Memory
- CLAUDE.md 是否过大？（>~120 行 → 把稳定规则晋升为测试/hook）
- 规则是否重复？（同一坑既在 lessons.md 又在 CLAUDE.md → 只留一处）
- lessons 是否过时？被自动化覆盖的标 `[已自动化]`
- 文档是否自相矛盾？

### Architecture
- 架构是否漂移？（对照 README / ADR）
- 模块边界是否仍被尊重？（src 不应直接依赖不该依赖的层）
- 新依赖是否合理？（本仓零运行时依赖原则）

### Verification
- 反复出现的失败是否缺回归测试？
- 重要不变量是否仍只写在散文里（该转成 test/lint/hook）？

### Automation
- 某条手写规则现在能否变成测试/hook？（例：`TERMINAL_STATUSES`、输出 JSON schema 已自动化）
- 重复的 Agent 失误能否变成 lint 规则？
- 是否有校验跑错了生命周期（太快/太慢）？

### Repository hygiene
- 死文件 / 重复代码 / 临时产物 / 过时文档 / 生成文件被意外提交？
- `git ls-files` 里有没有 `models/`、`testsets/pages/`、不该提交的 `output/*`？

## 输出格式（给 AI 读）

```
## Audit Report
Memory:      ✅ / ⚠️ <建议>
Architecture:✅ / ⚠️ <建议>
Verification:✅ / ⚠️ <建议>
Automation:  ✅ / ⚠️ <建议>
Hygiene:     ✅ / ⚠️ <建议>
Top 3 actions:
1. ...
2. ...
3. ...
```

只列真正值得做的；其余写"无需动作"。审计是咨询不是门禁（exit 0）。
