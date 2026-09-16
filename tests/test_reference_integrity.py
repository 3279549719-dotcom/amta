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

**只扫活文件**。`research/`
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

# 「陈述历史 vs 发指令」的标记词——**单一事实源在 src/amta/memory/lint.py**。
# 那里管 CLAUDE.md 的 ghost_path，这里管 tests/（S2）与操作文档（S4）；
# 同一套判断，不各写一份，否则又多一处要同步的漂移。
from amta.memory.lint import DELETION_MARKERS as _DELETION_MARKERS

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

# 守卫**自身**的文件：它们会故意写**合成样本**路径（用来反向验证"这条断言真会红"），
# 那些路径从来不是引用。第一版只豁免了 test_reference_integrity.py 一个名字，
# 2026-09-12 加了 test_harness_covenant.py 之后立刻被自己的样本误伤
# （S2 把 `scripts/ghost.py` 当成真引用报了出来）。
# 教训与 _REFERENCE_MARKERS 同源：**守卫必须盯着行为，不是盯着文本里出现过什么词。**
_GUARD_SELF_FILES = {
    "test_reference_integrity.py",
    "test_harness_covenant.py",
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
            if path.name in _GUARD_SELF_FILES:
                continue  # 守卫自己会写合成样本路径（见 _GUARD_SELF_FILES 的说明）
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
                    # 与 S4 同法：上下文带删除/替代标记 = 在陈述历史，不是在引用。
                    # （2026-09-12 补：删掉 CC hook 层后，解释性注释被这条守卫误报。）
                    if any(mark in context for mark in _DELETION_MARKERS):
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
    """生成物守卫：`docs/module-map.md` 是 `peek.py --index` 的产物。

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
            "`uv run python scripts/peek.py --index`）：\n  " + "\n  ".join(missing)
        )

    def test_module_map_is_regenerable_and_current(self):
        """重新生成一次，内容必须与磁盘上的一致 —— 否则地图是旧的。"""
        import subprocess
        import sys

        before = self.MODULE_MAP.read_text(encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "peek.py"), "--index"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=120,
        )
        assert r.returncode == 0, f"重新生成 module-map 失败：{r.stderr[-500:]}"
        after = self.MODULE_MAP.read_text(encoding="utf-8")

        assert before == after, (
            "module-map.md 已过期（重新生成后内容不同）。\n"
            "它不是手写文档，是生成物——代码改动后必须重跑：\n"
            "  uv run python scripts/peek.py --index"
        )


# --------------------------------------------------------------------------- S4

# S4 的执法面：**当前时态的操作文档**（会被人/agent 当作「照着做」的说明来读的那些）。
#
# ## 为什么必须补这条（2026-09-12 实测）
#
# S1/S2/S3 扫的都是**代码**。而 167 条文档指针逐条探活后，**60 条是死的（36%）**，
# 且全部集中在人写的散文文档里：
#
#   README.md 22 死 | RUNBOOK.md 11 死 | docs/lessons.md 8 死
#   .dsh/skills 6 死 | CLAUDE.md 4 死
#   docs/module-map.md 0 死 | package.json 0 死   ← 唯一零死亡的两份都是机器生成的
#
# 最有力的证据：module-map（生成物）第 136 行写着「run_pipeline.py 替代 00_run_all.py」——
# **机器早就知道编号脚本被替代了，而 README/RUNBOOK 到今天还在教人跑它们。**
#
# 结论（本接缝存在的全部理由）：**手写的路径清单必然腐烂，只有机械断言能挡住它。**
#
# ## 已知盲点（不要把 S4 信过头）
#
# 本接缝只认**带 `scripts/` 或 `src/` 前缀**的路径字面量。两类东西它扫不到：
#
#   1. **缩进树里的裸文件名**——旧 README 的目录树写成 `│   ├── koharu_client.py`，
#      整棵树里没有一处出现 `src/amta/` 前缀，于是 17 条死路径全部漏网。
#      反向验证方法：拿 `git show HEAD:README.md` 的旧版跑本扫描，ghost 数 = 0。
#   2. **CLI 子命令名**——`artifact.py {list|status}` 这类「子命令不存在」的错误
#      是实参层面的，不是路径层面的（那次是靠人肉实跑 `--help` 才发现的）。
#
# 因此：**S4 变绿 ≠ 文档干净**，它只是把"路径字面量腐烂"这一类钉死了。
# 治本的做法是**不写会腐烂的东西**——README 的目录树已被删除、改为指向生成物
# `docs/module-map.md`（`peek.py --index` 的产物，永远新鲜）。
# 这比"修好那 17 条路径"正确：修好了它还会再烂一次。
#
# ## 为什么 lessons/decisions **不在**执法面内
#
# 它们是**历史记录**：lesson 写「scripts/02_ocr.py 用 edit 改不动」时，那个文件确实存在。
# 要求历史条目符合今天的状态 = 伪造历史 = 守卫永远红 = 被人关掉 = 白做。
# 这与 S1 docstring 里对 `research/` 的豁免是同一条理由。
_OPERATIONAL_DOCS = (
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "RUNBOOK.md",
)

# 行内豁免：该行明确在说「这个已经没了 / 被谁替代了」。
# 例：module-map 的「替代 00_run_all.py 的统一入口」是**正确**表述，不该报。
# 行内豁免标记见文件头的 import：`_DELETION_MARKERS` 来自 src/amta/memory/lint.py。
# 例：module-map 的「替代 00_run_all.py 的统一入口」是**正确**表述，不该报。
# 2026-09-12 补「移除 / 删掉 / 废弃」三个词：删掉 CC hook 层后，
# CLAUDE.md 那句「已整体移除（scripts/hook_pretooluse.py …）」被三个守卫同时误报——
# 那次暴露的真正问题是**同一套规则被复制成了三份**，现已收敛到单一事实源。

_SRC_REF = re.compile(r"(src[/\\](?:[A-Za-z0-9_]+[/\\])*[A-Za-z0-9_]+\.py)")

# 树状代码块里的裸文件名（无 scripts//src/ 前缀）——S4 的第二道网。
# 为什么必须补：旧 README 的目录树写成 `│   ├── koharu_client.py`，整棵树里
# 没有一处出现 `src/amta/` 前缀，于是 17 条死路径**全部从第一道网漏掉**。
# 这不是推测——用 git HEAD 版的旧 README 反向跑过，ghost 数 = 0。
_FENCE_RE = re.compile(r"^\s*```")
_BARE_PY_RE = re.compile(r"\b([A-Za-z0-9_]+\.py)\b")


def _repo_py_basenames() -> set[str]:
    """全仓 .py 文件名集合（src/scripts/tests）。裸名只要求"存在同名文件"，
    不要求它在某个特定目录——因为文档里的 `backends/koharu_client.py` 这种
    相对写法无法可靠地还原成绝对路径，但"这个文件还在不在"是能判定的。"""
    names: set[str] = set()
    for base in ("src", "scripts", "tests"):
        for p in (ROOT / base).rglob("*.py"):
            if "__pycache__" not in p.parts:
                names.add(p.name)
    return names


def _fenced_bare_py_ghosts(doc_label: str, text: str, known: set[str]) -> list[str]:
    """在**围栏代码块内**找裸 `xxx.py` 名字，返回全仓找不到的那些。

    纯函数、不读磁盘，为的是能用一段**已知腐烂的样本**反向验证它真的会红
    （见 TestDocPathReferencesResolve.test_bare_name_scanner_is_not_vacuous）。
    """
    ghosts: list[str] = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if any(mark in line for mark in _DELETION_MARKERS):
            continue
        for m in _BARE_PY_RE.finditer(line):
            name = m.group(1)
            if name not in known:
                ghosts.append(f"{doc_label}:{i} 代码块里点名 {name}（全仓无此文件）")
    return ghosts


def _operational_doc_files() -> list[Path]:
    return [ROOT / rel for rel in _OPERATIONAL_DOCS if (ROOT / rel).is_file()]


def _scan_operational_docs() -> list[tuple[str, str]]:
    """扫操作文档里的 scripts/ 与 src/ 路径引用，返回 (类别, 失效描述) 列表。

    判定按**行**：该行带删除/替代标记即豁免（它在陈述历史，不是在发指令）。

    类别必须显式携带、不能靠拼好的字符串去反推：`_SCRIPT_REF` 捕获的是**文件名**
    （`00_run_all.py`，不含 `scripts/` 前缀），第一版用 `"scripts/" in msg` 分类，
    于是墓碑脚本的命中被静默漏掉——守卫差点又变成「接不到失败」的那种。
    """
    ghosts: list[tuple[str, str]] = []
    for path in _operational_doc_files():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if any(mark in line for mark in _DELETION_MARKERS):
                continue
            found: list[tuple[str, str]] = []
            found += [("scripts", f"scripts/{m.group(1)}") for m in _SCRIPT_REF.finditer(line)]
            found += [("src", m.group(1).replace("\\", "/")) for m in _SRC_REF.finditer(line)]
            for kind, ref in found:
                if (ROOT / ref).exists():
                    continue
                ghosts.append((kind, f"{path.relative_to(ROOT)}:{i + 1} 引用 {ref}（不存在）"))
    return ghosts


class TestDocPathReferencesResolve:
    """S4：操作文档里点名的脚本/源文件路径必须真实存在。

    这是把「指针必须指向活着的东西」（CLAUDE.md 原话）从散文变成机械断言的那一步。
    在此之前，那条规则只写在散文里，没有任何东西阻止文档腐烂——实测已烂掉 60 条。
    """

    def test_no_ghost_script_refs_in_operational_docs(self):
        ghosts = [msg for kind, msg in _scan_operational_docs() if kind == "scripts"]
        assert not ghosts, (
            "操作文档引用了不存在的脚本——删脚本/改结构时必须同步清理文档引用。\n"
            "（这正是 README/RUNBOOK 烂掉 33 条的成因：删了 00~05 编号脚本，文档没人跟）\n  "
            + "\n  ".join(ghosts)
        )

    def test_no_ghost_src_refs_in_operational_docs(self):
        ghosts = [msg for kind, msg in _scan_operational_docs() if kind == "src"]
        assert not ghosts, (
            "操作文档引用了不存在的源文件路径——包结构重构后旧路径必须同步更新。\n"
            "（实测：RUNBOOK 第 4 行写「以 src/amta/paths.py 为准」，而那个文件本身不存在）\n  "
            + "\n  ".join(ghosts)
        )

    def test_no_ghost_bare_py_names_in_doc_code_blocks(self):
        """第二道网：树状/示例代码块里的**裸** `xxx.py` 也必须真实存在。

        补它的理由（2026-09-12）：第一道网（`scripts/`+`src/` 前缀）对旧 README
        的目录树完全盲——那棵树里 17 条 `src/amta/*.py` 全部写成了裸文件名，
        ghost 数 = 0。若只有第一道网，本文档集的"绿"不能推出"干净"。
        """
        known = _repo_py_basenames()
        ghosts: list[str] = []
        for path in _operational_doc_files():
            ghosts += _fenced_bare_py_ghosts(
                path.relative_to(ROOT).as_posix(),
                path.read_text(encoding="utf-8", errors="ignore"),
                known,
            )
        assert not ghosts, (
            "操作文档的代码块里点名了全仓不存在的 .py 文件：\n  " + "\n  ".join(ghosts)
        )

    def test_s4_scanner_is_not_vacuous(self):
        """S4 的扫描面不能是空的——否则断言恒真，又是一个「接不到失败」的探测器。"""
        docs = _operational_doc_files()
        assert len(docs) >= 3, f"S4 只扫到 {len(docs)} 份操作文档，执法面可能失效"
        # 至少要能扫出**一些**引用，否则正则坏了、守卫静默变绿
        total = 0
        for path in docs:
            body = path.read_text(encoding="utf-8", errors="ignore")
            total += len(_SCRIPT_REF.findall(body)) + len(_SRC_REF.findall(body))
        assert total > 0, "S4 一条路径引用都没扫到——正则或执法面已失效"

    def test_bare_name_scanner_is_not_vacuous(self):
        """反向验证：拿一段**已知腐烂**的样本喂进扫描器，它必须能红。

        样本取自旧 README 的真实形态（缩进树 + 裸文件名）。没有这条，
        上面那条断言可能因为正则/围栏解析写错而恒真——那又是一台
        「存在、算得对、然后接不到任何会失败的东西上」的探测器。
        """
        sample = """```
amta/
├── src/amta/
│   ├── gt_alignment.py     # GT→detector 框对齐（仓库里已无此文件）
│   ├── koharu_client.py    # 真实存在于 backends/ 下
```"""
        known = _repo_py_basenames()
        assert "koharu_client.py" in known, "样本前提失效：koharu_client.py 应当存在"

        ghosts = _fenced_bare_py_ghosts("SAMPLE.md", sample, known)
        assert any("gt_alignment.py" in g for g in ghosts), (
            "扫描器对树状代码块里的裸文件名是盲的（这正是旧 README 17 条死路径漏网的原因）：\n"
            + repr(ghosts)
        )


# --------------------------------------------------------------------------- S5


class TestNpmScriptsAreNotShadowedByPreHooks:
    """S5：npm 脚本名不得互相构成 pre/post 生命周期 hook。

    ## 为什么需要这条（2026-09-12 实测：一个静默失效的护栏）

    package.json 里曾同时存在 `check` 与 `precheck`。npm 的约定是：跑 `npm run check`
    会**先**跑 `precheck`。于是实测结果是——

        $ npm run check
        > amta@0.1.0 precheck                    ← 实际跑的是 koharu 端口检查
        [precheck] FAIL: koharu not reachable on port 4000
        [exit code] 1                            ← npm 中止，compileall 一次都没跑

    而 `cycle-close`（第 29 行）与 `verify`（第 10 行）两个技能都写着
    「`npm run check` = 语法门」。也就是说：**语法门长期没有真正跑过，而它自己不会报错**——
    与 L45 的 hook 假死同型：护栏坏得没有声音。

    这类 bug 只有机械断言挡得住，所以名字冲突必须被断言拦下，而不是写进文档提醒。
    现已把 `precheck` 改名为 `koharu:check`（带冒号的脚本名不参与 hook 解析）。
    """

    def test_no_script_name_is_a_lifecycle_hook_of_another(self):
        import json

        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        names = set(scripts)
        shadowed: list[str] = []
        for name in sorted(names):
            for prefix in ("pre", "post"):
                if not name.startswith(prefix) or len(name) == len(prefix):
                    continue
                target = name[len(prefix):]
                if target in names:
                    shadowed.append(
                        f"`{name}` 是 `{target}` 的 npm {prefix}-hook："
                        f"跑 `npm run {target}` 会先跑它，它一失败就静默中止 `{target}`"
                    )
        assert not shadowed, (
            "npm 脚本名互相构成生命周期 hook——被劫持的那个会静默不跑（护栏假死）：\n  "
            + "\n  ".join(shadowed)
            + "\n修法：给 hook 侧改名（加冒号，如 koharu:check），冒号名不参与 hook 解析。"
        )


# --------------------------------------------------------------------------- S6

# 一方目录 = 仓库"自己的"代码与文档。刻意排除：
#   reference/  第三方 vendored 源码（koharu 快照）
#   output/     产物与 pytest 日志（里面有测试夹具伪造的整个 mini 仓库）
#   .git/
# 不排除的话，`settings.json` 会因为 reference/repos/koharu/.vscode/settings.json
# 而被判成"还活着"，S6 第一天就误报。
_FIRST_PARTY_DIRS = ("src", "scripts", "tests", "docs", ".dsh")

# 反引号里**带目录分隔符**的路径 token —— 它在声称"某文件位于某处"。
_PATH_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.(?:py|ps1|json|md|yml|yaml|toml|sh))`"
)


def _first_party_basenames() -> set[str]:
    names: set[str] = set()
    for base in _FIRST_PARTY_DIRS:
        d = ROOT / base
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    names.add(p.name)
    return names


def _half_path_references(doc_label: str, text: str, known: set[str]) -> list[str]:
    """纯函数：找出「半截路径」——路径写错，可它想指的文件其实还活着。

    判据：反引号里带目录分隔符的路径 token **不存在**，但它的**文件名**在一方目录里活着。
    这说明写的不是"某个已删除的东西"，而是**一个活文件的错误路径**。

    为什么这条规则不豁免带删除标记的行（2026-09-12）：豁免的本意是「这句话在陈述
    某物已被删除」，可一句话完全可以**前半段说"某某已删"、后半段顺手把活文件写错路径**，
    整行因为含 legacy/已删 而获得豁免，于是错路径全线放行。实测原例：

        AGENTS.md:5  仅存 legacy 客户端（`backends/koharu_client.py`、`start_koharu.ps1`）

    `backends/` 在仓库根下**根本不存在**，真实路径是 `src/amta/backends/koharu_client.py`。
    S4 的两道网都看不见它：第一道要 `src/`/`scripts/` 前缀，第二道只在围栏代码块内扫描。

    放宽到「所有行」前实测过误报面：拦到 0 条（唯一命中就是上面那条真错），
    故不再对标记行做特例——特例就是藏身处。
    """
    out: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in _PATH_TOKEN_RE.finditer(line):
            tok = m.group(1)
            if (ROOT / tok).exists():
                continue  # 路径有效
            base = tok.rsplit("/", 1)[-1]
            if base in known:
                out.append(
                    f"{doc_label}:{i} 写成 `{tok}`（此路径不存在）——但 `{base}` 在一方目录里活着；"
                    f"这是半截/写错的路径"
                )
    return out


class TestNoHalfPathsShadowingLiveFiles:
    """S6：不得留下「半截路径」——写了个不存在的相对路径，而它想指的文件还活着。

    这是 S4 的补丁缝，规则与实测理由见 `_half_path_references` docstring。一句话：
    **一个还在的文件，不许被写成一条不存在的路径。**
    """

    def test_no_half_path_shadows_a_live_file(self):
        known = _first_party_basenames()
        ghosts: list[str] = []
        for path in _operational_doc_files():
            ghosts += _half_path_references(
                path.relative_to(ROOT).as_posix(),
                path.read_text(encoding="utf-8", errors="ignore"),
                known,
            )
        assert not ghosts, (
            "操作文档里的路径写错了——它想指的文件其实活着：\n  "
            + "\n  ".join(ghosts)
            + "\n修法：写全路径（如 src/amta/backends/koharu_client.py），别写半截相对路径。"
        )

    def test_s6_surface_is_not_empty(self):
        """S6 的扫描面不能是空的，否则断言恒真。"""
        known = _first_party_basenames()
        assert len(known) > 100, f"一方目录只扫到 {len(known)} 个文件名，执法面可能失效"
        assert "koharu_client.py" in known, "样本前提失效：koharu_client.py 应当在一方目录里"

    def test_s6_scanner_is_not_vacuous(self):
        """反向验证：拿一段**已知错误**的样本喂进去，扫描器必须能红。

        样本模拟 AGENTS.md 的真实形态：墓碑与"写错的活文件路径"挤在同一行，
        整行因为含 legacy 曾获得豁免。没有这条，上面的断言可能因为正则写错而恒真。
        """
        sample = (
            "koharu v0.59.1 已退出主链路，仅存 legacy 客户端"
            "（`backends/koharu_client.py`、`scripts/start_koharu.ps1`），不要依赖它；"
            "旧的 `scripts/hook_sessionstart.py` 已删除。\n"
        )
        known = _first_party_basenames()
        ghosts = _half_path_references("SAMPLE.md", sample, known)

        assert any("backends/koharu_client.py" in g for g in ghosts), (
            "扫描器对错误路径是盲的（这正是 AGENTS.md 半截路径漏网的原因）：\n" + repr(ghosts)
        )
        assert not any("hook_sessionstart.py" in g for g in ghosts), (
            "扫描器把真墓碑也误报了——真墓碑（全仓无同名活文件）不该报：\n" + repr(ghosts)
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
