"""loop_state 模块测试：读（含损坏降级）/ 写（原子合并）/ 摘要一行。"""
from pathlib import Path

from amta.memory.loop_state import load, path, summarize, update


def test_path_is_repo_root_json(tmp_path: Path):
    assert path(tmp_path) == tmp_path / "loop_state.json"


def test_load_missing_returns_empty(tmp_path: Path):
    assert load(tmp_path) == {}


def test_load_corrupt_returns_empty(tmp_path: Path):
    (tmp_path / "loop_state.json").write_text("{not json", encoding="utf-8")
    assert load(tmp_path) == {}


def test_load_non_dict_returns_empty(tmp_path: Path):
    (tmp_path / "loop_state.json").write_text("[1, 2]", encoding="utf-8")
    assert load(tmp_path) == {}


def test_update_merges_fields_and_sets_updated_at(tmp_path: Path):
    st = update(tmp_path, mission="检测调优", current_step="对比 V2")
    assert st["mission"] == "检测调优"
    assert st["current_step"] == "对比 V2"
    assert "updated_at" in st
    # 第二次更新保留旧字段
    st2 = update(tmp_path, next_action="调 conf")
    assert st2["current_step"] == "对比 V2"
    assert st2["next_action"] == "调 conf"
    assert load(tmp_path)["mission"] == "检测调优"


def test_update_ignores_none_fields(tmp_path: Path):
    st = update(tmp_path, mission="m", current_step=None)
    assert st["mission"] == "m"
    assert "current_step" not in st


def test_summarize_is_one_line_and_covers_fields(tmp_path: Path):
    st = update(tmp_path, mission="m", next_action="n", last_verified="0 漏洞")
    line = summarize(st)
    assert "任务：m" in line
    assert "下一步：n" in line
    assert "验证：0 漏洞" in line
    assert "\n" not in line


def test_summarize_empty():
    assert summarize({}) == "（无状态）"
