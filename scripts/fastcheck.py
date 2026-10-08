"""fastcheck — 机械质检（分层：--quick 秒级 / 默认完整）。

两种模式（2026-09-10 分层，避免 pre-commit 与 /finish 重复跑 pytest）：
  --quick  秒级快检（pre-commit 钩子用）：compileall + ruff lint + pyright + ROOT/env（只读，不写文件）
  默认     完整（/finish 收尾用）：上面 5 条 + pytest + depguard + mem-lint/gc/inject
           + module-map 就地刷新（生成物在收口点更新，而不是事后检查）

退出码：0 = 全过；非 0 = 有失败。

## 收尾护栏的接口（2026-10-01 重构成 ClosingGuard，取代 `list[tuple[str, int]]`）

每条护栏**检测一个类别**的东西（行尾风格、依赖声明、生成物与代码一致……），
接口只有六个字段：`name / category / fn / repairs / depends_on / action`。

**从"枚举步骤"改成"声明关系"**的理由（bitter lesson 的用法）：旧写法把"谁必须排在谁前面"
写进注释和代码顺序里——`module-map` 刷新写在 pytest **之后**，而 pytest 里那条
"地图必须新鲜"的断言因此**第一次必红**、跑完刷新后第二次才绿（作者本意是它恒真，
见 `test_reference_integrity` 里那段 docstring，但意图当时无法表达，于是静默错位）。
现在"我修什么生成物"（`repairs`）与"我的判定以什么新鲜为前提"（`depends_on`）是**数据**，
顺序由 `order_guards()` 推出来；声明了前提却没有任何护栏提供它 → 直接抛
（前提没人保证 = 静默失效，见 lessons L58）。

护栏分两类，判据是 `fn` 会不会就地重写 `repairs`：

1. **生成物类**（`repairs` 非空）：先修再验。它**不因"生成物过期"变红**——
   过期状态在收尾入口下根本提交不进去（提交前必然被刷新）。红了只有一个含义：
   **生成器自己坏了**（exit != 0）。
2. **断事类**（`repairs` 为空）：只能验、不能修，因此**红项必须可行动**——
   `action` 字段就是"人看到红能做什么"。不可行动的红是噪声，会把操作者训练成
   伸手去 `--skip-check`（2026-09-10 那次事故的死因）。
"""
from __future__ import annotations

import argparse
import compileall
import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.paths import ROOT as _PATHS_ROOT

ROOT = _PATHS_ROOT  # 统一用 paths.ROOT，不自己算


@dataclass(frozen=True)
class ClosingGuard:
    """一条收尾护栏。

    Attributes:
        name: 打印用的护栏名。
        category: 它检测/维护的**类别**（一句话，人读的）。
        fn: 跑它，返回退出码。0 = 通过。
        repairs: 它会**就地重写**的生成物路径（相对 ROOT）。非空 = 生成物类护栏：
            过期不算红，先修再验。
        depends_on: 它的判定以哪些生成物**新鲜**为前提（相对 ROOT）。
            顺序由此推出，不再靠人记得把刷新步骤写在断言步骤前面。
        action: 红了之后人**能做什么**（断事类护栏的红项必须可行动）。
    """

    name: str
    category: str
    fn: Callable[[], int]
    repairs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    action: str = ""



def _run(cmd: list[str], label: str) -> int:
    print(f"== [fastcheck] {label} ==")
    r = subprocess.call(cmd, cwd=str(ROOT))
    print(f"== {label}: {'OK' if r == 0 else 'FAIL'} ==")
    return r


def _digest(paths: tuple[str, ...]) -> dict[str, str]:
    """生成物的内容摘要（不存在 → 空串）。用来判定"这一步到底刷新了什么"。"""
    out: dict[str, str] = {}
    for rel in paths:
        p = ROOT / rel
        try:
            out[rel] = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else ""
        except OSError:
            out[rel] = ""
    return out


def order_guards(guards: list[ClosingGuard]) -> list[ClosingGuard]:
    """按声明的关系排序：**修生成物的护栏，排在使用该生成物的护栏之前**。

    这是把"谁必须排在谁前面"从代码顺序搬进接口的那一步：不再靠人记得
    "module-map 刷新要写在 pytest 前面"，而是由 `repairs` / `depends_on` 推出来。

    声明了前提却没有任何护栏提供它 → **直接抛**：前提没人保证的断言是静默失效的
    断言（L58），宁可收尾当场炸，也不要它安静地永远为真。

    无依赖关系的护栏保持声明顺序（稳定）；真有环时保序返回，不让调度器卡死。
    """
    produced = {p: g.name for g in guards for p in g.repairs}
    for g in guards:
        for need in g.depends_on:
            if need not in produced:
                raise ValueError(
                    f"护栏 {g.name!r} 声明依赖生成物 {need!r}，"
                    f"但没有任何护栏声明会产出它——前提没人保证，断言会静默失效"
                )

    ordered: list[ClosingGuard] = []
    remaining = list(guards)
    done: set[str] = set()
    while remaining:
        progressed = False
        for g in list(remaining):
            if all(p in done for p in g.depends_on):
                ordered.append(g)
                remaining.remove(g)
                done.update(g.repairs)
                progressed = True
        if not progressed:
            ordered.extend(remaining)  # 环：保序收尾，不卡死
            break
    return ordered


@dataclass(frozen=True)
class GuardResult:
    """一条护栏跑完的结果。**永远带 category**——红项必须告诉人它属于哪一类。"""

    guard: ClosingGuard
    returncode: int
    refreshed: tuple[str, ...]  # 本次真被重写的生成物

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def status(self) -> str:
        if not self.ok:
            return "FAIL"
        return "刷新" if self.refreshed else "OK"

    def render(self) -> str:
        if self.refreshed:
            return f"  {self.status:<4} {self.guard.name:<12} {self.guard.category}（重写: {', '.join(self.refreshed)}）"
        return f"  {self.status:<4} {self.guard.name:<12} {self.guard.category}"


def run_guards(guards: list[ClosingGuard]) -> list[GuardResult]:
    """按接口跑完所有护栏：生成物类先修再验，断事类只验。

    生成物类护栏**不因"生成物过期"变红**：刷新本身就是它的正常结果（记为「刷新」）。
    它红了只剩一个含义——生成器自己坏了。
    """
    results: list[GuardResult] = []
    for g in guards:
        before = _digest(g.repairs)
        rc = g.fn()
        after = _digest(g.repairs)
        refreshed = tuple(p for p in g.repairs if before.get(p) != after.get(p))
        results.append(GuardResult(guard=g, returncode=rc, refreshed=refreshed))
    return results


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
    # --testmon：只跑受本次 diff 影响的测试（首次建库后秒级）。
    # 第一次跑会全量建 .testmondata，之后增量。全量回归用 --force-rerun。
    pytest_args = [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
                   "--testmon", "--basetemp", str(basetemp)]
    r = subprocess.run(
        pytest_args,
        cwd=str(ROOT), env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
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
    """生成物就地刷新：重跑 `peek.py --index` 重写 docs/module-map.md。

    **为什么是"写"而不是"查"**（2026-09-10 决定）：
    module-map 是 `peek.py --index` 的产物，CLAUDE.md 要求 agent「找代码先看它」。
    此前刷新是**手动**的，于是它腐化成 6/99 条指向几个月前删掉的文件；当时的修法是
    加一条守卫测试（test_reference_integrity.TestGeneratedDocsAreFresh）——
    但那只是**事后检查**：陈旧地图仍然躺在磁盘上被 agent 读到，守卫只在收尾喊一声。

    收口原则：生成物应该在**它该更新的那一刻**更新，而不是等谁事后发现它旧了。
    本步跑在**全量**分支（即 `state.py finish` 必经的收口点），因此跑完 fastcheck 后
    磁盘上的地图必然与代码一致，守卫测试随之恒真——它从"拦截器"退化为"冗余保险"，
    这正是它该有的位置。--quick 不跑本步（不写文件，保持 pre-commit 只读）。
    """
    return _run([sys.executable, str(ROOT / "scripts" / "peek.py"), "--index"], "module-map (生成物刷新)")



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


def _guard_roster(*, quick: bool) -> list[ClosingGuard]:
    """声明护栏名单。**顺序不是真相，关系才是**——真正的执行序由 `order_guards` 推出。

    这里只填六个字段：它检测哪一类东西、会不会重写生成物、判定以什么为前提、
    红了人该做什么。新增一条护栏 = 往这里加一条，不改调度代码。
    """
    guards = [
        ClosingGuard(
            name="compile",
            category="Python 源码可编译",
            fn=_compile,
            action="看 Traceback 指出的语法错误；compileall 只报文件不报行号，直接跑那个文件即可",
        ),
        ClosingGuard(
            name="lint",
            category="ruff 静态风格/错误",
            fn=_lint,
            action="按 ruff 输出的规则号改代码；不要逐条 noqa，先看是否是真问题",
        ),
        ClosingGuard(
            name="typecheck",
            category="pyright 类型正确",
            fn=_typecheck,
            action="按报错点的类型改签名或收窄；不要用 # type: ignore 掩盖",
        ),
        ClosingGuard(
            name="ROOT path",
            category="paths.ROOT 指向真正的项目根",
            fn=_root_check,
            action="检查 src/amta/common/paths.py 的 ROOT 上溯级数",
        ),
        ClosingGuard(
            name="env config",
            category=".env 存在且 API key 可加载",
            fn=_env_check,
            action="补 .env（CHAT_API_KEY），或修 amta.common.config 的加载路径",
        ),
    ]
    if quick:
        return guards

    guards.extend([
        ClosingGuard(
            name="unit tests",
            category="行为回归（pytest 全量）",
            fn=_test,
            # pytest 里那条「地图必须新鲜」的断言是本步的前提；顺序由此推出，
            # 不再靠人记得把 module-map 刷新写在 pytest 前面（2026-10-01 修）。
            depends_on=("docs/module-map.md",),
            action="先按 diagnosing-bugs 定位红项根因；确属既有红项也要先修或明确记账",
        ),
        ClosingGuard(
            name="depguard",
            category="第三方依赖已声明且在用",
            fn=_depguard,
            action="按 depguard 输出补 pyproject 声明，或删掉没用到的 import",
        ),
        ClosingGuard(
            name="memory lint",
            category="记忆机制活性（staleness/幽灵路径/预算）",
            fn=_memory_lint,
            action="按 WARN 条目清账：归档过期的 today-*.md、补 ADR 索引、清死路径",
        ),
        ClosingGuard(
            name="memory gc",
            category="记忆地产 GC 可用（dry-run）",
            fn=_memory_gc,
            action="跑 `scripts/memory.py gc` 看真实报错；dry-run 不该改任何文件",
        ),
        ClosingGuard(
            name="memory inject",
            category="DSH 注入包可生成（CLAUDE.local.md）",
            fn=_memory_inject,
            repairs=("CLAUDE.local.md",),
            action="生成器坏了：跑 `scripts/memory.py inject` 看报错",
        ),
        ClosingGuard(
            name="module-map",
            category="docs/module-map.md 与当前代码一致",
            fn=_module_map,
            repairs=("docs/module-map.md",),
            action="生成器坏了：跑 `scripts/peek.py --index` 看报错",
        ),
    ])
    return guards


def main() -> int:
    ap = argparse.ArgumentParser(description="amta fastcheck 机械质检")
    ap.add_argument("--quick", action="store_true",
                    help="only compile/lint/typecheck (seconds, read-only, used by pre-commit); full 9-step (incl. module-map refresh) is for /finish")
    args = ap.parse_args()

    guards = order_guards(_guard_roster(quick=args.quick))
    print(f"== [fastcheck] 收尾护栏 {len(guards)} 条"
          f"（{'--quick 只读' if args.quick else '全量'}）==")
    for g in guards:
        marks = []
        if g.repairs:
            marks.append(f"修: {', '.join(g.repairs)}")
        if g.depends_on:
            marks.append(f"前提: {', '.join(g.depends_on)}")
        suffix = f"  [{'; '.join(marks)}]" if marks else ""
        print(f"   {g.name:<12} 类别: {g.category}{suffix}")

    results = run_guards(guards)

    print("== 收尾护栏结果 ==")
    for r in results:
        print(r.render())

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"== [fastcheck] FAIL: {', '.join(r.guard.name for r in failed)} ==")
        print("== 红项可行动清单 ==")
        for r in failed:
            print(f"  · {r.guard.name}（{r.guard.category}）：{r.guard.action or '（未声明 action）'}")
        return 1
    print("== [fastcheck] QUICK PASS ==" if args.quick else "== [fastcheck] ALL PASS ==")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
