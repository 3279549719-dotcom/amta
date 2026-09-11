"""test_reference_integrity — 引用完整性守卫：不许指向不存在的东西。

## 为什么需要这条守卫（2026-09-10 体检结论）

这次体检最关键的病理不是「有 bug」，而是：

> **所有漂移探测器都存在、都算得对、然后接不到任何会失败的东西上。**

实证：
- 删掉 00~05 六个编号脚本后，**12 条测试**永久变红、无人察觉约两天；
- lessons 45→27 清理后，**27 个已删除的编号**仍被 19 个活文件引用（含 `src/` 生产文件）；
- `docs/module-map.md` 被 CLAUDE.md 要求「agent 必读」，其中 **6 条指向几个月前删掉的文件**。

三次清理、三次同一种错。说明流程里**根本没有「检查引用者」这一步**。
本守卫就是那一步——它把「删除必须同步引用」从人的记性变成机械断言。

## 扫描范围（关键决定）

**只扫活文件**。`docs/archive/`、`docs/superpowers/`、`research/`、`docs/progress.md`
是历史记录：里面的旧编号是**当时的事实**，不要求符合今天的状态。
对它们报错等于伪造历史，而且会让守卫永久变红 → 被人关掉 → 白做。

## 三条接缝

- **S1 lesson 引用**：代码里写的 `L<n>` 必须存在于 `docs/lessons.md`
- **S2 脚本路径引用**：测试里写的 `scripts/xxx.py` 必须真实存在
- **S3 文档链接**：活文档里的相对 md 链接必须指向存在的文件
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "docs" / "lessons.md"

# 活文件所在目录（守卫只在这里执法）
LIVE_DIRS = ("src", "scripts", "tests")

# 活文档（会被人/agent 当作当前事实来读的）
LIVE_DOCS = (
    "CLAUDE.md",
    "AGENTS.md",
    "RUNBOOK.md",
    "README.md",
    "docs/lessons.md",
    "docs/decisions",
    "docs/module-map.md",
    "docs/README.md",
)

# 明确豁免：这些是历史记录或生成物，不适用「今天必须成立」
EXEMPT_PARTS = (
    "archive",
    ".worktrees",
    ".venv",
    "node_modules",
    "__pycache__",
    "output",
    "workspace",
    "superpowers",   # 历史实施计划（sdd ledger）
    "progress.md",   # append-only 日志
)

_LESSON_REF = re.compile(r"\bL(\d{1,3})\b")
_SCRIPT_REF = re.compile(r"scripts[/\\]([A-Za-z0-9_]+\.py)")

# 「引用」与「提到」的区别（守卫第一版在这里假红过）：
#   - 引用：真的去读/执行/断言这个文件存在（read_text / spec_from_file_location / exists）
#   - 提到：docstring、墓碑测试里的名单、示例路径
# 只有前者才该被要求「文件必须存在」。墓碑测试**故意**点名已删脚本
# （test_final_integration.py 的 test_file_removed 断言它们不得复活），
# 报它就是让守卫自相矛盾——守卫必须盯着行为，不是盯着文本里出现过什么词。
_REFERENCE_MARKERS = (
    "spec_from_file_location",
    "read_text",
    "subprocess",
    "run_text",
    "sys.executable",
    "CLI =",
    "cli =",
    ".exists()",
    "Path(",
)

# 墓碑名单：这些脚本**已被删除**，而测试故意点名它们以断言「不得复活」。
# 报它们等于让守卫反对自己的目的。
_TOMBSTONE_ALLOWED = {
    "00_run_all.py", "01_detect.py", "02_ocr.py", "03_translate.py",
    "04_inpaint.py", "05_typeset.py",
    "ctd_detector.py", "ocr_detect.py", "translate_semantic_check.py",
    "x.py",  # 测试里的占位示例
}


def _exempt(path: Path) -> bool:
    return any(part in path.parts or part == path.name for part in EXEMPT_PARTS)


def _live_code_files() -> list[Path]:
    out: list[Path] = []
    for d in LIVE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if not _exempt(p):
                out.append(p)
    return out


def _live_doc_files() -> list[Path]:
    out: list[Path] = []
    for rel in LIVE_DOCS:
        p = ROOT / rel
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [q for q in p.rglob("*.md") if not _exempt(q)]
    return out


def _existing_lesson_ids() -> set[str]:
    body = LESSONS.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^##\s+(L\d+)\b", body, re.MULTILINE)}


def _builds_fake_estate(body: str) -> bool:
    """该文件是否自造 estate 夹具（tmp_path 里写假的 lessons.md）。

    判据用**结构性标记**，不用「猜字符串」（第一版猜标记，结果 `conftest.py`
    没被识别出来，守卫红在自己的夹具上——守卫必须盯着行为，不是盯着措辞）：
    - 出现 `estate` fixture 名（conftest 定义、其他测试以参数接收）
    - 出现往临时目录写 lessons.md 的动作
    - 出现 handle_call / do_read / do_grep 这类**地产 API 调用**
      （测试它们时用的 ID 天然是夹具 ID，如 L1/L2）
    """
    markers = (
        "estate(tmp_path",          # conftest fixture 定义
        "estate: Path",             # 以参数接收该 fixture
        "estate,", "estate)",       # 传给 do_* 的夹具
        "handle_call(",             # mcp_memory 的调用入口
        "do_read(", "do_grep(", "do_recent(", "do_index(",
        "parse_lessons(", "parse_adrs(",
        '"## L1', "'## L1",
        'lessons.md"', "lessons.md')",
    )
    return any(m in body for m in markers)


# --------------------------------------------------------------------------- S1


class TestLessonReferencesResolve:
    """S1：代码里引用的 lesson 编号必须存在。"""

    def test_lessons_file_exists(self):
        assert LESSONS.is_file(), "docs/lessons.md 不存在——守卫的前提没了"

    def test_no_ghost_lesson_ids_in_live_code(self):
        """活代码引用 lesson 编号时，该编号必须存在。

        两类**不算引用**的，必须排除，否则守卫会红在对的地方、错的事上：
        - 测试夹具：`conftest.py` 在 tmp_path 里造假的 lessons.md（L1/L2），
          那些编号属于**临时仓库**，与真 docs/lessons.md 无关；
        - 同一测试文件里的断言：跟着夹具走，同上。
        判据：只要该文件自己造了 estate（出现 "## L" 写入或 estate fixture），
        它引用的编号就是夹具编号。
        """
        existing = _existing_lesson_ids()
        assert existing, "没有解析到任何 lesson 编号，解析器可能坏了"

        ghosts: list[str] = []
        for path in _live_code_files():
            body = path.read_text(encoding="utf-8", errors="ignore")
            if _builds_fake_estate(body):
                continue
            for m in _LESSON_REF.finditer(body):
                lid = f"L{m.group(1)}"
                # 只认「像 lesson 引用」的：编号需在现存编号的量级内（<=60），
                # 否则会把 L129/L234 这类行号误判成 lesson 引用
                if int(m.group(1)) > 60:
                    continue
                if lid not in existing:
                    line_no = body[: m.start()].count("\n") + 1
                    ghosts.append(f"{path.relative_to(ROOT)}:{line_no} 引用 {lid}（不存在）")

        assert not ghosts, (
            "活代码引用了不存在的 lesson 编号——删 lesson 时必须同步清理引用：\n  "
            + "\n  ".join(ghosts)
        )


# --------------------------------------------------------------------------- S2


class TestScriptReferencesResolve:
    """S2：引用 scripts/xxx.py 的地方，那个文件必须存在。"""

    def test_no_ghost_script_paths_in_tests(self):
        """只报「真的去用它」的地方，不报「提到它」的地方。

        判据：该行（或紧邻上下文）必须带引用标记（read_text / subprocess / CLI= …）。
        墓碑测试写 `assert not (ROOT / "scripts/01_detect.py").exists()` 属于
        **引用**（它真的去查了），但那个文件"不存在"正是它要断言的——
        所以墓碑名单单独豁免（见 `_TOMBSTONE_ALLOWED`）。
        """
        ghosts: list[str] = []
        for path in (ROOT / "tests").rglob("*.py"):
            if _exempt(path):
                continue
            if path.name == "test_reference_integrity.py":
                continue  # 守卫自己会写示例路径
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for i, line in enumerate(lines):
                for m in _SCRIPT_REF.finditer(line):
                    name = m.group(1)
                    if name in _TOMBSTONE_ALLOWED:
                        continue
                    if (ROOT / "scripts" / name).exists():
                        continue
                    context = "\n".join(lines[max(0, i - 3): i + 2])
                    if not any(marker in context for marker in _REFERENCE_MARKERS):
                        continue
                    ghosts.append(f"{path.relative_to(ROOT)}:{i + 1} 引用 scripts/{name}（不存在）")
        assert not ghosts, (
            "测试引用了不存在的脚本——删脚本时必须同步清理引用（这正是 12 条红测试的成因）：\n  "
            + "\n  ".join(ghosts)
        )


# --------------------------------------------------------------------------- S3


class TestDocLinksResolve:
    """S3：活文档里的相对链接必须指向存在的文件。"""

    def test_no_broken_relative_links_in_live_docs(self):
        broken: list[str] = []
        for path in _live_doc_files():
            body = path.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"\]\(([^)\s#]+)\)", body):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                if not target.endswith((".md", ".py", ".json", ".html", ".yaml", ".yml", ".png", ".sh", ".ps1")):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    broken.append(f"{path.relative_to(ROOT)} → {target}")
        assert not broken, (
            "活文档里有断链（CLAUDE.md 要求 agent 信任这些文档，它们却在指向不存在的东西）：\n  "
            + "\n  ".join(broken)
        )


class TestGeneratedDocsAreFresh:
    """生成物守卫：`docs/module-map.md` 是 `find_code.py --index` 的产物。

    CLAUDE.md 明确要求 agent「找代码先看 module-map」。但它是**生成物**：
    代码一删，地图就开始撒谎（体检实测：6/99 条指向几个月前删掉的文件），
    而再生成是**手动**的 —— 手动步骤 = 迟早不跑。

    ## 本守卫的定位已于 2026-09-10 改变：从「拦截器」降级为「冗余保险」

    当时加的修法是**事后检查**：陈旧地图仍然躺在磁盘上被 agent 读到，守卫只在
    收尾喊一声。真正的修法是让生成物在**它该更新的那一刻**更新——现已接进
    `fastcheck.py` 全量分支的 `module-map` 步（即 `state.py finish` 必经的收口点），
    跑完 fastcheck 磁盘地图必然新鲜。

    因此本类的断言现在**恒真**（除非有人绕过 fastcheck 直接提交）。保留它是因为：
    ① 它是幂等性的独立证明，不依赖 fastcheck 的调用顺序；② 若有人把 module-map
    步骤从 fastcheck 里摘掉，这里会立刻变红——它是那条接线的守卫。
    **不要因为「它现在总是绿的」就删掉它**：它守的是接线，不是地图。
    """

    MODULE_MAP = ROOT / "docs" / "module-map.md"

    def test_module_map_exists(self):
        assert self.MODULE_MAP.is_file(), "docs/module-map.md 不存在（CLAUDE.md 要求 agent 读它）"

    def test_module_map_lists_only_existing_modules(self):
        """地图里点名的每个 .py 都必须在 src/amta/ 或 scripts/ 里真实存在。"""
        import re

        body = self.MODULE_MAP.read_text(encoding="utf-8")
        listed = set(re.findall(r"\*\*`([A-Za-z0-9_]+\.py)`\*\*", body))
        assert listed, "解析不到任何模块条目——地图格式变了，守卫会静默失效"

        real = {f.name for f in (ROOT / "src").rglob("*.py")}
        real |= {f.name for f in (ROOT / "scripts").glob("*.py")}
        missing = sorted(m for m in listed if m not in real)

        assert not missing, (
            "module-map.md 指向不存在的模块（生成物已腐坏，需重新生成："
            "`uv run python scripts/find_code.py --index`）：\n  " + "\n  ".join(missing)
        )

    def test_module_map_is_regenerable_and_current(self):
        """重新生成一次，内容必须与磁盘上的一致 —— 否则地图是旧的。"""
        import subprocess
        import sys

        before = self.MODULE_MAP.read_text(encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "find_code.py"), "--index"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=120,
        )
        assert r.returncode == 0, f"重新生成 module-map 失败：{r.stderr[-500:]}"
        after = self.MODULE_MAP.read_text(encoding="utf-8")

        assert before == after, (
            "module-map.md 已过期（重新生成后内容不同）。\n"
            "它不是手写文档，是生成物——代码改动后必须重跑：\n"
            "  uv run python scripts/find_code.py --index"
        )


# ------------------------------------------------------- 守卫自身的有效性检查


class TestGuardIsNotVacuous:
    """守卫必须真的能红——否则它就是又一个「接不到失败」的探测器。"""

    @pytest.mark.parametrize(
        ("name", "files"),
        [("活代码扫描", None), ("活文档扫描", None)],
    )
    def test_scanner_finds_files(self, name: str, files):
        """扫描面不能是空的（空集合会让断言恒真）。"""
        if name == "活代码扫描":
            assert len(_live_code_files()) > 50, "活代码文件数异常少，扫描面可能失效"
        else:
            assert len(_live_doc_files()) > 5, "活文档数异常少，扫描面可能失效"

    def test_lesson_parser_extracts_ids(self):
        ids = _existing_lesson_ids()
        assert "L11" in ids, "解析器读不到已知存在的 L11，S1 会静默失效"
        assert len(ids) > 20
