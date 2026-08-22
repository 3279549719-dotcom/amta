# ADR-001：钉 koharu v0.59.1 headless

**状态**：已采纳（勿改）

## 决策

引擎基线锁定 **koharu v0.59.1 headless**（REST `/api/v1` + MCP `/mcp` + 像素 mask 机制）。

## 理由

- v0.59.1 是 server 世代，提供完整自动化面：REST + MCP + 像素级 mask 读写 + headless 启动。
- 上游 **0.77.5 起已删除 headless/HTTP/MCP**，升级即失去全部自动化面——本项目的会话驱动执行器（`src/koharu_client.py`、`src/pipeline.py`）会全部失效。

## 后果 / 约束

- 一切接口/流程/坑以 v0.59.1 实证为准（见 `CLAUDE.md`、`koharu-drive` skill）。
- 评估新版本时先确认自动化面是否保留，再谈迁移。
