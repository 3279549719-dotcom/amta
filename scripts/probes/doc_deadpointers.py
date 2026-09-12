"""量出「手写散文文档里的死指针」有多少 —— 修复前 vs 现在。

关键：判断「死」必须对照 HEAD 自己的文件清单（git ls-tree），
而不是工作区 —— 否则删掉的文件会被误判成 HEAD 里就是死的。

一次性实验脚本，按项目约定放 scripts/probes/。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# 单一事实源：判定「这行在陈述历史而非发指令」的规则只有一份。
from amta.memory.lint import is_historical_note

DOCS = ("CLAUDE.md", "AGENTS.md", "README.md", "RUNBOOK.md")

# 反引号里的、看起来像仓库内路径的 token
TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|ps1|json|md|yml|yaml|toml|sh))`")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def head_files() -> set[str]:
    return {line.strip() for line in git("ls-tree", "-r", "--name-only", "HEAD").splitlines() if line.strip()}


def show(path: str) -> str:
    return git("show", f"HEAD:{path}")


def referenced(text: str) -> set[str]:
    out: set[str] = set()
    for m in TOKEN.finditer(text):
        tok = m.group(1)
        if tok.startswith(("http", "/")):
            continue
        out.add(tok)
    return out


def dead_against(text: str, universe: set[str]) -> list[str]:
    """逐行扫描：陈述历史的那一行不算「死指针」。"""
    univ_basenames = {p.rsplit("/", 1)[-1] for p in universe}
    dead = []
    for line in text.splitlines():
        if is_historical_note(line):
            continue
        for tok in referenced(line):
            if tok in universe:
                continue
            # 允许写成裸文件名，只要仓库里存在同名文件
            if "/" not in tok and tok in univ_basenames:
                continue
            dead.append(tok)
    return sorted(set(dead))


def main() -> int:
    head = head_files()
    now = {
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in ROOT.rglob("*")
        if p.is_file() and ".git/" not in str(p).replace("\\", "/")
    }

    old_total = 0
    new_total = 0
    for doc in DOCS:
        old_dead = dead_against(show(doc), head)
        new_text = (ROOT / doc).read_text(encoding="utf-8")
        new_dead = dead_against(new_text, now)
        old_total += len(old_dead)
        new_total += len(new_dead)
        print(f"{doc:12s} 修复前死指针 {len(old_dead):2d}  现在 {len(new_dead):2d}")
        for d in old_dead[:4]:
            print(f"               - {d}")

    print(f"\n合计：修复前 {old_total} 条 -> 现在 {new_total} 条")
    return 0 if new_total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
