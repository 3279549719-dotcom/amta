"""inject — DSH 原生记忆注入：把记忆包写进 CLAUDE.local.md（随会话自动加载）。

背景：DSH 没有 Claude Code 的 SessionStart stdout hook（不消费 stdout 注入），
但它有**自己的原生注入机制** —— `agent-instructions` 插件自动加载 workspace 根
（amta）的 AGENTS.md / CLAUDE.md，以及本地 overlay AGENTS.local.md /
CLAUDE.local.md（均为默认候选，无需改任何 profile / preset 配置）。
本项目 workspace 根 = 仓库根（amta），因此写 amta/CLAUDE.local.md 即可让**当前记忆包**
随每个 DSH 会话自动注入 —— 实现记忆系统「推送层」自动化，不再依赖执行纪律自触发。

用法（统一入口 scripts/memory.py inject）：
  python scripts/memory.py inject             # 生成/刷新 amta/CLAUDE.local.md（默认）
  python scripts/memory.py inject --stdout    # 只打印记忆包到 stdout（调试/外部消费）
  python scripts/memory.py inject --budget N  # 自定义包预算（默认 4096）
  python scripts/memory.py inject --source X  # startup|compact|resume|clear|fork（默认 startup）
  python scripts/memory.py inject --target P  # 覆盖输出路径（默认 <root>/CLAUDE.local.md）

纪律：① 恒 exit 0 不阻塞（地产异常降级为占位包）；② 输出显式 UTF-8（L30 Windows 编码坑）；
      ③ 幂等可重跑；④ 只写 .gitignore 已覆盖的生成文件（*.local），不碰 docs/ 权威源。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from amta.memory.estate import build_pack

DEFAULT_BUDGET = 4096  # DSH 本地 overlay 包预算（CC hook 1.5KB 上限不适用文件加载；4KB 兼顾内容与成本）
SOURCES = ("startup", "compact", "resume", "clear", "fork")

# 仓库根 = 本模块 src/amta/memory 的上三级（amta）。AGENTS.md/CLAUDE.md 与记忆地产 .remember/ 都在此，
# DSH 的 agent-instructions 以此扫描注入；不依赖调用时 cwd（fastcheck 在 amta 跑、手工在别处跑都对）。
REPO_ROOT = Path(__file__).resolve().parents[3]


def _pack(root: Path, source: str, budget: int) -> str:
    """构造记忆包；地产读取任何异常都不抛（注入纪律）。"""
    try:
        return build_pack(root, source=source, budget=budget)
    except Exception:  # noqa: BLE001 — 注入纪律：地产异常降级，不阻塞会话生成
        return "=== AMTA 记忆包(degraded) ===\n记忆地产读取异常：先跑 python scripts/memory.py status"


def build_local_md(root: Path, source: str, budget: int) -> str:
    """把记忆包包进一个带说明头的 CLAUDE.local.md 文档。"""
    pack = _pack(root, source, budget)
    return (
        "# 本地记忆注入包 — 自动生成，勿手改\n\n"
        "> 由 `python scripts/memory.py inject` 生成。DSH 的 `agent-instructions` 插件"
        "把本文件（CLAUDE.local.md）随每个会话自动注入上下文（记忆推送层，无需自触发）。\n"
        "> 刷新：`python scripts/memory.py inject`；完整记忆读取：memory_search / memory_grep。\n\n"
        + pack
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DSH 原生记忆注入：写 CLAUDE.local.md（自动加载）")
    ap.add_argument("--stdout", action="store_true", help="只打印到 stdout，不写文件")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help=f"包预算（默认 {DEFAULT_BUDGET}）")
    ap.add_argument("--source", default="startup", choices=SOURCES, help="注入包形态（默认 startup）")
    ap.add_argument("--target", default=None, help="覆盖输出路径（默认 <root>/CLAUDE.local.md）")
    args = ap.parse_args(argv)

    root = REPO_ROOT  # 地产根 = 仓库根 amta（与 AGENTS.md/CLAUDE.md 同处，DSH 自动扫描）
    text = build_local_md(root, args.source, args.budget)

    if args.stdout:
        print(text)
        return 0

    target = Path(args.target) if args.target else root / "CLAUDE.local.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[memory_inject] 写入失败: {exc}")
        return 1
    print(f"[memory_inject] wrote {target} ({len(text)} chars, source={args.source})")
    return 0
