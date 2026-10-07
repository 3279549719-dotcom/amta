"""残留 → 一次修复 → 低置信度分支。全部用假 LLM，不烧 API。

隔离方式见 tests/test_book_translation_memory.py 顶部说明：用显式
`isolated_workspace()` 而不是 pytest 夹具的 tmp_path——实测本仓
`--basetemp=.pytest_tmp` 下工作区状态会跨测试串味，而 `init_workspace` 幂等
（"文件已存在则不覆盖"，`src/amta/common/workstate.py:113`），残留的 decisions
会变成"既有记忆"让断言随机变红。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_book_translation_memory import isolated_workspace

from amta.translation.stage3_minimal import translate_page_minimal

CANON = [
    {"region_id": "r00", "baberu_text": "殺虫剤も虫の抵抗に合わせて年々強力になるらしいぞ?",
     "page": 7, "vlm_status": "ok"},
    {"region_id": "r01", "baberu_text": "そろそろ消費者も現状のヤミツキ茸の合有量に物足りなさがくる頃だろう?",
     "page": 7, "vlm_status": "ok"},
]


def _state(root: Path) -> Path:
    d = root / "w1" / "state"
    (root / "w1" / "artifacts").mkdir(parents=True, exist_ok=True)
    return d


def test_residue_triggers_exactly_one_repair():
    """第一次吐残留 → 恰好再问一次；第二次干净 → 无 low_confidence。"""
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        if len(calls) == 1:
            # 首次翻译：r01 残留片假名
            return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "ヤミツキ茸的含有量"]}'
        # 修复调用只问残留的 r01，必须返回干净译文——
        # 否则这个测试断言的是"修复失败"，证明不了修复能成功。
        return '{"translations": ["成瘾菇的含有量"]}'

    with isolated_workspace("w1") as root:
        out = translate_page_minimal("w1", CANON, state_dir=_state(root),
                                     page="page_7", llm_text=fake_llm)
        assert len(calls) == 2, "残留必须恰好触发一次修复调用"
        assert out["residue"] == []
        assert out["low_confidence"] == []
        assert "ヤミツキ茸" not in out["translations"]["r01"]


def test_residue_after_one_repair_sets_low_confidence():
    """两次都残留 → 最佳译文继续出图 + 机器可读低置信度；不生成第三次调用。"""
    calls = []

    def always_residue(messages):
        calls.append(messages)
        return '{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "ヤミツキ茸的含有量"]}'

    with isolated_workspace("w1") as root:
        out = translate_page_minimal("w1", CANON, state_dir=_state(root),
                                     page="page_7", llm_text=always_residue)
        assert len(calls) == 2, "一次修复，不得无限重试"
        assert out["residue"], "修复后仍残留 → residue 非空"
        lc = out["low_confidence"]
        assert lc and lc[0]["region_id"] == "r01"
        assert lc[0]["reason"] == "residue_after_one_repair"
        assert "ヤミツキ茸" in out["translations"]["r01"], "仍输出最佳译文，不丢内容"


def test_clean_page_makes_only_one_call():
    calls = []

    def clean(messages):
        calls.append(messages)
        return ('{"translations": ["杀虫剂也会随虫子抗药性变强哦?", "成瘾菇的含有量"],'
                ' "decisions": [{"surface": "ヤミツキ茸", "translation": "成瘾菇",'
                ' "surface_seen": "ヤミツキ茸"}]}')

    with isolated_workspace("w1") as root:
        out = translate_page_minimal("w1", CANON, state_dir=_state(root),
                                     page="page_7", llm_text=clean)
        assert len(calls) == 1, "干净页面必须仍然只有一次调用"
        assert out["low_confidence"] == []


def test_decisions_returned_by_translate_are_persisted():
    from amta.common import workstate
    from amta.common.metrics import norm

    def with_decision(messages):
        return ('{"translations": ["a", "b"], "decisions": ['
                '{"surface": "ヤミツキ茸", "translation": "成瘾菇",'
                ' "surface_seen": "ヤミツキ茸"}]}')

    with isolated_workspace("w1") as root:
        translate_page_minimal("w1", CANON, state_dir=_state(root),
                               page="page_7", llm_text=with_decision)
        d = workstate.load_decisions("w1")
        # decision 键为 norm(surface)——片假名归一后即 やみつき茸
        assert d[norm("ヤミツキ茸")]["translation"] == "成瘾菇"
        assert d[norm("ヤミツキ茸")]["evidence"][0]["page"] == 7
