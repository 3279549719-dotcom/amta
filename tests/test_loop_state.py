"""loop_state 模块测试：读（含损坏降级）/ 写（原子合并）/ 摘要一行 / plan 拆解（schema v2）。"""
from pathlib import Path

from amta.memory.loop_state import (
    load,
    path,
    plan_add,
    plan_done,
    plan_list,
    plan_reset,
    summarize,
    update,
)


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


# --- schema v2：plan 拆解 / 推进 ---

def test_plan_add_appends_chunk_not_done(tmp_path: Path):
    plan_add(tmp_path, "C1", "删除 v0 检索轨道", "fastcheck ALL PASS + grep 无引用")
    plan_add(tmp_path, "C2", "prompt read 指 estate", "read L19 命中")
    plan = plan_list(load(tmp_path))
    assert [c["chunk_id"] for c in plan] == ["C1", "C2"]
    assert all(c["done"] is False for c in plan)
    assert plan[0]["acceptance"].startswith("fastcheck")


def test_plan_add_duplicate_is_idempotent(tmp_path: Path):
    plan_add(tmp_path, "C1", "a")
    plan_add(tmp_path, "C1", "a-again")
    assert len(plan_list(load(tmp_path))) == 1


def test_plan_done_marks_single_chunk(tmp_path: Path):
    plan_add(tmp_path, "C1", "a")
    plan_add(tmp_path, "C2", "b")
    plan_done(tmp_path, "C1")
    plan = plan_list(load(tmp_path))
    assert plan[0]["done"] is True
    assert plan[1]["done"] is False


def test_plan_done_unknown_chunk_noop(tmp_path: Path):
    plan_add(tmp_path, "C1", "a")
    plan_done(tmp_path, "C9")
    assert plan_list(load(tmp_path))[0]["done"] is False


def test_plan_reset_clears_all(tmp_path: Path):
    plan_add(tmp_path, "C1", "a")
    plan_add(tmp_path, "C2", "b")
    plan_reset(tmp_path)
    assert load(tmp_path)["plan"] == []


def test_summarize_includes_plan_progress_single_line(tmp_path: Path):
    plan_add(tmp_path, "C1", "a")
    plan_add(tmp_path, "C2", "b")
    update(tmp_path, mission="退役 v0 轨道")
    plan_done(tmp_path, "C1")
    line = summarize(load(tmp_path))
    assert "任务：退役 v0 轨道" in line
    assert "计划 1/2" in line
    assert "\n" not in line


def test_summarize_ignores_malformed_plan(tmp_path: Path):
    st = update(tmp_path, mission="m")
    st["plan"] = "not-a-list"
    assert summarize(st) == "任务：m | 更新 " + st["updated_at"]


def test_v0_state_without_plan_still_summarizes(tmp_path: Path):
    # 向后兼容：无 plan 字段的旧状态照常
    st = update(tmp_path, mission="m", next_action="n")
    assert "计划" not in summarize(st)
