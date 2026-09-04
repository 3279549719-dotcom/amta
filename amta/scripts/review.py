"""review — L6 独立 model 审核门（ADR-030）：让一个"不知道你做了什么"的第二个模型独立审 diff。

把 git diff + 验收标准（loop_state.json 或 --mission）打包，spawn 一个新鲜的 `claude -p` 会话，
它没有任何本会话上下文，只能从 diff 和标准推断，审三件事：
  ① 达成度：改动是否达成验收标准（逐条对）
  ② 风险：有没有漏需求 / 引入 bug / 破坏既有契约
  ③ 证据：有没有"看起来对但没证据"的断言
输出结构化 VERDICT: PASS | FAIL | CONCERN + 编号发现（带证据）。

用法（在 amta 目录下）：
  uv run python scripts/review.py                                  # 审 main...HEAD + 工作区改动
  uv run python scripts/review.py --base main --out output/logs/review-1.md
  uv run python scripts/review.py --mission "验收: fastcheck ALL PASS + pytest 315 passed"
  uv run python scripts/review.py --no-worktree --model sonnet     # 只审已提交 diff，指定模型

退出码：0 = PASS / CONCERN（无阻断）；1 = FAIL（有阻断）；2 = 环境/调用错误。
零依赖（stdlib only）；spawn 用项目已有的 `claude -p`（ralph.ps1 同款），review 会话只给
Read/Grep/Glob 只读工具，可自行查证代码但不能改动任何文件。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_stdout = sys.stdout
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")

PROMPT_TEMPLATE = """你是 AMTA（漫画翻译自动化项目）的独立代码审核员。

你被派来审核一次代码改动。你【不知道】开发者做了什么、为什么这么改、怎么想的——
你只能从下面给出的 diff 和验收标准推断。请保持独立判断，不要假设改动是正确的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 一、验收标准
{criteria}

## 二、本次改动（git diff，base={base}...HEAD {worktree_note}）
{diff}

## 三、审核任务（三个维度，逐条作答）
① 达成度：改动是否达成验收标准？逐条核对，缺的 / 部分达成的标出来。
② 风险：有没有漏掉的需求、明显引入的 bug、会破坏既有功能 / 契约的改动？
③ 证据：有没有"看起来对但没证据"的断言（如注释声称已验证/已测试，但代码路径明显没跑、没有测试覆盖）？

## 四、输出格式（严格遵守）
正文用编号列出发现（1. 2. 3. ...），每条给出【证据】（文件:行 或 diff 摘录）+ 一句话理由。
只写有证据的发现，不要泛泛而谈。控制在 600 字以内。
最后一行必须是（大小写一致）：
VERDICT: PASS|FAIL|CONCERN
- PASS   = 三个维度都没有阻断性问题
- FAIL   = 有阻断性问题（漏需求 / 引入 bug / 验收未达成 / 有证据的矛盾）
- CONCERN= 有疑问但不阻断，需要开发者回应
"""


def _run_git(args: list[str], timeout: int = 30) -> str:
    """在项目根跑 git，返回 stdout；失败返回空串。"""
    if not shutil.which("git"):
        return ""
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _merge_base(base: str) -> str:
    mb = _run_git(["merge-base", base, "HEAD"]).strip()
    return mb if mb else base


def _collect_diff(base: str, include_worktree: bool, max_diff: int) -> tuple[str, str, str]:
    """返回 (commits, stat, diff_text)。diff_text 按 max_diff 截断。"""
    mb = _merge_base(base)
    commits = _run_git(["log", f"{base}..HEAD", "--oneline"]).strip()
    stat = _run_git(["diff", "--stat", f"{mb}..HEAD"]).strip()

    parts: list[str] = []
    committed = _run_git(["diff", f"{mb}..HEAD"])
    if committed.strip():
        parts.append(committed)
    if include_worktree:
        for extra in (_run_git(["diff", "HEAD"]), _run_git(["diff", "--cached"])):
            if extra.strip():
                parts.append(extra)
    diff_text = "\n".join(parts).strip()
    if len(diff_text) > max_diff:
        diff_text = diff_text[:max_diff] + f"\n...[diff 超长已截断 {max_diff} 字符，如需全文用 --max-diff 调大]"
    if not diff_text:
        diff_text = "（无 diff——可能改动为空，或 base 之后没有任何提交且工作区干净）"
    return commits, stat, diff_text


def _load_criteria(mission: str | None) -> str:
    if mission:
        return mission
    sp = ROOT / "loop_state.json"
    if sp.is_file():
        try:
            o = json.loads(sp.read_text(encoding="utf-8"))
            parts = [f"mission: {o.get('mission', '')}",
                     f"current_step: {o.get('current_step', '')}",
                     f"next_action: {o.get('next_action', '')}",
                     f"last_verified: {o.get('last_verified', '')}"]
            return "\n".join(p for p in parts if p)
        except (OSError, json.JSONDecodeError):
            pass
    return "（未提供验收标准 —— 维度①跳过，维度②③照常执行）"


def _locate_session_jsonl(since: float | None = None) -> str:
    """spawn 后定位 claude 会话 JSONL（供 trace_probe 观测）。since 传 review 启动时间戳，
    只认该时间之后有写入的会话，避免错指无关/并发会话（L6 review 首跑实测发现）。找不到返回空串。"""
    proj = Path.home() / ".claude" / "projects"
    if not proj.is_dir():
        return ""
    newest: tuple[Path, float] | None = None
    for p in sorted(proj.glob("*/*.jsonl")):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if since is not None and mt < since:
            continue
        if newest is None or mt > newest[1]:
            newest = (p, mt)
    return str(newest[0]) if newest else ""


def _spawn_review(prompt: str, timeout: int, model: str | None) -> tuple[str, int]:
    """spawn 独立 claude -p 审 prompt。返回 (review_text, rc)：rc=0 成功 / 1 超时 / 2 启动失败。

    Windows 下 claude 是 claude.cmd / claude.ps1，Python subprocess 不能直接执行，
    必须经 cmd /c 走 PATHEXT 解析（Linux/macOS 直接调 claude）。大 prompt 走 stdin 管道
    以绕开 Windows 命令行长度限制（L43）。"""
    if os.name == "nt":
        cmd = ["cmd", "/c", "claude", "-p", "--output-format", "text", "--allowedTools", "Read, Grep, Glob"]
    else:
        cmd = ["claude", "-p", "--output-format", "text", "--allowedTools", "Read, Grep, Glob"]
    if model:
        cmd += ["--model", model]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return "", 1
    except OSError:
        return "", 2
    text = (r.stdout or "").strip() or "(无输出)"
    if r.stderr:
        text += "\n[stderr]\n" + r.stderr.strip()
    return text, 0


def _parse_verdict(text: str) -> str:
    """从 review 输出解析 VERDICT 行，找不到返回 CONCERN。"""
    for line in text.splitlines():
        s = line.strip().upper()
        if s.startswith("VERDICT:"):
            v = s.split(":", 1)[1].strip()
            if v in ("PASS", "FAIL", "CONCERN"):
                return v
    return "CONCERN"


# --selfcheck 用：给 L6 门本身"体检"的固定样例。
# 坏样例 = 含明确缺陷的 diff，门必须抓出（VERDICT=FAIL/CONCERN 且命中预设缺陷词）；
# 干净样例 = 无缺陷的纯函数 diff，门不得误报（VERDICT 非 FAIL）。
SELFCHECK_FIXTURES = [
    {
        "name": "bad-divide-index",
        "criteria": "验收：提供安全的 divide（除零返回 None）和 get_first（空列表返回 None），并有测试覆盖。",
        "diff": (
            "diff --git a/src/amta/calc.py b/src/amta/calc.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/amta/calc.py\n"
            "@@ -0,0 +1,12 @@\n"
            "+def divide(a, b):\n"
            "+    return a / b  # b=0 时会抛 ZeroDivisionError，未处理\n"
            "+\n"
            "+def get_first(items):\n"
            "+    return items[0]  # 空列表会 IndexError，未处理\n"
        ),
        "expect_fail": True,
        "must_mention": ["除零", "ZeroDivision", "IndexError", "空列表"],
    },
    {
        "name": "clean-title",
        "criteria": "验收：提供 title(s) = 去首尾空白 + 标题化，纯函数无副作用。",
        "diff": (
            "diff --git a/src/amta/format.py b/src/amta/format.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/amta/format.py\n"
            "@@ -0,0 +1,4 @@\n"
            "+def title(s):\n"
            "+    return s.strip().title()\n"
        ),
        "expect_fail": False,
        "must_mention": [],
    },
]


def _run_selfcheck(timeout: int, model: str | None) -> int:
    """L6 门有效性自检：坏样例必须被抓到，干净样例必须不误报。0 = 门有效，1 = 门失灵。"""
    print("== [review:selfcheck] L6 门有效性体检：坏样例必须被抓到，干净样例必须不误报 ==")
    ok = True
    for fx in SELFCHECK_FIXTURES:
        prompt = PROMPT_TEMPLATE.format(criteria=fx["criteria"], base="(selfcheck fixture)",
                                        worktree_note="", diff=fx["diff"])
        print(f"== [review:selfcheck] fixture: {fx['name']}（expect_fail={fx['expect_fail']}）spawn claude...")
        text, rc = _spawn_review(prompt, timeout, model)
        if rc != 0:
            print(f"== [review:selfcheck] {fx['name']}: claude 调用失败 rc={rc}（超时或启动错误）→ FAIL ==")
            ok = False
            continue
        verdict = _parse_verdict(text)
        mention = [kw for kw in fx["must_mention"] if kw in text]
        if fx["expect_fail"]:
            caught = verdict in ("FAIL", "CONCERN") and bool(mention)
            status = "PASS（抓到缺陷）" if caught else "FAIL（漏报）"
            print(f"== [review:selfcheck] {fx['name']}: VERDICT={verdict} 命中缺陷词={mention} → {status} ==")
            ok = ok and caught
        else:
            false_pos = verdict == "FAIL"
            status = "PASS（无误报）" if not false_pos else "FAIL（误报干净样例）"
            print(f"== [review:selfcheck] {fx['name']}: VERDICT={verdict} → {status}（期望非 FAIL）==")
            ok = ok and not false_pos
    print("== [review:selfcheck] 总结:", "ALL PASS（L6 门有效）" if ok else "存在 FAIL（L6 门失灵，需排查）", "==")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="L6 独立 model 审核门（spawn 独立 claude -p 审 diff）")
    ap.add_argument("--base", default="main", help="diff 基准 ref（默认 main，用三点 ...HEAD 比较）")
    ap.add_argument("--mission", default=None, help="验收标准文本；缺省读 loop_state.json")
    ap.add_argument("--out", default=None, help="报告输出路径（默认 output/logs/review-<时间戳>.md）")
    ap.add_argument("--max-diff", type=int, default=60000, help="diff 最大字符数（默认 60000）")
    ap.add_argument("--model", default=None, help="claude 模型别名（如 sonnet/opus；缺省用默认模型）")
    ap.add_argument("--no-worktree", action="store_true", help="只审已提交 diff，不含工作区改动")
    ap.add_argument("--timeout", type=int, default=300, help="claude 会话超时秒数（默认 300）")
    ap.add_argument("--selfcheck", action="store_true",
                    help="L6 门有效性自检：用内置坏/好样例验证门真能抓错、不误报，不读真实 diff")
    args = ap.parse_args()

    if not shutil.which("claude"):
        print("review: 找不到 claude CLI（ralph.ps1 同款依赖），无法启动独立审核", file=sys.stderr)
        return 2

    if args.selfcheck:
        return _run_selfcheck(args.timeout, args.model)

    base = args.base
    commits, stat, diff_text = _collect_diff(base, not args.no_worktree, args.max_diff)
    criteria = _load_criteria(args.mission)

    prompt = PROMPT_TEMPLATE.format(
        criteria=criteria, base=base,
        worktree_note="" if args.no_worktree else "（含工作区未提交改动）",
        diff=diff_text,
    )

    out_path = args.out
    if not out_path:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = str(ROOT / "output" / "logs" / f"review-{ts}.md")

    print(f"== [review] base={base}  commits: {len([c for c in commits.splitlines() if c.strip()])}  diff chars={len(diff_text)} ==")
    print(f"== [review] 验收标准来源: {'--mission' if args.mission else 'loop_state.json'} ==")
    print("== [review] spawn 独立 claude -p（只读 Read/Grep/Glob，不知道你做了什么）== ")

    t0 = time.time()  # review 会话定位基准：只认该时刻之后有写入的 jsonl
    review_text, rc = _spawn_review(prompt, args.timeout, args.model)
    if rc == 1:
        print(f"== [review] FAIL: claude 会话超时（>{args.timeout}s）==")
        return 1
    if rc == 2:
        print("== [review] ERROR: claude 启动失败 ==")
        return 2

    verdict = _parse_verdict(review_text)

    lines = [
        "# L6 独立 model 审核报告",
        "",
        f"- 时间: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 基准: {base}...HEAD" + ("" if args.no_worktree else " + 工作区改动"),
        f"- 提交: {commits or '(无)'}",
        f"- diff 统计: {stat or '(空)'}",
        f"- 验收标准: {criteria}",
        f"- 审核模型: {args.model or '(默认)'}",
        f"- 最终判定: **{verdict}**",
        "",
        "---",
        "",
        review_text,
        "",
    ]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"== [review] 报告已写入: {out_path} ==")
    print(f"== [review] VERDICT: {verdict} ==")

    session = _locate_session_jsonl(since=t0)
    if session:
        print(f"== [review] review 会话 JSONL（可用 trace_probe 观测）: {session} ==")

    return 0 if verdict in ("PASS", "CONCERN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
