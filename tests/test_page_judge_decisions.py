"""apply_decisions：judge 决策 → repair/tickets 语义唯一归属（修 F6）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.page_judge import apply_decisions


JUDGE = {"decisions": [
    {"tool": "repair_region", "args": {"region_id": "page_0_u00"}},
    {"tool": "repair_region", "args": {"region_id": "page_0_u99"}},   # semantic 未标 fail
    {"tool": "open_ticket", "args": {"region_id": "page_0_u02", "reason": "看不清", "kind": "hard_case"}},
    {"tool": "open_ticket", "args": {}},  # 无 region_id，忽略
]}
SEM = {"failed": [{"region_id": "page_0_u00"}]}


def test_apply_decisions_repairable_and_tickets():
    out = apply_decisions(JUDGE, SEM)
    assert out["repair"] == ["page_0_u00"]  # 只修 semantic 已标 fail 的
    kinds = {(t["region_id"], t["kind"]) for t in out["tickets"]}
    assert ("page_0_u02", "hard_case") in kinds
    assert ("page_0_u99", "hard_case") in kinds  # unrepairable → 工单
    assert all(t["region_id"] for t in out["tickets"])  # 空 region_id 决策被滤


def test_apply_decisions_empty():
    out = apply_decisions({}, {"failed": []})
    assert out == {"repair": [], "tickets": []}
