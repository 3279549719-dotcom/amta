#!/usr/bin/env python3
"""memory.py — 记忆系统统一 CLI（ADR-025/026/027 收敛）。

单一入口替代 10+ 个独立 memory_*.py 脚本：逻辑全部在 src/amta/memory/
（estate 数据层 / tools 检索 / lint 检查 / gc 清理 / inject 注入）。

用法:
  # 项目级记忆 v0（INDEX.md 索引优先 + 全文兜底）
  python scripts/memory.py search "拟声词" [--json]
  python scripts/memory.py read L-007          # 按索引 ID 深读
  python scripts/memory.py add --id L-015 --trigger "..." --path "docs/lessons.md#L15" --value "..."
  python scripts/memory.py stats

  # 知识地产（estate：lessons/ADR/remember/research）
  python scripts/memory.py grep --query "关键词|正则" [--scope all] [--limit N]
  python scripts/memory.py read --entry L19 [--section Problem]   # 条目/节聚焦读
  python scripts/memory.py index [--type lessons|decisions|remember|all]
  python scripts/memory.py recent
  python scripts/memory.py status              # 活性自检（FAIL 不影响退出码）
  python scripts/memory.py lint [--strict]     # 门禁（fastcheck 用）

  # 维护 / 注入
  python scripts/memory.py gc [--dry-run] [--today YYYY-MM-DD]
  python scripts/memory.py inject [--stdout] [--budget N] [--source startup] [--target P]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_stdout = cast(Any, sys.stdout)
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")

from amta.memory import project_memory  # noqa: E402
from amta.memory import gc as memory_gc  # noqa: E402
from amta.memory import inject as memory_inject  # noqa: E402
from amta.memory import lint as memory_lint  # noqa: E402
from amta.memory import tools as memory_tools  # noqa: E402
from amta.memory.estate import estate_root  # noqa: E402


def _cmd_search(a: argparse.Namespace) -> int:
    out = project_memory.search(a.query)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    for h in out["index_hits"]:
        print(f"[index] {h['id']} | {h['trigger']} | {h['path']} | {h['value']}")
    for h in out["fulltext_hits"]:
        print(f"[text ] {h['file']}:{h['line']}: {h['text']}")
    if not out["index_hits"] and not out["fulltext_hits"]:
        print(f"[none] 语料中没有命中：{a.query}")
    return 0


def _cmd_read(a: argparse.Namespace) -> int:
    if a.rid:  # positional ID：先按地产条目解析（L##/ADR-N/remember —— 与注入清单同命名空间）
        try:
            print(memory_tools.do_read(estate_root(), entry=a.rid, section=a.section))
            return 0
        except SystemExit:
            pass  # 地产无此条目 → 回落 v0 索引（L-0xx 旧式；退役 v0 轨道时删此回落分支）
        print(project_memory.read(a.rid))
        return 0
    if a.entry:  # 显式 --entry：地产条目聚焦读（L19 / ADR-016 / remember 文件名，可配 --section）
        print(memory_tools.do_read(estate_root(), entry=a.entry, section=a.section))
        return 0
    print("[memory] read 需要条目 ID（L##/ADR-N，positional 或 --entry）")
    return 1


def _cmd_add(a: argparse.Namespace) -> int:
    print(project_memory.add(a.id, a.trigger, a.path, a.value))
    return 0


def _cmd_stats(a: argparse.Namespace) -> int:
    print(project_memory.stats())
    return 0


def _cmd_grep(a: argparse.Namespace) -> int:
    hits = memory_tools.do_grep(estate_root(), query=a.query, scope=a.scope, limit=a.limit)
    if not hits:
        print(f"[memory] 无命中：{a.query!r}（scope={a.scope}）——换个关键词，或 memory.py index 看清单")
        return 0
    for h in hits:
        print(memory_tools._fmt(h))  # noqa: SLF001 — 语义单兀行号指针格式，与 memory_grep 一致
    return 0


def _cmd_index(a: argparse.Namespace) -> int:
    print(memory_tools.do_index(estate_root(), type_=a.type_))
    return 0


def _cmd_recent(a: argparse.Namespace) -> int:
    print(memory_tools.do_recent(estate_root()))
    return 0


def _cmd_status(a: argparse.Namespace) -> int:
    findings = memory_lint.run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    n_fail = sum(1 for f in findings if f.level == "FAIL")
    print(f"[memory] {n_fail} FAIL / {sum(1 for f in findings if f.level == 'WARN')} WARN")
    return 0


def _cmd_lint(a: argparse.Namespace) -> int:
    findings = memory_lint.run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    fails = [f for f in findings if f.level == "FAIL"]
    if a.strict and fails:
        print(f"[memory] lint strict: {len(fails)} FAIL")
        return 1
    return 0


def _cmd_gc(a: argparse.Namespace) -> int:
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    root = Path.cwd()
    print(f"== memory_gc {('DRY-RUN' if a.dry_run else 'run')} @ {today} ==")
    for label, fn in (
        ("archive_today", lambda: memory_gc.archive_today(root, today, a.dry_run)),
        ("refresh_now", lambda: memory_gc.refresh_now(root, a.dry_run)),
        ("prune_tmp", lambda: memory_gc.prune_tmp(root, a.dry_run)),
    ):
        for line in fn():
            print(f"  [{label}] {line}")
    return 0


def _cmd_inject(a: argparse.Namespace) -> int:
    args: list[str] = []
    if a.stdout:
        args.append("--stdout")
    args += ["--budget", str(a.budget), "--source", a.source]
    if a.target:
        args += ["--target", a.target]
    return memory_inject.main(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="记忆系统统一 CLI（estate + 项目级记忆）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="索引 + 全文检索")
    p_search.add_argument("query")
    p_search.add_argument("--json", action="store_true", help="输出 JSON（供工具循环消费）")
    p_search.set_defaults(func=_cmd_search)

    p_read = sub.add_parser("read", help="按 ID 深读原文（索引 rid 或地产条目 --entry）")
    p_read.add_argument("rid", nargs="?", default=None, help="项目记忆索引 ID（如 L-007）")
    p_read.add_argument("--entry", default=None, help="知识地产条目（L19 / ADR-016 / remember 文件名）")
    p_read.add_argument("--section", default=None, help="仅 lessons 支持五段节名（配合 --entry）")
    p_read.set_defaults(func=_cmd_read)

    p_add = sub.add_parser("add", help="追加索引行（写回协议）")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--trigger", required=True)
    p_add.add_argument("--path", required=True)
    p_add.add_argument("--value", required=True)
    p_add.set_defaults(func=_cmd_add)

    sub.add_parser("stats", help="索引统计").set_defaults(func=_cmd_stats)

    p_grep = sub.add_parser("grep", help="知识地产内容检索")
    p_grep.add_argument("--query", required=True, help="关键词或正则")
    p_grep.add_argument("--scope", default="all", choices=["lessons", "decisions", "remember", "research", "all"])
    p_grep.add_argument("--limit", type=int, default=10)
    p_grep.set_defaults(func=_cmd_grep)

    p_index = sub.add_parser("index", help="知识地产清单")
    p_index.add_argument("--type", dest="type_", default="all", choices=["lessons", "decisions", "remember", "all"])
    p_index.set_defaults(func=_cmd_index)

    sub.add_parser("recent", help="时效状态").set_defaults(func=_cmd_recent)

    sub.add_parser("status", help="记忆活性自检（FAIL 不影响退出码）").set_defaults(func=_cmd_status)

    p_lint = sub.add_parser("lint", help="记忆机制门禁（--strict：任一 FAIL 退出码 1，fastcheck 用）")
    p_lint.add_argument("--strict", action="store_true")
    p_lint.set_defaults(func=_cmd_lint)

    p_gc = sub.add_parser("gc", help="记忆地产自动清理")
    p_gc.add_argument("--dry-run", action="store_true", help="只报告不改")
    p_gc.add_argument("--today", default=None, help="YYYY-MM-DD（默认为今天）")
    p_gc.set_defaults(func=_cmd_gc)

    p_inject = sub.add_parser("inject", help="DSH 原生记忆注入：写 CLAUDE.local.md")
    p_inject.add_argument("--stdout", action="store_true", help="只打印到 stdout")
    p_inject.add_argument("--budget", type=int, default=memory_inject.DEFAULT_BUDGET)
    p_inject.add_argument("--source", default="startup", choices=memory_inject.SOURCES)
    p_inject.add_argument("--target", default=None, help="覆盖输出路径")
    p_inject.set_defaults(func=_cmd_inject)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
