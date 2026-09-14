#!/usr/bin/env python3
"""mcp_memory — 记忆检索 MCP 字典工具（stdio，纯 stdlib）。

把现有 memory_grep/read/recent（CLI）包装成 Claude Code 可调的三只读 MCP 工具：
  memory_search(query, scope, limit)  渐进式披露：只回条目级命中行
  memory_read(entry, section)         取条目/节全文
  memory_recent()                     档案近况 + estate 最近提交

设计（ADR-027）：
  - 只读、本地、零第三方依赖；复用 amta.memory.tools 现有逻辑，不重造。
  - 预算 MAX_MEMORY_CALLS=6（仅 search/read 计数；每会话一个 MCP 子进程，进程内存计数即可）。
  - 超预算返回提示，让模型基于已得信息继续，不空转检索。

协议：MCP stdio（JSON-RPC 2.0，newline-delimited JSON）。注册：.claude/settings.json mcpServers。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from amta.memory.tools import Hit, do_grep, do_read, do_recent

MAX_MEMORY_CALLS = 6
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "amta-memory"
SERVER_VERSION = "0.1.0"

# 根 = 仓库根（与 memory_inject REPO_ROOT 同法）；测试可覆盖 _root。
_root = Path(__file__).resolve().parents[1]
_calls = 0  # 本进程内 search/read 累计计数

TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "在知识地产检索：坑库 docs/lessons.md（L##）、决策 docs/decisions/（ADR-N）、"
            "会话档案 .remember/、research/。按关键词或正则，返回条目级命中行（渐进式披露）。"
            "遇错/决策前先查，别硬扛。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词或正则"},
                "scope": {
                    "type": "string",
                    "enum": ["all", "lessons", "decisions", "remember", "research"],
                    "description": "检索范围，默认 all",
                },
                "limit": {"type": "integer", "description": "最多返回命中条目数，默认 10"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_read",
        "description": (
            "读取知识地产某条目全文（L## / ADR-N / now.md / recent.md 等），带路径与行号，"
            "默认上限 80 行。lessons 条目可指定节（Problem/Root cause/Durable lesson/Prevention/Regression）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry": {"type": "string", "description": "条目 ID，如 L45 / ADR-016 / now.md"},
                "section": {
                    "type": "string",
                    "description": "可选 lessons 节名（Problem/Root cause/Durable lesson/Prevention/Regression）",
                },
            },
            "required": ["entry"],
        },
    },
    {
        "name": "memory_recent",
        "description": "知识地产近况：.remember 会话档案头部 + estate 最近提交（git log）。接续前了解最近发生了什么。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _fmt_hit(h: Hit) -> str:
    rel = h.path.relative_to(_root) if h.path.is_relative_to(_root) else h.path
    rng = (
        f"{rel.as_posix()}:{h.start_line}-{h.end_line}"
        if h.end_line > h.start_line
        else f"{rel.as_posix()}:{h.hit_line_no}"
    )
    return f"{h.entry_id}|{h.title}|{rng}|{h.hit_text[:80]}"


def handle_call(name: str, args: dict) -> tuple[str, bool]:
    """执行工具调用，返回 (text, is_error)。"""
    global _calls
    if name in ("memory_search", "memory_read"):
        _calls += 1
        if _calls > MAX_MEMORY_CALLS:
            return (
                (f"记忆检索预算已用尽（MAX_MEMORY_CALLS={MAX_MEMORY_CALLS}）。"
                "基于已获得信息继续，别再检索。"),
                True,
            )
    if name == "memory_search":
        query = str(args.get("query", ""))
        if not query:
            return "memory_search 需要 query 参数。", True
        scope = str(args.get("scope", "all"))
        limit = int(args.get("limit", 10))
        # 多词查询 → 条目级 AND（每词在条目内任意行出现即中），像手边字典而非字面连排
        tokens = query.split()
        hits = do_grep(_root, query, scope=scope, limit=limit, tokens=tokens if len(tokens) > 1 else None)
        if not hits:
            return f"无命中：{query!r}（scope={scope}）——换关键词，或 memory_read 看清单。", False
        return "\n".join(_fmt_hit(h) for h in hits), False
    if name == "memory_read":
        try:
            return do_read(_root, str(args.get("entry", "")), args.get("section")), False
        except SystemExit as exc:
            return str(exc), True
    if name == "memory_recent":
        return do_recent(_root), False
    return f"未知工具 {name!r}。", True


def handle_message(msg: dict) -> dict | None:
    """JSON-RPC 分发；notification（无 id）返回 None（不响应）。"""
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        text, is_error = handle_call(str(params.get("name", "")), params.get("arguments") or {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return None


def main() -> int:
    # Windows 默认 locale 解码中文会炸；stdin/stdout 强制 UTF-8。
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            cast(Any, stream).reconfigure(encoding="utf-8", errors="replace")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")  # ensure_ascii=True：ASCII 安全上线
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
