"""trace_probe — 读 claude 会话 JSONL 的轻量探针（心跳 / 卡死诊断 / trace 统计）。

供 ralph.ps1 使用，零依赖（stdlib only）。三种子命令：

  live  <projects_dir> [--after <ISO>]  找当前 claude -p 会话的 jsonl
                                        （LastWriteTime >= after 的最新一个；不带 after = 全局最新）
  tail  <jsonl> [--lines N]             卡死诊断：最后一次工具调用 / 最后文本 / 最后 tool_result
  stats <jsonl>                         trace 统计：工具调用数 / 最常用工具 / 最大停顿 / 重复调用

CLAUDE Code 会话文件位于 ~/.claude/projects/<slug>/<uuid>.jsonl，每行一个 JSON 事件
（type: system / user / assistant / attachment / file-history-snapshot ...）。
assistant 消息的 message.content 是 block 数组，其中 {type:"tool_use", name, input} 是工具调用；
user 消息的 content 里 {type:"tool_result", is_error} 是工具结果。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter
from pathlib import Path

_stdout = sys.stdout
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _parse(line: str) -> dict | None:
    try:
        o = json.loads(line)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None


def _content(o: dict) -> list:
    return (o.get("message") or {}).get("content") or []


def _iso_ts(v) -> str:
    return str(v or "")


def _parse_ts(v: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def cmd_live(args: argparse.Namespace) -> int:
    """找 mtime >= --after 的最新 jsonl（即当前 claude -p 会话）。"""
    after = None
    if args.after:
        after = _parse_ts(args.after)
    newest: tuple[Path, float] | None = None
    for p in sorted(Path(args.projects_dir).glob("*/*.jsonl")):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if after is not None and mt < after.timestamp():
            continue
        if newest is None or mt > newest[1]:
            newest = (p, mt)
    if newest:
        print(newest[0])
        return 0
    return 1


def cmd_tail(args: argparse.Namespace) -> int:
    """扫描 jsonl 尾部，输出卡死现场：最后一次工具调用 / 最后文本 / 最后 tool_result。"""
    p = Path(args.jsonl)
    if not p.exists():
        print("trace_probe: jsonl 不存在", file=sys.stderr)
        return 1
    lines = _read_lines(p)
    tail = lines[-args.lines:] if args.lines else lines
    last_tool: tuple[str, str] | None = None      # (name, ts)
    last_text: tuple[str, str] | None = None      # (text, ts)
    last_result: tuple[str, str] | None = None    # (is_error, ts)
    for line in tail:
        o = _parse(line)
        if not o:
            continue
        ts = _iso_ts(o.get("timestamp"))
        typ = o.get("type")
        if typ == "assistant":
            for blk in _content(o):
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")
                if btype == "tool_use":
                    last_tool = (str(blk.get("name") or "?"), ts)
                elif btype == "text":
                    txt = (blk.get("text") or "").strip()
                    if txt:
                        last_text = (txt, ts)
        elif typ == "user":
            for blk in _content(o):
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    last_result = (str(bool(blk.get("is_error"))), ts)
    if last_tool:
        print(f"last_tool_call: {last_tool[0]} @ {last_tool[1]}")
    if last_text:
        preview = last_text[0].replace("\n", " ")[:100]
        print(f"last_text: {preview} @ {last_text[1]}")
    if last_result:
        print(f"last_tool_result: is_error={last_result[0]} @ {last_result[1]}")
    print(f"tail_lines_scanned: {len(tail)}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """trace 统计：工具调用数 / 最常用工具 / 最大停顿 / 重复调用（反查 Harness 低效）。"""
    p = Path(args.jsonl)
    if not p.exists():
        print("trace_probe: jsonl 不存在", file=sys.stderr)
        return 1
    tool_count = 0
    tools: Counter[str] = Counter()
    call_sigs: Counter[tuple[str, str]] = Counter()
    times: list[_dt.datetime] = []
    for line in _read_lines(p):
        o = _parse(line)
        if not o:
            continue
        if o.get("timestamp"):
            dt = _parse_ts(_iso_ts(o.get("timestamp")))
            if dt:
                times.append(dt)
        if o.get("type") != "assistant":
            continue
        for blk in _content(o):
            if not isinstance(blk, dict):
                continue
            if blk.get("type") != "tool_use":
                continue
            name = str(blk.get("name") or "?")
            tool_count += 1
            tools[name] += 1
            try:
                sig = json.dumps(blk.get("input") or {}, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                sig = ""
            call_sigs[(name, sig)] += 1
    print(f"tool_calls: {tool_count}")
    if tools:
        top = tools.most_common(5)
        print("tools: " + ", ".join(f"{n}={c}" for n, c in top))
    if len(times) >= 2:
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        print(f"max_stall_seconds: {int(max(gaps))}")
        wall = (times[-1] - times[0]).total_seconds()
        print(f"wall_seconds: {int(wall)}")
    repeated = [(n, s, c) for (n, s), c in call_sigs.items() if c > 1]
    print(f"repeated_calls: {len(repeated)}")
    for n, s, c in repeated[:5]:
        preview = s[:60].replace("\n", " ")
        print(f"  {n}: {preview} x{c}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="claude 会话 JSONL 探针（心跳/诊断/统计）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_live = sub.add_parser("live", help="找当前会话 jsonl")
    p_live.add_argument("projects_dir")
    p_live.add_argument("--after", help="只取 LastWriteTime >= 该 ISO 的最新文件")

    p_tail = sub.add_parser("tail", help="卡死诊断：扫描尾部")
    p_tail.add_argument("jsonl")
    p_tail.add_argument("--lines", type=int, default=40)

    p_stats = sub.add_parser("stats", help="trace 统计")
    p_stats.add_argument("jsonl")

    args = ap.parse_args()
    if args.cmd == "live":
        return cmd_live(args)
    if args.cmd == "tail":
        return cmd_tail(args)
    return cmd_stats(args)


if __name__ == "__main__":
    raise SystemExit(main())
