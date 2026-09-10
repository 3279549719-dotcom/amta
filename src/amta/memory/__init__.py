"""amta.memory — agent 记忆机制包（ADR-025/027）。

estate 单一事实源：docs/lessons.md / docs/decisions/ / .remember 动态解析，
服务 memory_* 工具族、MCP 字典、ralph 注入与 SessionStart 注入包
（estate 解析 / tools 检索 / lint 检查 / gc 清理 / inject 注入 / loop_state 接续）。

v0 轨道（INDEX 记忆索引 + 独立解析模块）已退役，本包只保留 estate 系符号。
"""
