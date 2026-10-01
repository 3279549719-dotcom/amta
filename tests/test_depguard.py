"""depguard 自身的解析与间接运行时依赖回归。"""
from __future__ import annotations

from scripts import depguard


def test_scan_third_party_accepts_utf8_bom(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "station.py").write_text("import onnxruntime\n", encoding="utf-8-sig")
    monkeypatch.setattr(depguard, "ROOT", tmp_path)
    monkeypatch.setattr(depguard, "SCAN_DIRS", ("src",))

    found = depguard._scan_third_party()

    assert found["src\\station.py"] == {"onnxruntime"}


def test_indirect_runtime_dependencies_are_explicit():
    assert depguard.INDIRECT_RUNTIME_DEPS == {"httpx", "python-multipart"}


def test_installed_import_names_resolves_real_distributions():
    """import 名 → 分布名 必须从已安装元数据解析出来，且非空。

    回归（2026-10-01）：这里原本走 `importlib.metadata.packages_distributions()`，
    它在 `scripts/` 包语境下**静默返回空 dict**（同进程内联调用却返回 80 条），
    于是 `deepseek_harness` 解析不到分布名 `deepseek-harness-sdk`，
    同一条合法依赖被同时误报「未声明」+「未使用」双杀，把全量门禁卡死。
    断言"表非空"就是为了让这种静默失效立刻变红，而不是安静地什么都查不到。
    """
    mapping = depguard._installed_import_names()
    assert mapping, "已安装元数据解析结果为空——依赖检查会静默失效"
    # 本仓 venv 里必然存在的两条：验证连字符/下划线/大小写差异都能对上
    assert mapping.get("PIL") == "pillow"
    assert mapping.get("deepseek_harness") == "deepseek-harness-sdk"


def test_no_dependency_is_reported_both_undeclared_and_unused(monkeypatch):
    """同一条依赖不得被同时判「未声明」和「未使用」。

    这正是 2026-10-01 的故障形状：分布名 `deepseek-harness-sdk` 与 import 名
    `deepseek_harness` 只差一个 `-sdk`，名字映射没解析出来 → 两个罪一起报，
    看起来"两头都错"，其实是一条完全合法的依赖。
    """
    monkeypatch.setattr(depguard, "_scan_third_party",
                        lambda: {"scripts/x.py": {"deepseek_harness"}})
    monkeypatch.setattr(depguard, "_declared_deps",
                        lambda: {"deepseek-harness-sdk"})
    monkeypatch.setattr(depguard, "INDIRECT_RUNTIME_DEPS", set())

    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = depguard.main()
    out = buf.getvalue()

    assert rc == 0, f"一条已声明的依赖被误报：\n{out}"
    assert "未声明" not in out
    assert "未使用" not in out


def test_undeclared_import_still_reported(monkeypatch):
    """反向：真正没声明的 import 必须照报，别把守卫改成永远放行。"""
    monkeypatch.setattr(depguard, "_scan_third_party",
                        lambda: {"scripts/x.py": {"some_random_pkg"}})
    monkeypatch.setattr(depguard, "_declared_deps", lambda: set())
    monkeypatch.setattr(depguard, "INDIRECT_RUNTIME_DEPS", set())

    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = depguard.main()

    assert rc == 1
    assert "未声明" in buf.getvalue()
