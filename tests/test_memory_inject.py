"""memory_inject 的确定性测试：DSH 本地 overlay 记忆包生成（写 CLAUDE.local.md / stdout）。

新语义（DSH 原生注入）：不再读 CC SessionStart stdin，而是把记忆包写进
CLAUDE.local.md（agent-instructions 自动加载）。只用 estate fixture 的临时根
构建包并验证文件写入/编码，不触碰真实 amta 地产。
"""
from amta.memory.inject import build_local_md, main


def test_build_local_md_has_header_and_pack_marker(estate):
    text = build_local_md(estate, "startup", 4096)
    assert text.startswith("# 本地记忆注入包")
    assert "自动生成" in text
    assert "AMTA 记忆包" in text
    assert "memory.py inject" in text  # 说明头带刷新命令


def test_build_local_md_has_dictionary_rule_not_session_summaries(estate):
    # 内容契约（ADR-027）：只装字典规则，不带会话摘要/lessons 采样
    text = build_local_md(estate, "startup", 4096)
    assert "知识字典" in text
    assert "memory_search" in text
    assert "## 最近摘要" not in text
    assert "2026-08-30" not in text


def test_build_local_md_includes_loop_state_summary(estate):
    # loop_state.json 存在时，注入包带接续状态摘要
    estate.joinpath("loop_state.json").write_text(
        '{"mission": "检测调优", "next_action": "调 conf", "updated_at": "2026-09-01T22:00"}',
        encoding="utf-8",
    )
    text = build_local_md(estate, "startup", 4096)
    assert "## 接续状态" in text
    assert "检测调优" in text


def test_main_writes_utf8_local_file(estate, tmp_path):
    target = tmp_path / "CLAUDE.local.md"
    rc = main(["--target", str(target), "--budget", "4096"])
    assert rc == 0
    assert target.exists()
    content = target.read_text(encoding="utf-8")  # UTF-8 无 BOM 可读
    assert "AMTA 记忆包" in content


def test_stdout_mode_returns_zero_and_prints(estate, capsys):
    rc = main(["--stdout", "--budget", "1024"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AMTA 记忆包" in out


def test_tiny_budget_drops_content_not_header(estate):
    # 极小预算：now/recent 整块丢弃，但头与包标记仍在（防膨胀静默吞信息）
    text = build_local_md(estate, "startup", 64)
    assert "AMTA 记忆包" in text
