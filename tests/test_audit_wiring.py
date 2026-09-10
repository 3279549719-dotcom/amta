"""test_audit_wiring — 漂移探测器必须接线，否则等于没有。

2026-09-10 体检发现的最关键病理：**所有漂移探测器都存在、都算得对，
然后接不到任何会失败的东西上**。

`scripts/audit.py` 是最典型的例子：它做 Harness 熵审计（workspace 空壳、
重复文件、顶层散落、gitignore 泄漏…），**exit code 永远 0，且不在 fastcheck 里**。
CLAUDE.md 自己写着「test/lint/hook 是唯一真强制层」——一个没人调、调了也不失败的
探测器，恰恰违背那条原则。

本文件把「接线」这件事变成机械可查的断言：
- audit 必须是 fastcheck 的一步（否则它永远不会失败，也就永远不会被看见）
- audit 的作用域必须指向**仓库根**，不是它的父目录
- audit 的白名单不能残留已删除的旧布局名（"amta"）

对应手术清单第 ① 项。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FASTCHECK = ROOT / "scripts" / "fastcheck.py"
AUDIT = ROOT / "scripts" / "audit.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestAuditIsWiredIntoFastcheck:
    """fastcheck 必须真的调用 audit。"""

    def test_fastcheck_references_audit(self):
        assert "audit.py" in _read(FASTCHECK), (
            "fastcheck 没有调用 audit.py —— 那么 audit 的结论永远不会影响任何人"
        )

    def test_fastcheck_has_an_audit_step_function(self):
        assert "def _audit(" in _read(FASTCHECK), "fastcheck 缺少 _audit() 步骤函数"

    def test_audit_runs_in_full_mode_not_quick(self):
        """audit 是秒级以下的重活（要遍历目录），放全量模式，不拖慢 pre-commit。"""
        body = _read(FASTCHECK)
        assert '("audit"' in body, "audit 没有出现在 checks 列表里"
        # quick 分支应跳过它
        quick_idx = body.find("if not args.quick:")
        assert quick_idx != -1
        assert body.find('("audit"') > quick_idx, "audit 应属于全量分支（if not args.quick 之后）"


class TestAuditScopesAreCorrect:
    """audit 的扫描范围必须指向仓库根。"""

    def test_top_level_clutter_scans_repo_root_not_parent(self):
        body = _read(AUDIT)
        assert "check_top_level_clutter(ROOT.parent)" not in body, (
            "顶层散落检查扫的是 ROOT.parent —— 应该扫仓库根 ROOT"
        )
        assert "check_top_level_clutter(ROOT)" in body

    def test_allowlist_has_no_deleted_layout_name(self):
        """平铺后 amta/ 子目录已不存在，白名单里的 'amta' 是死名字。

        只看**代码**（AST 里的字符串常量），不看注释与 docstring——否则解释
        「为什么删掉 amta」的那句注释会被误判成违规（本测试第一版就是这么假红的，
        正好是它要防的那类错误：守卫必须盯着行为，不是盯着文本里出现过什么词）。

        白名单 2026-09-10 从「函数默认参数」提升为模块级 `ROOT_ALLOWED`，
        所以这里同时接受两种形态。
        """
        import ast

        tree = ast.parse(_read(AUDIT))
        values: list[str] = []

        # 形态一：模块级 ROOT_ALLOWED = (...)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "ROOT_ALLOWED" for t in node.targets
            ) and isinstance(node.value, ast.Tuple):
                values += [
                    e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]

        # 形态二：函数默认参数
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "check_top_level_clutter":
                for default in node.args.defaults:
                    if isinstance(default, ast.Tuple):
                        values += [
                            e.value for e in default.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        ]

        assert values, "没有找到顶层白名单（ROOT_ALLOWED 或函数默认值）"
        assert "amta" not in values, (
            f"白名单仍含已删除的旧布局名 'amta'（平铺后仓库根就是项目根）：{values}"
        )


class TestAuditCanActuallyFail:
    """audit 必须能给出非零退出码——否则它在 fastcheck 里永远 PASS。"""

    def test_audit_supports_strict_mode(self):
        body = _read(AUDIT)
        assert "--strict" in body, "audit 没有 --strict；无法作为门禁步骤使用"

    def test_audit_strict_exits_nonzero_when_findings_exist(self, tmp_path):
        """构造一个必然有发现的场景：顶层放一个散落文件。"""
        import shutil
        sandbox = tmp_path / "repo"
        shutil.copytree(ROOT / "scripts", sandbox / "scripts")
        (sandbox / "docs" / "decisions").mkdir(parents=True)
        (sandbox / "docs" / "lessons.md").write_text("# Lessons\n", encoding="utf-8")
        (sandbox / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
        (sandbox / "workspace").mkdir()
        (sandbox / "stray_file_that_should_not_be_here.txt").write_text("x", encoding="utf-8")

        r = subprocess.run(
            [sys.executable, str(sandbox / "scripts" / "audit.py"), "--strict"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(sandbox), timeout=120,
        )
        assert r.returncode != 0, f"有发现却返回 0（exit 0 = 永远不拦截）\n{r.stdout[-800:]}"

    def test_audit_default_mode_still_exits_zero(self):
        """默认是咨询模式（exit 0），只有 --strict 才当门禁——保持兼容。"""
        r = subprocess.run(
            [sys.executable, str(AUDIT)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=300,
        )
        assert r.returncode == 0, f"默认模式不该失败\n{r.stdout[-800:]}"
