"""fastcheck — 机械质检（分层：--quick 秒级 / 默认完整 9 步）。

两种模式（2026-09-10 分层，避免 pre-commit 与 /finish 重复跑 pytest）：
  --quick  秒级快检（pre-commit 钩子用）：compileall + ruff lint + pyright（只读，不写文件）
  默认     完整 9 步（/finish 收尾用）：quick 三步 + pytest + depguard + mem-lint/gc/inject
           + audit + module-map 就地刷新（生成物在收口点更新，而不是事后检查）

退出码：0 = 全过；非 0 = 有失败。
"""
from __future__ import annotations

import argparse
import compileall
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.paths import ROOT as _PATHS_ROOT

ROOT = _PATHS_ROOT  # 统一用 paths.ROOT，不自己算


def _run(cmd: list[str], label: str) -> int:
    print(f"== [fastcheck] {label} ==")
    r = subprocess.call(cmd, cwd=str(ROOT))
    print(f"== {label}: {'OK' if r == 0 else 'FAIL'} ==")
    return r


def _compile() -> int:
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1, force=True)
    ok = compileall.compile_dir(str(ROOT / "scripts"), quiet=1, force=True) and ok
    return 0 if ok else 1


def _resolve_tool(name: str) -> str | None:
    """确定性地解析工具链：**先本 venv，再 PATH**。

    为什么必须定死（2026-09-10 实测，旧账见 lessons L26）：`shutil.which(name)` 的结果
    取决于谁在跑——`uv run` 把 PATH 收窄到 venv，于是拿到 `.venv\\Scripts\\ruff.EXE`；
    直接在 pwsh 里跑则拿到全局 Python313 的 ruff。**同一条命令两个判定**：
    实测 venv 的报 `I001`，全局的说"无问题"。

    收口原则：一切以 uv 环境为准（CLAUDE.md 规定所有 Python 命令走 `uv run python`）。
    """
    exe = ".exe" if os.name == "nt" else ""
    local = Path(sys.executable).parent / f"{name}{exe}"
    if local.exists():
        return str(local)
    return shutil.which(name)


def _resolve_and_report(name: str) -> str | None:
    """解析工具并**打印结果 + 漂移告警**——让"两个 ruff"这种事可见而不是静默。"""
    chosen = _resolve_tool(name)
    if chosen:
        print(f"== [fastcheck] {name} = {chosen} ==")
    on_path = shutil.which(name)
    if chosen and on_path and Path(on_path).resolve() != Path(chosen).resolve():
        print(f"== [fastcheck] !! {name} 漂移：venv={chosen} ｜ PATH={on_path}（以 venv 为准）==")
    return chosen


def _lint() -> int:
    ruff = _resolve_and_report("ruff")
    if ruff:
        return _run([ruff, "check", "src", "scripts", "tests"], "ruff lint")
    # 兜底：ruff 作为 python 模块
    print("== [fastcheck] ruff 未找到可执行文件，回退 python -m ruff ==")
    return _run([sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"], "ruff lint")


def _typecheck() -> int:
    pyright = _resolve_and_report("pyright")
    if not pyright:
        print("== [fastcheck] pyright 未安装，跳过 type check ==")
        return 0
    return _run([pyright, "src"], "pyright type check")


def _test() -> int:
    """跑 tests/ 单测。tests/ 是 pytest 风格（模块级 test_* 函数 + tmp_path/monkeypatch fixtures）；
    `unittest discover` 只收 TestCase 类会静默跳过模块级函数（曾致 translate/workstate 测试不跑却报 PASS）。
    Windows 下 pytest 尾部 PermissionError: pytest-current 是 tmp_path teardown 噪音，
    结果以汇总行 "N passed" 判定，不以 exit code 判定。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # --basetemp 规避 Windows 下 pytest 默认 basetemp 的 pytest-current symlink teardown
    # PermissionError：指定显式目录后 pytest 不建该 symlink。
    # 每次用 pid 唯一目录（2026-09-10 修复）：固定目录一旦权限损坏（WinError 5 僵尸目录，
    # 连 icacls/rd 都删不掉），teardown 失败会让每个文件首个用例后的全部用例 ERROR
    # （436 passed 退化为 253 passed+183 ERROR）；唯一目录跑完即弃，坏目录无法再污染。
    basetemp = ROOT / "output" / "logs" / f".pytest-bt-{os.getpid()}"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "--basetemp", str(basetemp)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    shutil.rmtree(basetemp, ignore_errors=True)  # best-effort: 删不掉不影响（下次换 pid 新目录）
    print(out[-2000:])
    import re as _re
    m = _re.search(r"(\d+) passed", out)
    failed = _re.search(r"(\d+) failed", out)
    if m and not failed:
        print(f"== [fastcheck] pytest: {m.group(1)} passed ==")
        return 0
    print(f"== [fastcheck] pytest 无通过汇总（exit {r.returncode}）==")
    return 1


def _depguard() -> int:
    """依赖膨胀守卫（ADR-015）：拦截未声明/未使用第三方依赖。"""
    return _run([sys.executable, str(ROOT / "scripts" / "depguard.py")], "depguard (依赖膨胀守卫)")


def _memory_lint() -> int:
    """记忆机制活性门（ADR-025）：staleness/幽灵路径/注入预算。strict：FAIL → 1。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "lint", "--strict"], "memory lint (ADR-025)")


def _memory_gc() -> int:
    """记忆地产 GC 活性检查：dry-run 验证 GC 可用、不真改文件（腐坏由 CLAUDE.md 协议在收尾时真跑清理）。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "gc", "--dry-run"], "memory gc (dry-run)")


def _memory_inject() -> int:
    """DSH 记忆推送层活性：重新生成 amta/CLAUDE.local.md（agent-instructions 自动注入的本地 overlay）。

    写模式：幂等重跑，只刷新 .gitignore 已覆盖（*.local）的生成文件，不碰 docs/ 权威源。
    既验证记忆包可构建，又保证每轮验证后注入包保持新鲜。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "inject"], "memory inject (CLAUDE.local.md)")


def _module_map() -> int:
    """生成物就地刷新：重跑 `find_code.py --index` 重写 docs/module-map.md。

    **为什么是"写"而不是"查"**（2026-09-10 决定）：
    module-map 是 `find_code.py --index` 的产物，CLAUDE.md 要求 agent「找代码先看它」。
    此前刷新是**手动**的，于是它腐化成 6/99 条指向几个月前删掉的文件；当时的修法是
    加一条守卫测试（test_reference_integrity.TestGeneratedDocsAreFresh）——
    但那只是**事后检查**：陈旧地图仍然躺在磁盘上被 agent 读到，守卫只在收尾喊一声。

    收口原则：生成物应该在**它该更新的那一刻**更新，而不是等谁事后发现它旧了。
    本步跑在**全量**分支（即 `state.py finish` 必经的收口点），因此跑完 fastcheck 后
    磁盘上的地图必然与代码一致，守卫测试随之恒真——它从"拦截器"退化为"冗余保险"，
    这正是它该有的位置。--quick 不跑本步（不写文件，保持 pre-commit 只读）。
    """
    return _run([sys.executable, str(ROOT / "scripts" / "find_code.py"), "--index"], "module-map (生成物刷新)")


def _audit() -> int:
    """Harness 熵审计（--strict 门禁模式）。

    2026-09-10 体检的核心发现：**所有漂移探测器都存在、都算得对、然后接不到
    任何会失败的东西上**。audit.py 是最典型的例子——它审计 workspace 空壳、
    重复文件、顶层散落，但 exit 永远 0 且不在本文件里，于是它的结论没有任何人
    能看见（workspace/ws-* 已从 595 涨到 2164，第三次长回来）。

    所以这里用 --strict 把它变成真门禁。跑在**全量**分支：它要遍历目录。
    """
    return _run([sys.executable, str(ROOT / "scripts" / "audit.py"), "--strict"], "audit (Harness 熵)")


def _root_check() -> int:
    """ROOT 路径回归检查（2026-09-10）：确保 paths.ROOT 指向正确的项目根。

    历史教训：paths.py 的 ROOT 上溯级数曾算错（三级→四级），导致 detect 找不到模型、
    inpaint 找不到 lama 权重、pre_scan 找不到 master dict。此检查在 commit 时自动拦截
    此类回归，不需要等跑管线才发现。
    """
    from amta.common.paths import ROOT
    expected_dirs = ["models", "src/amta", "scripts", "tests", "docs"]
    missing = [d for d in expected_dirs if not (ROOT / d).exists()]
    if missing:
        print(f"== [fastcheck] ROOT check FAIL: ROOT={ROOT}")
        print(f"   缺失目录: {', '.join(missing)}")
        print("   请检查 src/amta/common/paths.py 的 ROOT 上溯级数")
        return 1
    # 关键文件检查
    key_files = ["models/CTBD/detector.onnx", "models/big-lama.pt", "pyproject.toml"]
    missing_files = [f for f in key_files if not (ROOT / f).exists()]
    if missing_files:
        print(f"== [fastcheck] ROOT check FAIL: 缺失关键文件: {', '.join(missing_files)}")
        return 1
    print(f"== [fastcheck] ROOT check OK (ROOT={ROOT}) ==")
    return 0


def _env_check() -> int:
    """环境配置检查（2026-09-10）：确保 .env 存在、API key 能加载。

    只读检查，不修改环境变量（不自动关代理）。完整的环境自检（含自动修复）
    在 run_pipeline.py 启动时由 amta.common.environment 执行。
    """
    from amta.common.paths import ROOT
    # .env 可以在项目根或父目录
    env_paths = [ROOT / ".env", ROOT.parent / ".env"]
    env_found = any(p.exists() for p in env_paths)
    if not env_found:
        print("== [fastcheck] env check FAIL: 未找到 .env 文件")
        print(f"   查找位置: {env_paths[0]} 或 {env_paths[1]}")
        return 1
    # 尝试加载配置，确认 API key 存在
    try:
        from amta.common.config import get_chat_config
        cfg = get_chat_config()
        if not cfg.get("api_key"):
            print("== [fastcheck] env check FAIL: .env 已加载但 CHAT_API_KEY 为空")
            return 1
    except Exception as e:
        print(f"== [fastcheck] env check FAIL: 加载配置异常: {e}")
        return 1
    print("== [fastcheck] env check OK (.env 已加载, API key 存在) ==")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="amta fastcheck 机械质检")
    ap.add_argument("--quick", action="store_true",
                    help="only compile/lint/typecheck (seconds, read-only, used by pre-commit); full 9-step (incl. module-map refresh) is for /finish")
    args = ap.parse_args()

    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    root_rc = _root_check()
    env_rc = _env_check()
    checks: list[tuple[str, int]] = [
        ("compile", c),
        ("lint", lint_rc),
        ("typecheck", t),
        ("ROOT path", root_rc),
        ("env config", env_rc),
    ]
    if not args.quick:
        u = _test()
        d = _depguard()
        m = _memory_lint()
        g = _memory_gc()
        inj = _memory_inject()
        au = _audit()
        mm = _module_map()
        checks.extend([
            ("unit tests", u),
            ("depguard", d),
            ("memory lint", m),
            ("memory gc", g),
            ("memory inject", inj),
            ("audit", au),
            ("module-map", mm),
        ])
    else:
        print("== [fastcheck] --quick: skip pytest/depguard/memory/audit/module-map (full run at /finish) ==")
    fails = [name for name, rc in checks if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] QUICK PASS ==" if args.quick else "== [fastcheck] ALL PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
