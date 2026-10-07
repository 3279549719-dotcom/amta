from pathlib import Path
from amta.common.book_store import book_id_from_src_dir, load_glossary, save_glossary

def test_book_id_is_stable_for_same_path(tmp_path: Path):
    src = tmp_path / "my_book"
    src.mkdir()
    id1 = book_id_from_src_dir(str(src))
    id2 = book_id_from_src_dir(str(src))
    assert id1 == id2

def test_book_id_differs_for_different_paths(tmp_path: Path):
    a = tmp_path / "book_a"; a.mkdir()
    b = tmp_path / "book_b"; b.mkdir()
    assert book_id_from_src_dir(str(a)) != book_id_from_src_dir(str(b))

def test_save_and_load_glossary_roundtrip(tmp_path: Path, monkeypatch):
    # Redirect WORKSPACE to tmp
    import amta.common.book_store as bs
    monkeypatch.setattr(bs, "WORKSPACE_ROOT", tmp_path / "workspace")
    bid = "testbook123"
    glossary = {"スーさん": "苏桑", "風見幽香": "风见幽香"}
    save_glossary(bid, glossary)
    loaded = load_glossary(bid)
    assert loaded == glossary

def test_load_glossary_missing_returns_empty(tmp_path: Path, monkeypatch):
    import amta.common.book_store as bs
    monkeypatch.setattr(bs, "WORKSPACE_ROOT", tmp_path / "workspace")
    assert load_glossary("nonexistent") == {}
