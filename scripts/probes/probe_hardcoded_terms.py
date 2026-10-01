"""任务 6 验证：生产代码 / prompt / 专用规则里不得硬编码示例词。

用法：
    uv run python scripts/probes/probe_hardcoded_terms.py --patterns-file <file> [--scope src scripts ...]

背景（为什么不能写成一行 PowerShell 命令）：
    PowerShell 把 CJK 参数交给子进程时会损坏——实测把某个日文自造词直接用
    `git grep -e <词>` 传进去，到 python 里已变成乱码，`git grep` 因此 **0 命中**，
    看起来"验证通过"，其实是**假阴性**。所以模式一律从文件读，绝不走命令行 argv。

    同理，本脚本自己的文档字符串**不复述具体词**——否则它会命中自己，
    把真实结论淹没在自指噪声里（第一版就踩了这个，检查输出 1 条命中全是自己）。

四条设计规则（都是从真实事故里学来的）：
  1. 模式从文件读，不走 argv        —— 绕开命令行编码
  2. 强制 UTF-8 读写 + 显式子进程编码 —— 不靠系统默认代码页
  3. 必须报告"扫了多少文件、命中多少" —— 否则"0 命中"分不清是"干净"还是"根本没扫"
  4. 扫不到任何文件 → 报错退出       —— 检查本身失效时必须显式失败，不许静默成功

  第 3、4 条来自 depguard 的教训：它曾因解析库在包语境下静默返回空结果，
  既不报错也没查出任何东西——一个"看起来在检查、其实什么都没查"的机制，
  比没有机制更危险。另外 `git grep` 默认**看不见未跟踪的新文件**，
  所以这里必须带 `--untracked`，否则刚写出来还没 add 的违规是隐形的。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from amta.common.encoding import force_utf8_stdio  # noqa: E402

# 本脚本会打印中文诊断信息；Windows 控制台默认 GBK → 必须走仓库唯一 UTF-8 收口点，
# 否则 `UnicodeEncodeError`（tests/test_encoding.py 的中文脚本收口点断言会拦）。
force_utf8_stdio()


def _run_grep(pattern_file: Path, scope: str) -> tuple[int, str]:
    """在 scope 内跑 git grep，**包含未跟踪但未被忽略的文件**。

    必须加 `--untracked`：`git grep` 默认只看已跟踪文件，于是**刚写出来还没 add 的
    新文件是隐形的**——实测把一条违规植入未跟踪的新文件里，git grep 返回
    rc=1（无命中），检查静默通过。这正是本脚本要消灭的那类假阴性，
    不能自己再犯一次。
    模式走 `-f` 文件，绝不走 argv（PowerShell 传 CJK 参数会损坏）。
    """
    proc = subprocess.run(
        ["git", "grep", "-n", "-I", "--untracked", "-f", str(pattern_file), "--", scope],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # git grep: 0=有命中, 1=无命中, 其他=真错误
    return proc.returncode, (proc.stdout or "")


def _count_scanned(scope: str) -> int:
    """该 scope 下会被检查的文件数（已跟踪 + 未跟踪且未被忽略）。

    同时用于**证明"确实扫了东西"**：只有已跟踪计数的话，新写的文件不在里面，
    "0 命中"就可能是因为压根没看。
    """
    total = 0
    for extra in ([], ["--others", "--exclude-standard"]):
        proc = subprocess.run(
            ["git", "ls-files", *extra, "--", scope],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        total += len([ln for ln in (proc.stdout or "").splitlines() if ln.strip()])
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patterns-file", required=True, type=Path,
                    help="每行一个待查词（UTF-8，不走 argv）")
    ap.add_argument("--scope", nargs="+", default=["src/", "scripts/"],
                    help="要检查的路径（git grep 路径集）")
    ap.add_argument("--fail-on-hit", action="store_true", default=True,
                    help="命中即失败（默认开）")
    args = ap.parse_args()

    if not args.patterns_file.is_file():
        print(f"[probe] 模式文件不存在: {args.patterns_file}", file=sys.stderr)
        return 2

    # utf-8-sig：PowerShell 的 `Set-Content -Encoding UTF8` 会写 BOM。
    # 不去 BOM 的话，一个"空"文件会解析出一条 \ufeff 模式，而它匹配**每个文件的第一行**，
    # 报出一堆假命中（实测：BOM+空行 → 3 处假命中）。同一类 BOM 坑本仓已踩过多次。
    raw = args.patterns_file.read_text(encoding="utf-8-sig", errors="replace")
    patterns = [ln.strip().lstrip("\ufeff") for ln in raw.splitlines()]
    patterns = [p for p in patterns if p]
    if not patterns:
        print("[probe] 模式文件是空的——什么都不查的检查等于没检查", file=sys.stderr)
        return 2
    print(f"[probe] 模式 {len(patterns)} 条: {', '.join(patterns)}")

    total_scanned = 0
    failures = 0
    for scope in args.scope:
        n_files = _count_scanned(scope)
        total_scanned += n_files
        rc, out = _run_grep(args.patterns_file, scope)
        hits = [ln for ln in out.splitlines() if ln.strip()]
        if rc not in (0, 1):
            print(f"[probe] {scope}: git grep 出错 rc={rc}", file=sys.stderr)
            return 2
        status = "CLEAN" if not hits else f"{len(hits)} HITS"
        print(f"[probe] {scope}: 待查文件 {n_files} 个（含未跟踪）-> {status}")
        if hits:
            for ln in hits:
                print(f"    {ln}")
            failures += len(hits)

    # 规则 4：扫不到东西必须显式失败
    if total_scanned == 0:
        print("[probe] 未能扫描到任何文件——检查失效，判为失败（不许静默通过）",
              file=sys.stderr)
        return 2

    print(f"[probe] 合计待查文件 {total_scanned} 个")
    if failures and args.fail_on_hit:
        print(f"[probe] FAIL: {failures} 处命中", file=sys.stderr)
        return 1
    print("[probe] PASS: 无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
