"""memory_autoinject — UserPromptSubmit hook：按 prompt 关键词自动检索记忆并注入上下文。

把记忆检索从「模型自觉调 MCP（pull）」改成「hook 自动 push」：
用户每次提问 → Claude Code 调本 hook → 提取 prompt 关键词 → 检索知识地产
（lessons/ADR/remember）→ 命中则把条目级摘要打到 stdout → Claude Code
自动注入为上下文（UserPromptSubmit 是四个 stdout 注入例外事件之一）。

这是记忆字典唯一的真强制层：不依赖模型执行纪律，查询动作由 hook 完成。

契约（对齐 Claude Code hooks 文档）：
  - 输入：stdin 单行 JSON，字段含 prompt / cwd / hook_event_name
  - 输出：plain text 到 stdout（非 JSON，避免被当结构化输出解析）；无命中输出空
  - 恒 exit 0；绝不用 exit 2（会阻塞并擦除 prompt）
  - 预算 ≤3KB（CC 实测 ~10K 落盘替换为 2KB 预览，安全取 3K）
  - UserPromptSubmit 默认 30s 超时：本地 grep 毫秒级，远安全

用法（settings.json）：
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python scripts/memory_autoinject.py" }] }
    ]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.memory.estate import estate_root
from amta.memory.tools import Hit, do_grep

# 注入预算（字符）。实测超 ~10K 会被落盘替换，安全留 3 倍余量。
INJECT_BUDGET = 3000
# 最大命中条目数
MAX_HITS = 6
# 常见英文停用词，剔除避免噪音命中
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "these", "those",
    "you", "your", "what", "how", "why", "when", "where", "which", "about",
    "using", "use", "used", "via", "into", "onto", "than", "then", "that's",
    "it's", "dont", "don't", "didnt", "does", "was", "were", "are", "is", "am",
    "not", "no", "yes", "will", "would", "should", "can", "could", "please",
    "query", "question", "memory", "search", "ask", "help", "project", "code",
    "python", "script", "file", "todo", "need", "want", "get", "make", "run",
}


def extract_tokens(prompt: str) -> list[str]:
    """从 prompt 提取检索 token：英文/数字词 + 数字版式（如 page14、0.3）。"""
    en = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{1,}", prompt)
    return [t for t in en if t.lower() not in _STOP]


def fmt_hit(h: Hit, root: Path) -> str:
    """条目级摘要：ID|标题|路径:行|首个命中行片段。"""
    rel = h.path.relative_to(root) if h.path.is_relative_to(root) else h.path
    rng = (
        f"{rel.as_posix()}:{h.start_line}-{h.end_line}"
        if h.end_line > h.start_line
        else f"{rel.as_posix()}:{h.hit_line_no}"
    )
    return f"{h.entry_id}|{h.title}|{rng}|{h.hit_text[:90]}"


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            cast(Any, stream).reconfigure(encoding="utf-8", errors="replace")
    raw = sys.stdin.readline().strip()
    if not raw:
        return 0
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    prompt = str(msg.get("prompt", "")).strip()
    if not prompt:
        return 0
    root = estate_root()  # CLAUDE_PROJECT_DIR > cwd

    tokens = extract_tokens(prompt)
    if not tokens:
        return 0  # 无关键词：不注入，避免每轮白开

    # alternation 正则：prompt 里任一 token 出现在条目内即命中
    pattern = "|".join(re.escape(t) for t in tokens)
    hits = do_grep(root, pattern, scope="all", limit=MAX_HITS)

    lines = ["=== 记忆自动注入（按当前问题检索） ==="]
    for h in hits:
        lines.append(fmt_hit(h, root))
    out = "\n".join(lines)

    if len(out) > INJECT_BUDGET:
        out = out[: INJECT_BUDGET - 60] + "\n[检索注入截断：跑 memory_grep 打捞全量]"

    print(out)  # plain text → 自动注入上下文
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
