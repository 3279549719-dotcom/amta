"""harness 契约（Harness Covenant）—— 标准本身，以及它的自我执行。

## 总纲（一句话）

> **harness 里每一条「某机制已生效」的声明，都必须配一条**
> **只读、秒级、且会在声明为假时真的变红 的探针。**

## 为什么需要它

2026-09-12 体检的结论不是「有 bug」，而是：

    所有漂移探测器都存在、都算得对、然后接不到任何会失败的东西上。

同一天撞到三个独立实例，形状完全一样——**声明与探针脱钩**：

1. **操作文档**失效 33 条指针：README / RUNBOOK 教人跑早已删除的编号脚本，
   没有任何检查盯着"人写的散文文档"（机器生成的 `docs/module-map.md` 反而一条没错）。
2. **`npm run check` 长期没跑过**：`package.json` 里 `check` 与 `precheck` 并存，
   而 `precheck` 是 `check` 的 npm pre-hook —— 跑 `npm run check` 实际跑的是
   koharu 端口检查，不通就中止，`compileall` 一次都没执行。
   而 `cycle-close` 第 29 行、`verify` 第 10 行都写着「`npm run check` = 语法门」。
3. **白名单豁免写错了理由**：`tests/test_encoding.py` 曾豁免
   `("scripts/fastcheck.py", "subprocess.run")`，理由是「输出含中文，但它自己解析
   `N passed`（ASCII 正则）」—— 只考虑了能不能*解析*，没考虑能不能*解码*；
   恰恰因为输出含中文，GBK 解码当场炸掉，表现为"pytest 失败"，其实 515 条全过。

## 本文件不声明新规则

它只做一件事：**把「声明」和「探针」焊在一起，并拒绝接受没有探针的声明。**
条款清单见 `COVENANT`；`TestH5_CovenantIsFullyEnforced` 会拒绝
「写进清单但没人执行」的条款，也拒绝「有测试但没进清单」的孤儿。

## 条款

| ID | 声明 | 探针 |
|---|---|---|
| H1 | 所有 Python 入口走 `uv run python` | 解析 `package.json` 的 scripts |
| H2 | 配置里声明的 hook 必须是当前运行时真会加载的 | 读 `.claude/settings.json` |
| H3 | 排除名单里不得有死路径 | 解析 `scripts/depguard.py` 的 `EXCLUDE_FILES` |
| H4 | git hook 里引用的脚本必须存在 | 扫 `.githooks/*` |
| H5 | 契约自身完整（无孤儿条款 / 无孤儿测试） | 自省本模块 |
| H6 | 改动不得夹带行尾噪声（LF/CRLF 翻转） | 比对工作区与 HEAD blob 的行尾 |

### 与既有守卫的分工（不重复造）

- S1–S5 在 `tests/test_reference_integrity.py`：管**引用完整性**（代码与文档的指针）。
- S5 已在管 npm 脚本名互劫持（`check`/`precheck` 那类），故本条不再重写。
- 本文件管的是**"声明"这一层**：谁说机制生效，谁就得交出探针。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 契约条款登记表。每条的 key 必须与一个 `Test<key>_...` 测试类同名（H5 强制）。
COVENANT: dict[str, str] = {
    "H1": "所有 Python 入口走 `uv run python`，禁止裸 `python`",
    "H2": "配置里声明的 hook 必须是当前运行时真会加载的",
    "H3": "排除名单（depguard EXCLUDE_FILES）不得含不存在的路径",
    "H4": "git hook 里引用的脚本必须存在",
    "H5": "契约自身完整：无孤儿条款，也无孤儿测试",
    "H6": "改动不得夹带行尾噪声：被改文件的行尾风格必须与 HEAD 一致",
    "H7": "收尾规程单一真相源：skill/文档里不得出现第二套可执行收尾步骤",
}


# --------------------------------------------------------------------------- H1


def _bare_python_offenders(scripts: dict[str, str]) -> list[str]:
    """纯函数：找出「调用了裸 python」的 npm 脚本（可被合成样本反向验证）。

    判据：命令分词后出现 token == "python"，且它的前一个 token 不是 "run"。
    覆盖 `&&` / `||` 串联的多段命令。
    """
    bad: list[str] = []
    for name, cmd in scripts.items():
        tokens = re.split(r"[\s&|;]+", cmd)
        for i, tok in enumerate(tokens):
            if tok != "python":
                continue
            prev = tokens[i - 1] if i else ""
            if prev != "run":
                bad.append(f"{name}: {cmd}")
                break
    return bad


class TestH1_PythonEntryIsAlwaysUvRun:
    """H1：所有 Python 入口走 `uv run python`，禁止裸 `python`。

    CLAUDE.md「Python 运行规范（强制）」明写禁止裸 python。2026-09-12 实测：
    `check` / `test` / `lint` / `smoke` / `depcheck` / `fastcheck` / `audit` /
    `bench*` 共 16 条 npm 脚本**全部是裸 python**——规则写在散文里，没人执行。
    更糟的是 `npm run lint` 因此用的是全局 Python 3.13 的 ruff 0.15.22，
    而非 .venv 的 0.16.x，同一份代码两个判定（L26 的老账）。
    """

    def test_no_npm_script_calls_bare_python(self):
        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        bad = _bare_python_offenders(scripts)
        assert not bad, (
            "npm 脚本调用了裸 python（CLAUDE.md 禁止；会拿到全局解释器而非 .venv）：\n  "
            + "\n  ".join(bad)
        )

    def test_h1_probe_can_actually_fail(self):
        """反向验证：喂合成样本，探针必须报出来——否则它是个恒真的空转断言。"""
        sample = {
            "good": "uv run python -m pytest tests",
            "bad": "python -m pytest tests",
            "chained": "npm run check && python -m ruff check",
        }
        offenders = _bare_python_offenders(sample)
        assert any(o.startswith("bad:") for o in offenders), offenders
        assert any(o.startswith("chained:") for o in offenders), offenders
        assert not any(o.startswith("good:") for o in offenders), offenders


# --------------------------------------------------------------------------- H2


class TestH2_DeclaredHooksAreLoadedByTheRuntime:
    """H2：配置里声明的 hook 必须是**当前运行时真会加载**的。

    ## 证据（2026-09-12，文件:行号级）

    `.claude/settings.json` 声明了一个 SessionStart hook
    （`py -3.13 scripts/hook_sessionstart.py`）。而本项目的运行时是 **DSH**：

    - `packages/hooks/hooks-claude-code/src/index.ts:53,73` —— CC 方言 hook 桥**存在**，
      但需要**显式 `configPath`**（`z.string().required()`），**没有默认指向
      `.claude/settings.json`**；
    - `apps/cli/config/agent-presets/*/agent.cordis.yml` 与 `~/.dsh/settings.yaml`
      搜 `hooks` → **0 命中**，该插件未注册；
    - 项目自己的 L11 早已记载 `.claude/settings.json` / `.claude/skills` /
      `.claude/rules` **都不被 DSH 解释**。

    结论：**这个 hook 在 DSH 下从未触发过。** 它是一份"看起来机制已生效"的配置——
    而正是这种配置让 ADR-032 做出了错误的保留决策（见其 2026-09-12 后记）。

    现实承担记忆注入的是 DSH 的 agent-instructions 直接读 `CLAUDE.local.md`，
    **不需要触发点**；状态展示由 `run_pipeline.py` 启动时自动打印（Embedded）。
    """

    SETTINGS = ROOT / ".claude" / "settings.json"

    def test_settings_declares_no_hook_the_runtime_ignores(self):
        if not self.SETTINGS.exists():
            return  # 已删除 —— 契约满足
        data = json.loads(self.SETTINGS.read_text(encoding="utf-8"))
        hooks = data.get("hooks") or {}
        assert not hooks, (
            "`.claude/settings.json` 声明了 hook，但当前运行时（DSH）不读这个文件，"
            "这些 hook 永远不会触发。要么删掉该声明，要么先证明运行时会加载它"
            "（见本类 docstring 里的证据链）。声明的 hook：\n  "
            + json.dumps(hooks, ensure_ascii=False)
        )


# --------------------------------------------------------------------------- H3


def _module_level_literal_set(source: str, varname: str) -> set[str] | None:
    """从源码里取模块级 `varname = {...}` 的字面量集合（AST，安全只读）。"""
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == varname:
                value = ast.literal_eval(node.value)
                return set(value)
    return None


class TestH3_ExclusionListsContainNoDeadPaths:
    """H3：排除名单里的路径必须存在。

    2026-09-12 实测：`scripts/depguard.py` 的 `EXCLUDE_FILES` 有 **8 条**指向
    早已删除的文件（`run_detect_ab.py` / `ctd_detector.py` / `test_detect_ctd.py` …）。

    危害不在报错，在**静默**：死路径只是永远匹配不上，让人以为"这些文件已被豁免"。
    排除名单也是"指针"，同样会腐烂，同样没人盯着——与 README/RUNBOOK 同型。
    """

    DEPGUARD = ROOT / "scripts" / "depguard.py"

    def test_depguard_exclusions_all_exist(self):
        source = self.DEPGUARD.read_text(encoding="utf-8")
        exclude = _module_level_literal_set(source, "EXCLUDE_FILES")
        assert exclude, "解析不到 EXCLUDE_FILES（变量改名了？本断言会静默失效）"
        dead = sorted(p for p in exclude if not (ROOT / p).exists())
        assert not dead, (
            "depguard 的 EXCLUDE_FILES 里有不存在的路径——排除名单会静默失效：\n  "
            + "\n  ".join(dead)
        )

    def test_h3_parser_can_actually_fail(self):
        """反向验证：合成一段含死路径的源码，解析器必须把它们取出来。"""
        sample = 'EXCLUDE_FILES = {\n    "scripts/ghost.py",\n    "scripts/fastcheck.py",\n}\n'
        parsed = _module_level_literal_set(sample, "EXCLUDE_FILES")
        assert parsed == {"scripts/ghost.py", "scripts/fastcheck.py"}, parsed
        assert not (ROOT / "scripts" / "ghost.py").exists(), "样本前提失效"


# --------------------------------------------------------------------------- H4


class TestH4_GitHooksReferenceLiveScripts:
    """H4：`.githooks/*` 里引用的 `scripts/xxx.py` 必须存在。

    与 S4 的分工：S4 管**文档**（人写的散文），本条管**可执行的钩子**。
    钩子比文档更该被盯着——它是文档里说的"唯一真强制层"。

    2026-09-12 的教训来源：`run.ps1` 的 5 个分支指向已删的编号脚本而无人发现；
    git hook 是同一类可执行文件，只是它坏掉时**整个门槛静默消失**。
    """

    HOOKS_DIR = ROOT / ".githooks"
    _SCRIPT_REF = re.compile(r"scripts[/\\]([A-Za-z0-9_]+\.py)")

    def test_every_hook_script_reference_exists(self):
        assert self.HOOKS_DIR.is_dir(), ".githooks/ 不存在——门禁层没了"
        hooks = sorted(p for p in self.HOOKS_DIR.iterdir() if p.is_file())
        assert hooks, ".githooks/ 下没有钩子文件（本断言会静默失效）"

        dead: list[str] = []
        checked = 0
        for hook in hooks:
            for m in self._SCRIPT_REF.finditer(hook.read_text(encoding="utf-8", errors="ignore")):
                checked += 1
                if not (ROOT / "scripts" / m.group(1)).exists():
                    dead.append(f"{hook.name} → scripts/{m.group(1)}（不存在）")

        assert checked > 0, "钩子里一条 scripts/*.py 引用都没扫到——正则或钩子面已失效"
        assert not dead, "git hook 引用了不存在的脚本（门禁会静默失效）：\n  " + "\n  ".join(dead)


# --------------------------------------------------------------------------- H5


class TestH5_CovenantIsFullyEnforced:
    """H5：契约自身完整——**拒绝没有探针的声明**，也**拒绝没有声明的探针**。

    这是本文件存在的理由本身。一个"条款清单"若允许有条目没人执行，
    它就退化成了又一份会腐烂的散文。
    """

    def _carriers(self) -> set[str]:
        import sys

        module = sys.modules[__name__]
        found: set[str] = set()
        for name in dir(module):
            if name.startswith("TestH"):
                found.add(name[4:6])  # "TestH1Foo" -> "H1"
        return found

    def test_every_claim_has_a_test_class(self):
        missing = sorted(k for k in COVENANT if k not in self._carriers())
        assert not missing, (
            "契约里登记了条款但没有对应的测试类——该条款没有探针，等于没写：\n  "
            + "\n  ".join(f"{k}: {COVENANT[k]}" for k in missing)
        )

    def test_no_orphan_test_class_outside_the_covenant(self):
        orphans = sorted(k for k in self._carriers() if k not in COVENANT)
        assert not orphans, (
            "有 TestH* 测试类没登记进 COVENANT——要么补登记，要么它不属于契约：\n  "
            + "\n  ".join(orphans)
        )


# --------------------------------------------------------------------------- H6


def _eol_style(data: bytes) -> str:
    """判定字节流的行尾风格：'crlf' | 'lf' | 'mixed' | 'none'（二进制/无换行）。"""
    if b"\x00" in data:
        return "none"
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    lone_cr = data.count(b"\r") - crlf
    if crlf and (lf or lone_cr):
        return "mixed"
    if crlf:
        return "crlf"
    if lf:
        return "lf"
    return "none"


def _eol_drift(pairs: dict[str, tuple[bytes, bytes]]) -> list[str]:
    """纯函数：比对 {路径: (HEAD 字节, 工作区字节)}，返回行尾被翻转的文件。

    只报「原本单一行尾风格、被翻成另一种」的情况。原本就是 mixed 的文件
    （本仓库确实有）不追究——那不是本次改动引入的噪声，怪不到这一刀头上。
    """
    drifted: list[str] = []
    for path, (old, new) in sorted(pairs.items()):
        before, after = _eol_style(old), _eol_style(new)
        if before in ("lf", "crlf") and after in ("lf", "crlf") and before != after:
            drifted.append(f"{path}: HEAD 是 {before.upper()}，工作区变成了 {after.upper()}")
    return drifted


class TestH6_EditsCarryNoLineEndingNoise:
    """H6：改动不得夹带行尾噪声。

    ## 为什么需要它（2026-09-12，同一个坑踩了第二次）

    本仓库 `.gitattributes` 是 `* -text`，且 `core.autocrlf=true` —— 没有行尾归一化，
    谁的字节写进去就是谁的。而 AI 的 `edit` / `write` 工具在 Windows 上默认写 CRLF。

    实测后果：**改 1 行，diff 显示 22 行**（全部是行尾噪声），
    真实语义改动被淹没在噪声里，评审和 `git blame` 同时失效。
    第一次是 `CLAUDE.md`（6 行改动膨胀成 224 行 diff）。

    这条不写进散文的理由与 H1 相同：**散文拦不住工具**，只有断言能。
    修法：从 HEAD blob 还原该文件行尾（`git show HEAD:<路径>` 覆写后重放改动）。
    """

    #: 只在文本类文件上比对，避免把二进制产物拖进来。
    _TEXT_SUFFIXES = (
        ".py", ".md", ".json", ".ps1", ".yml", ".yaml", ".toml",
        ".cfg", ".txt", ".sh", ".js", ".ts", ".html", ".css",
    )

    def _modified_tracked_text_files(self) -> list[str]:
        import subprocess

        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return []
        out: list[str] = []
        for rel in proc.stdout.splitlines():
            rel = rel.strip()
            if not rel or not rel.endswith(self._TEXT_SUFFIXES):
                continue
            if (ROOT / rel).is_file():
                out.append(rel)
        return out

    def _pairs(self) -> dict[str, tuple[bytes, bytes]]:
        import subprocess

        pairs: dict[str, tuple[bytes, bytes]] = {}
        for rel in self._modified_tracked_text_files():
            head = subprocess.run(
                ["git", "show", f"HEAD:{rel}"],
                cwd=ROOT,
                capture_output=True,
            )
            if head.returncode != 0:
                continue
            pairs[rel] = (head.stdout, (ROOT / rel).read_bytes())
        return pairs

    def test_no_modified_file_flipped_its_line_endings(self):
        pairs = self._pairs()
        if not pairs:
            return  # 工作区干净或无文本改动 —— 无可比对
        drifted = _eol_drift(pairs)
        assert not drifted, (
            "有文件的行尾被整体翻转（diff 里全是噪声，真实改动被淹没）：\n  "
            + "\n  ".join(drifted)
            + "\n修法：git show HEAD:<路径> 还原行尾后重放改动"
        )

    def test_h6_detector_can_actually_fail(self):
        """反向验证：喂合成样本，探测器必须报出来。"""
        sample = {
            "flipped_to_crlf": (b"a\nb\nc\n", b"a\r\nb\r\nc\r\n"),
            "flipped_to_lf": (b"a\r\nb\r\n", b"a\nb\n"),
            "untouched": (b"a\nb\n", b"a\nb\n"),
            "already_mixed": (b"a\r\nb\n", b"a\r\nb\nc\r\n"),
        }
        drifted = _eol_drift(sample)  # type: ignore[arg-type]
        assert any(d.startswith("flipped_to_crlf:") for d in drifted), drifted
        assert any(d.startswith("flipped_to_lf:") for d in drifted), drifted
        assert not any(d.startswith("untouched:") for d in drifted), drifted
        assert not any(d.startswith("already_mixed:") for d in drifted), drifted

    def test_h6_style_detector_agrees_with_reality(self):
        """行尾判定器本身不能是瞎的——拿真实 HEAD blob 校一次。"""
        import subprocess

        blob = subprocess.run(
            ["git", "show", "HEAD:package.json"], cwd=ROOT, capture_output=True
        )
        assert blob.returncode == 0, "取不到 package.json 的 HEAD blob，H6 会静默失效"
        assert _eol_style(blob.stdout) in ("lf", "crlf"), (
            f"判定器对真实文本文件给出了 {_eol_style(blob.stdout)}，判定已失效"
        )

# --------------------------------------------------------------------------- H7


class TestH7_FinishProcedureHasASingleSourceOfTruth:
    """H7：收尾规程只有一个真相源——`state.py finish`。

    ## 为什么需要它（2026-09-12 实测）

    "收尾"这一个动作，仓库里曾同时有三种写法：

    - CLAUDE.md：`state.py finish "summary"`（自动质检 + 自动提交）
    - cycle-close skill：`npm run check` → `npm run test` → `npm run fastcheck`
      → `npm run finish`，然后**手工** `git add` + commit + push
    - verify skill：`npm run check` / `fastcheck` / `smoke` / `koharu:check` 又是一套

    三套互相矛盾，其中 cycle-close 的 Finish Report 模板还写着"本仓无独立 lint / 无类型检查器"
    ——而 `package.json` 里 `lint`=ruff、`typecheck`=pyright 一直在跑。**假事实 + 多真相源**
    合起来的效果是：每次收尾都得现场仲裁该信哪一份，而仲裁者没有判断依据。

    ## 判据

    可执行动作只能挂在**唯一命令**上；skill/文档里允许写「为什么」，不允许写第二套步骤。
    实现在 `_second_procedure_offenders`：扫规程面（CLAUDE.md + .dsh/skills），
    出现 `git add` / `git commit` / 已删除的 npm 别名（test/lint/fastcheck/audit/typecheck/depcheck）
    即算违规——它们在 2026-09-12 的收敛里已全部删除，再出现就是旧文案回流。

    H5 同时保证本条款有探针、探针有条款。
    """

    #: 规程面：会被 AI 当作"照着做"的说明来读的文件。
    _PROCEDURE_GLOBS = ("CLAUDE.md", ".dsh/skills/*/SKILL.md")

    #: 第二套步骤的特征串。命中即违规（行内含删除/废弃标记的行豁免——那是在陈述历史）。
    _FORBIDDEN = (
        "git add ",
        "git commit ",
        "npm run test",
        "npm run lint",
        "npm run typecheck",
        "npm run depcheck",
        "npm run fastcheck",
        "npm run audit",
    )

    def _procedure_files(self) -> list[Path]:
        out: list[Path] = []
        for pat in self._PROCEDURE_GLOBS:
            out.extend(sorted(ROOT.glob(pat)))
        return out

    def _second_procedure_offenders(self, files: list[Path]) -> list[str]:
        """纯函数式：对给定文件列表扫第二套步骤，返回违规描述（供合成样本反向验证）。"""
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "src"))

        from amta.memory.lint import is_historical_note

        bad: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if is_historical_note(line):
                    continue
                if "state.py finish" in line:  # 唯一合法入口所在行，豁免
                    continue
                for token in self._FORBIDDEN:
                    if token in line:
                        try:
                            where = path.relative_to(ROOT)
                        except ValueError:
                            where = path  # 仓库外合成样本(反向验证用),直接展示绝对路径
                        bad.append(f"{where}:{i} 出现第二套收尾步骤 {token!r}")
                        break
        return bad

    def test_only_one_finish_procedure_exists(self):
        files = self._procedure_files()
        assert len(files) >= 3, f"规程面只扫到 {len(files)} 个文件，执法面可能已失效"
        offenders = self._second_procedure_offenders(files)
        assert not offenders, (
            "收尾规程出现了第二套可执行步骤（规程必须只有一个真相源：state.py finish）：\n  "
            + "\n  ".join(offenders)
        )

    def test_h7_scanner_can_actually_fail(self, tmp_path):
        """反向验证：喂一份含第二套步骤的合成规程，扫描器必须报出来。"""
        fake = tmp_path / "SKILL.md"
        fake.write_text(
            "# 收尾\n\n### Step 8\n- git add <文件> → git commit -m \"x\"\n- npm run fastcheck\n",
            encoding="utf-8",
        )
        offenders = self._second_procedure_offenders([fake])
        assert any("git add" in o for o in offenders), offenders
        assert any("npm run fastcheck" in o for o in offenders), offenders
