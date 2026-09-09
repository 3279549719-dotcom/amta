import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.backends.koharu_client import KoharuClient


def test_run_inpaint_uploads_both_masks_and_waits(monkeypatch):
    """run_inpaint = put_mask(segment+bubble) + run_pipeline + wait_operation。"""
    c = KoharuClient()
    calls = []

    def fake_put_mask(page_id, role, png_bytes, engine=None):
        calls.append(("put_mask", page_id, role, len(png_bytes), engine))
        return {"ok": True}

    def fake_run_pipeline(page_ids, steps, **kw):
        calls.append(("run_pipeline", page_ids, steps))
        return "op1"

    def fake_wait(op_id, timeout):
        calls.append(("wait", op_id, timeout))
        return {"id": "op1", "status": "completed"}

    monkeypatch.setattr(c, "put_mask", fake_put_mask)
    monkeypatch.setattr(c, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(c, "wait_operation", fake_wait)

    masks = {"segment": b"seg-png", "bubble": b"bub-png"}
    res = c.run_inpaint("p1", masks, engine="lama-manga", timeout=999)

    assert res["status"] == "completed"
    assert ("put_mask", "p1", "segment", 7, "lama-manga") in calls
    assert ("put_mask", "p1", "bubble", 7, "lama-manga") in calls
    assert ("run_pipeline", ["p1"], ["lama-manga"]) in calls
    assert ("wait", "op1", 999) in calls


def test_run_inpaint_default_steps_and_timeout(monkeypatch):
    c = KoharuClient()
    seen = {}

    def fake_put_mask(page_id, role, png_bytes, engine=None):
        return {"ok": True}

    def fake_run_pipeline(page_ids, steps, **kw):
        seen["steps"] = steps
        return "op1"

    def fake_wait(op_id, timeout):
        seen["timeout"] = timeout
        return {"id": "op1", "status": "completed"}

    monkeypatch.setattr(c, "put_mask", fake_put_mask)
    monkeypatch.setattr(c, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(c, "wait_operation", fake_wait)

    c.run_inpaint("p1", {"segment": b"x"})
    assert seen["steps"] == ["lama-manga"]
    assert seen["timeout"] == 1800


def test_fetch_inpainted_returns_blob(monkeypatch):
    """fetch_inpainted: 遍历节点找 kind.image.role == inpainted → get_blob。"""
    c = KoharuClient()
    nodes = {
        "n1": {"kind": {"image": {"role": "source", "blob": "src-blob"}}},
        "n2": {"kind": {"image": {"role": "inpainted", "blob": "inp-blob"}}},
    }
    monkeypatch.setattr(c, "get_page_nodes", lambda pid: nodes)
    monkeypatch.setattr(c, "get_blob", lambda ref: b"WEBP-DATA:" + ref.encode())

    data = c.fetch_inpainted("p1")
    assert data == b"WEBP-DATA:inp-blob"


def test_fetch_inpainted_none_when_missing(monkeypatch):
    c = KoharuClient()
    monkeypatch.setattr(c, "get_page_nodes", lambda pid: {"n1": {"kind": {"image": {"role": "source"}}}})
    assert c.fetch_inpainted("p1") is None
