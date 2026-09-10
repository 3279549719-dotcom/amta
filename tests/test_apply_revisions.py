import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import apply_revisions as ar


def test_apply_single_revision():
    trans = {"page_9_u01": "下次再让她给你吧", "page_0_u01": "不变"}
    revs = [{"region_id": "page_9_u01", "revised": "下次我帮你拿过来吧"}]
    out, log = ar.apply(trans, revs)
    assert out["page_9_u01"] == "下次我帮你拿过来吧"
    assert out["page_0_u01"] == "不变"
    assert log["page_9_u01"] == "下次再让她给你吧"


def test_apply_unknown_region_ignored():
    trans = {"a": "x"}
    out, _ = ar.apply(trans, [{"region_id": "zzz", "revised": "y"}])
    assert out == {"a": "x"}


def test_apply_empty_revised_ignored():
    trans = {"a": "x"}
    out, log = ar.apply(trans, [{"region_id": "a", "revised": ""}])
    assert out == {"a": "x"}
    assert log == {}
