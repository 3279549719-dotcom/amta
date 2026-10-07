"""书内翻译记忆：跨页检索、证据留痕、幂等、修订不丢证据。

这些测试在实现前必须全部失败（AttributeError / ImportError）。

隔离方式说明（踩过坑，别再改回去）：
不用 `monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)` + `init_workspace`。实测在
本仓的 `--basetemp=.pytest_tmp`（`pyproject.toml:81`）下，工作区状态会**跨测试串味**，
而 `init_workspace` 又按设计幂等（"文件已存在则不覆盖"，
`src/amta/common/workstate.py:113`），于是别的测试写下的 decisions 会变成这里的
"既有记忆"，断言随机变红。改成显式 `isolated_workspace()` 上下文管理器：每个测试一个
唯一目录、`finally` 还原模块级 `WORKSPACE`，不依赖任何 pytest 夹具的临时目录行为。
"""
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.common import workstate
from amta.common.metrics import norm

_TMP_ROOT = Path(__file__).resolve().parents[1] / "output" / "logs" / "pytest-ws"


@contextmanager
def isolated_workspace(*work_ids: str):
    """把 workstate.WORKSPACE 指向一个独占目录，并写入给定 work_id 的空 state。

    退出时无论正常结束还是断言失败都还原原来的 WORKSPACE。
    """
    prev = workstate.WORKSPACE
    root = _TMP_ROOT / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    workstate.WORKSPACE = root
    try:
        for wid in work_ids:
            workstate.ensure_workspace(wid)
            workstate.save_state(wid, dict(workstate.TEMPLATE_WORK_STATE, work_id=wid))
        yield root
    finally:
        workstate.WORKSPACE = prev


def test_record_creates_tentative_decision_with_evidence():
    with isolated_workspace("w1"):
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
             "page": 2, "region_id": "r05", "match": "exact"},
        ])
        d = workstate.load_decisions("w1")
        # decision 字典以 norm(surface) 为权威键——片假名归一后键为 やみつき茸
        assert norm("ヤミツキ茸") in d
        e = d[norm("ヤミツキ茸")]
        assert e["translation"] == "成瘾菇"
        assert e["status"] == "tentative"
        assert e["source"] == "translate"
        assert e["evidence"] == [
            {"page": 2, "region_id": "r05", "surface_seen": "ヤミツキ茸", "match": "exact"}
        ]


def test_retrieval_ignores_page_distance():
    """第 3 页记的决定，第 8 页出现时必须命中——页距不存在。"""
    with isolated_workspace("w1"):
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
             "page": 2, "region_id": "r05", "match": "exact"},
        ])
        page8 = ["そろそろ消費者も現状のヤミツキ茸の合有量に物足りなさがくる頃だろう?"]
        hits = workstate.relevant_decisions("w1", page8)
        assert "ヤミツキ茸" in hits
        assert hits["ヤミツキ茸"]["translation"] == "成瘾菇"


def test_evidence_append_is_idempotent():
    """同一 (surface, page, region_id) 跑两次，证据不得重复追加。"""
    with isolated_workspace("w1"):
        ev = {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
              "page": 2, "region_id": "r05", "match": "exact"}
        workstate.record_decisions("w1", [ev])
        workstate.record_decisions("w1", [ev])
        assert len(workstate.load_decisions("w1")[norm("ヤミツキ茸")]["evidence"]) == 1


def test_revision_keeps_old_evidence():
    with isolated_workspace("w1"):
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
             "page": 2, "region_id": "r05", "match": "exact"},
        ])
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "迷幻菇", "surface_seen": "ヤミツキ茸",
             "page": 7, "region_id": "r00", "match": "exact"},
        ])
        e = workstate.load_decisions("w1")[norm("ヤミツキ茸")]
        assert e["translation"] == "迷幻菇"          # 新证据生效
        assert len(e["evidence"]) == 2               # 旧证据不丢
        assert e["evidence"][0]["page"] == 2


def test_model_judged_variant_records_alias():
    with isolated_workspace("w1"):
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
             "page": 2, "region_id": "r05", "match": "exact"},
        ])
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ",
             "page": 7, "region_id": "r04", "match": "model_judged"},
        ])
        e = workstate.load_decisions("w1")[norm("ヤミツキ茸")]
        assert "ヤミツキ" in e["aliases"]
        assert {x["match"] for x in e["evidence"]} == {"exact", "model_judged"}


def test_terms_take_precedence_and_conflict_is_surfaced():
    """terms（人工/词典先验）优先于 decisions；冲突不覆盖、要被看见。"""
    with isolated_workspace("w1"):
        st = workstate.load_state("w1")
        st.setdefault("terms", {})["ヤミツキ茸"] = {
            "translation": "迷幻菇", "status": "confirmed", "source": "pre_scan"}
        workstate.save_state("w1", st)
        workstate.record_decisions("w1", [
            {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
             "page": 2, "region_id": "r05", "match": "exact"},
        ])
        hits, conflicts = workstate.relevant_decisions_with_conflicts("w1", ["ヤミツキ茸が"])
        assert hits["ヤミツキ茸"]["translation"] == "迷幻菇"     # terms 优先
        assert conflicts and conflicts[0]["surface"] == "ヤミツキ茸"


def test_corrupt_state_degrades_to_empty_without_raising():
    with isolated_workspace("w1") as root:
        p = workstate.work_dir("w1") / "state" / "work_state.json"
        assert p.is_relative_to(root)
        p.write_text("{ this is not json", encoding="utf-8")
        assert workstate.load_decisions("w1") == {}
