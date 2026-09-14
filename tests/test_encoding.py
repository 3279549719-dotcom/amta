"""test_encoding — Windows 编码收口的回归测试（2026-09-10 事故驱动）。

两个真实事故：
1. `import amta` 后 CLI 的 stdout 仍是宿主 locale（cp936/gbk），而 DSH/管道按 UTF-8 读
   → 所有中文输出到达 agent 侧变成 `�ؼ���` 乱码 → agent 放弃深接口改用 read/grep。
2. `subprocess.run(..., text=True)` 不解码失败会**静默返回 stdout=None**（不抛异常），
   且默认用 locale 解码 → 中文 commit message 直接炸掉 `state.py bootstrap`。

本文件锁定这两条不变量：
- 包导入即归一化 stdio 为 UTF-8（收口点在 `amta/__init__.py`，新脚本自动继承）
- 跨进程文本一律走 `run_text` / `run_text_or`，不再依赖宿主 locale，也永不返回 None
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from amta.common.encoding import run_text, run_text_or

REPO_ROOT = Path(__file__).resolve().parent.parent


def _child_env() -> dict[str, str]:
    """子进程环境：强制回到 locale 模式，模拟真实 `uv run python scripts/x.py` 现场。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = ""
    return env


class TestStdioChokePoint:
    """包导入即生效的 stdio 归一化。"""

    def test_import_amta_makes_stdout_utf8(self):
        """import amta 之后，中文必须以 UTF-8 字节穿出管道（而不是 locale 编码）。"""
        code = "import amta, sys; sys.stdout.write('中文测试')"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, env=_child_env(), check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.decode("utf-8") == "中文测试"

    def test_without_import_amta_stdout_is_locale(self):
        """反证：不加 import，宿主 locale 会把中文写成非 UTF-8 字节。

        这条是上面那条的对照——如果哪天宿主默认变成 UTF-8，本测试会失败，
        提醒我们"收口点已无意义"，而不是让它假装还在保护什么。
        """
        code = "import sys; sys.stdout.write('中文测试')"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, env=_child_env(), check=False,
        )
        assert proc.returncode == 0, proc.stderr
        if sys.platform == "win32" and (proc.stdout.decode("utf-8", errors="replace") == "中文测试"):
            pytest.skip("宿主已是 UTF-8 默认，对照条件不成立")


class TestRunText:
    """run_text：跨进程文本读取的唯一入口。"""

    def test_decodes_utf8_child_output(self):
        """子进程输出 UTF-8 时原样读回。"""
        code = "import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.stdout.write('中文 OK')"
        result = run_text([sys.executable, "-c", code])
        assert result.returncode == 0
        assert result.stdout == "中文 OK"

    def test_undecodable_bytes_do_not_crash_or_return_none(self):
        """无法解码的字节必须降级为替换字符，绝不崩、绝不返回 None。"""
        code = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe bad')"
        result = run_text([sys.executable, "-c", code])
        assert result.returncode == 0
        assert result.stdout is not None
        assert "bad" in result.stdout

    def test_never_returns_none_stdout(self):
        """stdout 为 None 的历史事故（AttributeError: 'NoneType'）不再可能。"""
        result = run_text([sys.executable, "-c", "pass"])
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)

    def test_check_raises_called_process_error(self):
        """check=True 保持 subprocess 语义。"""
        with pytest.raises(subprocess.CalledProcessError):
            run_text([sys.executable, "-c", "import sys; sys.exit(3)"], check=True)


class TestRunTextOr:
    """run_text_or：失败即降级为默认值，调用方不再写 try/except 样板。"""

    def test_returns_stdout_on_success(self):
        assert run_text_or([sys.executable, "-c", "print('hi')"]).strip() == "hi"

    def test_returns_default_on_nonzero_exit(self):
        assert run_text_or([sys.executable, "-c", "import sys; sys.exit(1)"], default="") == ""

    def test_returns_default_when_command_missing(self):
        assert run_text_or(["definitely-not-a-real-binary-xyz"], default="unknown") == "unknown"

    def test_returns_default_on_timeout(self):
        code = "import time; time.sleep(5)"
        assert run_text_or([sys.executable, "-c", code], timeout=0.2, default="timeout") == "timeout"


# ------------------------------------------------- 系统守卫：不许再长出裸 text=True
#
# 为什么加这条（2026-09-11 实测）：
# 同一个坑在这一天**第三次复发**——新写的 `tests/test_artifact_cli.py` 里
# `subprocess.run(..., text=True)` 读中文 stderr，解码在线程里炸掉、stderr 静默变
# None，断言 `result.stderr.lower()` 抛 AttributeError，全量门 501 passed → 1 failed。
#
# 前两次（state.py bootstrap、run_text 收口）都是**逐点修复**，所以坑又长回来了。
# 这条守卫把「逐点修」升级为「系统性拦截」：直接扫源码，发现裸 text=True 就红。

# 允许保留的白名单：这些调用**只读 ASCII**（git config 值、本机路径），
# 不接触中文，改造它们的收益为负（引入 amta 依赖反而扩大耦合面）。
_ALLOWED_BARE_TEXT_TRUE = {
    # 只读 git config（ASCII 路径/布尔值）
    ("tests/test_lessons_guard.py", "subprocess.run"),
    ("tests/test_state_manager.py", "subprocess.run"),
    # 以下两条白名单条目已删除（2026-09-12，随整个「CC 方言 hook 层」一起）：
    #     ("scripts/hook_pretooluse.py", "subprocess.run")
    #     ("scripts/hook_sessionstart.py", "subprocess.run")
    # 理由：`.claude/settings.json` 声明的 hook 在 DSH 下**从未触发过**（证据见
    # tests/test_harness_covenant.py 的 H2），两个脚本因此没有任何触发点；其职责分别由
    # `state.py bootstrap`（状态展示）与 fastcheck 的 memory inject（注入刷新）
    # + DSH agent-instructions 直接读 CLAUDE.local.md 承担。
    # 留着这两条就是又一批"指向不存在文件的指针"。
    # 2026-09-12 实测：这里原本还有一条
    #     ("scripts/fastcheck.py", "subprocess.run")
    # 理由写的是「输出含中文，但它自己解析 "N passed"（ASCII 正则）」。
    # **这条豁免本身是错的**：它只考虑了「能不能*解析*」，没考虑「能不能*解码*」。
    # 恰恰因为它输出含中文，GBK 解码在线程里当场炸掉：
    #     UnicodeDecodeError: 'gbk' codec can't decode byte 0xab in position 890
    # → reader 线程死掉 → stdout/stderr 静默变 None → 报「pytest 无通过汇总（exit 1）」，
    #   而**所有测试其实全过**。护栏白名单把唯一必炸的位置豁免了，
    #   于是它红了十几天没人当回事（大家只看到 "1 failed"）。
    # 已改为 encoding="utf-8", errors="replace"，本条目就此删除。
    # 教训：白名单的理由必须写清「为什么安全」，而「只读 ASCII」才是安全的理由。
}

_BARE_TEXT_TRUE_OWNERS = {"subprocess.run", "subprocess.Popen", "_sp.run", "sp.run"}


def _bare_text_true_calls(path: Path) -> list[tuple[int, str]]:
    """AST 找出「有 text=True 但没有 encoding=」的 subprocess 调用。

    用 AST 而不是正则：正则会被 docstring 里描述这个坑的**说明文字**误伤
    （本仓库已经因为"把提及当成引用"假红过两次，见 test_reference_integrity）。
    """
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # 归一化被调用者名字：subprocess.run / _sp.run / sp.run
        if isinstance(fn, ast.Attribute):
            name = fn.attr
            owner = getattr(fn.value, "id", "") or getattr(fn.value, "attr", "")
            dotted = f"{owner}.{name}" if owner else name
        elif isinstance(fn, ast.Name):
            dotted = fn.id
        else:
            continue
        if dotted not in _BARE_TEXT_TRUE_OWNERS:
            continue
        kwargs = {k.arg for k in node.keywords if k.arg}
        if "text" not in kwargs and "universal_newlines" not in kwargs:
            continue
        if "encoding" in kwargs:
            continue
        found.append((node.lineno, dotted))
    return found


class TestNoBareTextTrueInLiveCode:
    """活代码里不许出现「text=True 但没有 encoding=」——那是 Windows 上的静默炸弹。"""

    def _scan(self) -> list[str]:
        offenders: list[str] = []
        for base in ("src", "scripts", "tests"):
            for path in (REPO_ROOT / base).rglob("*.py"):
                if "__pycache__" in path.parts or ".venv" in path.parts:
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                for lineno, dotted in _bare_text_true_calls(path):
                    if (rel, dotted) in _ALLOWED_BARE_TEXT_TRUE:
                        continue
                    offenders.append(f"{rel}:{lineno} → {dotted}(text=True) 缺 encoding=")
        return offenders

    def test_no_bare_text_true(self):
        offenders = self._scan()
        assert not offenders, (
            "发现裸 `text=True`（缺 encoding=）：Windows 上按 cp936 解码中文会在线程内\n"
            "抛 UnicodeDecodeError 并被吞掉，导致 stdout/stderr **静默变成 None**，\n"
            "下游 `.lower()` / `.strip()` 抛 AttributeError（2026-09-11 实测复发）。\n"
            "修法：改用 `amta.common.encoding.run_text` / `run_text_or`，\n"
            "或就地加 `encoding=\"utf-8\", errors=\"replace\"`。\n  " + "\n  ".join(offenders)
        )

    def test_scanner_actually_detects_violations(self, tmp_path):
        """守卫必须真的能红——用一个人造违规文件证明扫描器不是空转。"""
        bad = tmp_path / "bad_module.py"
        bad.write_text(
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git', 'log'], capture_output=True, text=True)\n",
            encoding="utf-8",
        )
        assert _bare_text_true_calls(bad), "扫描器没能识别人造违规——守卫是空转的"

    def test_scanner_accepts_compliant_call(self, tmp_path):
        """对照组：带 encoding= 的调用不该被报。"""
        good = tmp_path / "good_module.py"
        good.write_text(
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git', 'log'], capture_output=True,\n"
            "                          text=True, encoding='utf-8', errors='replace')\n",
            encoding="utf-8",
        )
        assert not _bare_text_true_calls(good), "带 encoding= 的合规调用被误报"


# ------------------------------------------- 系统守卫：中文输出的脚本必须到达收口点
#
# 为什么加这条（2026-09-11 实测）：
# `amta/__init__.py` 末尾的 `force_utf8_stdio()` 是**包级**收口点——但它是
# **Chained（链式）契约**：只有 `import amta` 的脚本才继承它。
# 实测 `scripts/share_file.py --help` 输出中文全是 `һ���ϴ��ļ�` 乱码，
# 因为它不 import amta。全仓扫出 **13 个脚本** 绕过了收口点。
#
# CLAUDE.md 的原则是「指针必须指向活着的东西」+「test/lint/hook 是唯一真强制层」：
# 一条"新脚本记得 import amta"的口头约定不是强制层，这条守卫才是。


def _cjk_in_string_node(node: ast.AST, cjk: re.Pattern[str]) -> bool:
    """节点里是否含中文字面量 —— 字符串常量**和 f-string** 都算。

    2026-09-12 补：第一版只认 `ast.Constant`，于是 f-string 全部漏掉
    （f-string 是 `ast.JoinedStr`，不是 Constant）。实测漏网者
    `scripts/probes/eol_restore.py`：它的每一句中文输出都写在 f-string 里，
    守卫判它"不输出中文"，而它在 Windows 上**确实**吐乱码。
    盲点方向与 L26 同型：**"我没看见"被当成了"它没问题"。**
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(cjk.search(node.value))
    if isinstance(node, ast.JoinedStr):
        return any(_cjk_in_string_node(v, cjk) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _cjk_in_string_node(node.value, cjk)
    return False


def _emits_chinese(path: Path) -> bool:
    """脚本是否会向用户输出中文（docstring 不算——那是给读代码的人看的）。

    判定：`print` / `sys.stdout.write` / `sys.stderr.write` / argparse 的
    `help=` / `description=` 里出现中日韩字符（字符串常量与 f-string 都算）。
    """
    CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False

    for node in ast.walk(tree):
        # print("中文") / print(f"{x} 中文") / sys.stdout.write(...)
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in {"print", "write", "error", "exit"}:
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    if _cjk_in_string_node(arg, CJK):
                        return True
            # argparse: help="中文" / description="中文"
            for k in node.keywords:
                if k.arg in {"help", "description"} and _cjk_in_string_node(k.value, CJK):
                    return True
    return False


def _reaches_choke_point(path: Path) -> bool:
    """脚本是否触发 `amta/__init__.py` 的 force_utf8_stdio()。

    三种合法途径——用 **AST** 判定，不用字符串搜索：
    ① `import amta` / `import amta.xxx`
    ② `from amta... import ...`（**同样会执行包 __init__**，这是最容易漏判的一种）
    ③ 显式调用 `force_utf8_stdio()`

    第一版用 `"import amta" in body` 做子串匹配，把 21 个**已经合规**的脚本
    （`from amta.common.paths import ROOT` 这种）全部误报成违规——
    正是本仓库反复踩的「把提及/子串当成事实」那类假红。用 AST 看真实导入语句。
    """
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False

    for node in ast.walk(tree):
        # import amta / import amta.xxx
        if isinstance(node, ast.Import):
            if any(a.name == "amta" or a.name.startswith("amta.") for a in node.names):
                return True
        # from amta... import ...
        elif isinstance(node, ast.ImportFrom):
            if node.module == "amta" or (node.module or "").startswith("amta."):
                return True
        # 显式调用 force_utf8_stdio()
        elif isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name == "force_utf8_stdio":
                return True
    return False


class TestChineseScriptsReachTheChokePoint:
    """输出中文的 scripts/ 必须到达 UTF-8 收口点，否则 agent 侧读到的就是乱码。"""

    def _offenders(self) -> list[str]:
        bad: list[str] = []
        for path in sorted((REPO_ROOT / "scripts").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if _emits_chinese(path) and not _reaches_choke_point(path):
                bad.append(path.relative_to(REPO_ROOT).as_posix())
        return bad

    def test_chinese_scripts_reach_choke_point(self):
        offenders = self._offenders()
        assert not offenders, (
            "以下脚本会输出中文，但**没有**到达 UTF-8 收口点（`import amta` 或显式\n"
            "`force_utf8_stdio()`）。Windows 上 stdout 按 cp936 编码，DSH/管道按 UTF-8 读，\n"
            "agent 侧收到的就是 `һ���ϴ��ļ�` 这类乱码，于是弃用深接口退回 read/grep。\n"
            "修法二选一：\n"
            "  a) `import amta`（顺便获得全部深接口）\n"
            "  b) `from amta.common.encoding import force_utf8_stdio; force_utf8_stdio()`\n"
            "     （需先 `sys.path.insert(0, .../src)`）\n  " + "\n  ".join(offenders)
        )

    def test_detector_recognizes_chinese_output(self, tmp_path):
        """守卫不能空转：人造一个输出中文的脚本必须被识别。"""
        f = tmp_path / "cn.py"
        f.write_text('print("中文输出")\n', encoding="utf-8")
        assert _emits_chinese(f), "扫描器识别不出中文输出——守卫是空转的"

    def test_detector_ignores_docstring_only_chinese(self, tmp_path):
        """对照组：只有 docstring 是中文的脚本不算「输出中文」。"""
        f = tmp_path / "doc.py"
        f.write_text('"""这是一个中文模块说明，但不输出任何中文。"""\nprint("ok")\n', encoding="utf-8")
        assert not _emits_chinese(f), "只有 docstring 中文被误判为输出中文"

    def test_detector_recognizes_fstring_chinese_output(self, tmp_path):
        """反向验证：中文只写在 f-string 里，也必须被识别。

        2026-09-12 补：第一版只认 `ast.Constant`，把 f-string（`ast.JoinedStr`）
        整类漏掉。实测漏网者 `scripts/probes/eol_restore.py`——它的中文全在
        f-string 里，于是"输出中文却没到收口点"，也就是**真会乱码**，守卫却说它没事。
        没有这条，同一个盲点会再被踩回来。
        """
        f = tmp_path / "fstr.py"
        f.write_text('x = 1\nprint(f"{x}: 中文输出")\n', encoding="utf-8")
        assert _emits_chinese(f), "f-string 里的中文输出没被识别——盲点又回来了"

    def test_detector_accepts_choke_point_import(self, tmp_path):
        """对照组：import amta 的脚本应被判为已到达收口点。"""
        f = tmp_path / "good.py"
        f.write_text("import amta\nprint('中文')\n", encoding="utf-8")
        assert _reaches_choke_point(f)
