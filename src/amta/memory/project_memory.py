"""memory.py — 项目级记忆检索（v0，索引优先 + 全文兜底）。

读协议：动手改翻译策略 / 工位架构 / 引擎选型前，先 ``search``；命中后 ``read`` 深读原文。
写协议：会话 / 迭代收尾产生新经验时，``add`` 追加索引行，并把正文写进对应文档。
读者：AI 会话（现在）与项目级自主循环（Lesson 05，届时包一层 function-calling 声明即可）。
零依赖：仅标准库。索引格式见 docs/INDEX.md。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]  # src/amta/memory/project_memory.py → 仓库根（原 memory.py 在 src/amta/ 下为 parents[2]）
INDEX_PATH = ROOT / "docs" / "INDEX.md"
CORPUS_GLOBS = [
    "docs/decisions/*.md",
    "docs/lessons.md",
    "docs/progress.md",
    "docs/superpowers/plans/*.md",
]
MAX_LINES_PER_FILE = 3
ROW_RE = re.compile(r"^\|\s*([DLR]-\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")

_stdout = cast(Any, sys.stdout)
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_index(index_path: Path = INDEX_PATH) -> list[dict[str, str]]:
    """解析 INDEX.md 表格行，返回 [{id, trigger, path, value}]。"""
    rows: list[dict[str, str]] = []
    if not index_path.exists():
        return rows
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append(
                {
                    "id": m.group(1),
                    "trigger": m.group(2),
                    "path": m.group(3).strip(),
                    "value": m.group(4),
                }
            )
    return rows


def _corpus_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for pattern in CORPUS_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    return files


def search(query: str, index_path: Path = INDEX_PATH, root: Path = ROOT) -> dict[str, Any]:
    """索引命中（按命中词数排序）+ 全文行命中（每文件限 MAX_LINES_PER_FILE 行）。"""
    terms = [t for t in query.split() if t]
    if not terms:
        return {"query": query, "index_hits": [], "fulltext_hits": []}
    low_terms = [t.lower() for t in terms]

    index_hits: list[dict[str, Any]] = []
    for row in parse_index(index_path):
        hay = f"{row['id']} {row['trigger']} {row['path']} {row['value']}".lower()
        score = sum(1 for t in low_terms if t in hay)
        if score:
            index_hits.append({"score": score, **row})
    index_hits.sort(key=lambda x: (-x["score"], str(x["id"])))

    fulltext_hits: list[dict[str, Any]] = []
    for f in _corpus_files(root):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        shown = 0
        for i, line in enumerate(lines, 1):
            low = line.lower()
            if any(t in low for t in low_terms):
                fulltext_hits.append(
                    {"file": rel, "line": i, "text": line.strip()[:160]}
                )
                shown += 1
                if shown >= MAX_LINES_PER_FILE:
                    break
    return {"query": query, "index_hits": index_hits, "fulltext_hits": fulltext_hits}


def _extract_section(body: str, anchor: str) -> str:
    """按标题关键词截取小节（如 lessons.md 的 L7），找不到返回全文。"""
    pat = re.compile(rf"^(#+\s*.*?{re.escape(anchor)}\b.*$)", re.MULTILINE)
    m = pat.search(body)
    if not m:
        return body
    nxt = re.search(r"^#{1,3}\s+", body[m.end():], re.MULTILINE)
    end = m.end() + nxt.start() if nxt else len(body)
    return body[m.start():end].strip()


def read(rid: str, index_path: Path = INDEX_PATH, root: Path = ROOT) -> str:
    """按 ID 打开索引指向的文件；路径含 #锚点 时只输出对应小节。"""
    for row in parse_index(index_path):
        if row["id"].lower() == rid.lower():
            raw_path = row["path"]
            anchor = ""
            if "#" in raw_path:
                raw_path, anchor = raw_path.split("#", 1)
            p = root / raw_path
            if not p.exists():
                return f"[miss] {row['path']} 不存在（索引过期？）"
            body = p.read_text(encoding="utf-8", errors="replace")
            if anchor:
                body = _extract_section(body, anchor)
            head = f"== {row['id']} | {row['trigger']} | {row['value']}\n== {row['path']}\n"
            return head + "\n" + body
    return f"[miss] 索引里没有 {rid}（先 add）"


def add(
    rid: str,
    trigger: str,
    path: str,
    value: str,
    index_path: Path = INDEX_PATH,
) -> str:
    """向 INDEX.md 表格末尾追加一行（写回协议的落点）。"""
    rows = parse_index(index_path)
    if any(r["id"].lower() == rid.lower() for r in rows):
        return f"[skip] {rid} 已在索引"
    lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
    table_lines = [i for i, line in enumerate(lines) if line.strip().startswith("|")]
    if not table_lines:
        return "[miss] INDEX.md 里没有表格可追加"
    row = f"| {rid} | {trigger} | {path} | {value} |"
    lines.insert(table_lines[-1] + 1, row)
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"[added] {row}"


def stats(index_path: Path = INDEX_PATH, root: Path = ROOT) -> str:
    rows = parse_index(index_path)
    by_prefix: dict[str, int] = {}
    for row in rows:
        prefix = row["id"].split("-")[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
    parts = [f"{k}:{v}" for k, v in sorted(by_prefix.items())]
    corpus = _corpus_files(root)
    return f"索引 {len(rows)} 条（{' '.join(parts)}）；全文语料 {len(corpus)} 个文件"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="项目级记忆检索 v0（索引优先 + 全文兜底）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_search = sub.add_parser("search", help="索引 + 全文检索")
    p_search.add_argument("query")
    p_search.add_argument("--json", action="store_true", help="输出 JSON（供工具循环消费）")
    p_read = sub.add_parser("read", help="按 ID 深读原文")
    p_read.add_argument("rid")
    p_add = sub.add_parser("add", help="追加索引行（写回协议）")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--trigger", required=True)
    p_add.add_argument("--path", required=True)
    p_add.add_argument("--value", required=True)
    sub.add_parser("stats", help="索引统计")
    args = ap.parse_args(argv)

    if args.cmd == "search":
        out = search(args.query)
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        for h in out["index_hits"]:
            print(f"[index] {h['id']} | {h['trigger']} | {h['path']} | {h['value']}")
        for h in out["fulltext_hits"]:
            print(f"[text ] {h['file']}:{h['line']}: {h['text']}")
        if not out["index_hits"] and not out["fulltext_hits"]:
            print(f"[none] 语料中没有命中：{args.query}")
    elif args.cmd == "read":
        print(read(args.rid))
    elif args.cmd == "add":
        print(add(args.id, args.trigger, args.path, args.value))
    elif args.cmd == "stats":
        print(stats())
    return 0
